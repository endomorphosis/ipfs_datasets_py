#!/usr/bin/env python3
"""Samoa: Consolidation of Laws PDFs from Attorney General (ag.gov.ws).

Official only:
  https://www.ag.gov.ws/consolidation-of-laws-of-samoa/

≥267 public consolidation PDFs under /wp-content/uploads/.
SKIP palemene.sharepoint.com (403 auth wall). No WAF bypass. Not legal advice.
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
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, split_by_pattern

CC = "ws"
COUNTRY = "Samoa"
SOURCE_TYPE = "ag_gov_ws_consolidation"
LICENSE = (
    "Official Consolidation of Laws of Samoa as published by the Office of the "
    "Attorney General (ag.gov.ws). The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.ag.gov.ws/"
INDEX = "https://www.ag.gov.ws/consolidation-of-laws-of-samoa/"
SLEEP = float(os.environ.get("SLEEP", "0.55"))
MIN_TEXT = 80
log = logging.getLogger("ws")
ART_WS = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
        return []
    out = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = stem.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", stem).strip()[:240] or "Act"


def get_bytes(url: str) -> tuple[bytes, str]:
    if "sharepoint.com" in url.lower():
        return b"", "skip_sharepoint"
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
            headers={"Accept": "application/pdf,*/*", "Referer": INDEX},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live"
    res = af.fetch_with_fallbacks(url, try_http=False)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 100:
        log.info("resume catalog n=%s", len(existing))
        return existing
    try:
        r = http_get(INDEX, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4)
    except Exception as exc:
        log.error("index fail: %s", exc)
        return existing
    if r.status_code != 200 or not r.text:
        log.error("index HTTP %s", r.status_code)
        return existing
    items, seen = [], set()
    for href in PDF_HREF.findall(r.text):
        url = urljoin(INDEX, href.split("#")[0])
        low = url.lower()
        if "sharepoint.com" in low:
            continue
        if "ag.gov.ws" not in low:
            continue
        if url in seen:
            continue
        seen.add(url)
        title = title_from_url(url)
        ident = Path(unquote(url.split("?")[0])).stem[:160]
        items.append({"url": url, "title": title, "identifier": ident, "kind": "act"})
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_ws(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_WS, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    ident = it.get("identifier") or Path(unquote(url.split("?")[0])).stem
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    body, method = get_bytes(url)
    if method == "skip_sharepoint":
        return "skip"
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=50)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    year_m = re.search(r"(19|20)\d{2}", title) or re.search(r"(19|20)\d{2}", url)
    date = f"{year_m.group(0)}-01-01" if year_m else None
    docs = split_ws(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ws.py", date=date, official_identifier=ident,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages,
            "text_extraction": {"source": "official", "backend": backend},
            "consolidation": "Laws of Samoa 2023 (AG)",
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    log.info("ok %s method=%s chars=%s arts=%s", rid[:70], method, len(text), len(docs))
    return "ok"


def main():
    setup()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "0") or "0")
    max_seconds = int(os.environ.get("MAX_SECONDS", "7200") or "7200")
    t_start = time.time()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for it in items:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        status = fetch_one(it, done)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="AG Consolidation of Laws of Samoa (ag.gov.ws)",
        source_urls=[INDEX],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="ag-consolidation-2023-pdfs",
        notes=(
            "Consolidation of Laws of Samoa PDFs from official ag.gov.ws. "
            "Parliament SharePoint binaries skipped (403). Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
