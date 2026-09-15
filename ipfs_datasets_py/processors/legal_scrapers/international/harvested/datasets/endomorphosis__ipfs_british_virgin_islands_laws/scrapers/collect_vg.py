#!/usr/bin/env python3
"""British Virgin Islands: laws.gov.vg (Virgin Islands Laws Online / Attorney
General's Chambers) + Official Gazette (eservices.gov.vg/gazette) + gov.vg
Cabinet Office Gazette bulletins.

Official-only *.gov.vg. Live Drupal shelves (Constitution / In force / Revised /
Imperial / Consolidated Index) + embedded sites/default/files PDFs + CDX of the
same official URLs. Skip bills. Not vLex / commercial aggregators.
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

CC, COUNTRY, LANG = "vg", "British Virgin Islands", "en"
SOURCE_TYPE = "laws_gov_vg"
LICENSE = (
    "Government of the Virgin Islands (British Virgin Islands) — laws.gov.vg "
    "(Virgin Islands Laws Online / Attorney General's Chambers) + Official Gazette "
    "(eservices.gov.vg/gazette; Cabinet Office Gazette Unit) + gov.vg Gazette "
    "bulletins. Authentic Official Gazette / Government Printer text prevails. "
    "Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://laws.gov.vg/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule|PART)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("vg")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "laws.gov.vg", "www.laws.gov.vg", "gov.vg", "www.gov.vg",
    "eservices.gov.vg", "bvi.gov.vg", "www.bvi.gov.vg",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|vacancy|tender|questionnaire|"
    r"organisational.?chart|organizational.?chart|explanatory.?memorandum|"
    r"\bbill\b|/bills/|_INTRODUCED|draft-|draft_|draft\s|"
    r"credit.?card.?authorization|electoral.?candidates.?decla|"
    r"cabinet.?office.?logo|official.?vigilate|"
    r"privacy.?policy|refunds.?and.?returns|faqs|"
    r"premier.?debates|strategic.?action.?plan|press.?release|"
    r"speech|budget.?address|throne.?speech|consultation.?paper|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(legislation|gazette|act|acts|constitution|regulation|order|rules?|"
    r"statutory|instrument|notice|proclamation|subsidiary|revised|"
    r"consolidated.?index|s\.?i\.?|si[\s_\-]|sites/default/files)",
    re.I,
)
CDX_PREFIXES = (
    "laws.gov.vg/sites/default/files/",
    "www.laws.gov.vg/sites/default/files/",
    # Narrow gov.vg: Gazette Unit bulletins / consolidated index only (YYYY-MM folders)
    "gov.vg/sites/default/files/2024-",
    "gov.vg/sites/default/files/2025-",
    "gov.vg/sites/default/files/2026-",
    "www.gov.vg/sites/default/files/2024-",
    "www.gov.vg/sites/default/files/2025-",
    "www.gov.vg/sites/default/files/2026-",
    "eservices.gov.vg/gazette/sites/eservices.gov.vg.gazette/files/",
)
SEED_DOCS = (
    ("https://laws.gov.vg/laws/virgin-islands-constitution-order-2007",
     "Virgin Islands (Constitution) Order 2007", "CONSTITUTION"),
    ("https://laws.gov.vg/laws/virgin-islands-constitution-amendment-order-2015",
     "Virgin Islands (Constitution) (Amendment) Order 2015", "CONSTITUTION"),
    ("https://laws.gov.vg/laws/virgin-islands-constitution-order-1976",
     "Virgin Islands (Constitution) Order 1976", "CONSTITUTION"),
    ("https://laws.gov.vg/laws/virgin-islands-constitution-order-1967",
     "Virgin Islands (Constitution) Order 1967", "CONSTITUTION"),
    ("https://laws.gov.vg/sites/default/files/2026-02/Final%20Consolidated%20Index%20with%20User%20Guide%20as%20at%20January%201%2C%202026.pdf",
     "Consolidated Index of Virgin Islands Legislation as at 1 January 2026", "INDEX"),
)
LIVE_SHELVES = (
    ("https://laws.gov.vg/viconstitution", "CONSTITUTION", 0),
    ("https://laws.gov.vg/revised-laws", "REVISED", 5),
    ("https://laws.gov.vg/inforce", "INFORCE", 45),
    ("https://laws.gov.vg/imperial", "IMPERIAL", 2),
    ("https://laws.gov.vg/alphabet-listing-all", "INFORCE", 12),
    ("https://laws.gov.vg/index", "INDEX", 0),
)
GOV_GAZETTE_NEWS = (
    "https://gov.vg/news/gazette-no-29-2026-available-public-review",
    "https://gov.vg/news/first-two-acts-2026-gazetted-public-review",
    "https://www.gov.vg/news/consolidated-index-virgin-islands-legislation-updated-1-january-2026",
)
LAW_PATH_RE = re.compile(
    r'href=["\']((?:https://(?:www\.)?laws\.gov\.vg)?(?:/index\.php)?/laws/[^"\'?#]+)',
    re.I,
)
PDF_DATA_RE = re.compile(
    r'data-src=["\'](https?://[^"\']+\.pdf)["\']',
    re.I,
)
PDF_HREF_RE = re.compile(
    r'href=["\']([^"\']+\.pdf[^"\']*)["\']',
    re.I,
)
PDF_FILES_RE = re.compile(
    r'(https?://(?:(?:www\.)?laws\.gov\.vg|(?:www\.)?gov\.vg|eservices\.gov\.vg)' 
    r'/[^\s"\'<>]+\.pdf)',
    re.I,
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    host = (urlparse(url).hostname or "").lower()
    if "?" in url and ".pdf" in url.lower():
        url = url.split("?")[0]
    if host.endswith("gov.vg") or host.endswith("laws.gov.vg"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    if host == "www.laws.gov.vg":
        url = url.replace("://www.laws.gov.vg", "://laws.gov.vg", 1)
    if host == "www.gov.vg":
        url = url.replace("://www.gov.vg", "://gov.vg", 1)
    url = re.sub(r"https://laws\.gov\.vg/index\.php/laws/", "https://laws.gov.vg/laws/", url, flags=re.I)
    url = re.sub(r"https://laws\.gov\.vg/Laws/", "https://laws.gov.vg/laws/", url)
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
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(".gov.vg")


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    path = unquote(urlparse(url).path).lower()
    if "constitut" in blob:
        return "CONSTITUTION"
    if shelf == "INDEX" or "consolidated index" in blob or "consolidated%20index" in path:
        return "INDEX"
    if shelf == "REVISED" or "/revised" in blob:
        if re.search(r"\bact\b", blob) and "bill" not in blob:
            return "REVISED_ACT"
        return "REVISED"
    if shelf == "IMPERIAL" or "imperial" in blob or "overseas.?territor" in blob:
        return "IMPERIAL"
    if "gazette" in blob:
        return "GAZETTE"
    if re.search(r"\bact\b", blob) and "bill" not in blob:
        if re.search(r"amendment|amending", blob):
            return "AMENDING_ACT"
        return "ACT"
    if re.search(
        r"regulation|rules?|order|notice|proclamation|instrument|s\.?i\.?|"
        r"subsidiary|code.?of.?practice|by-?laws?",
        blob,
    ):
        return "SI"
    if shelf == "INFORCE":
        return "INFORCE"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(url).path)
    m = re.search(r"/laws/([^/]+?)/?$", path, re.I)
    if m:
        return re.sub(r"[^\w.\-]+", "_", m.group(1)).strip("_")[:160]
    m = re.search(r"/sites/default/files/\d{4}-\d{2}/([^/]+?)(?:\.pdf)?$", path, re.I)
    if m:
        title_s = re.sub(r"[^\w.\-]+", "_", unquote(m.group(1))).strip("_")[:140]
        return title_s[:160]
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
    if cat == "CONSTITUTION" or "constitut" in blob:
        return 0
    if cat == "INDEX":
        return 1
    if cat in ("REVISED_ACT", "REVISED"):
        return 2
    if cat == "ACT" and "amendment" not in blob:
        return 3
    if cat in ("AMENDING_ACT", "INFORCE"):
        return 4
    if cat == "SI":
        return 5
    if cat == "IMPERIAL":
        return 6
    if cat == "GAZETTE" or "gazette" in blob:
        return 7
    return 8


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(url).path)
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = re.sub(r"^Act\s*No\.?\s*\d+\s*of\s*\d{4}[\s\-–—]+", "", stem, flags=re.I)
    stem = re.sub(r"^S\.?I\.?\s*No\.?\s*\d+\s*of\s*\d{4}[\s\-–—]+", "", stem, flags=re.I)
    return stem.replace("_", " ").replace("+", " ")[:200]


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def _extract_pdfs_from_html(html: str, base: str = "https://laws.gov.vg/") -> list[str]:
    out = []
    for m in PDF_DATA_RE.finditer(html or ""):
        out.append(m.group(1))
    for m in PDF_HREF_RE.finditer(html or ""):
        out.append(urljoin(base, m.group(1)))
    for m in PDF_FILES_RE.finditer(html or ""):
        out.append(m.group(1))
    for m in re.finditer(r"file=(https?%3A%2F%2F[^\"'&]+\.pdf)", html or "", re.I):
        out.append(unquote(m.group(1)))
    return [_norm(u) for u in out if u]


def _resolve_law_pdf(sess: requests.Session, law_url: str) -> tuple[str, str]:
    law_url = _norm(law_url)
    try:
        r = sess.get(law_url, timeout=45)
        if r.status_code != 200:
            return "", ""
        pdfs = _extract_pdfs_from_html(r.text, r.url)
        pdfs = [p for p in pdfs if _host_ok(p) and ".pdf" in p.lower()]
        pdfs.sort(key=lambda u: (0 if "laws.gov.vg/sites/default/files" in u else 1, len(u)))
        title = ""
        m = re.search(r"<h1[^>]*>(.*?)</h1>", r.text, re.I | re.S)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1))
            title = re.sub(r"\s+", " ", title).strip()[:200]
        return (pdfs[0] if pdfs else ""), title
    except Exception as exc:
        log.debug("resolve fail %s: %s", law_url[:80], exc)
        return "", ""


def discover():
    seen_url, best = set(), {}
    sess = _session()

    def add(url, ts="", title_hint="", cat="", shelf=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        is_pdf = ".pdf" in low
        is_law_page = bool(re.search(r"laws\.gov\.vg/(?:index\.php/)?laws/[^/]+/?$", low))
        if not is_pdf and not is_law_page:
            return
        if not _host_ok(url):
            return
        host = (urlparse(url).hostname or "").lower()
        if "laws.gov.vg" not in host and host.endswith("gov.vg"):
            gblob = f"{low} {title_hint}"
            if not re.search(
                r"(gazette|consolidated.?index|constitution.?order|"
                r"act[_\-\s].*20\d{2}|act,\s*20\d{2}|s\.?i\.?\s*no|"
                r"regulation|proclamation|statutory)",
                gblob,
                re.I,
            ):
                return
        blob = f"{low} {title_hint} {cat} {shelf}"
        if SKIP_RE.search(blob):
            return
        if "/bills/" in low:
            return
        if re.search(r"\bbill\b", title_hint or "", re.I) and "act" not in (title_hint or "").lower():
            if "bills of lading" not in (title_hint or "").lower():
                return
        if not KEEP_RE.search(blob) and not is_law_page and "constitution" not in blob:
            if not re.search(r"act|order|regulation|rules|proclamation|instrument|gazette|index|si[\s_\-]", low):
                return
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            if is_law_page:
                cat = "INFORCE"
            elif "gazette" in low:
                cat = "GAZETTE"
            else:
                cat = "ACT" if re.search(r"\bact\b", blob) else "SI"
        ident = _ident_from_url(url, title_hint)
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
            prev_pdf = ".pdf" in prev[1].lower()
            new_pdf = ".pdf" in url.lower()
            if new_pdf and not prev_pdf:
                best[ident] = row
            elif _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
                best[ident] = row
            elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
                if (ts or "") > (prev[4] or "") or (new_pdf and not prev_pdf):
                    best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat)

    for base, shelf, max_page in LIVE_SHELVES:
        for pg in range(0, max_page + 1):
            page = base if pg == 0 else f"{base}?page={pg}"
            try:
                r = sess.get(page, timeout=45)
                if r.status_code != 200:
                    log.warning("live %s status=%s", page, r.status_code)
                    break
                before = len(best)
                for pdf in _extract_pdfs_from_html(r.text, r.url):
                    tip = _title_from_path(pdf)
                    add(pdf, "", tip, shelf=shelf)
                for href in LAW_PATH_RE.findall(r.text):
                    full = href if href.startswith("http") else urljoin("https://laws.gov.vg/", href)
                    full = _norm(full)
                    tip = _title_from_path(full).replace("-", " ")
                    add(full, "", tip, shelf=shelf)
                log.info("shelf %s p%s +%s catalog=%s", shelf, pg, len(best) - before, len(best))
                if pg > 0:
                    pages = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
                    if pages and pg > max(pages):
                        break
                    if not LAW_PATH_RE.findall(r.text) and not _extract_pdfs_from_html(r.text):
                        break
            except Exception as exc:
                log.warning("shelf %s p%s fail: %s", shelf, pg, exc)
                break

    for page in GOV_GAZETTE_NEWS:
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                continue
            before = len(best)
            for href in PDF_HREF_RE.findall(r.text):
                full = urljoin(r.url, href)
                if not _host_ok(full):
                    continue
                tip = _title_from_path(full)
                cat = "GAZETTE"
                if "index" in (full + tip).lower():
                    cat = "INDEX"
                elif re.search(r"\bact\b", tip, re.I) and "bill" not in tip.lower():
                    cat = "ACT"
                add(full, "", tip, cat, shelf="GAZETTE")
            log.info("gov news %s +%s catalog=%s", page.split("/")[-1][:40], len(best) - before, len(best))
        except Exception as exc:
            log.warning("gov news fail %s: %s", page, exc)

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
                tip = _title_from_path(orig)
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    resolve_cap = env_int("VG_RESOLVE_LIMIT", 400)
    pending = [
        row for row in best.values()
        if ".pdf" not in row[1].lower() and "/laws/" in row[1].lower()
    ]
    pending.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    resolved = 0
    for ident, url, hint, cat, ts, shelf in pending[:resolve_cap]:
        pdf, page_title = _resolve_law_pdf(sess, url)
        if not pdf:
            continue
        if ident in best and ".pdf" not in best[ident][1].lower():
            del best[ident]
            seen_url.discard(url)
        tip = page_title or hint or _title_from_path(pdf)
        add(pdf, ts, tip, cat, shelf=shelf)
        resolved += 1
        if resolved % 50 == 0:
            log.info("resolved %s/%s catalog=%s", resolved, min(len(pending), resolve_cap), len(best))
    log.info("resolved_pdfs=%s pending_were=%s", resolved, len(pending))

    items = [
        (ident, url, hint, cat, ts)
        for ident, url, hint, cat, ts, shelf in best.values()
        if ".pdf" in url.lower()
    ]
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s (pdfs)", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    sess = _session()
    sess.headers["Referer"] = "https://laws.gov.vg/"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_vg.py",
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
            "Virgin Islands Laws Online (laws.gov.vg / AG Chambers) / "
            "Official Gazette (eservices.gov.vg/gazette) / gov.vg Cabinet Office"
        ),
        source_urls=[
            "https://laws.gov.vg/",
            "https://laws.gov.vg/viconstitution",
            "https://laws.gov.vg/inforce",
            "https://laws.gov.vg/revised-laws",
            "https://laws.gov.vg/imperial",
            "https://laws.gov.vg/index",
            "https://eservices.gov.vg/gazette/",
            "https://gov.vg/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (laws.gov.vg Constitution/In-force/Revised/"
            "Imperial + Consolidated Index + gov.vg Gazette bulletins + CDX)"
        ),
        notes=(
            f"Official laws.gov.vg (AG Chambers) Drupal shelves + "
            f"sites/default/files PDFs + Constitution Orders + Consolidated Index + "
            f"gov.vg Cabinet Office Gazette bulletin PDFs + Wayback CDX. Prefer "
            f"Constitution + Revised Acts + In-force Acts/SIs. Skip bills/drafts. "
            f"OCR eng used={ocr_used}. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
