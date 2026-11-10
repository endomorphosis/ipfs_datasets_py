#!/usr/bin/env python3
"""Croatia (HR): ARTICLE_EXTRACT collector from narodne-novine.nn.hr (official ELI HTML).

Mirrors /workspace/scripts/lt_extract_articles.py.

Mapping: hub law ids -> NN document
  hr-<year>-<issue>-<act>        -> https://narodne-novine.nn.hr/eli/sluzbeni/<year>/<issue>/<act>
                                    (302 -> /clanci/sluzbeni/<year>_<MM>_<issue>_<act>.html)
  hr-<year>_<MM>_<issue>_<act>   -> https://narodne-novine.nn.hr/clanci/sluzbeni/<id>.html (direct)
  hr-<year>-<issue>-<act>-pdf    -> PDF-only duplicate of hr-<year>-<issue>-<act>: NOT fetched
                                    (status pdf_duplicate; base id carries the articles)
  laws already having hub articles (108 rows / 15 laws) -> hub rows kept verbatim, not re-fetched.
robots.txt is honoured (redirect target checked before fetching the HTML).
Each mappable law is processed exactly once (+ at most ONE retry pass for fetch_fail),
then the script stops by itself. Never probes unmapped ids.

Never thins: laws.parquet copied verbatim from hub snapshot (if missing), never rewritten.
articles.jsonl is append-only; articles.parquet rebuilt by streaming. No Hub publish, no IR.
Memory guard: TERM self when MemAvailable <= 3.5 GiB (watchdog thread + per-law check). No restart.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import html as htmlmod
import json
import logging
import os
import re
import shutil
import signal
import sys
import threading
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin

import pyarrow as pa
import pyarrow.parquet as pq
import requests

HUB_DIR = Path("/workspace/country-laws-ir/cache/hf/datasets--endomorphosis--ipfs_croatia_laws/"
               "snapshots/9469c387c221cf5ab435b0c4cabb9426213a48ee/data")
HUB_LAWS = HUB_DIR / "laws.parquet"
HUB_ARTS = HUB_DIR / "articles.parquet"
ROOT = _CORPORA / "hr"
REL = Path("{_CORPORA}-releases/croatia")
LAWS_PQ = REL / "data" / "laws.parquet"
ARTS_PQ = REL / "data" / "articles.parquet"
WORK = ROOT / "extract"
ARTS_JSONL = WORK / "articles.jsonl"
DONE_PATH = WORK / "done_law_ids.txt"
STATUS_JSONL = WORK / "law_status.jsonl"
STATE_PATH = WORK / "state.json"
PID_PATH = WORK / "hr_extract_articles.pid"
SEEDED_FLAG = WORK / ".hub_articles_seeded"

BASE = "https://narodne-novine.nn.hr"
UA = "CountryLawScraper/hr-extract (+https://huggingface.co/endomorphosis)"
FLOOR_LAWS = 30315
FETCH_SLEEP = float(os.environ.get("HR_FETCH_SLEEP", "0.6"))  # between every request (<=~1.5 req/s)
PROGRESS_EVERY = 25
PARQUET_EVERY = 200
MAX_ARTS_PER_LAW = 3000
MEM_STOP_KB = int(3.5 * 1024 * 1024)  # 3.5 GiB
MAX_CONSEC_FAIL = 15
MAX_403 = 3
LIMIT = int(os.environ.get("HR_LIMIT", "0"))
COLS = ["law_id", "id", "title", "text", "source_url", "document_number",
        "article_number", "record_type", "metadata_json"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("hr_extract")
STOP = False
STOP_REASON = ""


def _sig(_s, _f):
    global STOP
    STOP = True
    log.info("signal received; stopping after current law")


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def mem_available_kb() -> int:
    with open("/proc/meminfo") as f:
        for ln in f:
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1])
    return 0


def rss_kb() -> int:
    with open("/proc/self/status") as f:
        for ln in f:
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1])
    return 0


def mem_watchdog() -> None:
    global STOP_REASON
    while not STOP:
        ma = mem_available_kb()
        if ma <= MEM_STOP_KB:
            STOP_REASON = f"mem_guard MemAvailable={ma}kB"
            log.error("MEM GUARD (watchdog): MemAvailable %s kB <= 3.5G; TERM self (no restart)", ma)
            os.kill(os.getpid(), signal.SIGTERM)
            return
        time.sleep(5)


# ---------------------------------------------------------------- mapping
def map_law(law_id: str) -> tuple[str, str]:
    """Return (url, kind): kind in {eli, clanci, pdf_duplicate, none}."""
    m = re.match(r"^hr-(\d{4})-(\d+)-(\d+)$", law_id)
    if m:
        return f"{BASE}/eli/sluzbeni/{m.group(1)}/{m.group(2)}/{m.group(3)}", "eli"
    m = re.match(r"^hr-(\d{4}_\d{2}_\d+_\d+)$", law_id)
    if m:
        return f"{BASE}/clanci/sluzbeni/{m.group(1)}.html", "clanci"
    m = re.match(r"^hr-(\d{4})-(\d+)-(\d+)-pdf$", law_id)
    if m:
        return f"{BASE}/eli/sluzbeni/{m.group(1)}/{m.group(2)}/{m.group(3)}/pdf", "pdf_duplicate"
    return "", "none"


# ---------------------------------------------------------------- fetching
class Blocked(Exception):
    pass


N403 = 0


def get(session: requests.Session, url: str) -> requests.Response | None:
    global N403
    backoff = 5.0
    for attempt in range(5):
        try:
            r = session.get(url, timeout=(20, 120), allow_redirects=False)
        except Exception as exc:
            log.info("fetch err %s %s", url, exc)
            time.sleep(backoff); backoff = min(backoff * 2, 120)
            continue
        finally:
            time.sleep(FETCH_SLEEP)
        if r.status_code == 403:
            N403 += 1
            log.warning("HTTP 403 %s (consecutive=%s)", url, N403)
            if N403 >= MAX_403:
                raise Blocked(f"{N403} consecutive HTTP 403, last {url}")
            time.sleep(60)
            return r
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("Retry-After")
            wait = max(backoff, float(ra)) if ra and ra.isdigit() else backoff
            log.info("HTTP %s %s attempt=%s wait=%.0fs", r.status_code, url, attempt + 1, wait)
            time.sleep(min(wait, 600)); backoff = min(backoff * 2, 300)
            continue
        N403 = 0
        return r
    return None


def fetch_html(session, rp, url: str) -> tuple[str, str, str, int]:
    """Returns (html, final_url, outcome, http). outcome in ok|not_found|robots|fetch_fail."""
    for _hop in range(4):
        if not rp.can_fetch(UA, url):
            return "", url, "robots", 0
        r = get(session, url)
        if r is None:
            return "", url, "fetch_fail", -1
        if r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", ""))
            continue
        if r.status_code == 404:
            return "", url, "not_found", 404
        if r.status_code == 200:
            r.encoding = "utf-8"
            t = r.text
            if 'class="sl-content"' not in t:
                return "", url, "no_content", 200
            return t, url, "ok", 200
        return "", url, "fetch_fail", r.status_code
    return "", url, "fetch_fail", -2


# ---------------------------------------------------------------- parsing
ART_RE = re.compile(r"^(?:Članak|Član|ČLANAK|ČLAN)\.?\s+(\d+\s*\.?\s*[a-zA-Z]?)\s*\.?\s*$")
STRUCT_RE = re.compile(
    r"^((?:[IVXLCDM]+\.?\s+)?(?:DIO|GLAVA|ODJELJAK|POGLAVLJE|PODODJELJAK)\b.*|"
    r"(?:Dio|Glava|Odjeljak|Poglavlje|Pododjeljak)\s+(?:[IVXLCDM]+|\d+|prvi|drugi|treći|četvrti|peti|šesti|sedmi|"
    r"osmi|deveti|deseti)\b\.?.{0,150}|"
    r"(?:PRVI|DRUGI|TREĆI|ČETVRTI|PETI|ŠESTI|SEDMI|OSMI|DEVETI|DESETI)\s+DIO\b.*|"
    r"[IVXLCDM]+\.\s+[A-ZČĆŽŠĐ][A-ZČĆŽŠĐ ,\-–]{3,})$")
ROMAN_RE = re.compile(r"^([IVXLCDM]{1,7})\.?$")
PT_RE = re.compile(r"^(\d{1,3})\.\s*(\S.*)?$")


def html_to_lines(h: str) -> list[str]:
    i = h.find('<div class="sl-content">')
    j = h.find('id="sticky-anchor2"', i)
    if i < 0:
        return []
    h = h[i:j if j > i else len(h)]
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", h)
    h = re.sub(r"(?i)<br[^>]*>|</p>|</h\d>|</div>|</tr>|</li>|</td>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    t = htmlmod.unescape(h).replace("\xa0", " ").replace("\u00ad", "").replace("\r", "")
    out = []
    for ln in t.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln and not ln.startswith("<"):
            out.append(ln)
    return out


def roman_to_int(s: str) -> int:
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    tot = 0
    for a, b in zip(s, s[1:] + " "):
        tot += -v[a] if b != " " and v.get(b, 0) > v[a] else v[a]
    return tot


def split_units(lines: list[str]) -> tuple[list[dict], str]:
    """Split into članak units (quote-aware); fallback roman points, then arabic points."""
    ctx: dict[str, str] = {}
    arts: list[dict] = []
    cur = None
    depth = 0  # inside »...« quoted amendment text
    pending_heading = ""
    prev_int = 0
    prev_ln = ""
    for ln in lines:
        at_depth = depth
        depth = max(0, depth + ln.count("»") - ln.count("«"))
        m = ART_RE.match(ln)
        if m:
            num = re.sub(r"\s+", "", m.group(1)).rstrip(".")
            mi = re.match(r"^(\d+)(.*)$", num)
            n_int, suf = int(mi.group(1)), mi.group(2).strip(". ")
            quoted_ctx = prev_ln == "»" or prev_ln.endswith(":") or prev_ln.endswith("»")
            # v2: quote tracking can desync on unbalanced »« typos; resync when the next
            # sequential article number appears outside a quoting context.
            resync = at_depth > 0 and not suf and n_int == prev_int + 1
            if at_depth == 0 or (resync and not quoted_ctx):
                if cur:
                    arts.append(cur)
                cur = {"num": num, "heading": pending_heading, "lines": [ln], "ctx": dict(ctx)}
                pending_heading = ""
                prev_int = n_int
                depth = 0 if resync else depth
                prev_ln = ln
                continue
        if at_depth == 0 and not m:
            if (STRUCT_RE.match(ln) and len(ln) < 250 and not (ln.endswith(".") and len(ln) > 25)
                    and not (cur and len(cur["lines"]) == 1)):
                key = ln.split()[0].lower() if not ROMAN_RE.match(ln.split()[0]) else "section"
                ctx[key] = ln
                if cur:
                    arts.append(cur); cur = None
                prev_ln = ln
                continue
        if cur:
            cur["lines"].append(ln)
        prev_ln = ln
    if cur:
        arts.append(cur)
    # a short trailing line before 'Članak' is usually the article heading; keep simple: no reassign
    arts = [a for a in arts if len(" ".join(a["lines"])) >= 25]
    if arts:
        return arts[:MAX_ARTS_PER_LAW], "clanak"
    # fallback 1: roman-numeral points on their own line (Odluka/Rješenje: I., II., ...)
    for kind, matcher in (("tocka_rim", ROMAN_RE), ("tocka", PT_RE)):
        pts: list[dict] = []
        cur = None; prev = 0; depth = 0
        for ln in lines:
            at_depth = depth
            depth = max(0, depth + ln.count("»") - ln.count("«"))
            m = matcher.match(ln) if at_depth == 0 else None
            if m:
                n = roman_to_int(m.group(1)) if kind == "tocka_rim" else int(m.group(1))
                if n == prev + 1:
                    if cur:
                        pts.append(cur)
                    cur = {"num": m.group(1), "heading": "", "lines": [ln], "ctx": {}}
                    prev = n
                    continue
            if cur:
                cur["lines"].append(ln)
        if cur:
            pts.append(cur)
        pts = [p for p in pts if len(" ".join(p["lines"])) >= 25]
        if len(pts) >= 2:
            return pts[:MAX_ARTS_PER_LAW], kind
    return [], "none"


# ---------------------------------------------------------------- io
def load_done() -> set[str]:
    if not DONE_PATH.exists():
        return set()
    return {ln.strip() for ln in DONE_PATH.open(encoding="utf-8") if ln.strip()}


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def rebuild_articles_parquet() -> int:
    schema = pa.schema([(c, pa.string()) for c in COLS])
    tmp = ARTS_PQ.with_suffix(".parquet.tmp")
    seen: set[str] = set()
    n = 0
    w = pq.ParquetWriter(tmp, schema, compression="zstd")
    batch: list[dict] = []
    if ARTS_JSONL.exists():
        with ARTS_JSONL.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rid = r.get("id")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                batch.append({c: ("" if r.get(c) is None else str(r.get(c))) for c in COLS})
                if len(batch) >= 2000:
                    w.write_table(pa.Table.from_pylist(batch, schema=schema)); n += len(batch); batch = []
    if batch:
        w.write_table(pa.Table.from_pylist(batch, schema=schema)); n += len(batch)
    w.close()
    prev = pq.ParquetFile(ARTS_PQ).metadata.num_rows if ARTS_PQ.exists() else 0
    if n < prev:
        log.warning("refuse arts thin %s -> %s", prev, n)
        tmp.unlink(missing_ok=True)
        return prev
    tmp.replace(ARTS_PQ)
    return n


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-z.]+", "-", s.lower()).strip("-") or "x"


def process_law(session, rp, law_id: str, url: str, kind: str, c: dict) -> tuple[dict, list[dict]]:
    status = {"law_id": law_id, "url": url, "kind": kind}
    rows_out: list[dict] = []
    h, final, outcome, code = fetch_html(session, rp, url)
    status.update({"final_url": final, "outcome": outcome, "http": code})
    if outcome in ("fetch_fail",):
        status["status"] = "fetch_fail"; return status, rows_out
    if outcome in ("robots", "not_found", "no_content"):
        status["status"] = outcome; return status, rows_out
    lines = html_to_lines(h)
    units, unit_kind = split_units(lines)
    for i, u in enumerate(units):
        num = u["num"]
        label = {"clanak": f"Članak {num}.", "tocka_rim": f"{num}.", "tocka": f"{num}."}[unit_kind]
        rows_out.append({
            "law_id": law_id,
            "id": f"{law_id}-{'cl' if unit_kind == 'clanak' else 't'}-{slug(num)}-{i}"[:200],
            "title": label,
            "text": "\n".join(u["lines"]),
            "source_url": url if kind == "eli" else final,
            "document_number": law_id[3:],
            "article_number": num,
            "record_type": "article",
            "metadata_json": json.dumps({
                "collector": "hr_extract_articles", "source": "narodne-novine.nn.hr",
                "text_url": final, "unit": unit_kind, "heading": u["heading"],
                "context": u["ctx"], "ordinal": i,
            }, ensure_ascii=False),
        })
    status.update({"status": "ok" if rows_out else "empty", "unit": unit_kind,
                   "n_arts": len(rows_out), "n_lines": len(lines)})
    return status, rows_out


def main() -> None:
    global STOP_REASON
    WORK.mkdir(parents=True, exist_ok=True)
    (REL / "data").mkdir(parents=True, exist_ok=True)
    if not LAWS_PQ.exists():
        shutil.copy2(HUB_LAWS, LAWS_PQ)  # verbatim copy, never rewritten
    nl = pq.ParquetFile(LAWS_PQ).metadata.num_rows
    if nl < FLOOR_LAWS:
        log.error("laws %s < floor %s: refuse", nl, FLOOR_LAWS); sys.exit(2)
    ma = mem_available_kb()
    if ma <= MEM_STOP_KB:
        log.error("MemAvailable %s kB <= guard; refuse to start", ma); sys.exit(3)
    PID_PATH.write_text(f"{os.getpid()}\n")
    threading.Thread(target=mem_watchdog, daemon=True).start()

    # seed existing hub articles verbatim (never thin)
    hub_art_laws: set[str] = set()
    if HUB_ARTS.exists():
        ht = pq.read_table(HUB_ARTS)
        hub_art_laws = set(ht.column("law_id").to_pylist())
        if not SEEDED_FLAG.exists():
            append_jsonl(ARTS_JSONL, [{k: r.get(k) for k in COLS} for r in ht.to_pylist()])
            SEEDED_FLAG.write_text(f"{ht.num_rows}\n")
            log.info("seeded %s hub article rows (%s laws)", ht.num_rows, len(hub_art_laws))

    ids = sorted(pq.read_table(LAWS_PQ, columns=["id"]).column("id").to_pylist())
    plan = []
    skipped = {"pdf_duplicate": 0, "hub_has_articles": 0, "unmapped": 0}
    for lid in ids:
        url, kind = map_law(lid)
        if kind == "none":
            skipped["unmapped"] += 1; continue
        if kind == "pdf_duplicate":
            skipped["pdf_duplicate"] += 1; continue
        if lid in hub_art_laws:
            skipped["hub_has_articles"] += 1; continue
        plan.append((lid, url, kind))
    # newest first (most relevant texts first)
    plan.sort(key=lambda x: x[0], reverse=True)
    n_map = len(plan)

    rp = urllib.robotparser.RobotFileParser()
    rr = requests.get(f"{BASE}/robots.txt", headers={"User-Agent": UA}, timeout=60)
    if rr.status_code == 403:
        log.error("robots.txt 403 -> site blocking us; stop"); sys.exit(4)
    rp.parse(rr.text.splitlines())
    time.sleep(FETCH_SLEEP)

    done = load_done()
    st = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    keys = ("processed", "with_arts", "articles", "empty", "fetch_fail", "not_found", "robots",
            "no_content", "clanak_laws", "tocka_laws", "retried", "retry_ok")
    c = {k: int(st.get(k, 0)) for k in keys}
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "hr,en;q=0.5"})
    t0 = time.time(); run_n = 0; consec_fail = 0
    log.info("start laws=%s mappable_to_fetch=%s skipped=%s done=%s mem_avail_kB=%s sleep=%s",
             nl, n_map, skipped, len(done), ma, FETCH_SLEEP)

    def record(status, rows_out, retry=False):
        if rows_out:
            append_jsonl(ARTS_JSONL, rows_out)
            c["with_arts"] += 1; c["articles"] += len(rows_out)
            c["clanak_laws" if status.get("unit") == "clanak" else "tocka_laws"] += 1
        s = status["status"]
        if s in ("empty", "fetch_fail", "not_found", "robots", "no_content"):
            c[s] += 1
        append_jsonl(STATUS_JSONL, [status])

    def progress(final=False):
        el = time.time() - t0
        left = n_map - len(done)
        rate = run_n / el * 60 if el else 0
        state = dict(c, mappable_to_fetch=n_map, skipped=skipped, laws_rows=nl, remaining=left,
                     run_processed=run_n, run_elapsed_s=int(el), laws_per_min=round(rate, 2),
                     eta_h=round(left / rate / 60, 1) if rate else None,
                     arts_per_law_ok=round(c["articles"] / c["with_arts"], 2) if c["with_arts"] else 0,
                     mem_avail_kB=mem_available_kb(), rss_kB=rss_kb(),
                     updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        STATE_PATH.write_text(json.dumps(state, indent=2))
        return state

    blocked = ""
    try:
        for lid, url, kind in plan:
            if STOP:
                break
            if lid in done:
                continue
            ma = mem_available_kb()
            if ma <= MEM_STOP_KB:
                STOP_REASON = f"mem_guard MemAvailable={ma}kB"
                log.error("MEM GUARD: MemAvailable %s kB <= 3.5G; stopping (do not restart)", ma)
                break
            status, rows_out = process_law(session, rp, lid, url, kind, c)
            record(status, rows_out)
            with DONE_PATH.open("a", encoding="utf-8") as f:
                f.write(lid + "\n")
            done.add(lid)
            c["processed"] += 1; run_n += 1
            consec_fail = consec_fail + 1 if status["status"] == "fetch_fail" else 0
            log.info("law %s status=%s http=%s unit=%s arts=%s", lid, status["status"],
                     status.get("http"), status.get("unit"), len(rows_out))
            if consec_fail >= MAX_CONSEC_FAIL:
                STOP_REASON = f"{consec_fail} consecutive fetch failures"
                log.error("STOP: %s", STOP_REASON); break
            if c["processed"] % PARQUET_EVERY == 0:
                rebuild_articles_parquet()
            if c["processed"] % PROGRESS_EVERY == 0:
                log.info("progress %s", json.dumps(progress()))
            if LIMIT and run_n >= LIMIT:
                STOP_REASON = "limit"; break
        # ONE retry pass for fetch failures (only if main pass completed cleanly)
        if not STOP and not STOP_REASON and len(done) >= n_map and not st.get("retry_pass_done"):
            fails = []
            if STATUS_JSONL.exists():
                last = {}
                for line in STATUS_JSONL.open(encoding="utf-8"):
                    r = json.loads(line); last[r["law_id"]] = r
                fails = [r for r in last.values() if r["status"] == "fetch_fail"]
            log.info("retry pass: %s fetch_fail laws", len(fails))
            for r in fails:
                if STOP or mem_available_kb() <= MEM_STOP_KB:
                    break
                status, rows_out = process_law(session, rp, r["law_id"], r["url"], r["kind"], c)
                status["retry"] = True
                c["retried"] += 1
                if status["status"] != "fetch_fail":
                    c["fetch_fail"] -= 1; c["retry_ok"] += 1
                    record(status, rows_out)
                else:
                    append_jsonl(STATUS_JSONL, [status])
            else:
                c["retry_pass_done"] = 1
    except Blocked as exc:
        blocked = str(exc)
        STOP_REASON = f"BLOCKED: {blocked}"
        log.error("SITE BLOCK DETECTED: %s -- stopping, not working around it", blocked)
    n = rebuild_articles_parquet()
    state = progress()
    state.update(articles_parquet_rows=n, stopped=bool(STOP), stop_reason=STOP_REASON,
                 retry_pass_done=int(c.get("retry_pass_done", st.get("retry_pass_done", 0))),
                 done=(len(done) >= n_map))
    STATE_PATH.write_text(json.dumps(state, indent=2))
    log.info("END %s", json.dumps(state))
    try:
        PID_PATH.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    main()
