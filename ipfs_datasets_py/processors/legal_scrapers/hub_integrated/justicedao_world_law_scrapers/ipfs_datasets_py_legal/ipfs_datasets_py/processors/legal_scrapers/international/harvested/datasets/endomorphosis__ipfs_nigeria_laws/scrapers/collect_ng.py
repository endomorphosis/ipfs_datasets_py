#!/usr/bin/env python3
"""Nigeria: Constitution + Acts/Bills from official hosts.

Official only:
  - Federal Ministry of Justice constitution + select law PDFs (justice.gov.ng)
  - National Assembly Act/Bill PDFs:
      nass.gov.ng/documents/download/{id}     (current portal)
      nass.gov.ng/document/download/{id}      (legacy portal; Wayback CDX)
      nass.gov.ng/documents/billdownload/{id}.pdf
  - National Human Rights Commission constitution PDF (nigeriarights.gov.ng)
    as a second official government copy if FMOJ fetch fails
  - Wayback / Common Crawl of those same official URLs when live blocked/429

Not used as source of record: LawNigeria, LawPavilion, Legalpedia, NigeriaLII,
PLAC compilations. gazettes.africa is not crawled (robots.txt Disallow: /gazettes/
and Disallow: /). No WAF bypass.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

try:
    from pdf_extract_lib import extract_pdf_text
except Exception:  # pragma: no cover
    extract_pdf_text = None  # type: ignore

try:
    from world_lib import env_int
except Exception:
    def env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except Exception:
            return default

CC = "ng"
COUNTRY = "Nigeria"
SOURCE_TYPE = "nigeria_official"
LICENSE = (
    "Official texts of the Federal Republic of Nigeria as published by the "
    "Federal Ministry of Justice, the National Assembly, and (where used) other "
    "federal government hosts. The Official Gazette of the Federal Republic of "
    "Nigeria prevails over this research snapshot. Not legal advice. Not "
    "LawNigeria / LawPavilion / Legalpedia."
)
UA = DEFAULT_UA + " source=https://nass.gov.ng/"
FMOJ_CONST = "https://justice.gov.ng/wp-content/uploads/2020/09/Nigerian-Constitution.pdf"
FMOJ_CONST_PAGE = "https://justice.gov.ng/nigerian-constitution/"
NASS = "https://nass.gov.ng/"
NHRC_CONST = "https://nigeriarights.gov.ng/files/constitution.pdf"
SLEEP = 0.35
log = logging.getLogger("ng")

SEC_RE = re.compile(
    r"(?im)^\s*((?:Section|SECTION)\s+\d+[A-Z]?|[0-9]+\.—|[0-9]+\.\s+[A-Z])"
)
ART_RE = re.compile(r"(?im)^\s*((?:Chapter|CHAPTER|Part|PART)\s+[IVXLCDM0-9]+|[0-9]+\.\s+[A-Z])")

# Parliamentary procedure docs — not Acts/Bills full text.
REJECT_HEAD_RE = re.compile(
    r"(?is)^\s*.{0,800}?(?:"
    r"votes\s+and\s+proceedings|"
    r"order\s+paper|"
    r"notice\s+paper|"
    r"national\s+assembly\s+debates|"
    r"house\s+of\s+representatives\s+debates|"
    r"orders\s+of\s+the\s+day"
    r")",
    re.I,
)
KEEP_LEGISLATIVE_RE = re.compile(
    r"(?is)(?:"
    r"\ban\s+act\b|"
    r"\ba\s+bill\s+for\s+an\s+act\b|"
    r"\bbill,?\s+(?:19|20)\d{2}\b|"
    r"\bact,?\s+(?:19|20)\d{2}\b|"
    r"constitution\s+of\s+the\s+federal\s+republic|"
    r"executive\s+order\s+no|"
    r"arrangement\s+of\s+sections|"
    r"explanatory\s+memorandum"
    r")",
    re.I,
)
FMOJ_KEEP_RE = re.compile(
    r"(?i)(constitution|executive[_\-\s]?order|"
    r"administration-of-justice|criminal-act|"
    r"data[_\-\s]?protection|"
    r"(?:^|/)[^/]*(?:act|lfn|bill|decree|statute)[^/]*\.pdf$)"
)
FMOJ_SKIP_RE = re.compile(
    r"(?i)(media|press|release|malami|sahara|twitter|workshop|seminar|"
    r"presentation|procurement|advert|bulletin|newsletter|vacancy|"
    r"repatriation|agreement|mou|fjsc|action[-_]?plan|lawyer|capacity|"
    r"assets_recovery|report_from)"
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
    """OCR image-only PDFs via pdftoppm + tesseract eng."""
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(Path(td) / "p")],
                check=False, capture_output=True, timeout=300,
            )
            if proc.returncode != 0:
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
    """Return (text, backend). Prefer extract_pdf_text; OCR image-only via tesseract."""
    if not raw or raw[:4] != b"%PDF":
        return "", "not_pdf"
    enable_ocr = env_int("OCR_ALL", 1) == 1
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
        except Exception as exc:
            log.warning("extract_pdf_text: %s", exc)
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
        huge = len(raw) > env_int("OCR_HUGE_BYTES", 12_000_000)
        if huge and env_int("OCR_HUGE", 0) != 1:
            return text, "pdftotext_short_skip_huge_ocr" if text else "skip_huge_ocr"
        ocr = ocr_pdf_pdftoppm(raw, max_pages=max_pages, dpi=dpi)
        if len(ocr) >= 120:
            return ocr, "ocr_tesseract_pdftoppm"
        if len(ocr) > len(text):
            return ocr, "ocr_tesseract_pdftoppm" if ocr else "failed"
    return text, ("pdftotext" if text else "failed")


def wayback_only(url: str, timestamp: Optional[str] = None) -> dict:
    res = af.get_wayback_content(url, timestamp=timestamp)
    res.setdefault("retrieval", "archive")
    return res


def get_official(url: str, *, timeout=(20, 120), retries: int = 2, accept: Optional[str] = None) -> dict:
    headers = {}
    if accept:
        headers["Accept"] = accept
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries, headers=headers or None)
    except Exception as exc:
        log.info("live fail %s: %s — wayback of official URL", url, exc)
        return wayback_only(url)
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype) and body[:4] != b"%PDF":
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 200 and body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "", "content_type": ctype or "application/pdf",
            "original_url": url, "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if status == 200 and body and len(body) >= 500:
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    if status == 429:
        log.info("HTTP 429 %s — archive_fallbacks wayback", url)
        return wayback_only(url)
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    log.info("HTTP %s %s — wayback of official URL", status, url)
    return wayback_only(url)


def try_common_crawl(url: str) -> dict:
    if env_int("TRY_CC", 1) != 1:
        return {"status": "error", "error": "cc_disabled"}
    try:
        hits = af.search_common_crawl(url, limit=8)
    except Exception as exc:
        return {"status": "error", "error": f"cc_search:{exc}"}
    for hit in hits:
        try:
            res = af.fetch_common_crawl_warc(hit, max_bytes=8_000_000)
        except Exception as exc:
            log.info("cc warc fail %s: %s", url, exc)
            continue
        body = res.get("content") or b""
        if res.get("status") == "success" and body[:4] == b"%PDF":
            res["retrieval"] = "common_crawl"
            return res
    return {"status": "error", "error": "cc_no_pdf"}


def split_ng(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    pat = ART_RE if constitution else SEC_RE
    matches = list(pat.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "ng"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def write_law(*, ident, title, text, source_url, date, doc_type, extra_meta, official=None) -> str:
    rid = slug_id(CC, ident)
    if rid in existing_ids(CC):
        return "skip"
    if len(text or "") < 120:
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ng.py", date=date, official_identifier=official or ident,
        document_type=doc_type, law_status="current", is_current=True,
        documents=split_ng(text, rid, source_url, date, constitution=(doc_type == "constitution")),
        extra_meta=extra_meta,
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    return "ok"


def is_legislative_fulltext(text: str) -> tuple[bool, str]:
    """Keep Acts/Bills/Constitution/Orders; drop Votes/Order Papers/Debates."""
    head = (text or "")[:6000]
    if not head or len(head) < 80:
        return False, "too_short"
    if REJECT_HEAD_RE.search(head):
        # Still keep if clearly an Act title dominates (rare)
        if re.search(r"(?im)^\s*an\s+act\b", head[:1200]) and "votes and proceedings" not in head[:400].lower():
            return True, "act_despite_proc"
        return False, "parliamentary_procedure"
    if KEEP_LEGISLATIVE_RE.search(head):
        return True, "legislative"
    # Journal index pages with only bill lists — reject
    if re.search(r"(?i)national\s+assembly\s+journal", head[:800]):
        return False, "journal"
    return False, "not_legislative"


def parse_nass_homepage(html: str) -> list[dict]:
    items = []
    seen = set()
    for href, inner in re.findall(
        r'href="(https://nass\.gov\.ng/documents/download/\d+)"[^>]*>(.*?)</a>', html, re.S | re.I
    ):
        if href in seen:
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        if not title or title.lower().startswith("read act"):
            continue
        seen.add(href)
        did = href.rstrip("/").rsplit("/", 1)[-1]
        items.append({
            "url": href, "title": title, "download_id": did, "kind": "nass_act",
            "ident_prefix": "ng-nass", "discovery": "nass_homepage",
        })
    for did in re.findall(r"documents/download/(\d+)", html):
        url = f"https://nass.gov.ng/documents/download/{did}"
        if url in seen:
            continue
        seen.add(url)
        items.append({
            "url": url, "title": f"National Assembly document {did}",
            "download_id": did, "kind": "nass_act", "ident_prefix": "ng-nass",
            "discovery": "nass_homepage",
        })
    return items


def _cdx_best(prefix: str, *, limit: int, id_re: str) -> dict[str, dict]:
    """Return download_id -> best CDX row (largest length) for a prefix."""
    best: dict[str, dict] = {}
    try:
        recs = af.search_wayback_machine(
            prefix, match_type="prefix", limit=limit,
            extra_filters=["mimetype:application/pdf"],
        )
    except Exception as exc:
        log.warning("cdx %s: %s", prefix, exc)
        return best
    log.info("wayback cdx %s n=%s", prefix, len(recs))
    for rec in recs:
        orig = rec.get("original") or ""
        m = re.search(id_re, orig)
        if not m:
            continue
        did = m.group(1)
        try:
            ln = int(rec.get("length") or 0)
        except Exception:
            ln = 0
        # Skip tiny error/redirect captures (documents/download ~750B stubs)
        if ln and ln < 5000:
            continue
        prev = best.get(did)
        prev_ln = int(prev.get("length") or 0) if prev else -1
        if not prev or ln > prev_ln:
            best[did] = {
                "download_id": did,
                "timestamp": rec.get("timestamp"),
                "length": ln,
                "cdx_original": orig,
            }
    return best


def rank_items(items: list[dict]) -> list[dict]:
    """Constitution first; prefer archived medium PDFs (throughput under MAX_NEW)."""
    def _rank(it: dict) -> tuple:
        kind = it.get("kind") or ""
        if kind == "constitution":
            return (0, 0, 0, "")
        score = 50
        if kind == "nass_doc":
            score -= 20  # legacy Acts via Wayback — highest yield
        elif kind == "nass_act":
            score -= 10
        elif kind == "nass_bill":
            score -= 5
        elif kind == "fmj_pdf":
            score -= 8
        if it.get("wayback_ts"):
            score -= 15
        try:
            ln = int(it.get("cdx_length") or 0)
        except Exception:
            ln = 0
        if ln > 8_000_000:
            score += 40
        elif ln > 3_000_000:
            score += 15
        elif 20_000 <= ln <= 1_500_000:
            score -= 10
        return (1, score, ln or 0, it.get("download_id") or it.get("url") or "")
    return sorted(items, key=_rank)


def discover(*, force: bool = False) -> list[dict]:
    dest = ROOT / CC / "raw" / "catalog.jsonl"
    force = force or env_int("FORCE_REDISCOVER", 0) == 1
    if not force and dest.exists() and dest.stat().st_size > 40:
        cached = []
        with dest.open(encoding="utf-8") as f:
            for line in f:
                try:
                    cached.append(json.loads(line))
                except Exception:
                    continue
        if cached:
            log.info("resume catalog n=%s (set FORCE_REDISCOVER=1 to rebuild)", len(cached))
            return rank_items(cached)

    items: list[dict] = []
    seen_keys: set[str] = set()

    def add(it: dict) -> None:
        key = it.get("ident") or f"{it.get('ident_prefix')}-{it.get('download_id')}" or it["url"]
        if key in seen_keys:
            return
        seen_keys.add(key)
        items.append(it)

    add({
        "url": FMOJ_CONST, "title": "Constitution of the Federal Republic of Nigeria 1999",
        "kind": "constitution", "fallback": [NHRC_CONST],
        "page": FMOJ_CONST_PAGE, "ident": "ng-constitution-1999",
        "discovery": "fmj_constitution_pdf",
    })

    res = get_official(NASS)
    html = res.get("text") or ""
    nass_items = parse_nass_homepage(html)
    log.info("nass homepage acts=%s retrieval=%s", len(nass_items), res.get("retrieval"))
    for it in nass_items:
        add(it)

    # Current portal: documents/download/{id}
    for prefix in (
        "https://nass.gov.ng/documents/download/",
        "https://www.nass.gov.ng/documents/download/",
        "http://nass.gov.ng/documents/download/",
    ):
        best = _cdx_best(prefix, limit=400, id_re=r"documents/download/(\d+)")
        for did, row in best.items():
            add({
                "url": f"https://nass.gov.ng/documents/download/{did}",
                "title": f"National Assembly Act PDF {did}",
                "download_id": did, "kind": "nass_act",
                "ident_prefix": "ng-nass",
                "wayback_ts": row.get("timestamp"),
                "cdx_original": row.get("cdx_original"),
                "cdx_length": row.get("length"),
                "discovery": "wayback_documents_download",
            })

    # Legacy portal with real PDF captures: document/download/{id}
    for prefix in (
        "http://nass.gov.ng/document/download/",
        "https://nass.gov.ng/document/download/",
        "http://www.nass.gov.ng/document/download/",
        "https://www.nass.gov.ng/document/download/",
    ):
        best = _cdx_best(prefix, limit=500, id_re=r"document/download/(\d+)")
        log.info("legacy document/download unique usable from %s: %s", prefix, len(best))
        for did, row in best.items():
            add({
                "url": f"https://nass.gov.ng/document/download/{did}",
                "title": f"National Assembly document {did}",
                "download_id": did, "kind": "nass_doc",
                "ident_prefix": "ng-nass-doc",
                "wayback_ts": row.get("timestamp"),
                "cdx_original": row.get("cdx_original"),
                "cdx_length": row.get("length"),
                "discovery": "wayback_document_download",
            })

    # Bill PDFs hosted on NASS
    for prefix in (
        "https://nass.gov.ng/documents/billdownload/",
        "https://www.nass.gov.ng/documents/billdownload/",
    ):
        best = _cdx_best(prefix, limit=400, id_re=r"billdownload/(\d+)")
        for did, row in best.items():
            add({
                "url": f"https://nass.gov.ng/documents/billdownload/{did}.pdf",
                "title": f"National Assembly bill PDF {did}",
                "download_id": did, "kind": "nass_bill",
                "ident_prefix": "ng-nass-bill",
                "wayback_ts": row.get("timestamp"),
                "cdx_original": row.get("cdx_original"),
                "cdx_length": row.get("length"),
                "discovery": "wayback_billdownload",
            })

    # FMOJ official law-like PDFs
    fmj = []
    for prefix in (
        "https://justice.gov.ng/wp-content/uploads/",
        "https://www.justice.gov.ng/wp-content/uploads/",
    ):
        try:
            fmj += af.search_wayback_machine(
                prefix, match_type="prefix", limit=200,
                extra_filters=["mimetype:application/pdf"],
            )
        except Exception as exc:
            log.warning("fmj cdx: %s", exc)
    log.info("wayback fmj pdf cdx=%s", len(fmj))
    seen_pdf = {FMOJ_CONST}
    for rec in fmj:
        orig = (rec.get("original") or "").split("?")[0]
        if not orig.lower().endswith(".pdf"):
            continue
        if orig in seen_pdf:
            continue
        path = urlparse(orig).path
        if FMOJ_SKIP_RE.search(path) and not FMOJ_KEEP_RE.search(path):
            continue
        if not FMOJ_KEEP_RE.search(path):
            continue
        seen_pdf.add(orig)
        stem = Path(path).stem.replace("-", " ").replace("_", " ")
        add({
            "url": orig.replace("http://", "https://"),
            "title": stem,
            "kind": "fmj_pdf",
            "ident": f"ng-fmj-{Path(path).name}",
            "wayback_ts": rec.get("timestamp"),
            "cdx_original": orig,
            "cdx_length": rec.get("length"),
            "discovery": "wayback_fmj_uploads",
        })

    # NHRC official Act PDFs (federal .gov.ng)
    for seed in (
        {
            "url": "https://nigeriarights.gov.ng/files/nhrcact.pdf",
            "title": "National Human Rights Commission Act",
            "ident": "ng-nhrc-act",
            "kind": "nhrc_pdf",
            "discovery": "nhrc_files",
        },
        {
            "url": "https://nigeriarights.gov.ng/files/NHRC_ACT_2010%20AMMENDMENT.pdf",
            "title": "National Human Rights Commission Act 2010 Amendment",
            "ident": "ng-nhrc-act-2010-amendment",
            "kind": "nhrc_pdf",
            "discovery": "nhrc_files",
        },
        {
            "url": "https://www.nigeriarights.gov.ng/files/childrightact.pdf",
            "title": "Child Rights Act",
            "ident": "ng-nhrc-child-rights-act",
            "kind": "nhrc_pdf",
            "discovery": "nhrc_files",
        },
    ):
        try:
            hits = af.search_wayback_machine(
                seed["url"], match_type="exact", limit=8,
                extra_filters=["mimetype:application/pdf"],
            )
        except Exception:
            hits = []
        best = None
        for h in hits:
            try:
                ln = int(h.get("length") or 0)
            except Exception:
                ln = 0
            if ln < 5000:
                continue
            if not best or ln > int(best.get("length") or 0):
                best = h
        if best:
            seed = dict(seed)
            seed["wayback_ts"] = best.get("timestamp")
            seed["cdx_original"] = best.get("original")
            seed["cdx_length"] = best.get("length")
        add(seed)

    items = rank_items(items)
    atomic_write(dest, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
    log.info("catalog n=%s", len(items))
    return items


def fetch_pdf_bytes(
    url: str,
    wayback_ts: Optional[str] = None,
    *,
    archive_first: bool = False,
    cdx_original: Optional[str] = None,
) -> tuple[bytes, str, str]:
    """Return (pdf_bytes, retrieval, used_url)."""
    res: dict = {"retrieval": "skip_live"}
    if not archive_first:
        res = get_official(url, accept="application/pdf,application/octet-stream,*/*")
        body = res.get("content") or b""
        if res.get("status") == "success" and body[:4] == b"%PDF" and len(body) >= 5000:
            return body, res.get("retrieval") or "live", res.get("final_url") or url

    # Prefer exact CDX original (often http://www.nass.gov.ng:80/...) then variants
    candidates = []
    if cdx_original and wayback_ts:
        candidates.append((cdx_original, wayback_ts))
    if wayback_ts:
        candidates.append((url, wayback_ts))
        if url.startswith("https://"):
            candidates.append((url.replace("https://", "http://", 1), wayback_ts))
        if "www.nass.gov.ng" not in url and "nass.gov.ng" in url:
            candidates.append((url.replace("://nass.gov.ng", "://www.nass.gov.ng"), wayback_ts))
            candidates.append((url.replace("https://nass.gov.ng", "http://www.nass.gov.ng:80"), wayback_ts))
            candidates.append((url.replace("https://nass.gov.ng", "http://nass.gov.ng:80"), wayback_ts))
    # Newest snapshot (may 302 on some paths)
    if cdx_original:
        candidates.append((cdx_original, None))
    candidates.append((url, None))
    if url.startswith("https://"):
        candidates.append((url.replace("https://", "http://", 1), None))

    seen = set()
    for cand_url, ts in candidates:
        key = (cand_url, ts or "")
        if key in seen:
            continue
        seen.add(key)
        wb = wayback_only(cand_url, ts)
        body = wb.get("content") or b""
        if wb.get("status") == "success" and body[:4] == b"%PDF" and len(body) >= 5000:
            return body, "archive", wb.get("wayback_url") or cand_url

    # Common Crawl of official URL
    cc = try_common_crawl(url)
    body = cc.get("content") or b""
    if cc.get("status") == "success" and body[:4] == b"%PDF" and len(body) >= 5000:
        return body, "common_crawl", url

    return b"", res.get("retrieval") or "fail", url


def pdf_quick_text(raw: bytes, max_pages: int = 3) -> str:
    """First-pages pdftotext for classification (no OCR)."""
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8",
                 "-f", "1", "-l", str(max_pages), tmp.name, "-"],
                check=False, capture_output=True, timeout=60,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdf_quick_text: %s", exc)
    return ""


def fetch_pdf_text(
    url: str,
    wayback_ts: Optional[str] = None,
    *,
    archive_first: bool = False,
    cdx_original: Optional[str] = None,
) -> tuple[str, str, str, str]:
    """Return (text, retrieval, used_url, backend)."""
    body, retrieval, used = fetch_pdf_bytes(
        url, wayback_ts, archive_first=archive_first, cdx_original=cdx_original,
    )
    if not body:
        return "", retrieval, used, "no_pdf"
    text, backend = pdf_to_text(body)
    return text, retrieval, used, backend


def improve_title(text: str, fallback: str) -> str:
    if not text:
        return fallback
    head = text[:2000]
    m = re.search(
        r"(?im)^(AN ACT[^\n]+|"
        r"[A-Z][A-Za-z0-9 ,.'()&\-]{8,140} (?:ACT|BILL),?\s+\d{4}|"
        r"A BILL[^\n]{10,160})",
        head,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    # First substantial line
    for line in head.splitlines():
        line = line.strip()
        if len(line) >= 20 and re.search(r"(?i)act|bill|constitution|order", line):
            return re.sub(r"\s+", " ", line)[:240]
    return fallback


def fetch_one(it: dict) -> str:
    kind = it.get("kind")
    url = it["url"]
    if kind == "constitution":
        ident = it.get("ident") or "ng-constitution-1999"
        text, retrieval, used, backend = fetch_pdf_text(url, it.get("wayback_ts"))
        if len(text) < 200:
            for fb in it.get("fallback") or []:
                text, retrieval, used, backend = fetch_pdf_text(fb)
                if len(text) >= 200:
                    url = fb
                    break
        title = "Constitution of the Federal Republic of Nigeria 1999"
        st = write_law(
            ident=ident, title=title, text=text, source_url=url, date="1999-05-29",
            doc_type="constitution", official="Constitution of the Federal Republic of Nigeria 1999",
            extra_meta={
                "discovery": {"method": it.get("discovery") or "fmj_constitution_pdf", "page": it.get("page")},
                "retrieval": {"method": retrieval, "used_url": used},
                "text_extraction": {"source": "official", "backend": backend},
                "gaps": "FMOJ PDF is the 2020 ministry upload of the 1999 Constitution; later Alteration Acts may not be consolidated in this file.",
            },
        )
        if st == "fail":
            log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "constitution_empty"})
        return st

    prefix = it.get("ident_prefix") or "ng-nass"
    if it.get("ident"):
        ident = it["ident"]
    elif it.get("download_id"):
        ident = f"{prefix}-{it['download_id']}"
    else:
        ident = url

    # Legacy document/download is dead live (SPA HTML); go Wayback/CDX first.
    # Prefer archive whenever CDX has a fat snapshot timestamp.
    try:
        cdx_ln = int(it.get("cdx_length") or 0)
    except Exception:
        cdx_ln = 0
    archive_first = (
        kind in ("nass_doc", "nass_bill", "nhrc_pdf")
        or "/document/download/" in url
        or "/billdownload/" in url
        or (bool(it.get("wayback_ts")) and cdx_ln >= 5000)
    )
    body, retrieval, used = fetch_pdf_bytes(
        url, it.get("wayback_ts"),
        archive_first=archive_first,
        cdx_original=it.get("cdx_original"),
    )
    if not body:
        log_failure(CC, {
            "id": ident, "url": url, "status": "failed", "reason": "empty_pdf",
            "retrieval": retrieval, "backend": "no_pdf",
        })
        return "fail"

    # Fast classify on first pages before expensive OCR
    quick = pdf_quick_text(body, max_pages=3)
    if quick:
        ok_q, reason_q = is_legislative_fulltext(quick)
        if not ok_q and reason_q in ("parliamentary_procedure", "journal"):
            log_failure(CC, {
                "id": ident, "url": url, "status": "filtered", "reason": reason_q,
                "retrieval": retrieval,
            })
            log.info("filter %s reason=%s (quick)", ident, reason_q)
            return "skip"

    text, backend = pdf_to_text(body)
    if len(text) < 120:
        log_failure(CC, {
            "id": ident, "url": url, "status": "failed", "reason": "empty_pdf",
            "retrieval": retrieval, "backend": backend,
        })
        return "fail"

    ok, reason = is_legislative_fulltext(text)
    if not ok:
        log_failure(CC, {
            "id": ident, "url": url, "status": "filtered", "reason": reason,
            "retrieval": retrieval,
        })
        log.info("filter %s reason=%s", ident, reason)
        return "skip"  # not a hard fail — intentional filter

    title = improve_title(text, it.get("title") or ident)
    low = title.lower()
    if "constitution" in low:
        doc_type = "constitution"
    elif "bill" in low:
        doc_type = "bill"
    elif "order" in low:
        doc_type = "executive_order"
    else:
        doc_type = "statute"

    st = write_law(
        ident=ident, title=title, text=text, source_url=url, date=None,
        doc_type=doc_type, extra_meta={
            "discovery": {
                "method": it.get("discovery") or kind,
                "cdx_original": it.get("cdx_original"),
                "cdx_length": it.get("cdx_length"),
            },
            "retrieval": {"method": retrieval, "used_url": used},
            "text_extraction": {"source": "official", "backend": backend},
            "nass_download_id": it.get("download_id"),
            "content_class": reason,
        },
    )
    if st == "fail":
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "write_fail"})
    else:
        log.info("%s %s chars=%s retrieval=%s backend=%s", st, ident, len(text), retrieval, backend)
    return st


def main():
    setup()
    t0 = utcnow()
    t_start = time.time()
    max_new = env_int("MAX_NEW", 120)
    max_seconds = env_int("MAX_SECONDS", 7200)
    items = discover(force=env_int("FORCE_REDISCOVER", 0) == 1)
    already = existing_ids(CC)
    counters = {"ok": 0, "skip": 0, "fail": 0}
    notes = (
        "Constitution from Federal Ministry of Justice official PDF; Acts/Bills from "
        "National Assembly nass.gov.ng documents/download, legacy document/download, "
        "and documents/billdownload (live + Wayback CDX of official PDF URLs; Common "
        "Crawl fallback when enabled). Parliamentary Votes/Order/Notice Papers filtered "
        "out. Image-only official PDFs OCR'd with tesseract eng when text layer missing. "
        "gazettes.africa not crawled (robots Disallow: /gazettes/). Not "
        "LawNigeria/LawPavilion/Legalpedia. NASS current SPA hosts a subset; older "
        "full-text Acts recovered from Wayback of official nass.gov.ng paths. Official "
        f"Gazette prevails. Started {t0}. MAX_NEW={max_new}."
    )
    for n, it in enumerate(items, 1):
        if counters["ok"] >= max_new:
            log.info("hit MAX_NEW=%s", max_new)
            break
        if time.time() - t_start >= max_seconds:
            log.info("hit MAX_SECONDS=%s", max_seconds)
            break
        # Pre-skip known ids without network
        if it.get("kind") == "constitution":
            rid = slug_id(CC, it.get("ident") or "ng-constitution-1999")
        elif it.get("ident"):
            rid = slug_id(CC, it["ident"])
        elif it.get("download_id"):
            rid = slug_id(CC, f"{it.get('ident_prefix') or 'ng-nass'}-{it['download_id']}")
        else:
            rid = None
        if rid and rid in already:
            counters["skip"] += 1
            continue
        try:
            st = fetch_one(it)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if st == "ok" and rid:
            already.add(rid)
        if n % 10 == 0 or n == len(items) or st == "ok":
            log.info(
                "progress %s/%s ok=%s skip=%s fail=%s elapsed=%.0fs last=%s",
                n, len(items), counters["ok"], counters["skip"], counters["fail"],
                time.time() - t_start, st,
            )
        if st == "ok" and counters["ok"] % 10 == 0:
            n_instr = len(existing_ids(CC))
            write_summary(
                CC, country=COUNTRY,
                source="Federal Ministry of Justice + National Assembly (official hosts)",
                source_urls=[NASS, FMOJ_CONST_PAGE, FMOJ_CONST, NHRC_CONST],
                license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
                skipped=counters["skip"], failed=counters["fail"],
                coverage="partial-official-fulltext", notes=notes + f" Mid-run checkpoint.",
                extra=f"instruments_now={n_instr}. checkpoint_ok={counters['ok']}.",
            )
            atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
                "discovered": len(items), **counters, "coverage": "partial-official-fulltext",
                "instruments_now": n_instr, "started": t0, "checkpoint": utcnow(),
                "max_new": max_new, "max_seconds": max_seconds,
            }, indent=2) + "\n")
    n_instr = len(existing_ids(CC))
    cov = "partial-official-fulltext"
    if counters["ok"] + counters["skip"] >= 1 and counters["fail"] == 0:
        cov = "official-hosted-snapshot"
    elif n_instr >= 80:
        cov = "official-hosted-snapshot"
    write_summary(
        CC, country=COUNTRY,
        source="Federal Ministry of Justice + National Assembly (official hosts)",
        source_urls=[NASS, FMOJ_CONST_PAGE, FMOJ_CONST, NHRC_CONST],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=cov, notes=notes,
        extra=f"instruments_now={n_instr}. MAX_NEW={max_new}.",
    )
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "instruments_now": n_instr,
        "started": t0, "finished": utcnow(),
        "max_new": max_new, "max_seconds": max_seconds,
    }, indent=2) + "\n")
    log.info("done %s instruments_now=%s", counters, n_instr)


if __name__ == "__main__":
    main()
