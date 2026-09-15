#!/usr/bin/env python3
"""Bermuda: bermudalaws.bm (Attorney-General's Chambers Drafting Section /
Bermuda Laws Online) + Official Gazette cross-links on gov.bm.

Official-only *.bermudalaws.bm / *.gov.bm. Live Laws/ + Document/{uuid} PDFs,
RSS feeds, letter/search shelves + CDX of the same official URLs.
Not vLex / commercial aggregators.
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
from xml.etree import ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "bm", "Bermuda", "en"
SOURCE_TYPE = "bermudalaws_bm"
LICENSE = (
    "Government of Bermuda — Bermuda Laws Online (bermudalaws.bm; Attorney-General's "
    "Chambers Drafting Section) + Official Gazette (gov.bm). Crown Copyright. "
    "Authentic Official Gazette / Bermuda Laws Online text prevails. Site material "
    "does not yet have official sanction for all consolidations — verify currency. "
    "Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.bermudalaws.bm/)"
)
# Commonwealth drafting: Section / s. / Article / Schedule
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule|PART)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("bm")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "bermudalaws.bm",
    "www.bermudalaws.bm",
    "gov.bm",
    "www.gov.bm",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|vacancy|tender|questionnaire|"
    r"organisational.?chart|organizational.?chart|explanatory.?memorandum|"
    r"\bbill\b|_INTRODUCED|draft-|draft_|draft\s|"
    r"fact[-_ ]?sheet|consultation|infographic|judgment|judgement|"
    r"pati.?information|drafting.?instructions|drafting.?section.?protocols|"
    r"employer\s*-|v\s+employer|physician.?survey|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(legislation|gazette|act|acts|constitution|regulation|order|rules?|"
    r"statutory|instrument|notice|proclamation|br\s*\d|/Laws/|/Document/|"
    r"consolidated|annual.?law|special.?development|amendment|"
    r"sites/default/files)",
    re.I,
)
CDX_PREFIXES = (
    "bermudalaws.bm/Document/",
    "www.bermudalaws.bm/Document/",
    "bermudalaws.bm/Laws/",
    "www.bermudalaws.bm/Laws/",
    "bermudalaws.bm/laws/",
    "www.bermudalaws.bm/laws/",
    # Narrow gov.bm enacted Acts sometimes published under sites/default/files/YYYY-MM/
    "www.gov.bm/sites/default/files/2024-",
    "www.gov.bm/sites/default/files/2025-",
    "www.gov.bm/sites/default/files/2026-",
)
RSS_FEEDS = (
    "https://www.bermudalaws.bm/annuallaw.rss",
    "https://www.bermudalaws.bm/consolidatedlaw.rss",
    "https://www.bermudalaws.bm/gazette.rss",
    "https://www.bermudalaws.bm/specialdevelopmentorder.rss",
)
# Search shelves (Blazor prerender ≈40 results each) — prefer Consolidated via queries
SEARCH_QUERIES = (
    ["Constitution Order", "Constitution", "Interpretation Act", "Human Rights Act",
     "Companies Act", "Criminal Code", "Evidence Act", "Police Act", "Immigration"]
    + [f"{c}*" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    + [f"{a}{b}*" for a in "ABCDEFGHILMNPRST" for b in "aeiou"]  # digraph expand
    + [str(y) for y in range(2018, 2027)]
)
SEED_DOCS = (
    (
        "https://www.bermudalaws.bm/Laws/Consolidated%20Law/1968/Bermuda%20Constitution%20Order%201968",
        "Bermuda Constitution Order 1968",
        "CONSTITUTION",
    ),
)
LIVE_PAGES = (
    "https://www.bermudalaws.bm/",
    "https://www.bermudalaws.bm/LawIndex",
    "https://www.bermudalaws.bm/gazette",
    "https://www.bermudalaws.bm/latestdevelopments",
    "https://www.gov.bm/official-gazette",
    "https://www.gov.bm/theofficialgazette",
    "https://www.gov.bm/department/attorney-generals-chambers",
)

UUID_RE = re.compile(
    r"(?:%7[Bb]|\{)?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:%7[Dd]|\})?",
    re.I,
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    host = (urlparse(url).hostname or "").lower()
    # Drop cache-busters on PDFs / Document links; keep path
    if "?" in url and (
        ".pdf" in url.lower()
        or "/document/" in url.lower()
        or "/laws/" in url.lower()
    ):
        url = url.split("?")[0]
    if host.endswith("bermudalaws.bm") or host.endswith("gov.bm"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    # Prefer www.bermudalaws.bm; normalize Document UUID braces away
    if host in ("bermudalaws.bm", "www.bermudalaws.bm"):
        url = url.replace("://bermudalaws.bm", "://www.bermudalaws.bm", 1)
        m = re.search(r"/Document/(.+)$", url, re.I)
        if m:
            uid_m = UUID_RE.search(unquote(m.group(1)))
            if uid_m:
                url = f"https://www.bermudalaws.bm/Document/{uid_m.group(1).lower()}"
    # Encode spaces in Laws paths carefully
    try:
        parts = urlparse(url)
        if parts.path and (" " in parts.path or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%~") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(
        ".gov.bm"
    ) or host.endswith(".bermudalaws.bm")


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    path = unquote(urlparse(url).path)
    pl = path.lower()
    if "constitut" in blob:
        return "CONSTITUTION"
    if "/laws/consolidated" in pl or "consolidated law" in blob:
        if re.search(r"\bact\b", blob) and "bill" not in blob:
            return "CONSOLIDATED_ACT"
        if re.search(r"regulation|rules?|order|notice|instrument|br\s*\d", blob):
            return "CONSOLIDATED_SI"
        return "CONSOLIDATED"
    if "/laws/annual" in pl or "annual law" in blob:
        if "/acts/" in pl or (re.search(r"\bact\b", blob) and "bill" not in blob):
            return "ANNUAL_ACT"
        return "ANNUAL_SI"
    if "special development" in blob or "/laws/sdo/" in pl:
        return "SDO"
    if "/document/" in pl:
        if re.search(r"\bact\b", blob) and "bill" not in blob:
            return "ACT"
        if re.search(r"regulation|rules?|order|notice|instrument", blob):
            return "SI"
        return "DOCUMENT"
    if "gazette" in blob or "/theofficialgazette" in pl:
        return "GAZETTE"
    if re.search(r"\bact\b", blob) and "bill" not in blob and "fact" not in blob:
        return "ACT"
    if re.search(r"regulation|statutory|instrument|notice|order", blob):
        return "SI"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(url).path)
    # Document UUID
    m = re.search(r"/Document/(.+)$", path, re.I)
    if m:
        uid_m = UUID_RE.search(m.group(1))
        if uid_m:
            return f"doc_{uid_m.group(1).lower()}"
    # Laws/.../Year/Title
    m = re.search(
        r"/Laws/([^/]+)/(?:([^/]+)/)?(\d{4})/([^/]+?)(?:\.pdf)?$",
        path,
        re.I,
    )
    if m:
        kind, sub, year, title = m.groups()
        kind_l = kind.lower().replace(" ", "_")
        title_s = re.sub(r"[^\w.\-]+", "_", title).strip("_")[:120]
        prefix = "consol" if "consolidat" in kind_l else (
            "sdo" if kind_l == "sdo" or "special" in kind_l else "annual"
        )
        if sub and "act" in sub.lower():
            prefix = f"{prefix}_act"
        elif sub and ("stat" in sub.lower() or "instrument" in sub.lower()):
            prefix = f"{prefix}_si"
        return f"{prefix}_{year}_{title_s}"[:160]
    # Older Consolidated Laws/*.pdf
    m = re.search(r"/laws/Consolidated%20Laws/([^/]+?)(?:\.pdf)?$", path, re.I) or re.search(
        r"/laws/Consolidated Laws/([^/]+?)(?:\.pdf)?$", path, re.I
    )
    if m:
        title_s = re.sub(r"[^\w.\-]+", "_", unquote(m.group(1))).strip("_")[:140]
        return f"consol_{title_s}"[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 6:
            return h
    stem = Path(path).stem
    if stem and stem.lower() not in ("document", "laws"):
        return re.sub(r"[^\w.\-]+", "_", unquote(stem)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    path = unquote(urlparse(url).path).lower()
    if cat == "CONSTITUTION" or "constitut" in blob:
        return 0
    if cat == "CONSOLIDATED_ACT" or (
        "consolidated" in path and "act" in blob and "amendment" not in blob
    ):
        return 1
    if cat == "CONSOLIDATED" or cat == "CONSOLIDATED_SI" or "consolidated" in path:
        return 2
    if cat in ("ANNUAL_ACT", "ACT") or ("/acts/" in path and "annual" in path):
        return 3
    if cat in ("ANNUAL_SI", "SI", "DOCUMENT"):
        return 4
    if cat == "SDO":
        return 5
    if cat == "GAZETTE" or "gazette" in blob:
        return 6
    return 7


def _prefer_url(new: str, old: str) -> bool:
    n, o = unquote(new).lower(), unquote(old).lower()
    # Prefer Consolidated Law path over Annual / Document UUID alone
    n_c = "consolidated" in n
    o_c = "consolidated" in o
    if n_c and not o_c:
        return True
    if o_c and not n_c:
        return False
    # Prefer Laws/ path over bare Document/
    n_l = "/laws/" in n
    o_l = "/laws/" in o
    if n_l and not o_l:
        return True
    if o_l and not n_l:
        return False
    return False


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(url).path)
    if "/Document/" in path:
        return ""
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    return stem.replace("_", " ").replace("+", " ")[:200]


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        is_doc = "/document/" in low
        is_laws = "/laws/" in low
        is_pdf = ".pdf" in low or is_doc or is_laws
        if not is_pdf:
            return
        if not _host_ok(url):
            return
        # gov.bm: only keep clear enacted Act / Amendment Act / BR PDFs
        host = (urlparse(url).hostname or "").lower()
        if host.endswith("gov.bm"):
            if not re.search(
                r"(amendment\s*act|act\s*20\d{2}|act_20\d{2}|%20act%20|regulation|"
                r"bermuda\s+regulation|\bbr[_\-\s]?\d)",
                low + " " + (title_hint or ""),
                re.I,
            ):
                return
            if SKIP_RE.search(low + " " + (title_hint or "")):
                return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and not is_doc and not is_laws:
            return
        cat = cat or _category(url, title_hint)
        if not cat and not is_doc and not is_laws:
            return
        if not cat:
            cat = "DOCUMENT" if is_doc else "CONSOLIDATED" if "consolidat" in low else "ANNUAL_ACT"
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        # Collapse brace/non-brace Document variants via ident
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            if _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
                best[ident] = row
            elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
                if _prefer_url(row[1], prev[1]) or (ts or "") > (prev[4] or ""):
                    best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat)

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/rss+xml,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # RSS — recent Annual / Consolidated / Gazette / SDO Document UUIDs
    for feed in RSS_FEEDS:
        try:
            r = sess.get(feed, timeout=45)
            if r.status_code != 200:
                log.warning("rss %s status=%s", feed, r.status_code)
                continue
            root = ET.fromstring(r.content)
            before = len(best)
            for it in root.findall(".//item"):
                link = (it.findtext("link") or "").strip()
                title = (it.findtext("title") or "").strip()
                desc = (it.findtext("description") or "").strip()
                cat = ""
                blob = f"{title} {desc} {feed}".lower()
                if "constitut" in blob:
                    cat = "CONSTITUTION"
                elif "consolidated" in feed.lower() or "consolidated" in blob:
                    cat = "CONSOLIDATED_ACT" if "act" in blob else "CONSOLIDATED_SI"
                elif "gazette" in feed.lower():
                    cat = "GAZETTE"
                elif "special" in feed.lower() or "sdo" in blob:
                    cat = "SDO"
                elif "act" in blob and "bill" not in blob:
                    cat = "ANNUAL_ACT"
                else:
                    cat = "ANNUAL_SI"
                add(link, "", title[:200], cat)
            log.info("rss %s +%s catalog=%s", feed.split("/")[-1], len(best) - before, len(best))
        except Exception as exc:
            log.warning("rss %s fail: %s", feed, exc)

    # Live landing pages
    for page in LIVE_PAGES:
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                log.warning("live %s status=%s", page, r.status_code)
                continue
            before = len(best)
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text, re.I):
                full = urljoin(r.url, href)
                if "/Document/" in full or "/Laws/" in full or "/laws/" in full or ".pdf" in full.lower():
                    tip = _title_from_path(full)
                    add(full, "", tip)
            log.info("live %s +%s catalog=%s", page.split("/")[-1] or page, len(best) - before, len(best))
        except Exception as exc:
            log.warning("live %s fail: %s", page, exc)

    # Search shelves (prerender page-1 only; digraphs expand coverage)
    max_search = env_int("BM_SEARCH_QUERIES", len(SEARCH_QUERIES))
    for q in SEARCH_QUERIES[:max_search]:
        page = f"https://www.bermudalaws.bm/search/{quote(q, safe='*')}"
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                continue
            before = len(best)
            for href in re.findall(
                r'href=["\'](https://www\.bermudalaws\.bm/Laws/[^"\']+)["\']', r.text, re.I
            ):
                tip = _title_from_path(href)
                add(href, "", tip)
            # Relative Laws links
            for href in re.findall(r'href=["\'](/Laws/[^"\']+)["\']', r.text, re.I):
                full = urljoin("https://www.bermudalaws.bm/", href)
                tip = _title_from_path(full)
                add(full, "", tip)
            log.info("search %s +%s catalog=%s", q[:40], len(best) - before, len(best))
        except Exception as exc:
            log.warning("search %s fail: %s", q, exc)

    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            before = len(best)
            extra = ["mimetype:application/pdf"]
            # Laws/ paths sometimes lack pdf mimetype in CDX
            if "/Laws" in prefix or "/laws" in prefix:
                hits = list(cdx_urls(prefix, limit=lim, match_type="prefix"))
            else:
                hits = list(
                    cdx_urls(
                        prefix,
                        limit=lim,
                        match_type="prefix",
                        extra_filters=extra,
                    )
                )
            for h in hits:
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig:
                    continue
                tip = _title_from_path(orig)
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = list(best.values())
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    """Live session first; fetch_official/Wayback fallback."""
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "application/pdf,application/octet-stream,text/html,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.bermudalaws.bm/",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    url = _norm(url)
    try:
        r = sess.get(url, timeout=90, allow_redirects=True)
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
                    "source_url": url,
                }
            text2, how, pages = ocr_pdf(body)
            if text2 and len(text2) >= 100:
                return {
                    "status": "success",
                    "text": text2,
                    "content": body,
                    "method": f"ocr:{how}",
                    "error": "",
                    "source_url": url,
                }
    except Exception as exc:
        log.debug("session fetch fail %s: %s", url[:80], exc)

    got = fetch_official(
        url, ua=UA, verify=False, min_text=120, wayback_ts=wayback_ts or None
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
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bm.py",
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
        source="Bermuda Laws Online (bermudalaws.bm / AG Chambers) / Official Gazette (gov.bm)",
        source_urls=[
            "https://www.bermudalaws.bm/",
            "https://www.bermudalaws.bm/LawIndex",
            "https://www.bermudalaws.bm/annuallaw.rss",
            "https://www.bermudalaws.bm/consolidatedlaw.rss",
            "https://www.bermudalaws.bm/gazette.rss",
            "https://www.bermudalaws.bm/specialdevelopmentorder.rss",
            "https://www.bermudalaws.bm/Laws/Consolidated%20Law/1968/Bermuda%20Constitution%20Order%201968",
            "https://www.gov.bm/official-gazette",
            "https://www.gov.bm/department/attorney-generals-chambers",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (bermudalaws.bm Consolidated/Annual Laws + "
            "Document UUID PDFs + RSS + Official Gazette cross-links + CDX)"
        ),
        notes=(
            f"Official bermudalaws.bm (AG Chambers Drafting Section) Laws/ + Document/"
            f"{{uuid}} PDFs + RSS (Annual/Consolidated/Gazette/SDO) + letter/search "
            f"shelves + Wayback CDX. Prefer Constitution + Consolidated Acts + Annual "
            f"Acts + SIs. Skip bills/drafts/fact-sheets/judgments. OCR eng used={ocr_used}. "
            f"Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
