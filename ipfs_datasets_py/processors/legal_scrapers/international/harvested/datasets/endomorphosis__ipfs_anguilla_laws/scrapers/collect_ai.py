#!/usr/bin/env python3
"""Anguilla: laws.gov.ai (Government of Anguilla Law Revision Library /
2022 Revised Statutes and Regulations) + gov.ai Laws shelves (Gazette Acts /
LSI / Regulations / UK SI) + Gazette cross-links (gazette.gov.ai).

Official-only *.gov.ai / laws.gov.ai. Live Livewire catalog (storage/pdfs) +
annual Gazette Act PDFs on gov.ai/storage + CDX of official URLs.
Not vLex / commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import html as html_mod
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "ai", "Anguilla", "en"
SOURCE_TYPE = "gov_ai_laws"
LICENSE = (
    "Government of Anguilla — Law Revision Library (laws.gov.ai; Attorney General's "
    "Chambers / Regional Law Revision Centre) + Gazette Acts/LSI/Regulations on gov.ai "
    "+ Official Gazette (gazette.gov.ai). Online revised texts are unofficial relative "
    "to the printed Revised Edition / Official Gazette; authentic Official Gazette / "
    "Government Printer / printed Revised Edition prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://laws.gov.ai/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule|PART)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("ai")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "gov.ai", "www.gov.ai", "laws.gov.ai", "www.laws.gov.ai",
    "gazette.gov.ai", "www.gazette.gov.ai",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|minutes|hansard|favicon|"
    r"vacancy|tender|questionnaire|organisational.?chart|organizational.?chart|"
    r"explanatory.?memorandum|\bbill\b|/bills/|_INTRODUCED|draft-|draft_|draft\s|"
    r"privacy.?policy|faqs|press.?release|speech|budget.?address|throne.?speech|"
    r"consultation.?paper|photo.?competition|subscription.?form|notice.?form|"
    r"fact.?sheet|progress.?report|missive|appointment.?of|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(legislation|gazette|act|acts|constitution|ordinance|regulation|order|rules?|"
    r"statutory|instrument|notice|proclamation|subsidiary|revised|lsi|"
    r"statutes|r\.?s\.?a|r\.?r\.?a|sanctions|storage/pdfs|storage/documents|"
    r"/dg/documents/)",
    re.I,
)
CDX_PREFIXES = (
    "laws.gov.ai/storage/pdfs/",
    "gov.ai/storage/documents/",
    "www.gov.ai/storage/documents/",
    "gov.ai/dg/documents/",
    "www.gov.ai/dg/documents/",
    "gazette.gov.ai/documents/",
    "gov.ai/document/",
    "www.gov.ai/document/",
)
LIVE_SHELVES = (
    "https://gov.ai/index.php/laws/acts-2025",
    "https://gov.ai/index.php/laws/lsi-2025",
    "https://gov.ai/index.php/laws/uk-si-2025",
    "https://gov.ai/index.php/laws/lsi-2024",
    "https://gov.ai/index.php/laws/uk-si-2024",
    "https://gov.ai/index.php/laws/2024",
    "https://gov.ai/index.php/laws/lsi-2023-2",
    "https://gov.ai/index.php/laws/regulations-2023",
    "https://gov.ai/index.php/laws",
    "https://www.gov.ai/service/2022-revised-statutes-and-regulations",
    "https://gazette.gov.ai/",
    "https://gazette.gov.ai/publications.php",
    "https://gazette.gov.ai/archive.php",
)
SEED_DOCS = (
    (
        "https://gov.ai/dg/documents/Anguilla%20Constitution%20Order%201982.pdf",
        "Anguilla Constitution Order 1982",
        "CONSTITUTION",
    ),
    (
        "https://www.gov.ai/document/2020%2009%2030%20-%20The%20Anguilla%20Constitution%20(Amendment)%20Order%202020%20-%20Deputy%20Speaker%20.pdf",
        "Anguilla Constitution (Amendment) Order 2020",
        "CONSTITUTION",
    ),
)
REVISION_URL = "https://laws.gov.ai/?revision=2022+Revision&year=2022"


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    host = (urlparse(url).hostname or "").lower()
    if host in ("www.gov.ai", "www.laws.gov.ai", "www.gazette.gov.ai"):
        url = url.replace("://" + host, "://" + host[4:], 1)
        host = (urlparse(url).hostname or "").lower()
    if host in HOST_OK or host.endswith(".gov.ai"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    try:
        parts = urlparse(url)
        if parts.path and (" " in parts.path or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%~[],") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(".gov.ai")


def _storage_url(rel_pdf: str) -> str:
    """Map laws.gov.ai relative pdfs/... path to live /storage/ URL."""
    rel = (rel_pdf or "").lstrip("/")
    if rel.startswith("storage/"):
        rel = rel[len("storage/") :]
    return "https://laws.gov.ai/storage/" + quote(rel, safe="/")


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    if re.search(r"anguilla\s+constitution|(^|[^a-z])constitution\s+order\b", blob) and "association" not in blob and "court of appeal" not in blob:
        return "CONSTITUTION"
    if shelf == "REVISED_ACT" or ("(acts)" in blob and "revised" in blob) or "/a-r.s.a" in blob or "r.s.a" in blob:
        if "amendment" in blob or "amending" in blob:
            return "AMENDING_ACT"
        return "REVISED_ACT"
    if shelf == "REVISED_REG" or "(regulations)" in blob or "/a-r.r.a" in blob or "r.r.a" in blob:
        return "REVISED_REG"
    if "gazette" in blob and "act" not in blob and "lsi" not in blob:
        return "GAZETTE"
    if re.search(r"\buk.?si\b|sanctions|overseas.?territor", blob):
        return "UK_SI"
    if re.search(r"\bact\b", blob) and "bill" not in blob:
        if re.search(r"amendment|amending", blob):
            return "AMENDING_ACT"
        return "ACT"
    if re.search(
        r"regulation|rules?|order|lsi|statutory|instrument|s\.?i\.?|"
        r"subsidiary|commencement|by-?laws?",
        blob,
    ):
        return "SI"
    if shelf in ("ACT", "SI", "UK_SI", "GAZETTE"):
        return shelf
    return ""


def _ident_from_url(url: str, hint: str = "", chapter: str = "") -> str:
    path = unquote(urlparse(url).path)
    # Revised: .../A005-Access to Beaches Act.pdf
    m = re.search(r"/([^/]+\.pdf)$", path, re.I)
    if m:
        stem = m.group(1)[:-4]
        # prefer chapter code prefix when present
        if chapter:
            stem = f"{chapter}_{stem}"
        return re.sub(r"[^\w.\-]+", "_", stem).strip("_")[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 4:
            return h
    stem = Path(path).stem
    if stem:
        return re.sub(r"[^\w.\-]+", "_", unquote(stem)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or (
        re.search(r"anguilla\s+constitution|(^|[^a-z])constitution\s+order\b", blob)
        and "association" not in blob
        and "court of appeal" not in blob
    ):
        return 0
    if cat == "REVISED_ACT" and "amendment" not in blob:
        return 1
    if cat == "ACT" and "amendment" not in blob:
        return 2
    if cat in ("AMENDING_ACT", "REVISED_REG"):
        return 3
    if cat in ("SI", "UK_SI"):
        return 4
    if cat == "GAZETTE":
        return 5
    return 6


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(url).path)
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = re.sub(r"^[A-Z]\d+-", "", stem)  # strip A005-
    stem = re.sub(r"^Act-\d+---+", "", stem, flags=re.I)
    stem = re.sub(r"^UK-SI-\d+-of-\d+---+", "", stem, flags=re.I)
    return stem.replace("-", " ").replace("_", " ").replace("+", " ")[:200].strip()


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://laws.gov.ai/",
        }
    )
    sess.verify = False
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def _livewire_revision_catalog(sess: requests.Session) -> list[dict]:
    """Fetch full 2022 Revision rows via Livewire perPage bump."""
    try:
        r = sess.get(REVISION_URL, timeout=90)
        if r.status_code != 200:
            log.warning("revision page status=%s", r.status_code)
            return []
        snaps = re.findall(r'wire:snapshot="([^"]+)"', r.text or "")
        if len(snaps) < 2:
            log.warning("livewire snapshots missing (%s)", len(snaps))
            return []
        snap_str = html_mod.unescape(snaps[1])
        xsrf = unquote(sess.cookies.get("XSRF-TOKEN", ""))
        headers = {
            "X-Livewire": "true",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": REVISION_URL,
            "X-XSRF-TOKEN": xsrf,
            "User-Agent": UA,
        }
        payload = {
            "components": [
                {"snapshot": snap_str, "updates": {"perPage": 800}, "calls": []}
            ]
        }
        rr = sess.post(
            "https://laws.gov.ai/livewire/update",
            json=payload,
            headers=headers,
            timeout=120,
        )
        if rr.status_code != 200:
            log.warning("livewire update status=%s body=%s", rr.status_code, rr.text[:200])
            return []
        snap = json.loads(rr.json()["components"][0]["snapshot"])
        rows = snap.get("data", {}).get("rows", [None])[0] or []
        out = []
        for entry in rows:
            it = entry[0] if isinstance(entry, list) else entry
            if not isinstance(it, dict):
                continue
            ar = (it.get("acts_regulations") or [{}])[0]
            ch = (it.get("chapter_no") or [{}])[0]
            rg = (it.get("regulation_no") or [{}])[0]
            title = (ar.get("text") or "").strip()
            rel = (ar.get("url") or "").strip()
            if not rel or not rel.lower().endswith(".pdf"):
                continue
            if re.search(r"\[?(Inoperative|Repealed)\]?", title, re.I) and not rel:
                continue
            chapter = (ch.get("text") or rg.get("text") or "").strip()
            out.append(
                {
                    "title": title,
                    "rel": rel,
                    "chapter": chapter,
                    "date": (ch.get("date") or rg.get("date") or "").strip(),
                }
            )
        log.info("livewire revision rows with pdf=%s (total claimed=%s)", len(out), snap["data"].get("total"))
        return out
    except Exception as exc:
        log.warning("livewire catalog fail: %s", exc)
        return []


def discover():
    seen_url, best = set(), {}
    sess = _session()

    def add(url, ts="", title_hint="", cat="", shelf="", chapter=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        is_pdf = ".pdf" in low
        if not is_pdf:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat} {shelf}"
        if SKIP_RE.search(blob):
            return
        if "/bills/" in low:
            return
        if re.search(r"\bbill\b", title_hint or "", re.I) and "act" not in (title_hint or "").lower():
            return
        if not KEEP_RE.search(blob):
            return
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            if re.search(r"anguilla\s+constitution|(^|[^a-z])constitution\s+order\b", blob) and "association" not in blob:
                cat = "CONSTITUTION"
            elif "(acts)" in blob or re.search(r"\bact\b", blob):
                cat = "REVISED_ACT" if "revised" in blob or "/storage/pdfs/" in low else "ACT"
            elif "(regulations)" in blob or "regulation" in blob:
                cat = "REVISED_REG" if "revised" in blob or "/storage/pdfs/" in low else "SI"
            else:
                cat = "SI"
        ident = _ident_from_url(url, title_hint, chapter)
        if not ident:
            return
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "", shelf or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            pr = _rank(prev[0], prev[3], prev[1])
            nr = _rank(row[0], row[3], row[1])
            if nr < pr or (nr == pr and (ts or "") > (prev[4] or "")):
                best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat, shelf="CONSTITUTION")

    # 2022 Revised Statutes & Regulations (laws.gov.ai storage PDFs)
    for row in _livewire_revision_catalog(sess):
        url = _storage_url(row["rel"])
        shelf = "REVISED_ACT" if "(Acts)" in row["rel"] else "REVISED_REG"
        cat = "REVISED_ACT" if shelf == "REVISED_ACT" else "REVISED_REG"
        tip = row["title"] or _title_from_path(url)
        add(url, "", tip, cat, shelf=shelf, chapter=row.get("chapter") or "")

    # Annual Gazette Act / LSI / Regulation / UK SI shelves on gov.ai
    for base in LIVE_SHELVES:
        try:
            r = sess.get(base, timeout=60)
            if r.status_code != 200:
                log.warning("live %s status=%s", base, r.status_code)
                continue
            before = len(best)
            hrefs = re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I)
            for href in hrefs:
                full = urljoin(base, href)
                if ".pdf" not in full.lower():
                    continue
                tip = _title_from_path(full)
                low = full.lower()
                if "uk-si" in low or "sanctions" in tip.lower():
                    shelf = "UK_SI"
                elif re.search(r"act-\d+|/acts-", low) or re.search(r"\bact\b", tip, re.I):
                    shelf = "ACT"
                else:
                    shelf = "SI"
                add(full, "", tip, shelf=shelf)
            log.info("shelf %s +%s catalog=%s", base[-40:], len(best) - before, len(best))
        except Exception as exc:
            log.warning("shelf %s fail: %s", base, exc)

    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            before = len(best)
            hits = list(
                cdx_urls(
                    prefix,
                    limit=lim,
                    match_type="prefix",
                    extra_filters=["mimetype:application/pdf"],
                )
            )
            for h in hits:
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig or ".pdf" not in orig.lower():
                    continue
                tip = _title_from_path(orig)
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = [
        (ident, url, hint, cat, ts)
        for ident, url, hint, cat, ts, shelf in best.values()
    ]
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    sess = _session()
    sess.headers["Referer"] = "https://laws.gov.ai/"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
    url = _norm(url)
    candidates = [url]
    # normalize laws.gov.ai pdfs/ without /storage/
    if "laws.gov.ai" in url and "/pdfs/" in url and "/storage/" not in url:
        candidates.insert(0, url.replace("://laws.gov.ai/", "://laws.gov.ai/storage/", 1))

    for cand in candidates:
        try:
            r = sess.get(cand, timeout=90, allow_redirects=True)
            body = r.content or b""
            if r.status_code == 200 and body[:4] == b"%PDF" and len(body) <= MAX_PDF:
                from world_lib import pdf_to_text

                text = pdf_to_text(body)
                if text and len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "http_pdf_session",
                        "error": "",
                        "source_url": cand,
                    }
                text2, how, pages = ocr_pdf(body)
                if text2 and len(text2) >= 100:
                    return {
                        "status": "success",
                        "text": text2,
                        "content": body,
                        "method": f"ocr:{how}",
                        "error": "",
                        "source_url": cand,
                    }
        except Exception as exc:
            log.debug("session fetch fail %s: %s", cand[:80], exc)

    got = fetch_official(
        url,
        ua=UA,
        verify=False,
        min_text=120,
        wayback_ts=wayback_ts or None,
    )
    if got.get("status") == "success":
        return got
    raw = got.get("content") or b""
    if isinstance(raw, bytes) and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
        text, how, pages = ocr_pdf(raw)
        if text and len(text) >= 100:
            got.update(status="success", text=text, method=f"ocr:{how}", error="")
            return got
        got["error"] = (got.get("error") or "") + f";ocr_failed:{how}"
    return got


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 175)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, hint, cat, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url, ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if "ocr" in str(got.get("method") or "").lower():
            ocr_used += 1
        title = hint or None
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower().replace("_", " ") not in title.lower():
            title = f"{title} [{cat}]"
        src = got.get("source_url") or url
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title or ident,
            text=text,
            source_url=src,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_ai.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source=(
            "Law Revision Library (laws.gov.ai 2022 Revised Statutes and Regulations) / "
            "gov.ai Laws (Gazette Acts/LSI/Regulations/UK SI) / Official Gazette (gazette.gov.ai)"
        ),
        source_urls=[
            "https://laws.gov.ai/",
            "https://laws.gov.ai/?revision=2022+Revision&year=2022",
            "https://gov.ai/index.php/laws",
            "https://www.gov.ai/service/2022-revised-statutes-and-regulations",
            "https://gazette.gov.ai/",
            "https://gov.ai/service/legal/attorney-generals-chambers",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (laws.gov.ai 2022 Revised Acts/Regs via Livewire "
            "+ gov.ai annual Gazette Act/LSI/UK SI PDFs + CDX; gazette.gov.ai login-walled)"
        ),
        notes=(
            f"Official laws.gov.ai /storage/pdfs (2022 Revised) via Livewire catalog + "
            f"gov.ai/storage Gazette annual Acts/LSI/Regs/UK SI + Wayback CDX of official "
            f"gov.ai/dg and gazette.gov.ai URLs. Prefer Constitution + Revised Acts + annual "
            f"Acts. Online revised texts unofficial vs printed Revised Edition / Gazette. "
            f"Skip bills/drafts/press. OCR eng used={ocr_used}. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
