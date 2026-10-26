#!/usr/bin/env python3
"""Nauru: RONLAW official API + PDF assets (ronlaw.gov.nr).

Official only — public JSON API (no login):
  GET  /api/pdf/availableyears/acts
  GET  /api/pdf/latest/{year|any}/{month|any}/acts/{letter|any}/50
  POST /api/pdf/search  (Elasticsearch DSL)
  PDF  https://ronlaw.gov.nr/assets + file_path

Prefer acts category. SPA HTML shell is empty — do not scrape it.
No captcha/WAF bypass. Not legal advice.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, split_by_pattern

CC = "nr"
COUNTRY = "Nauru"
SOURCE_TYPE = "ronlaw_gov_nr"
LICENSE = (
    "Official Nauruan legislation as published on RONLAW (ronlaw.gov.nr), "
    "Department of Justice & Border Control. The authentic official text prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://ronlaw.gov.nr/"
API = "https://ronlaw.gov.nr/api/pdf"
ASSETS = "https://ronlaw.gov.nr/assets"
PORTAL = "https://ronlaw.gov.nr/"
SLEEP = float(os.environ.get("SLEEP", "0.3"))
MIN_TEXT = 80
log = logging.getLogger("nr")
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
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


def title_clean(title: str) -> str:
    t = (title or "").replace(".pdf", "").replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"_serv\d+$", "", t, flags=re.I)
    t = re.sub(r"\s+serv\d+$", "", t, flags=re.I)
    return t[:240] or "Act"


def pdf_url(file_path: str) -> str:
    fp = file_path if file_path.startswith("/") else "/" + file_path
    # encode path segments but keep slashes
    parts = fp.split("/")
    enc = "/".join(quote(p, safe="") if p else "" for p in parts)
    return ASSETS + enc


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 100:
        log.info("resume catalog n=%s", len(existing))
        return existing
    # Prefer POST search size=1000 for full acts catalog
    body = {
        "_source": {"excludes": ["pages"]},
        "query": {"bool": {"must": [{"term": {"category": "acts"}}]}},
        "size": 1000,
        "sort": [
            {"year": {"order": "desc"}, "month": {"order": "desc"}, "title.keyword": {"order": "asc"}}
        ],
    }
    items, seen = [], set()
    try:
        if SLEEP:
            time.sleep(SLEEP)
        r = get_session(UA).post(
            f"{API}/search", json=body, timeout=(20, 90),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
    except Exception as exc:
        log.error("search fail: %s", exc)
        r = None
    hits = []
    if r is not None and r.status_code == 200:
        try:
            data = r.json()
            hits = (data.get("hits") or {}).get("hits") or []
            if not hits and isinstance(data, list):
                hits = data
        except Exception as exc:
            log.error("search parse: %s", exc)
    if not hits:
        # fallback: availableyears + latest per year
        try:
            yr = http_get(f"{API}/availableyears/acts", ua=UA, sleep=SLEEP, timeout=(20, 60), retries=3)
            years = yr.json() if yr.status_code == 200 else []
        except Exception:
            years = []
        for y in years:
            try:
                lr = http_get(
                    f"{API}/latest/{y}/any/acts/any/50", ua=UA, sleep=SLEEP,
                    timeout=(20, 60), retries=2,
                )
                if lr.status_code == 200:
                    hits.extend(lr.json() or [])
            except Exception as exc:
                log.info("latest %s fail: %s", y, exc)
    for hit in hits:
        src = hit.get("_source") or hit
        if (src.get("category") or "").lower() != "acts" and "acts" not in (src.get("file_path") or ""):
            continue
        if src.get("is_deleted"):
            continue
        fp = src.get("file_path") or ""
        if not fp or not fp.lower().endswith(".pdf"):
            continue
        if fp in seen:
            continue
        seen.add(fp)
        title = title_clean(src.get("title") or Path(unquote(fp)).stem)
        ident = Path(unquote(fp)).stem[:160]
        year = src.get("year")
        items.append({
            "url": pdf_url(fp),
            "file_path": fp,
            "title": title,
            "identifier": ident,
            "year": year,
            "kind": "act",
            "doc_id": hit.get("_id"),
        })
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def get_bytes(url: str) -> tuple[bytes, str]:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
            headers={"Accept": "application/pdf,*/*", "Referer": PORTAL},
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


def split_nr(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    ident = it.get("identifier") or Path(unquote((it.get("file_path") or url).split("?")[0])).stem
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    body, method = get_bytes(url)
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=40)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_clean(ident)
    year = it.get("year")
    date = f"{year}-01-01" if year else None
    if not date:
        year_m = re.search(r"(19|20)\d{2}", title)
        date = f"{year_m.group(0)}-01-01" if year_m else None
    docs = split_nr(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_nr.py", date=date, official_identifier=ident,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "ronlaw_file_path": it.get("file_path"),
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    log.info("ok %s method=%s chars=%s", rid[:70], method, len(text))
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
        CC, country=COUNTRY, source="RONLAW — Nauru Online Legal Database (ronlaw.gov.nr)",
        source_urls=[PORTAL, f"{API}/availableyears/acts", f"{API}/search"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="ronlaw-acts-api-pdfs",
        notes=(
            "Acts via public RONLAW /api/pdf/search + /assets PDF downloads. "
            "SPA shell not scraped. Admin API unused. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
