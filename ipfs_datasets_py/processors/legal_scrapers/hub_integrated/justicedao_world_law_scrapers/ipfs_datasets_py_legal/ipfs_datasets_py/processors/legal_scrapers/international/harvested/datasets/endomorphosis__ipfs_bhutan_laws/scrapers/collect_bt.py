#!/usr/bin/env python3
"""Bhutan: Acts PDFs from Office of the Attorney General (oag.gov.bt).

Official only:
  https://oag.gov.bt/language/en/resources/acts-2/

Public Act PDFs under /wp-content/uploads/. Bilingual EN/Dzongkha when published.
No WAF bypass. Not legal advice.
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

CC = "bt"
COUNTRY = "Bhutan"
SOURCE_TYPE = "oag_gov_bt_acts"
LICENSE = (
    "Official Acts of the Kingdom of Bhutan as published by the Office of the "
    "Attorney General (oag.gov.bt). The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://oag.gov.bt/"
ACTS_URL = "https://oag.gov.bt/language/en/resources/acts-2/"
SLEEP = float(os.environ.get("SLEEP", "0.55"))
MIN_TEXT = 80
log = logging.getLogger("bt")

ART_BT = re.compile(
    r"(?im)^\s*((?:Section|Article|CHAPTER|Chapter|Part|PART)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
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


def guess_lang(url: str, title: str) -> str:
    blob = (url + " " + title).lower()
    if "dzongkha" in blob or "dzongkha" in blob or re.search(r"[\u0f00-\u0fff]", title):
        return "dz"
    return "en"


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:240] or "Act"


def get_bytes(url: str) -> tuple[bytes, str]:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
            headers={"Accept": "application/pdf,*/*", "Referer": ACTS_URL},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live"
    if r is not None and r.status_code in (403, 429, 503, 202):
        res = af.fetch_with_fallbacks(url, try_http=False)
        body = res.get("content") or b""
        if res.get("status") == "success" and body[:4] == b"%PDF":
            return body, res.get("method") or "archive"
    res = af.fetch_with_fallbacks(url, try_http=False)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 50:
        log.info("resume catalog n=%s", len(existing))
        return existing
    try:
        r = http_get(ACTS_URL, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4)
    except Exception as exc:
        log.error("acts page fail: %s", exc)
        return existing
    if r.status_code != 200 or not r.text:
        log.error("acts page HTTP %s", r.status_code)
        return existing
    items, seen = [], set()
    for href in PDF_HREF.findall(r.text):
        url = urljoin(ACTS_URL, href.split("#")[0])
        if "oag.gov.bt" not in url.lower():
            continue
        if url in seen:
            continue
        seen.add(url)
        title = title_from_url(url)
        # Prefer anchor text if present nearby — keep URL stem as baseline
        m = re.search(
            rf'href=["\'][^"\']*{re.escape(Path(url).name)}["\'][^>]*>(.*?)</a>',
            r.text, re.I | re.S,
        )
        if m:
            t = re.sub(r"<[^>]+>", " ", m.group(1))
            t = re.sub(r"\s+", " ", t).strip()
            if len(t) > 8:
                title = t[:240]
        lang = guess_lang(url, title)
        ident = Path(unquote(url.split("?")[0])).stem[:160]
        items.append({
            "url": url, "title": title, "language": lang,
            "identifier": ident, "kind": "act",
        })
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_bt(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_BT, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    ident = it.get("identifier") or Path(unquote(url.split("?")[0])).stem
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    body, method = get_bytes(url)
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=60)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    lang = it.get("language") or guess_lang(url, title)
    year_m = re.search(r"(19|20)\d{2}", title) or re.search(r"(19|20)\d{2}", url)
    date = f"{year_m.group(0)}-01-01" if year_m else None
    docs = split_bt(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_bt.py", date=date, official_identifier=ident,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages,
            "text_extraction": {"source": "official", "backend": backend},
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
            log.info("time budget exhausted")
            break
        status = fetch_one(it, done)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Office of the Attorney General Acts (oag.gov.bt)",
        source_urls=[ACTS_URL],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="oag-acts-pdf-shelf",
        notes=(
            "Acts PDFs from official OAG Acts library (~185 hrefs). "
            "EN and Dzongkha versions retained when both published. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
