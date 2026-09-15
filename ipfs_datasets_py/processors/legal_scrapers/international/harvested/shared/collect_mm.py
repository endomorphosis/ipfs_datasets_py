#!/usr/bin/env python3
"""Myanmar: Ministry of Information published laws (official gazette promulgation host).

Official sources only:
  https://www.moi.gov.mm/laws
  PDF downloads: https://www.moi.gov.mm/file-download/download/public/<id>

The Gazette of the Republic of the Union of Myanmar is published by the Ministry
of Information; moi.gov.mm/laws hosts promulgated law PDFs with Drupal paging
(?page=0..N). mlis.gov.mm / myanmar.gov.mm TLS often EOFs from this host — not
used when MOI listing works. No WAF bypass. Not commercial LIIs.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import logging
import re
import sys
from html import unescape
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC, COUNTRY, SOURCE_TYPE = "mm", "Myanmar", "moi_laws"
LICENSE = (
    "Laws of the Republic of the Union of Myanmar as published by the Ministry "
    "of Information (moi.gov.mm). Official gazette promulgation texts prevail. "
    "Not legal advice. Not commercial compilations."
)
UA = DEFAULT_UA + " source=https://www.moi.gov.mm/laws"
BASE = "https://www.moi.gov.mm"
INDEX = f"{BASE}/laws"
SLEEP = 0.4
# Starter: first N Drupal pages (page=80 observed as last)
MAX_PAGE = int(__import__("os").environ.get("MAX_PAGE", "90"))
log = logging.getLogger("mm")
PAIR_RE = re.compile(
    r'href="(/laws/(\d+))"[^>]*>([^<]+)</a>.*?href="(/file-download/download/public/\d+)"',
    re.S | re.I,
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


def discover() -> list[dict]:
    items, seen = [], set()
    empty = 0
    for page in range(0, MAX_PAGE + 1):
        url = f"{INDEX}?title=&field_law_year_target_id=All&page={page}"
        try:
            r = http_get(url, ua=UA, sleep=SLEEP, retries=3, timeout=(20, 90))
        except Exception as exc:
            log.info("page fail %s: %s", page, exc)
            empty += 1
            if empty >= 3:
                break
            continue
        if r.status_code != 200 or not r.text:
            empty += 1
            if empty >= 3:
                break
            continue
        pairs = PAIR_RE.findall(r.text)
        if not pairs:
            # fallback: downloads only
            downs = re.findall(r'href="(/file-download/download/public/\d+)"', r.text, re.I)
            laws = re.findall(r'href="(/laws/(\d+))"[^>]*>([^<]+)<', r.text, re.I)
            if not downs:
                empty += 1
                if empty >= 3:
                    break
                continue
            empty = 0
            for i, d in enumerate(downs):
                nid = laws[i][1] if i < len(laws) else d.rsplit("/", 1)[-1]
                title = unescape(laws[i][2]).strip() if i < len(laws) else nid
                pdf = urljoin(BASE + "/", unescape(d))
                if pdf in seen:
                    continue
                seen.add(pdf)
                row = {"url": pdf, "ident": f"moi-{nid}", "title": title, "law_path": laws[i][0] if i < len(laws) else ""}
                items.append(row)
                append_catalog(CC, row)
            log.info("page %s items=%s (fallback)", page, len(items))
            continue
        empty = 0
        for law_path, nid, title, dl in pairs:
            pdf = urljoin(BASE + "/", unescape(dl))
            if pdf in seen:
                continue
            seen.add(pdf)
            row = {
                "url": pdf,
                "ident": f"moi-{nid}",
                "title": unescape(title).strip() or nid,
                "law_path": law_path,
            }
            items.append(row)
            append_catalog(CC, row)
        log.info("page %s items=%s", page, len(items))
    log.info("discovered %s", len(items))
    return items


def fetch_one(item: dict, done: set[str]) -> str:
    ident = item["ident"]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = item["url"]
    body = b""
    retrieval = "live"
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=2, timeout=(20, 90),
                     headers={"Accept": "application/pdf,*/*"})
        if r.status_code == 200 and r.content:
            body = r.content
            if body[:4] != b"%PDF":
                idx = body.find(b"%PDF", 0, 8192)
                if idx >= 0:
                    body = body[idx:]
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
    if (not body or body[:4] != b"%PDF") and __import__("os").environ.get("ARCHIVE", "0") == "1":
        # Wayback of the same official MOI URL only (no WAF bypass). Off by default —
        # live moi.gov.mm PDFs work; archive attempts were hanging the run.
        try:
            fb = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
            content = fb.get("content") or b""
            if fb.get("status") == "success" and content:
                if content[:4] != b"%PDF":
                    idx = content.find(b"%PDF", 0, 8192)
                    content = content[idx:] if idx >= 0 else b""
                if content[:4] == b"%PDF":
                    body = content
                    retrieval = "archive"
        except Exception as exc:
            log.info("archive fail %s: %s", url, exc)
    if not body or body[:4] != b"%PDF":
        log_failure(CC, {"identifier": ident, "source_url": url, "reason": "no_pdf"})
        return "fail"
    import os
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    text = pdf_bytes_to_text(body)
    extract_method = "pdftotext"
    my_chars = sum(1 for c in (text or "") if "က" <= c <= "႟")
    # Image-only MOI PDFs (Acrobat Image Conversion) need Myanmar OCR.
    # Keep non-empty text-layer even if custom-encoded; OCR only when empty/short.
    if not text or len(text) < 80:
        try:
            from pdf_extract_lib import extract_pdf_text
            ocr_pages = int(os.environ.get("OCR_PAGES", "3"))
            text2, method2, pages = extract_pdf_text(
                body, enable_ocr=True, ocr_lang="mya", ocr_max_pages=ocr_pages,
            )
            if text2 and len(text2) >= 80:
                text, extract_method = text2, method2
                my_chars = sum(1 for c in text if "က" <= c <= "႟")
                log.info("ocr ok %s method=%s pages=%s chars=%s my=%s", ident, method2, pages, len(text), my_chars)
        except Exception as exc:
            log.info("ocr fail %s: %s", ident, exc)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "reason": "empty_pdf_text"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="my", ident=ident, title=item["title"],
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="mm-moi-laws", document_type="statute",
        extra_meta={
            "discovery": {"method": "moi_laws_pager", "law_path": item.get("law_path")},
            "retrieval": retrieval,
            "extract_method": extract_method,
            "myanmar_chars": my_chars,
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def load_catalog_items() -> list[dict]:
    p = ROOT / CC / "raw" / "catalog.jsonl"
    if not p.exists() or p.stat().st_size < 40:
        return []
    items, seen = [], set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            url = row.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            items.append(row)
    return items


def main():
    setup()
    t0 = utcnow()
    items = load_catalog_items()
    if len(items) < 50:
        items = discover()
    else:
        log.info("reusing catalog %s", len(items))
    done = existing_ids(CC)
    ok = skip = fail = 0
    import os, threading
    workers = int(os.environ.get("WORKERS", "4"))
    lock = threading.Lock()

    def _one(item):
        try:
            return fetch_one(item, done)
        except Exception as exc:
            log_failure(CC, {"source_url": item.get("url"), "reason": repr(exc)})
            return "fail"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, it): it for it in items}
        for i, fut in enumerate(as_completed(futs), 1):
            st = fut.result()
            with lock:
                ok += st == "ok"
                skip += st == "skip"
                fail += st == "fail"
                if i % 20 == 0 or i == len(futs):
                    log.info("progress %s/%s ok=%s skip=%s fail=%s", i, len(futs), ok, skip, fail)
    write_summary(
        CC, country=COUNTRY,
        source="Myanmar Ministry of Information laws (moi.gov.mm/laws)",
        source_urls=[INDEX], license_text=LICENSE, discovered=len(items),
        fetched=ok, skipped=skip, failed=fail,
        coverage=f"MOI laws Drupal pages 0..{MAX_PAGE} (full pager target; site last page ~80)",
        notes=(
            "Official MOI promulgated law PDFs. MLIS TLS EOF from this host — MOI used. "
            "Incomplete vs full gazette run. Not legal advice."
        ),
        last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(items), ok, skip, fail)


if __name__ == "__main__":
    main()
