#!/usr/bin/env python3
"""Grenada: laws.gov.gd (Chapters / Acts / S.R.&O.) + Official Gazette (gazettes.gov.gd).

Official-only *.gov.gd. Live eDocMan shelves + Government Printery Gazette PDFs +
CDX of the same official URLs. Not vLex / commercial aggregators.
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
from urllib.parse import urljoin, urlparse, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "gd", "Grenada", "en"
SOURCE_TYPE = "laws_gov_gd"
LICENSE = (
    "Government of Grenada — laws.gov.gd / Official Gazette (gazettes.gov.gd; "
    "Government Printery; Ministry of Legal Affairs). "
    "Authentic Official Gazette / Government Printer text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://laws.gov.gd/)"
)
# Commonwealth Cap / Constitution densify (OECS Cap-style Section split)
# Short Cap headings + legal openers; ART_NARROW for gazette shells / speeches.
ART = re.compile(
    r"(?im)^\s*((?:Section|SECTION|Article|Art\.?|SCHEDULE|Schedule|PART|Part|CHAPTER|Chapter)\s+[0-9IVXLC]+[A-Za-z]?\b|"
    r"s\.\s*[0-9]+[A-Za-z]?\b|"
    r"\d+[A-Za-z]?\.\s+[A-Z][A-Za-z0-9'()\-/ ,\"]{0,55}\.?\s*$|"
    r"\d+[A-Za-z]?\.\s+(?:This |In |These |The |For |Any |Every |Where |If |Subject |"
    r"No |Nothing |Notwithstanding |On |It |Whenever |Unless |Except |"
    r"\([0-9]|[\"'])"
    r")"
)
ART_NARROW = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("gd")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "laws.gov.gd",
    "gazettes.gov.gd",
    "gov.gd",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|directory|emergency.?shelter|"
    r"vacancy|tender|questionnaire|communiqu|budget.?address|"
    r"\bbill\b|draft-|draft_|draft\s|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|"
    r"gen-pdf-\d|thumbs?/)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|act|acts|constitution|cap|chapter|statutory|instrument|"
    r"s[_ ]?r[_ ]?&?o|sro|regulation|order|rules?|proclamation|"
    r"/chapters/|/acts/|/s-r-o/|/publications/|/download|viewdocument|"
    r"extraordinary|extra-?ordinary)",
    re.I,
)
CDX_PREFIXES = (
    "laws.gov.gd/index.php/chapters/",
    "www.laws.gov.gd/index.php/chapters/",
    "laws.gov.gd/index.php/acts/",
    "www.laws.gov.gd/index.php/acts/",
    "laws.gov.gd/index.php/s-r-o/",
    "www.laws.gov.gd/index.php/s-r-o/",
    "gazettes.gov.gd/index.php/component/edocman/",
    "gazettes.gov.gd/publications/",
    "www.gazettes.gov.gd/publications/",
    "www.gov.gd/pdf/",
    "gov.gd/pdf/",
)
SEED_DOCS = (
    (
        "https://www.gov.gd/pdf/Cap177%20-%20MAGISTRATES%20ACT.pdf",
        "Magistrates Act Cap. 177",
        "CAP",
    ),
    (
        "https://www.gov.gd/pdf/Cap179%20-%20MAGISTRATES%20PROTECTION%20ACT.pdf",
        "Magistrates Protection Act Cap. 179",
        "CAP",
    ),
    (
        "https://www.gov.gd/index.php/government/the-constitution",
        "Constitution of Grenada",
        "CONSTITUTION",
    ),
)
GAZETTE_YEARS = tuple(range(2026, 2014, -1))  # 2026..2015


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    # Prefer canonical download URL over viewdocument
    if "/viewdocument/" in url:
        url = re.sub(r"/viewdocument/\d+/?$", "/download", url)
    if "?" in url and (".pdf" in url.lower() or url.rstrip("/").endswith("/download")):
        url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("gov.gd"):
        url = url.replace("http://", "https://").replace(":80/", "/")
        # drop www for laws/gazettes consistency except gov.gd pdfs often use www
        if host in ("www.laws.gov.gd", "www.gazettes.gov.gd"):
            url = url.replace("://www.", "://", 1)
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK)


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob:
        return "CONSTITUTION"
    if "/chapters/" in blob or re.search(r"\bcap\.?\s*\d|chapter\s+\d", blob):
        return "CAP"
    if "/s-r-o/" in blob or re.search(r"\bs\.?r\.?&?o|sro\b|statutory", blob):
        return "SRO"
    if "/acts/" in blob or re.search(r"\bact\s*no|act\b", blob):
        if "gazette" in blob and "/acts/" not in blob:
            pass
        else:
            return "ACT"
    if "gazette" in blob or "/publications/" in blob or "extraordinary" in blob:
        return "GAZETTE"
    if re.search(r"regulation|order|rules?|proclamation", blob):
        return "SRO"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem and len(stem) > 6:
            return stem
    path = unquote(urlparse(url).path)
    # .../994-cap1-abatement-of-litter-act/download -> 994-cap1-...
    parts = [p for p in path.strip("/").split("/") if p and p != "download"]
    if parts:
        stem = parts[-1]
        stem = re.sub(r"^viewdocument$", parts[-2] if len(parts) > 1 else stem, stem)
        return stem[:160]
    return (Path(path).stem[:160] or "doc")


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitution" in blob:
        return 0
    if cat == "CAP" or "/chapters/" in blob or re.search(r"\bcap\.?\s*\d|cap\d", blob):
        return 1
    if cat == "ACT" or "/acts/" in blob:
        return 2
    if cat == "SRO" or "/s-r-o/" in blob or "sro" in blob or "sr-o" in blob:
        return 3
    if cat == "GAZETTE" or "gazette" in blob or "/publications/" in blob:
        return 4
    return 5


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def _get(sess: requests.Session, url: str, timeout: int = 45) -> requests.Response:
    """GET with Grenada humans_* cookie challenge handling."""
    r = sess.get(url, timeout=timeout, allow_redirects=True)
    if r.status_code == 409 and "humans_" in (r.text or ""):
        m = re.search(r'document\.cookie\s*=\s*"([^"=]+)=([^"]+)"', r.text)
        if m:
            host = urlparse(url).hostname or "laws.gov.gd"
            sess.cookies.set(m.group(1), m.group(2), domain=host)
            r = sess.get(url, timeout=timeout, allow_redirects=True)
    return r


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        low = url.lower()
        is_dl = low.rstrip("/").endswith("/download") or ".pdf" in low
        is_html_const = "the-constitution" in low
        if not is_dl and not is_html_const:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and not is_html_const:
            return
        cat = cat or _category(url, title_hint)
        ident = _ident_from_url(url, title_hint)
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "")
        prev = best.get(ident)
        if prev is None or _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
            best[ident] = row
        elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
            if (ts or "") > (prev[4] or ""):
                best[ident] = row

    def add_downloads_from_html(page_url: str, html: str, default_cat: str = ""):
        # titled download anchors
        for m in re.finditer(
            r'href=["\']([^"\']+/download)["\'][^>]*>(.*?)</a>',
            html,
            re.I | re.S,
        ):
            href, tip = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            tip = re.sub(r"\s+", " ", tip)
            if tip.lower() in ("download", "view", "details", ""):
                tip = ""
            full = urljoin(page_url, href)
            if not tip:
                tip = Path(unquote(urlparse(full).path)).parent.name.replace("-", " ")
            add(full, "", tip[:200], default_cat)
        # bare download / viewdocument hrefs
        for href in re.findall(
            r'href=["\']([^"\']+(?:/download|viewdocument/\d+)[^"\']*)["\']',
            html,
            re.I,
        ):
            full = urljoin(page_url, href)
            tip = Path(unquote(urlparse(_norm(full)).path)).parent.name.replace("-", " ")
            add(full, "", tip[:200], default_cat)
        # direct PDFs
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
            full = urljoin(page_url, href)
            tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ").replace("-", " ")
            add(full, "", tip[:200], default_cat)

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat)

    sess = _session()

    # --- Chapters (Caps): letter folders -> chapter category -> PDF download ---
    try:
        ch = _get(sess, "https://laws.gov.gd/index.php/chapters")
        letters = sorted(
            set(
                re.findall(
                    r'href=["\'](/index\.php/chapters/[a-z0-9-]+)["\']',
                    ch.text,
                    re.I,
                )
            )
        )
        letters = [x for x in letters if x.rstrip("/").count("/") == 3]
        log.info("chapter letter folders %s", len(letters))
        for letter in letters:
            letter_url = urljoin("https://laws.gov.gd", letter)
            try:
                lr = _get(sess, letter_url)
                if lr.status_code != 200:
                    continue
                # category pages under this letter
                cats = sorted(
                    set(
                        re.findall(
                            rf'href=["\']({re.escape(letter)}/[^"\'?#]+)["\']',
                            lr.text,
                            re.I,
                        )
                    )
                )
                cats = [
                    c
                    for c in cats
                    if "layout=" not in c
                    and "limitstart" not in c
                    and "/download" not in c
                    and "viewdocument" not in c
                ]
                for cat_path in cats:
                    cat_url = urljoin("https://laws.gov.gd", cat_path)
                    try:
                        cr = _get(sess, cat_url, timeout=40)
                        if cr.status_code != 200:
                            continue
                        # title from h1
                        hm = re.search(
                            r'edocman-page-heading[^>]*>\s*(.*?)</h1>',
                            cr.text,
                            re.I | re.S,
                        )
                        hint = ""
                        if hm:
                            hint = re.sub(r"<[^>]+>", "", hm.group(1)).strip()
                            hint = re.sub(r"\s+", " ", hint)
                        add_downloads_from_html(cr.url, cr.text, "CAP")
                        # if downloads found without good hint, re-add with chapter title
                        if hint:
                            for href in re.findall(
                                r'href=["\']([^"\']+/download)["\']', cr.text, re.I
                            ):
                                add(urljoin(cr.url, href), "", hint[:200], "CAP")
                    except Exception as exc:
                        log.warning("chapter cat %s fail: %s", cat_path[:80], exc)
                log.info("letter %s cats=%s catalog=%s", letter.split("/")[-1], len(cats), len(best))
            except Exception as exc:
                log.warning("letter %s fail: %s", letter, exc)
    except Exception as exc:
        log.warning("chapters root fail: %s", exc)

    # --- Acts by year (newest first) ---
    try:
        ar = _get(sess, "https://laws.gov.gd/index.php/acts")
        years = sorted(
            set(re.findall(r'href=["\'](/index\.php/acts/\d+-20\d{2})["\']', ar.text, re.I)),
            reverse=True,
        )
        log.info("act year folders %s", len(years))
        for ypath in years:
            try:
                yr = _get(sess, urljoin("https://laws.gov.gd", ypath))
                if yr.status_code != 200:
                    continue
                # titled docs
                for m in re.finditer(
                    r'href=["\']([^"\']+/download)["\'][^>]*>(.*?)</a>',
                    yr.text,
                    re.I | re.S,
                ):
                    tip = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                    tip = re.sub(r"\s+", " ", tip)
                    if tip.lower() in ("download", "view", ""):
                        tip = Path(unquote(urlparse(m.group(1)).path)).parent.name
                    add(urljoin(yr.url, m.group(1)), "", tip[:200], "ACT")
                add_downloads_from_html(yr.url, yr.text, "ACT")
                log.info("acts %s catalog=%s", ypath.split("/")[-1], len(best))
            except Exception as exc:
                log.warning("acts year %s fail: %s", ypath, exc)
    except Exception as exc:
        log.warning("acts root fail: %s", exc)

    # --- S.R.&O. by year ---
    try:
        sr = _get(sess, "https://laws.gov.gd/index.php/map-of-folders/sro-folder")
        years = sorted(
            set(re.findall(r'href=["\'](/index\.php/s-r-o/\d+-20\d{2})["\']', sr.text, re.I)),
            reverse=True,
        )
        log.info("sro year folders %s", len(years))
        for ypath in years:
            try:
                yr = _get(sess, urljoin("https://laws.gov.gd", ypath))
                if yr.status_code != 200:
                    continue
                for m in re.finditer(
                    r'href=["\']([^"\']+/download)["\'][^>]*>(.*?)</a>',
                    yr.text,
                    re.I | re.S,
                ):
                    tip = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                    tip = re.sub(r"\s+", " ", tip)
                    if tip.lower() in ("download", "view", ""):
                        tip = Path(unquote(urlparse(m.group(1)).path)).parent.name
                    add(urljoin(yr.url, m.group(1)), "", tip[:200], "SRO")
                add_downloads_from_html(yr.url, yr.text, "SRO")
                log.info("sro %s catalog=%s", ypath.split("/")[-1], len(best))
            except Exception as exc:
                log.warning("sro year %s fail: %s", ypath, exc)
    except Exception as exc:
        log.warning("sro root fail: %s", exc)

    # --- Official Gazette publications by year ---
    for year in GAZETTE_YEARS:
        start = 0
        while start < 200:
            page = f"https://gazettes.gov.gd/publications/{year}"
            if start:
                page = f"{page}?start={start}"
            try:
                gr = _get(sess, page)
                if gr.status_code != 200:
                    break
                before = len(best)
                # document title + download pairs
                for m in re.finditer(
                    r'edocman-document-title[^>]*>.*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                    gr.text,
                    re.I | re.S,
                ):
                    href, tip = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
                    tip = re.sub(r"\s+", " ", tip)
                    full = urljoin(gr.url, href)
                    if "/download" not in full.lower() and "viewdocument" not in full.lower():
                        # category leaf — try sibling download path
                        if full.rstrip("/").endswith(tuple("0123456789")) or "/publications/" in full:
                            # look for matching download in page for same slug
                            pass
                    add(full if full.rstrip("/").endswith("/download") else (full.rstrip("/") + "/download"), "", tip[:200], "GAZETTE")
                add_downloads_from_html(gr.url, gr.text, "GAZETTE")
                log.info("gazette %s start=%s catalog=%s", year, start, len(best))
                # pagination
                more = re.findall(rf'/publications/{year}\?start=(\d+)', gr.text)
                nexts = sorted({int(x) for x in more if int(x) > start})
                if not nexts or len(best) == before and start > 0:
                    # also break if no new downloads found on first page with no next
                    if not nexts:
                        break
                if not nexts:
                    break
                start = nexts[0]
            except Exception as exc:
                log.warning("gazette %s start=%s fail: %s", year, start, exc)
                break

    # --- CDX of official PDF / download endpoints ---
    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            for h in cdx_urls(
                prefix,
                limit=lim,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            ):
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if orig:
                    tip = Path(unquote(urlparse(orig).path)).stem.replace("_", " ")[:200]
                    # normalize viewdocument -> download for live preference
                    add(orig, ts, tip)
            # also without mimetype (edocman download URLs often tagged oddly)
            for h in cdx_urls(prefix, limit=min(lim, 500), match_type="prefix"):
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig:
                    continue
                if "/download" in orig or "viewdocument" in orig or orig.lower().endswith(".pdf"):
                    tip = Path(unquote(urlparse(orig).path)).parent.name.replace("-", " ")[:200]
                    add(orig, ts, tip)
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
    # Cookie-aware live fetch for *.gov.gd eDocMan (humans_* challenge)
    if _host_ok(url) and ("gov.gd" in (urlparse(url).hostname or "")):
        try:
            sess = _session()
            r = _get(sess, url, timeout=90)
            raw = r.content or b""
            ctype = r.headers.get("content-type") or ""
            if r.status_code == 200 and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
                text, how, pages = extract_pdf_text(raw, enable_ocr=False)
                if text and len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "method": f"live_cookie:{how}",
                        "content": raw,
                        "error": "",
                    }
                text, how, pages = ocr_pdf(raw)
                if text and len(text) >= 100:
                    return {
                        "status": "success",
                        "text": text,
                        "method": f"live_cookie_ocr:{how}",
                        "content": raw,
                        "error": "",
                    }
            # HTML constitution page
            if r.status_code == 200 and "the-constitution" in url and "html" in ctype.lower():
                from world_lib import html_to_text
                text = html_to_text(r.text)
                if text and len(text) >= 500 and "fundamental rights" in text.lower():
                    return {
                        "status": "success",
                        "text": text,
                        "method": "live_html_constitution",
                        "content": raw,
                        "error": "",
                    }
        except Exception as exc:
            log.warning("live_cookie %s fail: %s", url[:80], exc)

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


def reprocess_existing() -> int:
    """Re-split articles on saved instruments with Cap densify ART (no re-fetch)."""
    from common import ROOT, atomic_write
    import json
    n = 0
    for path in sorted((ROOT / CC / "instruments").glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 80:
            continue
        rid = rec.get("id") or path.stem
        cat = ((rec.get("metadata") or {}).get("category") or "")
        blob = (text[:3000] or "").lower()
        if cat in ("GAZETTE", "EXTRAORDINARY") or "budget speech" in blob or "we must " in blob:
            use_re = ART_NARROW
        elif cat in ("ACT", "CONSTITUTION", "SRO", "CAP", "SI", "PRINCIPAL", "AMENDING", "SUBORDINATE", "CODE", "CHAPTER") or "sustant" in cat.lower() or "substant" in cat.lower():
            use_re = ART
        else:
            use_re = ART
        docs = __import__("world_lib", fromlist=["split_custom"]).split_custom(
            text, rid, rec.get("source_url") or "", rec.get("date"), use_re
        )
        old = int(rec.get("article_count") or 0)
        if len(docs) == old and old > 0:
            continue
        if len(docs) < old and old >= 2 and len(docs) < 2:
            continue
        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok" if len(docs) >= 2 else ("missing" if not docs else "partial")
        meta = rec.get("metadata") or {}
        meta["article_re"] = "oecs_cap_section_v1"
        rec["metadata"] = meta
        atomic_write(path, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        n += 1
        log.info("reprocess %s arts %s->%s", rid[:70], old, len(docs))
    return n


def main():
    setup_log(CC)
    t0 = utcnow()
    if os.environ.get("REPROCESS_EXISTING", "1") not in ("0", "false", "False"):
        rp = reprocess_existing()
        log.info("reprocessed %s instruments", rp)
    max_new = env_int("MAX_NEW", 150)
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
        if cat and title and cat.lower() not in title.lower():
            title = f"{title} [{cat}]"
        if cat in ("GAZETTE", "EXTRAORDINARY"):
            use_re = ART_NARROW
        elif cat in ("ACT", "CONSTITUTION", "SRO", "CAP", "SI", "PRINCIPAL", "AMENDING", "SUBORDINATE", "CODE", "CHAPTER") or "sustant" in (cat or "").lower():
            use_re = ART
        else:
            use_re = ART
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_gd.py",
            article_re=use_re,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Grenada laws.gov.gd / Official Gazette (gazettes.gov.gd)",
        source_urls=[
            "https://laws.gov.gd/",
            "https://laws.gov.gd/index.php/chapters",
            "https://laws.gov.gd/index.php/acts",
            "https://laws.gov.gd/index.php/map-of-folders/sro-folder",
            "https://gazettes.gov.gd/",
            "https://gazettes.gov.gd/index.php/publications",
            "https://www.gov.gd/index.php/government/the-constitution",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (laws.gov.gd Chapters/Acts/S.R.&O. + Official Gazette + CDX)",
        notes=(
            f"Official laws.gov.gd eDocMan Chapters (Caps) + Acts + S.R.&O. + "
            f"gazettes.gov.gd Official Gazette PDFs; live-first (humans cookie) + Wayback CDX. "
            f"Prefer Constitution + Caps + Acts + SROs + Gazettes. "
            f"OCR used={ocr_used}. Skip bills/drafts. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
