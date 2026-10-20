#!/usr/bin/env python3
"""Lithuania deepening: e-seimas.lrs.lt /rs/legalact read-only renderer.

Official discovery route: the Seimas legal-act search portal is a slow JSF app,
e-tar.lt is Cloudflare-gated, and the data.gov.lt Spinta API returns HTTP 500.
The read-only renderer at /rs/legalact/TAD/<id>/ serves full act texts as
server-rendered Word-HTML (crawlable, no JS). Two id schemes work there:
TAIS.<n> (legacy TAIS document numbers) and 32-hex TAR uuids.

Discovery: enumerate legacy document ids via the Wayback CDX index of the old
www3.lrs.lt showdoc_l?p_id=<n> URLs (same id space: TAIS.<n>), then fetch
https://e-seimas.lrs.lt/rs/legalact/TAD/TAIS.<n>/ with a browser UA.

Idempotent: skips instrument ids already present; caches the pid list and
fetch results under raw/.
"""
from __future__ import annotations
import concurrent.futures
import html as ihtml
import logging
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa

CC, COUNTRY, SOURCE_TYPE = "lt", "Lithuania", "eseimas"
LICENSE = ("Official texts of the Republic of Lithuania as published via the Seimas "
           "legal information system (e-seimas.lrs.lt); the Register of Legal Acts (e-tar.lt) "
           "is the authentic source. Not legal advice.")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
log = logging.getLogger("lt-eseimas")

MAX_NEW = int(os.environ.get("MAX_NEW", "800"))
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "3600"))
FETCH_BUDGET = int(os.environ.get("LT_FETCH_BUDGET", "2600"))
WORKERS = int(os.environ.get("LT_WORKERS", "4"))

CDX = ("https://web.archive.org/cdx/search/cdx"
       "?url=www3.lrs.lt/pls/inter3/dokpaieska.showdoc_l&matchType=prefix"
       "&fl=original&collapse=urlkey&limit=10000&page={page}")

# Notable acts, kept as fallback seeds if CDX discovery fails.
SEED_PIDS = [21892,  # Constitution of the Republic of Lithuania
             21827, 21839, 21900, 157066, 402802, 448855, 210209, 233965,
             30000, 50000]

MONTHS_LT = {"sausio": "01", "vasario": "02", "kovo": "03", "balandžio": "04",
             "gegužės": "05", "birželio": "06", "liepos": "07", "rugpjūčio": "08",
             "rugsėjo": "09", "spalio": "10", "lapkričio": "11", "gruodžio": "12"}


class ParaParser(HTMLParser):
    """Collect <p> paragraphs in document order with alignment/bold flags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras = []
        self._cur = None

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            a = dict(attrs)
            self._cur = {"text": [], "align": a.get("align", ""),
                         "bold": False, "cls": a.get("class", "")}

    def handle_endtag(self, tag):
        if tag == "p" and self._cur is not None:
            t = "".join(self._cur["text"]).replace("\xa0", " ").strip()
            t = re.sub(r"[ \t]+", " ", t)
            if t:
                self._cur["text"] = t
                self.paras.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur["text"].append(data)


def normalize_spaced(text: str) -> str:
    """'Į S T A T Y M A S' -> 'ĮSTATYMAS'; collapse whitespace."""
    t = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"(?:\w\s+)+\w", t) and len(t) > 3:
        t = re.sub(r"\s+", "", t)
    return t


MIN_TEXT = 300

DOCTYPE_WORDS = ("ĮSTATYMAS", "ĮSTATYMO", "NUTARIMAS", "NUTARIMO", "ĮSAKYMAS",
                 "SPRENDIMAS", "DEKRETAS", "POTVARKIS", "REZOLIUCIJA",
                 "KONSTITUCIJA", "KODEKSAS", "STATUTAS", "NUOSTATAI",
                 "REGLAMENTAS", "SUSITARIMAS")


def looks_like_header(t: str) -> bool:
    if len(t) > 140:
        return False
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.6


def parse_act(html: str) -> dict | None:
    """Extract title/date/number/body from an e-seimas /rs/ Word-HTML page."""
    p = ParaParser()
    try:
        p.feed(html)
    except Exception:
        return None
    paras = p.paras
    if not paras:
        return None
    full = "\n".join(x["text"] for x in paras)
    if len(full) < MIN_TEXT:
        return None
    if re.search(r"Nerasta teisės|Klaida|puslapis nerastas", full[:500], re.I):
        return None

    def fix_year(y: str) -> str | None:
        y = y.replace("l", "1").replace("I", "1").replace("o", "0").replace("O", "0")
        return y if re.fullmatch(r"(19|20)\d{2}", y) else None

    header: list[str] = []
    date_iso, number = None, None
    seen_doctype = False
    tail = 0
    date_re = re.compile(r"([lI1oO0\d]{4})\s*m\.\s*([a-zA-Ząčęėįšųūž]+)\s*(\d{1,2})\s*d\.")
    date_en_re = re.compile(r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})")
    for para in paras[:18]:
        t = para["text"]
        m = date_re.search(t)
        if m:
            yr = fix_year(m.group(1))
            if yr and MONTHS_LT.get(m.group(2).lower()):
                date_iso = f"{yr}-{MONTHS_LT[m.group(2).lower()]}-{int(m.group(3)):02d}"
                nm = re.search(r"Nr\.\s*([A-Za-z0-9\-\.]+)", t)
                if nm:
                    number = nm.group(1)
            continue
        m = date_en_re.search(t)
        if m and not date_iso:
            date_iso = f"{m.group(3)}-{MONTHS_EN[m.group(2).lower()]}-{int(m.group(1)):02d}"
            continue
        t_norm = normalize_spaced(t)
        if seen_doctype:
            # title may continue after the doctype word; date line often follows
            if looks_like_header(t) and len(header) < 8:
                header.append(t_norm)
                tail = 0
            else:
                tail += 1
                if tail > 2:
                    break
            continue
        if looks_like_header(t) and len(header) < 6:
            header.append(t_norm)
            if any(w in t_norm.upper() for w in DOCTYPE_WORDS):
                seen_doctype = True
            continue
        if header:
            break
    title = re.sub(r"\s+", " ", " ".join(header)).strip(" -–—")
    if not title:
        for para in paras[:6]:
            if len(para["text"]) > 30:
                title = normalize_spaced(para["text"])[:200]
                break
    if not title or len(full) < MIN_TEXT:
        return None
    return {"title": title, "date": date_iso, "number": number, "text": full}


def is_law(title: str) -> bool:
    t = title.upper()
    return any(k in t for k in ("ĮSTATYMAS", "ĮSTATYMO", "KONSTITUCIJA", "KONSTITUCIJOS",
                                "KODEKSAS", "KODEKSO", "STATUTAS",
                                "CONSTITUTION", "STATUTE", "CODE"))


def doc_type(title: str) -> str:
    t = title.upper()
    if any(k in t for k in ("ĮSTATYMAS", "ĮSTATYMO", "KONSTITUCIJA", "KODEKSAS",
                            "CONSTITUTION", "STATUTE", "CODE", "STATUTAS")):
        return "statute"
    if "NUTARIM" in t:
        return "resolution"
    if "ĮSAKYM" in t:
        return "order"
    if "SPRENDIM" in t:
        return "decision"
    if "DEKRET" in t:
        return "decree"
    return "legal_act"


MONTHS_EN = {"january": "01", "february": "02", "march": "03", "april": "04",
             "may": "05", "june": "06", "july": "07", "august": "08",
             "september": "09", "october": "10", "november": "11", "december": "12"}


def discover_pids(session) -> list[int]:
    cache = ROOT / CC / "raw" / "lt_eseimas_pids.txt"
    if cache.exists():
        pids = [int(x) for x in cache.read_text().split() if x.isdigit()]
        if pids:
            return pids
    pids: set[int] = set()
    for page in range(12):
        try:
            r = session.get(CDX.format(page=page), timeout=60)
            if r.status_code != 200 or not r.text.strip():
                break
            n0 = len(pids)
            for line in r.text.splitlines():
                m = re.search(r"p_id=(\d+)", line)
                if m:
                    pid = int(m.group(1))
                    if 0 < pid < 2000000:
                        pids.add(pid)
            if len(pids) == n0:
                break
            time.sleep(1.0)
        except Exception as exc:
            log.warning("cdx page %s failed: %s", page, exc)
            break
    ordered = sorted(pids)
    if ordered:
        cache.write_text("\n".join(str(x) for x in ordered) + "\n", encoding="utf-8")
        return ordered
    log.warning("CDX discovery failed; using fallback seeds")
    return list(SEED_PIDS)


def fetch_pid(session, pid: int):
    url = f"https://e-seimas.lrs.lt/rs/legalact/TAD/TAIS.{pid}/"
    for attempt in range(2):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                return pid, None, "404"
            if r.status_code != 200:
                return pid, None, f"http_{r.status_code}"
            parsed = parse_act(r.text)
            if not parsed:
                return pid, None, "unparseable"
            parsed["pid"] = pid
            parsed["url"] = url
            return pid, parsed, None
        except Exception as exc:
            err = str(exc)[:80]
            time.sleep(2 + attempt * 2)
    return pid, None, err


def main():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "lt_eseimas.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    t0 = time.time()
    notes = []
    session = get_session(ua=UA, pool=WORKERS + 2)

    pids = discover_pids(session)
    notes.append(f"discovery: {len(pids)} pids (Wayback CDX of www3.lrs.lt showdoc_l)")
    # Strided order spreads eras across the whole id range from the start.
    stride = 7
    ordered = [pid for off in range(stride) for pid in sorted(pids)[off::stride]]
    done = existing_ids(CC)
    notes.append(f"already existing instruments: {len(done)}")

    fetched = failed = skipped = 0
    written = 0
    deferred: list[dict] = []  # non-law parses, used only to fill remaining slots
    deadline = t0 + MAX_SECONDS

    _validate_warned = {"done": False}

    def keep(parsed: dict):
        nonlocal written
        ident = f"TAIS.{parsed['pid']}"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
        title = parsed["title"]
        official = parsed["number"] or ident
        rec = base_record(
            cc=CC, country=COUNTRY, language="lt", ident=ident, title=title,
            text=parsed["text"], source_url=parsed["url"], source_type=SOURCE_TYPE,
            license_text=LICENSE, collector="lt-eseimas",
            date=parsed["date"], official_identifier=f"LT {official}",
            document_type=doc_type(title), law_status="current", is_current=True,
            extra_meta={"tais_id": parsed["pid"], "act_number": parsed["number"]},
        )
        try:
            err = validate_record(rec)
        except Exception as exc:
            err = str(exc)
        if err and ("_templates" in err or "jsonschema" in err or "No module named" in err):
            # schema file not shipped in this environment; other collectors
            # (e.g. gh) also write without schema validation.
            if not _validate_warned["done"]:
                log.warning("schema validation unavailable (%s); writing without it", err[:100])
                notes.append(f"validation skipped: {err[:120]}")
                _validate_warned["done"] = True
            err = None
        if err:
            log_failure(CC, {"pid": parsed["pid"], "error": f"validate: {err[:120]}"})
            return "fail"
        write_instrument(CC, rec)
        done.add(rid)
        return "ok"

    idx = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        pending = {}
        def feed():
            nonlocal idx
            while idx < len(ordered) and len(pending) < WORKERS * 3 \
                    and fetched + failed < FETCH_BUDGET and written < MAX_NEW \
                    and time.time() < deadline:
                pid = ordered[idx]; idx += 1
                if slug_id(CC, f"TAIS.{pid}") in done:
                    skipped += 1
                    continue
                pending[ex.submit(fetch_pid, session, pid)] = pid
        feed()
        while pending and written < MAX_NEW and time.time() < deadline:
            for fut in concurrent.futures.as_completed(list(pending)):
                pid = pending.pop(fut)
                try:
                    _pid, parsed, err = fut.result()
                except Exception as exc:
                    parsed, err = None, str(exc)[:80]
                if parsed is None:
                    failed += 1
                    if failed <= 25:
                        log_failure(CC, {"pid": pid, "error": err})
                else:
                    fetched += 1
                    if is_law(parsed["title"]):
                        res = keep(parsed)
                        if res == "ok":
                            written += 1
                        elif res == "fail":
                            failed += 1
                        else:
                            skipped += 1
                    else:
                        deferred.append(parsed)
                feed()
                if fetched % 100 == 0:
                    log.info("progress fetched=%d written=%d failed=%d skipped=%d",
                             fetched, written, failed, skipped)
            feed()

    # Phase 2: fill remaining slots with non-law acts already parsed.
    for parsed in deferred:
        if written >= MAX_NEW or time.time() >= deadline:
            break
        res = keep(parsed)
        if res == "ok":
            written += 1
        elif res == "fail":
            failed += 1
        else:
            skipped += 1

    notes.append(f"fetch results: parsed_ok={fetched} failed={failed} skipped_existing={skipped}")
    notes.append(f"priority: statutes/constitutions/codes first, then other acts to fill {MAX_NEW} slots")
    notes.append("Blockers still open: e-tar.lt Cloudflare challenge; data.gov.lt Spinta HTTP 500; "
                 "portal legalActSearch JSF too slow to drive at scale.")
    write_summary(
        CC, country=COUNTRY,
        source="Seimas legal information system (e-seimas.lrs.lt /rs renderer); Register of Legal Acts (TAR) / data.gov.lt",
        source_urls=["https://e-seimas.lrs.lt/rs/legalact/TAD/TAIS.21892/",
                     "https://www.e-tar.lt/", "https://get.data.gov.lt",
                     "https://data.gov.lt/datasets/2613/"],
        license_text=LICENSE, discovered=len(pids), fetched=written,
        skipped=skipped, failed=failed, coverage="official-hosted-snapshot",
        notes="\n".join(notes), last_run=utcnow(),
        extra=f"started {utcnow()} (run t0 epoch {int(t0)}); collector=lt-eseimas; prior baseline run 2026-09-15T22:16:22Z found 0 via TAR/Spinta",
    )
    log.info("done discovered=%d written=%d failed=%d skipped=%d", len(pids), written, failed, skipped)


if __name__ == "__main__":
    main()
