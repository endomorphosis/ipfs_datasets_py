#!/usr/bin/env python3
"""Turks and Caicos Islands: gov.tc/agc (Attorney General's Chambers / Edocman
Revised + Annual Laws) + CGIS Official Gazette index (subscription-walled PDFs).

Official-only *.gov.tc. Live Joomla Edocman shelves (2021 Revised preferred +
Annual Acts/Ordinances/Subsidiary 2015–2026) via /component/edocman/.../fdocument
+ CDX of viewdocument PDF captures. Skip bills/press/forms. Not vLex / commercial.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, quote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "tc", "Turks and Caicos Islands", "en"
SOURCE_TYPE = "gov_tc_agc"
LICENSE = (
    "Government of the Turks and Caicos Islands — Attorney General's Chambers "
    "(gov.tc/agc; Revised Edition of the Laws / Annual Laws via Edocman) + "
    "Customer & Government Information Services Official Gazette (gov.tc/cgis; "
    "cgis.gov.tc). Authentic Official Gazette / Government Printer text prevails. "
    "Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://gov.tc/agc/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule|PART)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("tc")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "gov.tc", "www.gov.tc", "cgis.gov.tc", "www.cgis.gov.tc",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|minutes|hansard|favicon|"
    r"vacancy|tender|questionnaire|organisational.?chart|organizational.?chart|"
    r"explanatory.?memorandum|\bbill\b|/bills/|_INTRODUCED|draft-|draft_|draft\s|"
    r"privacy.?policy|faqs|press.?release|speech|budget.?address|throne.?speech|"
    r"consultation.?paper|photo.?competition|online_payments|"
    r"subscription.?form|\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(legislation|gazette|act|acts|constitution|ordinance|regulation|order|rules?|"
    r"statutory|instrument|notice|proclamation|subsidiary|revised|edocman|"
    r"viewdocument|fdocument|s\.?i\.?|commencement)",
    re.I,
)
CDX_PREFIXES = (
    "gov.tc/agc/component/edocman/",
    "www.gov.tc/agc/component/edocman/",
)
# Prefer latest revised edition; annual post-revision + recent years
LIVE_SHELVES = (
    ("https://gov.tc/agc/2021-revised-laws", "REVISED_2021", 0),
    ("https://gov.tc/agc/component/content/article/2026-acts?catid=9&Itemid=114", "ACT", 0),
    ("https://gov.tc/agc/component/content/article/2026-subsidiary-legislation?catid=9&Itemid=114", "SI", 0),
    ("https://gov.tc/agc/component/content/article/2025-ordinance?catid=9&Itemid=114", "ORDINANCE", 0),
    ("https://gov.tc/agc/component/content/article/2025-subsidiary-legislation?catid=9&Itemid=114", "SI", 0),
    ("https://gov.tc/agc/component/content/article/2024-ordinance?catid=9&Itemid=114", "ORDINANCE", 0),
    ("https://gov.tc/agc/component/content/article/2024-subsidiary-legislation?catid=9&Itemid=114", "SI", 0),
    ("https://gov.tc/agc/2023-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2023-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2022-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2022-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2021-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2021-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2020-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2020-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2019-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2019-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2018-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2018-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2017-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2017-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2016-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2016-subsidiary-legislation", "SI", 0),
    ("https://gov.tc/agc/2015-ordinances", "ORDINANCE", 0),
    ("https://gov.tc/agc/2015-subsidiary-legislation", "SI", 0),
    # Older revised editions as lower-priority fill (deduped against 2021)
    ("https://gov.tc/agc/2018-revised-laws", "REVISED_2018", 0),
    ("https://gov.tc/agc/2014-revised-laws", "REVISED_2014", 0),
)
SEED_DOCS = (
    ("https://gov.tc/agc/component/edocman/01-01-tci-constitution-2-3/viewdocument/1789",
     "Turks and Caicos Islands Constitution (01.01)", "CONSTITUTION"),
    ("https://gov.tc/agc/component/edocman/2021-revised-laws-list-of-titles-and-chapters/viewdocument/2021",
     "2021 Revised Laws List of Titles and Chapters", "INDEX"),
    ("https://gov.tc/agc/component/edocman/2021-revised-laws-general-index/viewdocument/2022",
     "2021 Revised Laws General Index", "INDEX"),
    ("https://gov.tc/agc/component/edocman/2021-revised-laws-preliminary-booklet/viewdocument/2023",
     "2021 Revised Laws Preliminary Booklet", "INDEX"),
)
EDOC_RE = re.compile(
    r'href=["\']((?:https?://(?:www\.)?gov\.tc)?/agc/component/edocman/'
    r'[^"\']+/viewdocument/\d+[^"\']*)["\']',
    re.I,
)
VIEWDOC_RE = re.compile(
    r"(https?://(?:www\.)?gov\.tc/agc/component/edocman/"
    r"[^?\s\"'<>]+/viewdocument/\d+(?:\?[^?\s\"'<>]*)?)",
    re.I,
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    host = (urlparse(url).hostname or "").lower()
    if host in ("www.gov.tc", "gov.tc", "www.cgis.gov.tc", "cgis.gov.tc"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    if host == "www.gov.tc":
        url = url.replace("://www.gov.tc", "://gov.tc", 1)
    if host == "www.cgis.gov.tc":
        url = url.replace("://www.cgis.gov.tc", "://cgis.gov.tc", 1)
    # normalize empty Itemid=
    url = re.sub(r"\?Itemid=$", "", url)
    url = re.sub(r"\?Itemid=&", "?", url)
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
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(".gov.tc")


def _to_fdocument(view_url: str) -> str:
    """Convert Edocman viewdocument URL to live PDF download (fdocument)."""
    u = _norm(view_url)
    m = re.search(
        r"(https?://(?:www\.)?gov\.tc/agc/component/edocman/[^/]+)/viewdocument/\d+",
        u,
        re.I,
    )
    if not m:
        return u
    return m.group(1) + "/fdocument?Itemid=99"


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    if "constitut" in blob:
        return "CONSTITUTION"
    if shelf.startswith("REVISED") or "revised-laws" in blob or re.search(
        r"/\d{2}-\d{2}-", urlparse(url).path
    ):
        if "uk-statutory" in blob or "uk_statutory" in blob:
            return "UK_SI"
        if "index" in blob or "preliminary" in blob or "list-of-titles" in blob:
            return "INDEX"
        if shelf == "REVISED_2021" or "2021-revised" in blob:
            return "REVISED_2021"
        if shelf == "REVISED_2018":
            return "REVISED_2018"
        if shelf == "REVISED_2014":
            return "REVISED_2014"
        return "REVISED"
    if "gazette" in blob:
        return "GAZETTE"
    if re.search(r"\bact\b", blob) and "bill" not in blob:
        if re.search(r"amendment|amending", blob):
            return "AMENDING_ACT"
        return "ACT"
    if re.search(r"ordinance", blob):
        if re.search(r"amendment|amending", blob):
            return "AMENDING_ORDINANCE"
        return "ORDINANCE"
    if re.search(
        r"regulation|rules?|order|notice|proclamation|instrument|s\.?i\.?|"
        r"subsidiary|commencement|by-?laws?",
        blob,
    ):
        return "SI"
    if shelf in ("ACT", "ORDINANCE", "SI"):
        return shelf
    return ""


def _chapter_key(slug: str) -> str:
    """Normalize revised-law slug to chapter key (strip trailing -2/-3 variants)."""
    s = slug.lower()
    m = re.match(r"^(\d{2}-\d{2}-.+?)(?:-\d+(?:-\d+)*)?$", s)
    if m and re.match(r"^\d{2}-\d{2}-", s):
        base = m.group(1)
        # keep meaningful trailing words; strip only numeric edition suffixes at end
        base = re.sub(r"(-\d+)+$", "", s)
        # if that ate too much, fall back
        if len(base) < 8:
            base = re.sub(r"-\d+$", "", s)
            base = re.sub(r"-\d+$", "", base)
        return base[:160]
    # annual: 1-of-2026-...
    return s[:160]


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(url).path)
    m = re.search(r"/edocman/([^/]+)/(?:viewdocument|fdocument)(?:/\d+)?", path, re.I)
    if m:
        slug = m.group(1)
        key = _chapter_key(slug)
        return re.sub(r"[^\w.\-]+", "_", key).strip("_")[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 4:
            return h
    stem = Path(path).stem
    if stem:
        return re.sub(r"[^\w.\-]+", "_", unquote(stem)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _doc_id(url: str) -> int:
    m = re.search(r"/viewdocument/(\d+)", url)
    return int(m.group(1)) if m else 0


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitut" in blob:
        return 0
    if cat == "INDEX":
        return 1
    if cat == "REVISED_2021":
        return 2
    if cat in ("REVISED", "REVISED_2018"):
        return 3
    if cat == "REVISED_2014":
        return 4
    if cat == "ACT" and "amendment" not in blob:
        return 5
    if cat in ("AMENDING_ACT", "ORDINANCE") and "amendment" not in blob:
        return 6
    if cat in ("AMENDING_ORDINANCE", "SI"):
        return 7
    if cat == "UK_SI":
        return 8
    if cat == "GAZETTE":
        return 9
    return 10


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(url).path)
    m = re.search(r"/edocman/([^/]+)/", path, re.I)
    stem = m.group(1) if m else Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = re.sub(r"^(\d{2})-(\d{2})-", r"\1.\2 ", stem)
    stem = re.sub(r"^(\d+)-of-(\d{4})-", r"\1 of \2 - ", stem, flags=re.I)
    return stem.replace("-", " ").replace("_", " ").replace("+", " ")[:200]


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://gov.tc/agc/",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def discover():
    seen_url, best = set(), {}
    sess = _session()

    def add(url, ts="", title_hint="", cat="", shelf=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        is_edoc = bool(re.search(r"/agc/component/edocman/.+/(?:viewdocument|fdocument)", low))
        is_pdf = ".pdf" in low
        if not is_edoc and not is_pdf:
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
        if not KEEP_RE.search(blob) and not is_edoc:
            return
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            if "constitut" in blob:
                cat = "CONSTITUTION"
            elif re.search(r"\bact\b", blob):
                cat = "ACT"
            elif "ordinance" in blob:
                cat = "ORDINANCE"
            elif "revised" in blob:
                cat = shelf if shelf.startswith("REVISED") else "REVISED"
            else:
                cat = "SI"
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        # canonicalize storage URL to viewdocument form for wayback, keep live via fdocument at fetch
        if "/fdocument" in low and "/viewdocument/" not in low:
            # keep as-is for live; still ok
            pass
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "", shelf or "", _doc_id(url))
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            pr = _rank(prev[0], prev[3], prev[1])
            nr = _rank(row[0], row[3], row[1])
            if nr < pr:
                best[ident] = row
            elif nr == pr:
                if row[6] > prev[6] or (ts or "") > (prev[4] or ""):
                    best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat, shelf="REVISED_2021")

    for base, shelf, _max_page in LIVE_SHELVES:
        try:
            r = sess.get(base, timeout=60)
            if r.status_code != 200:
                log.warning("live %s status=%s", base, r.status_code)
                continue
            before = len(best)
            found = EDOC_RE.findall(r.text or "")
            for href in found:
                full = href if href.startswith("http") else urljoin("https://gov.tc", href)
                full = _norm(full)
                tip = _title_from_path(full)
                add(full, "", tip, shelf=shelf)
            log.info("shelf %s +%s catalog=%s (links=%s)", shelf, len(best) - before, len(best), len(found))
        except Exception as exc:
            log.warning("shelf %s fail: %s", shelf, exc)

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
                if not orig:
                    continue
                if "/viewdocument/" not in orig.lower() and "/fdocument" not in orig.lower():
                    continue
                tip = _title_from_path(orig)
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = [
        (ident, url, hint, cat, ts)
        for ident, url, hint, cat, ts, shelf, did in best.values()
    ]
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), -_doc_id(it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    sess = _session()
    sess.headers["Referer"] = "https://gov.tc/agc/"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
    url = _norm(url)
    candidates = []
    if "/viewdocument/" in url.lower():
        candidates.append(_to_fdocument(url))
        candidates.append(url)
    elif "/fdocument" in url.lower():
        candidates.append(url)
    else:
        candidates.append(url)

    for cand in candidates:
        try:
            r = sess.get(cand, timeout=90, allow_redirects=True)
            body = r.content or b""
            # Sucuri may bounce viewdocument to Google viewer (empty); fdocument should be PDF
            if r.status_code == 200 and body[:4] == b"%PDF" and len(body) <= MAX_PDF:
                from world_lib import pdf_to_text
                text = pdf_to_text(body)
                if text and len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "http_pdf_fdocument" if "fdocument" in cand else "http_pdf_session",
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

    # Wayback of original viewdocument (CDX stores these as application/pdf)
    wb_url = url
    if "/fdocument" in wb_url and "/viewdocument/" not in wb_url:
        # try reconstruct viewdocument from slug only — fetch_official uses wayback_ts+original
        pass
    got = fetch_official(
        url if "/viewdocument/" in url else (candidates[-1] if candidates else url),
        ua=UA, verify=False, min_text=120, wayback_ts=wayback_ts or None,
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
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=src,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_tc.py",
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
            "Attorney General's Chambers (gov.tc/agc Edocman Revised/Annual Laws) / "
            "Official Gazette (gov.tc/cgis; CGIS — subscription for gazette PDFs)"
        ),
        source_urls=[
            "https://gov.tc/agc/",
            "https://gov.tc/agc/laws/revised",
            "https://gov.tc/agc/laws/annual",
            "https://gov.tc/agc/2021-revised-laws",
            "https://gov.tc/cgis/tci-gazettes",
            "https://www.cgis.gov.tc/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (gov.tc/agc 2021 Revised + Annual "
            "Acts/Ordinances/Subsidiary + CDX; CGIS Gazette PDFs subscription-walled)"
        ),
        notes=(
            f"Official gov.tc/agc Edocman (viewdocument→fdocument live PDF) + "
            f"Wayback CDX of viewdocument captures. Prefer Constitution + 2021 Revised "
            f"Ordinances + Annual Acts/Ordinances/SIs. CGIS Official Gazette listed but "
            f"PDFs require subscription (not scraped). Skip bills/drafts/press. "
            f"OCR eng used={ocr_used}. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
