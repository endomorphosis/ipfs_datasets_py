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

import logging
import re
import sys
from html import unescape
from pathlib import Path
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
MAX_PAGE = 20
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
        r = http_get(url, ua=UA, sleep=SLEEP, retries=3, timeout=(20, 120),
                     headers={"Accept": "application/pdf,*/*"})
        if r.status_code == 200 and r.content:
            body = r.content
    except Exception as exc:
        log.info("live fail %s: %s — archive", url, exc)
    if body[:4] != b"%PDF":
        fb = af.fetch_with_fallbacks(url, try_http=False, try_cc=True)
        if fb.get("status") == "success" and (fb.get("content") or b"")[:4] == b"%PDF":
            body = fb["content"]
            retrieval = "archive"
    if body[:4] != b"%PDF":
        log_failure(CC, {"identifier": ident, "source_url": url, "reason": "no_pdf"})
        return "fail"
    text = pdf_bytes_to_text(body)
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
        },
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for i, item in enumerate(items, 1):
        try:
            st = fetch_one(item, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"source_url": item.get("url"), "reason": repr(exc)})
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 20 == 0:
            log.info("progress %s/%s ok=%s fail=%s", i, len(items), ok, fail)
    write_summary(
        CC, country=COUNTRY,
        source="Myanmar Ministry of Information laws (moi.gov.mm/laws)",
        source_urls=[INDEX], license_text=LICENSE, discovered=len(items),
        fetched=ok, skipped=skip, failed=fail,
        coverage=f"MOI laws Drupal pages 0..{MAX_PAGE} (starter; site last page ~80)",
        notes=(
            "Official MOI promulgated law PDFs. MLIS TLS EOF from this host — MOI used. "
            "Incomplete vs full gazette run. Not legal advice."
        ),
        last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(items), ok, skip, fail)


if __name__ == "__main__":
    main()
