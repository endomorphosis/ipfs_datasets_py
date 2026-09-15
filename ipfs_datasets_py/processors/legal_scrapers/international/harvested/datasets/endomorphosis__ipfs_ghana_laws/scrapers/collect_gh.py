#!/usr/bin/env python3
"""Ghana: Constitution + Acts/Bills of Parliament from official hosts.

Official only:
  - Parliament of Ghana https://www.parliament.gh/docs?type=Acts  (public catalog)
  - Judicial Service constitution HTML https://judicial.gov.gh/index.php/the-constitution
  - Act/Bill PDFs under parliament.gh (and ir.parliament.gh institutional repo)
  - /epanel/ is robots Disallow — archive (Wayback/Common Crawl) of those official
    PDF URLs only; never live-crawl /epanel/.
  - Legacy official paths /assets/file/, /docs/uploads/, /files/ are allowed live
    (robots allow) with Wayback fallback.

Not GhanaLII as primary. Not commercial databases (gpclonline / egazetteghana
paywalled). No WAF bypass. Ghana Publishing Company e-Gazette is paywalled —
not used as a free full-text source.

Densify: Ghana Acts/Bills use Commonwealth ``1. Title.`` / ``12A. Interpretation.``
section numbering (not only ``Section N`` / ``Article N``). Prefer enacting body after
``BE IT ENACTED`` / ``PASSED by Parliament`` / ARRANGEMENT OF SECTIONS TOC (port of
ug/mu/tz/zm). Reprocess-first; harvest MAX_NEW lean.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

try:
    from pdf_extract_lib import extract_pdf_text
except Exception:  # pragma: no cover
    extract_pdf_text = None  # type: ignore

try:
    from world_lib import env_int, split_custom
except Exception:
    def env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)) or default)
        except Exception:
            return default

    split_custom = None  # type: ignore

CC = "gh"
COUNTRY = "Ghana"
SOURCE_TYPE = "ghana_official"
LICENSE = (
    "Official texts of the Republic of Ghana as published by Parliament of Ghana "
    "and the Judicial Service. The Ghana Gazette (Ghana Publishing Company) authentic "
    "text prevails. Not legal advice. Not GhanaLII as source of record."
)
UA = DEFAULT_UA + " source=https://www.parliament.gh/"
PARL = "https://www.parliament.gh"
ACTS = f"{PARL}/docs?OT=&type=Acts"
ACTS_ALT = f"{PARL}/docs?type=Acts"
BILLS = f"{PARL}/docs?OT=&type=Bills"
BILLS_ALT = f"{PARL}/docs?type=Bills"
CONST = "https://judicial.gov.gh/index.php/the-constitution"
CONST_FEED = (
    "https://judicial.gov.gh/index.php?option=com_content&view=category"
    "&id=111&format=feed&type=rss"
)
EPANEL = f"{PARL}/epanel/docs/"  # robots Disallow: /epanel/ — archive only
SLEEP = 0.5
log = logging.getLogger("gh")
SHOWPDF = re.compile(r"showPDF\('([^']+)'\s*,\s*'([^']*)'\)")
# Commonwealth body: "1. Application." / "12A. Interpretation." PLUS classic Section/Article/CHAPTER
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|CHAPTER|Chapter)\s+[0-9IVXLCDM]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s+[A-Z\"'(])"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")
ART_GH = ART  # back-compat alias for any external refs
ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|ARRANGEMENT OF SECTIONS|PASSED by Parliament|"
    r"AN ACT\b|A BILL\b|This Act may be cited|Short title|I assent|"
    r"CHAPTER\s+\d+|THE\s+[A-Z][A-Z0-9 \-',()]{6,100}\s+ACT|"
    r"Right to Information|Stamp Duty|Companies|Criminal)"
)

# Paths that are parliamentary procedure / hansard / budgets — not Acts corpus.
SKIP_PATH_RE = re.compile(
    r"/(?:pb|hansard|hansard\d*|budget(?:\s|%20|_|-)?(?:statement|speech)?|"
    r"business[_\s%20.-]*statements?|committees?\s*reports?|agenda)/|"
    r"(?:ord\.?\s*paper|order\s*paper|votes[-_]|han\.|bus[_\s.]|"
    r"budget\s*(?:speech|highlights?|statement)|mid[- ]?year\s*(?:speech|fiscal)|"
    r"sona\s|speakercb|policy\s*brief|background\s*paper|"
    r"record\s*of\s*bills|financing\s*agreement|contract\s*(?:for|agreement|between)|"
    r"memorandum\s*(?:to|by)\s*parliament|parliamentary\s*memo|"
    r"master\s*project\s*support|engineering\s*,?\s*procurement)",
    re.I,
)
ACTISH_NAME_RE = re.compile(
    r"\b(?:act|bill|code|law|constitution|statute|decree)\b|"
    r"(?:companies|criminal|police|insurance|petroleum|education|"
    r"exemptions?|registration|rent|rti|affirmative|domestic\s*violence|"
    r"stamp\s*duty|procurement|interpretation|extradition|narcotic|"
    r"trustees|securities|banking|banks\s+and|chartered)",
    re.I,
)



def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def ocr_pdf_pdftoppm(raw: bytes, *, max_pages: int = 60, dpi: int = 150) -> str:
    """OCR image-only PDFs via pdftoppm + tesseract eng (no pymupdf required)."""
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(Path(td) / "p")],
                check=False, capture_output=True, timeout=300,
            )
            if proc.returncode != 0:
                log.warning("pdftoppm: %s", (proc.stderr or b"")[:200])
                return ""
            pages = sorted(Path(td).glob("p*.png"))
            chunks = []
            for img in pages[:max_pages]:
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "eng", "--psm", "6"],
                    check=False, capture_output=True, timeout=180,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf_pdftoppm: %s", exc)
        return ""


def pdf_to_text(raw: bytes) -> tuple[str, str]:
    """Return (text, backend). Prefer pdf_extract_lib; OCR image-only via tesseract."""
    if not raw or raw[:4] != b"%PDF":
        return "", "not_pdf"
    enable_ocr = env_int("OCR_ALL", 1) == 1
    # Cap OCR pages for huge scans (Promotion Bill ~40MB).
    max_pages = env_int("OCR_MAX_PAGES", 60)
    dpi = env_int("OCR_DPI", 150)
    if extract_pdf_text is not None:
        try:
            text, method, _pages = extract_pdf_text(
                raw, enable_ocr=enable_ocr, ocr_lang="eng", ocr_max_pages=max_pages,
            )
            text = (text or "").strip()
            if len(text) >= 120 or not enable_ocr:
                return text, method or "pdf_extract"
            # extract_pdf_text may lack pymupdf in bare python3 — fall through to OCR
        except Exception as exc:
            log.warning("extract_pdf_text: %s", exc)
    # Fallback: pdftotext, then pdftoppm+tesseract for image-only
    import subprocess, tempfile
    text = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            text = proc.stdout.decode("utf-8", "replace").strip()
            if len(text) >= 120:
                return text, "pdftotext"
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    if enable_ocr:
        ocr = ocr_pdf_pdftoppm(raw, max_pages=max_pages, dpi=dpi)
        if len(ocr) >= 120:
            return ocr, "ocr_tesseract_pdftoppm"
        if len(ocr) > len(text):
            text = ocr
            return text, "ocr_tesseract_pdftoppm" if text else "failed"
    return text, ("pdftotext" if text else "failed")


def normalize_url(url: str) -> str:
    u = (url or "").strip()
    u = u.replace("http://www.parliament.gh:80/", "https://www.parliament.gh/")
    u = u.replace("http://parliament.gh:80/", "https://www.parliament.gh/")
    u = u.replace("http://www.parliament.gh/", "https://www.parliament.gh/")
    u = u.replace("http://parliament.gh/", "https://www.parliament.gh/")
    u = u.replace("https://parliament.gh/", "https://www.parliament.gh/")
    u = u.replace("http://ir.parliament.gh:80/", "https://ir.parliament.gh/")
    u = u.replace("http://ir.parliament.gh/", "https://ir.parliament.gh/")
    return u.split("#")[0]


def url_key(url: str) -> str:
    u = normalize_url(url).lower()
    u = unquote(u).split("?")[0]
    return u.rstrip("/")


def is_epanel(url: str) -> bool:
    return "/epanel/" in (url or "").lower()


def looks_like_act_bill(url: str, title: str = "") -> bool:
    u = unquote(url or "")
    t = title or ""
    blob = f"{u} {t}"
    if SKIP_PATH_RE.search(blob):
        return False
    if re.search(r"(?i)\breport\s+of\s+the\b|committee\s+on\s+the\s+terms", blob):
        return False
    # epanel/docs/bills/ are the Acts catalog — keep all
    if re.search(r"(?i)/epanel/docs/bills/", u):
        return True
    # assets/file Acts or BILLS folders
    if re.search(r"(?i)/assets/file/(?:acts(?:\s|%20|_)*\d*|bills(?:\s|%20|_)*(?:for\s*\d*)?)/", u):
        return True
    # docs/uploads acts
    if re.search(r"(?i)/docs/uploads/", u) and ACTISH_NAME_RE.search(Path(unquote(u)).name):
        return True
    # /files/ named bills/acts
    if re.search(r"(?i)/files/", u) and ACTISH_NAME_RE.search(Path(unquote(u)).name):
        if re.search(r"(?i)ord\.|han\.|budget", Path(unquote(u)).name):
            return False
        return True
    # IR bitstream with act/bill in filename
    if re.search(r"(?i)ir\.parliament\.gh/bitstream/", u):
        name = Path(unquote(u).split("?")[0]).name
        if re.fullmatch(r"\d{6,}.*", name):
            return False
        if ACTISH_NAME_RE.search(name) and not SKIP_PATH_RE.search(name):
            # exclude "Record of Bills" indexes / contracts / memos
            if re.search(r"(?i)record\s*of\s*bills|memo|contract|agreement|sinohydro|billion\s*corporation", name):
                return False
            return True
        return False
    # live catalog showPDF bills/
    if re.search(r"(?i)^bills/", u) or "/bills/" in u.lower():
        return True
    return bool(ACTISH_NAME_RE.search(blob))


def _archive_official(url: str, wayback_ts: Optional[str] = None) -> dict:
    """Wayback-first archive fetch; CC only if Wayback fails."""
    res = {"status": "error", "error": "not_tried"}
    if wayback_ts:
        res = af.get_wayback_content(url, timestamp=wayback_ts)
        body = res.get("content") or b""
        if res.get("status") == "success" and (body[:4] == b"%PDF" or (res.get("text") or "").strip()):
            res.setdefault("retrieval", "archive")
            return res
    try:
        hits = af.search_wayback_machine(url, match_type="exact", limit=5)
        for h in sorted(hits, key=lambda r: r.get("timestamp") or "", reverse=True):
            ts = h.get("timestamp")
            if not ts:
                continue
            res2 = af.get_wayback_content(url, timestamp=ts)
            body2 = res2.get("content") or b""
            if res2.get("status") == "success" and (body2[:4] == b"%PDF" or (res2.get("text") or "").strip()):
                res2.setdefault("retrieval", "archive")
                return res2
    except Exception as exc:
        log.info("cdx exact retry fail: %s", exc)
    # Generic wayback; CC only if TRY_CC=1 (GH epanel/assets almost never in CC)
    res = af.fetch_with_fallbacks(url, wayback_ts=wayback_ts, try_http=False, try_cc=False)
    if res.get("status") != "success" and env_int("TRY_CC", 0) == 1:
        res = af.fetch_with_fallbacks(url, wayback_ts=wayback_ts, try_http=False, try_cc=True)
    if res.get("status") != "success":
        return {"status": "error", "error": res.get("error") or "no_archive_snapshot",
                "original_url": url, "retrieval": "archive"}
    res.setdefault("retrieval", "archive")
    return res


def get_official(
    url: str,
    *,
    timeout=(20, 180),
    retries: int = 4,
    wayback_ts: Optional[str] = None,
    allow_epanel_live: bool = False,
) -> dict:
    url = normalize_url(url)
    if is_epanel(url) and not allow_epanel_live:
        log.info("robots Disallow /epanel/ — archive of official URL %s ts=%s", url, wayback_ts)
        return _archive_official(url, wayback_ts)
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s — archive of official URL", url, exc)
        return _archive_official(url, wayback_ts)
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "",
            "content_type": ctype or "application/pdf", "original_url": url,
            "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype):
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 429:
        log.info("HTTP 429 %s — archive", url)
        return _archive_official(url, wayback_ts)
    if status == 200 and body:
        # IR bitstream and other PDF URLs often return DSpace/HTML shells live —
        # only accept live PDF bytes; otherwise fall through to Wayback.
        if body[:4] != b"%PDF" and re.search(
            r"(?i)\.pdf(?:\?|$)|/bitstream/", url
        ):
            log.info(
                "live non-PDF for PDF URL %s (%s bytes ctype=%s) — archive",
                url, len(body), ctype,
            )
            return _archive_official(url, wayback_ts)
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    # 404/other — archive of the official URL (wayback-first)
    return _archive_official(url, wayback_ts)


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def extract_article(html: str) -> str:
    m = re.search(r"<article\b[^>]*>(.*)</article>", html or "", re.I | re.S)
    chunk = m.group(1) if m else (html or "")
    chunk = re.sub(r"<script\b[^>]*>.*?</script>", " ", chunk, flags=re.I | re.S)
    chunk = re.sub(r"<style\b[^>]*>.*?</style>", " ", chunk, flags=re.I | re.S)
    return html_to_text(chunk).strip()


def constitution_chapter_urls() -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for start in range(0, 80, 10):
        u = f"{CONST_FEED}&limitstart={start}&limit=10"
        res = get_official(u)
        html = res.get("text") or ""
        items = re.findall(r"<item>(.*?)</item>", html, re.S)
        if not items:
            break
        for it in items:
            link = re.search(r"<link>(.*?)</link>", it, re.S)
            if not link:
                continue
            href = (link.group(1) or "").strip()
            if "judicial.gov.gh" not in href or href in seen:
                continue
            seen.add(href)
            urls.append(href)
    log.info("judicial constitution chapters n=%s", len(urls))
    return urls


def fetch_constitution_text() -> tuple[str, str, list[str]]:
    chapters = constitution_chapter_urls()
    if not chapters:
        chapters = [CONST, "https://judicial.gov.gh/index.php/preamble"]
    parts: list[tuple[int, str]] = []
    used: list[str] = []
    for href in chapters:
        res = get_official(href)
        html = res.get("text") or ""
        text = extract_article(html)
        if len(text) < 80:
            continue
        if "I accept cookies" in text and "CHAPTER" not in text and "PREAMBLE" not in text.upper() and "Sovereignty" not in text:
            continue
        m = re.search(r"CHAPTER\s+0*(\d+)", text)
        if m:
            order = int(m.group(1))
        elif re.search(r"PREAMBLE", text, re.I):
            order = 0
        elif re.search(r"FIRST SCHEDULE", text, re.I):
            order = 90
        elif re.search(r"SECOND SCHEDULE", text, re.I):
            order = 91
        else:
            order = 50
        parts.append((order, text))
        used.append(href)
    parts.sort(key=lambda x: x[0])
    best: dict[int, str] = {}
    for order, text in parts:
        if order not in best or len(text) > len(best[order]):
            best[order] = text
    body = "\n\n".join(best[k] for k in sorted(best))
    return body, "live", used


def parse_acts_page(html: str) -> list[dict]:
    items = []
    seen = set()
    for path, title in SHOWPDF.findall(html or ""):
        if not path.lower().startswith("bills/"):
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        # Encode path segments carefully for epanel URL
        enc = "/".join(quote(seg, safe="()[],.-_") for seg in path.split("/"))
        pdf_url = EPANEL + enc
        items.append({
            "url": pdf_url,
            "path": path,
            "title": title or Path(path).stem,
            "kind": "act",
            "discovery": "parliament_docs_acts_live",
        })
    return items


def _add_cdx_items(
    items: list[dict],
    seen: set[str],
    prefix: str,
    *,
    limit: int = 400,
    discovery: str,
) -> int:
    added = 0
    try:
        recs = af.search_wayback_machine(
            prefix, match_type="prefix", limit=limit,
            extra_filters=["mimetype:application/pdf"],
        )
    except Exception as exc:
        log.warning("cdx %s: %s", prefix, exc)
        return 0
    log.info("wayback cdx %s n=%s", prefix, len(recs))
    # Prefer newest timestamp per original
    best: dict[str, dict] = {}
    for rec in recs:
        orig = normalize_url(rec.get("original") or "")
        if not orig:
            continue
        if not looks_like_act_bill(orig):
            continue
        key = url_key(orig)
        ts = rec.get("timestamp") or ""
        if key not in best or ts > (best[key].get("wayback_ts") or ""):
            stem = Path(unquote(orig.split("?")[0])).stem
            best[key] = {
                "url": orig,
                "title": stem,
                "kind": "act",
                "wayback_ts": ts,
                "cdx_original": orig,
                "cdx_length": rec.get("length"),
                "discovery": discovery,
            }
    for key, it in best.items():
        if key in seen:
            # merge timestamp onto existing
            for existing in items:
                if url_key(existing.get("url") or "") == key:
                    if it.get("wayback_ts") and (
                        not existing.get("wayback_ts")
                        or it["wayback_ts"] > existing.get("wayback_ts", "")
                    ):
                        existing["wayback_ts"] = it["wayback_ts"]
                        existing["cdx_original"] = it.get("cdx_original")
                    break
            continue
        seen.add(key)
        items.append(it)
        added += 1
    return added


def discover(*, force: bool = False) -> list[dict]:
    force = force or env_int("FORCE_REDISCOVER", 0) == 1
    existing = load_catalog()
    if existing and len(existing) >= 5 and not force:
        # Still enrich missing wayback_ts from a light epanel CDX pass
        log.info("resume catalog n=%s (set FORCE_REDISCOVER=1 to rebuild)", len(existing))
        seen = {url_key(it.get("url") or "") for it in existing}
        _add_cdx_items(
            existing, seen,
            "https://www.parliament.gh/epanel/docs/bills/",
            limit=100, discovery="wayback_epanel_bills",
        )
        save_catalog(existing)
        return existing

    items: list[dict] = [{
        "url": CONST,
        "title": "Constitution of the Republic of Ghana 1992",
        "kind": "constitution",
        "discovery": "judicial_service",
    }]
    seen = {url_key(CONST)}

    # Live Acts + Bills catalog pages (robots allow /docs)
    for page_url in (ACTS, ACTS_ALT, BILLS, BILLS_ALT):
        res = get_official(page_url)
        html = res.get("text") or ""
        page_items = parse_acts_page(html)
        log.info("parliament catalog %s n=%s retrieval=%s", page_url, len(page_items), res.get("retrieval"))
        for it in page_items:
            k = url_key(it["url"])
            if k in seen:
                continue
            seen.add(k)
            items.append(it)

    # Wayback CDX of official parliament Act/Bill PDF paths
    cdx_prefixes = [
        ("https://www.parliament.gh/epanel/docs/bills/", "wayback_epanel_bills"),
        ("http://www.parliament.gh/assets/file/Acts", "wayback_assets_acts"),
        ("http://www.parliament.gh/assets/file/BILLS", "wayback_assets_bills"),
        ("http://www.parliament.gh/assets/file/Bills", "wayback_assets_bills_lc"),
        ("http://www.parliament.gh/docs/uploads/", "wayback_docs_uploads"),
        ("http://www.parliament.gh/files/", "wayback_files"),
        ("https://ir.parliament.gh/bitstream/", "wayback_ir_bitstream"),
    ]
    for prefix, disc in cdx_prefixes:
        n = _add_cdx_items(items, seen, prefix, limit=400, discovery=disc)
        log.info("cdx added from %s: %s (catalog=%s)", disc, n, len(items))

    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def prefer_enacting_body(text: str, *, constitution: bool = False) -> str:
    """Skip arrangement/TOC so article split targets operative sections (ug/tz/zm port).

    Ghana Acts often use ``1. (1)`` body style after a titled heading, and
    ``PASSED by Parliament`` near the Act start. Constitutions mention
    "passed by Parliament" mid-text — never treat those as enacting cuts.
    """
    if not text:
        return text
    if not constitution:
        # Early enacting formula only (first 80k) — avoid constitution procedure refs
        m = re.search(r"(?is)PASSED by Parliament[^\n]*\n", text[:80000])
        if m and m.end() < len(text) - 200:
            rest = text[m.end():]
            # Prefer CHAPTER ONE / Application body immediately after assent block
            ch = re.search(r"(?im)^\s*CHAPTER\s+(?:ONE|1|I)\b", rest[:5000])
            if ch:
                return rest[ch.start():]
            return rest
        m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
        if m and m.end() < len(text) - 200:
            rest = text[m.end():]
            arr = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)", rest[:2500])
            if not arr:
                return rest
            text = rest
    ones = list(
        re.finditer(
            r"(?im)^\s*1\.\s+(?:Short title|Citation|Interpretation|Definitions|Application|"
            r"Right of access|Charge of|Title|Establishment)\b",
            text,
        )
    )
    if len(ones) >= 2:
        return text[ones[1].start():]
    # Ghana body style: titled heading then ``1. (1) ...`` (TOC has ``1. Title`` only)
    body_paren = list(re.finditer(r"(?im)^\s*1\.\s*\(1\)", text))
    if len(body_paren) >= 1:
        arr = re.search(r"(?i)ARRANGEMENT OF", text)
        # Prefer first 1.(1) after arrangement TOC
        if arr:
            for bp in body_paren:
                if bp.start() > arr.start():
                    return text[bp.start():]
        elif not constitution:
            return text[body_paren[0].start():]
    if len(ones) == 1:
        arr = re.search(r"(?i)ARRANGEMENT OF", text)
        # Only take lone ``1. Title`` if it looks like body (has subsection soon), not TOC
        if arr and ones[0].start() > arr.start():
            snip = text[ones[0].start(): ones[0].start() + 400]
            if re.search(r"\(1\)", snip):
                return text[ones[0].start():]
    m = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)|Arrangement of Sections", text)
    if m:
        after = text[m.end():]
        # Prefer ``1. (1)`` operative body after TOC
        paren = list(re.finditer(r"(?im)^\s*1\.\s*\(1\)", after))
        if paren:
            return after[paren[0].start():]
        body = list(re.finditer(r"(?im)^\s*1\.\s+[A-Z\"'(]", after))
        if len(body) >= 2:
            # second ``1. Title`` ≈ body when first is TOC
            return after[body[1].start():]
        # Body often resumes at CHAPTER ONE— after TOC (Companies Bill)
        ch = list(re.finditer(r"(?im)^\s*CHAPTER\s+(?:ONE|1|I)\b", after))
        for c in ch:
            if c.start() > 200:
                return after[c.start():]
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", after))
        if len(parts) >= 2:
            return after[parts[1].start():]
    return text


def _split_with_pattern(text: str, law_id: str, source_url: str, date: Optional[str], pattern) -> list[dict]:
    if split_custom is not None:
        return split_custom(text, law_id, source_url, date, pattern)
    # Fallback without world_lib.split_custom
    matches = list(pattern.finditer(text or ""))
    if len(matches) < 2:
        return split_articles(text, law_id, source_url, date)
    out = []
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 20:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")[:80]
        out.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": chunk.split("\n", 1)[0][:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "gh"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else split_articles(text, law_id, source_url, date)


def split_gh_articles(text: str, rid: str, source_url: str, date: Optional[str] = None, constitution: bool = False) -> list[dict]:
    """Commonwealth ``1. Title.`` body split by default; constitutions prefer Article N."""
    blob = f"{rid}|{source_url}"
    is_const = bool(constitution) or (
        bool(re.search(r"(?i)constitution", blob))
        and not bool(re.search(r"(?i)amm?endment", blob))
    )
    body = prefer_enacting_body(text, constitution=is_const)
    docs_sec = _split_with_pattern(body, rid, source_url, date, ART)
    docs_art = _split_with_pattern(body, rid, source_url, date, ART_ONLY)
    if is_const:
        if len(docs_art) >= 20:
            return docs_art
        if len(docs_art) >= 2 and len(docs_sec) > max(20, len(docs_art) * 3):
            return docs_art
        # Judicial HTML / OCR style: CHAPTER + bare ``13. (1)`` when Article markers sparse
        if len(docs_sec) >= 2:
            return docs_sec
        return docs_art if docs_art else docs_sec
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def split_gh(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    return split_gh_articles(text, law_id, source_url, date, constitution=constitution)


def reprocess_existing() -> int:
    """Re-split articles on Act-like instruments with Commonwealth section regex."""
    inst = ROOT / CC / "instruments"
    improved = 0
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 200:
            continue
        name = p.name
        blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:2500]}"
        # Skip obvious non-Acts (committee reports / budget estimates) unless text has Act markers
        if re.search(r"(?i)report of the (?:finance |select )?committee|annual budget estimates", name + (rec.get("title") or "")):
            if not ACT_TEXT_RE.search(text[:3000]):
                continue
        rid = rec.get("id") or p.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        is_const = bool(re.search(r"(?i)constitution", rid + (rec.get("title") or ""))) and not bool(
            re.search(r"(?i)amm?endment", rid + (rec.get("title") or ""))
        )
        docs = split_gh_articles(text, rid, url, date, constitution=is_const)
        old = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        new = len(docs)
        if new <= old and old > 0:
            continue
        if new < 2 and old >= new:
            continue
        rec["documents"] = docs
        rec["article_count"] = new
        rec["article_extraction_status"] = "ok" if docs else "missing"
        meta = rec.get("metadata") or {}
        meta["article_reprocess"] = "collect_gh.py-commonwealth-sections"
        meta["article_split"] = "commonwealth-body"
        rec["metadata"] = meta
        atomic_write(p, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        improved += 1
        log.info("reprocess %s %s->%s", rid[:70], old, new)
    return improved


def rebuild_index() -> int:
    inst = ROOT / CC / "instruments"
    rows = []
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        line = {k: rec.get(k) for k in INDEX_FIELDS if k not in ("path", "bytes", "article_count")}
        line["path"] = f"instruments/{p.name}"
        line["article_count"] = rec.get("article_count") or len(rec.get("documents") or [])
        line["bytes"] = p.stat().st_size
        line["id"] = rec.get("id") or p.stem
        rows.append(line)
    out = ROOT / CC / "index.jsonl"
    atomic_write(out, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    log.info("rebuilt index lines=%s", len(rows))
    return len(rows)



def soft_id(rid: str) -> str:
    """Letter-token fingerprint so legacy %%20→-20- ids match unquoted stems."""
    s = (rid or "").lower()
    # insurance-20bill → insurance-bill
    s = re.sub(r"(?<=[a-z])-20(?=[a-z])", "-", s)
    s = s.replace("-20-", "-")
    s = re.sub(r"-{2,}", "-", s)
    parts = re.findall(r"[a-z]+", s)
    drop = {
        "gh", "act", "bill", "law", "the", "of", "and", "a", "an", "to", "for",
        "no", "nos", "amendment", "pdf",
    }
    parts = [x for x in parts if x not in drop and len(x) > 1]
    return "-".join(parts)




def instrument_ident(it: dict) -> str:
    kind = it.get("kind")
    if kind == "constitution":
        return "gh-constitution-1992"
    path = it.get("path") or ""
    url = it.get("url") or ""
    stem = Path(unquote(path or url.split("?")[0])).stem
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", stem)[:80].strip("-")
    return "gh-act-" + (stem or "unknown")


def fetch_one(it: dict, done: set[str]) -> str:
    kind = it.get("kind")
    url = normalize_url(it["url"])
    if kind == "constitution":
        ident = "gh-constitution-1992"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
        text, retrieval, used_urls = fetch_constitution_text()
        if len(text) < 20000:
            log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "constitution_incomplete", "chars": len(text)})
            return "fail"
        rec = base_record(
            cc=CC, country=COUNTRY, language="en", ident=ident,
            title="Constitution of the Republic of Ghana 1992", text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_gh.py", date="1993-01-07",
            official_identifier="Constitution of the Republic of Ghana 1992",
            document_type="constitution", law_status="current", is_current=True,
            documents=split_gh(text, rid, url, "1993-01-07", True),
            extra_meta={
                "discovery": {"method": "judicial_service_constitution_chapters", "chapter_urls": used_urls},
                "retrieval": {"method": retrieval},
                "text_extraction": {"source": "official", "backend": "html-article"},
                "gaps": "Official Judicial Service HTML chapters (Joomla category 111). Authentic Gazette text prevails.",
            },
        )
        rec["id"] = rid
        write_instrument(CC, rec)
        done.add(rid)
        ds = getattr(fetch_one, "_done_soft", None)
        if ds is not None:
            ds.add(soft_id(rid))
        return "ok"

    ident = instrument_ident(it)
    rid = slug_id(CC, ident)
    soft = soft_id(rid)
    done_soft = getattr(fetch_one, "_done_soft", None)
    if done_soft is None:
        done_soft = {soft_id(x) for x in done}
        fetch_one._done_soft = done_soft
    if rid in done or soft in done or soft in done_soft:
        return "skip"

    res = get_official(url, wayback_ts=it.get("wayback_ts"))
    body = res.get("content") or b""
    retrieval = res.get("retrieval") or res.get("method") or "archive"
    used = res.get("final_url") or res.get("wayback_url") or url
    text = ""
    backend = "none"
    if body[:4] == b"%PDF":
        # Skip OCR for extremely large PDFs unless OCR_HUGE=1 (Promotion ~41MB)
        huge = len(body) > env_int("OCR_HUGE_BYTES", 12_000_000)
        if huge and env_int("OCR_HUGE", 0) != 1:
            # text-layer only for huge PDFs
            old = os.environ.get("OCR_ALL")
            os.environ["OCR_ALL"] = "0"
            try:
                text, backend = pdf_to_text(body)
            finally:
                if old is None:
                    os.environ.pop("OCR_ALL", None)
                else:
                    os.environ["OCR_ALL"] = old
            if len(text) < 120:
                log_failure(CC, {
                    "id": ident, "url": url, "status": "failed",
                    "reason": "huge_pdf_no_text_layer", "bytes": len(body),
                })
                return "fail"
        else:
            text, backend = pdf_to_text(body)
    elif res.get("text"):
        text = html_to_text(res.get("text") or "")
        backend = "html"
    if "DSpace Repository" in text or (
        "Skip to main content" in text and "Institutional Repository" in text and len(text) < 8000
    ):
        log_failure(CC, {
            "id": ident, "url": url, "status": "failed", "reason": "dspace_html_shell",
            "retrieval": retrieval, "bytes": len(body),
        })
        return "fail"
    if len(text) < 120:
        log_failure(CC, {
            "id": ident, "url": url, "status": "failed", "reason": "empty_pdf",
            "retrieval": retrieval, "bytes": len(body), "error": res.get("error"),
        })
        return "fail"
    title = it.get("title") or ident
    head = text[:2000]
    m = re.search(r"(?im)^(AN ACT[^\n]+|[A-Z][A-Za-z0-9 ,.'()]{8,140} ACT,?\s+\d{4})", head)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_gh.py", date=None, official_identifier=title,
        document_type="statute", law_status="current", is_current=True,
        documents=split_gh(text, rid, url, None, False),
        extra_meta={
            "discovery": {
                "method": it.get("discovery") or "parliament_docs_acts",
                "cdx_original": it.get("cdx_original"),
                "wayback_ts": it.get("wayback_ts"),
            },
            "retrieval": {
                "method": retrieval,
                "used_url": used,
                "robots": "epanel_archive_only" if is_epanel(url) else "live_ok",
            },
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Constitution from Judicial Service of Ghana official HTML. Acts/Bills from "
        "parliament.gh/docs?type=Acts (robots allow /docs; Disallow /epanel/), plus "
        "Wayback/CDX of official parliament.gh epanel/docs/bills/, assets/file Acts|BILLS, "
        "docs/uploads, files, and ir.parliament.gh bitstream Act/Bill PDFs. Act PDF bodies "
        "under /epanel/ via Wayback/Common Crawl only (no live /epanel/ crawl). Image-only "
        "PDFs OCR'd with tesseract eng when text layer missing. Not GhanaLII. Ghana "
        "Publishing e-Gazette is paywalled — not used. Gazette authentic text prevails. "
        "glc.gov.gh is the General Legal Council, not used as a general Acts host. " + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="Parliament of Ghana + Judicial Service (official hosts)",
        source_urls=[ACTS, BILLS, CONST, PARL + "/", "https://ir.parliament.gh/", "https://ghanapublishing.gov.gh/"],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def rank_item(it: dict) -> tuple:
    """Prefer Acts, smaller archives, known timestamps; deprioritize huge scans."""
    kind = it.get("kind") or ""
    if kind == "constitution":
        return (0, 0, "")
    title = (it.get("title") or "") + " " + (it.get("url") or "")
    score = 50
    if re.search(r"(?i)\bact\b|code", title) and not re.search(r"(?i)\bbill\b", title):
        score -= 20
    if it.get("wayback_ts"):
        score -= 50  # archived snapshots are the ones that succeed
    else:
        score += 30  # live-catalog epanel without CDX usually 404 in Wayback
    try:
        ln = int(it.get("cdx_length") or 0)
    except Exception:
        ln = 0
    if ln > 12_000_000:
        score += 40
    elif ln > 3_000_000:
        score += 10
    return (score, ln or 0, url_key(it.get("url") or ""))


def main():
    setup()
    t0 = utcnow()
    t_start = time.time()
    max_new = env_int("MAX_NEW", 30)
    max_seconds = env_int("MAX_SECONDS", 3600)
    do_reprocess = os.environ.get("REPROCESS", "1") not in ("0", "false", "no")
    reproc_n = 0
    if do_reprocess:
        reproc_n = reprocess_existing()
        rebuild_index()
        log.info("reprocess improved=%s", reproc_n)

    items = discover(force=env_int("FORCE_REDISCOVER", 0) == 1)
    items = sorted(items, key=rank_item)
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s max_new=%s max_seconds=%s", len(items), len(done), max_new, max_seconds)
    for n, it in enumerate(items, 1):
        if counters["ok"] >= max_new:
            log.info("hit MAX_NEW=%s", max_new)
            break
        if time.time() - t_start > max_seconds:
            log.info("hit MAX_SECONDS=%s", max_seconds)
            break
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 10 == 0 or n == len(items) or st == "ok":
            log.info(
                "progress %s/%s ok=%s skip=%s fail=%s last=%s",
                n, len(items), counters["ok"], counters["skip"], counters["fail"], st,
            )
    rebuild_index()
    cov = "partial-official-fulltext"
    if counters["ok"] + counters["skip"] >= 1 or reproc_n:
        cov = "official-hosted-snapshot"
    n_instr = len(existing_ids(CC))
    arts = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            arts += int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        except Exception:
            pass
    write_progress(
        items, counters, cov,
        extra=(
            f"Started {t0}. instruments_now={n_instr} articles={arts}. "
            f"reprocess_improved={reproc_n}. Commonwealth 1. Title. split + enacting-body prefer. "
            f"MAX_NEW={max_new}."
        ),
    )
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "instruments": n_instr, "articles": arts,
        "reprocess_improved": reproc_n,
        "started": t0, "finished": utcnow(),
        "max_new": max_new, "max_seconds": max_seconds,
    }, indent=2) + "\n")
    log.info("done %s instruments=%s articles=%s reprocess=%s", counters, n_instr, arts, reproc_n)


if __name__ == "__main__":
    main()
