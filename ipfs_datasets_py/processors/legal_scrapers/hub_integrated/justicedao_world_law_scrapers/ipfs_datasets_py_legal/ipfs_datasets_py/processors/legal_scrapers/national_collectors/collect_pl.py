#!/usr/bin/env python3
"""Poland: in-force Dziennik Ustaw via official Sejm ELI API."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa

CC = "pl"
COUNTRY = "Poland"
SOURCE_TYPE = "sejm_eli"
LICENSE = (
    "Official texts of generally binding law of the Republic of Poland are not "
    "subject to copyright (Art. 4 of the Act on Copyright and Related Rights). "
    "ELI API: https://api.sejm.gov.pl/eli — reuse of API data as published by Sejm."
)
UA = DEFAULT_UA + " source=https://api.sejm.gov.pl/eli"
API = "https://api.sejm.gov.pl/eli"
WORKERS = 8
SLEEP = 0.15

log = logging.getLogger("pl")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items = []
    if cat.exists() and cat.stat().st_size > 1000:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog %s rows", len(items))
            return items
    offset = 0
    limit = 500
    total = None
    while True:
        url = f"{API}/acts/search"
        r = http_get(url, ua=UA, params={"publisher": "DU", "inForce": "1", "limit": limit, "offset": offset}, sleep=0.2)
        r.raise_for_status()
        data = r.json()
        total = data.get("totalCount") or data.get("count")
        batch = data.get("items") or []
        if not batch:
            break
        for it in batch:
            items.append(it)
            append_catalog(CC, it)
        log.info("catalog offset=%s got=%s total=%s", offset, len(items), total)
        offset += len(batch)
        if total is not None and offset >= int(total):
            break
        if len(batch) < limit:
            break
    return items


def pdf_text(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        try:
            out = subprocess.run(
                ["pdftotext", "-layout", "-q", tmp.name, "-"],
                capture_output=True, timeout=60,
            )
            return out.stdout.decode("utf-8", "replace").strip()
        except Exception:
            return ""


def fetch_one(it: dict, done: set[str]) -> str:
    pub = it.get("publisher") or "DU"
    year = it.get("year")
    pos = it.get("pos")
    ident = f"{pub}-{year}-{pos}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    detail = it
    try:
        r = http_get(f"{API}/acts/{pub}/{year}/{pos}", ua=UA, sleep=SLEEP)
        if r.status_code == 200 and r.content:
            detail = r.json()
    except Exception:
        pass
    text = ""
    fmt = None
    html_url = f"{API}/acts/{pub}/{year}/{pos}/text.html"
    try:
        r = http_get(html_url, ua=UA, sleep=SLEEP, allow_empty=True)
        if r.status_code == 200 and r.content and len(r.content) > 80:
            low = r.content.lower()
            if b"<html" in low or b"<section" in low or b"<h1" in low or b"<body" in low:
                text = html_to_text(r.text)
                fmt = "html"
    except Exception:
        pass
    if not text:
        pdf_url = f"{API}/acts/{pub}/{year}/{pos}/text.pdf"
        try:
            r = http_get(pdf_url, ua=UA, sleep=SLEEP, headers={"Accept": "application/pdf"})
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                text = pdf_text(r.content)
                fmt = "pdf"
        except Exception:
            pass
    if not text:
        log_failure(CC, {"identifier": ident, "source_url": html_url, "status": "failed", "reason": "empty_text"})
        return "fail"
    in_force = (detail.get("inForce") or it.get("inForce") or "")
    status = (detail.get("status") or it.get("status") or "")
    if in_force == "IN_FORCE" or status == "obowiązujący":
        law_status = "current"
        is_cur = True
    elif in_force == "NOT_IN_FORCE":
        law_status = "repealed"
        is_cur = False
    else:
        law_status = "unknown"
        is_cur = None
    title = detail.get("title") or it.get("title") or ident
    eli = detail.get("ELI") or it.get("ELI")
    eli_uri = f"https://eli.gov.pl/{eli}" if eli else None
    source_url = f"https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id={detail.get('address') or it.get('address')}"
    rec = base_record(
        cc=CC, country=COUNTRY, language="pl", ident=ident, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="pl-sejm-eli", eli=eli_uri,
        date=iso_date(detail.get("promulgation") or detail.get("announcementDate") or it.get("promulgation")),
        official_identifier=detail.get("displayAddress") or it.get("displayAddress") or ident,
        document_type=(detail.get("type") or it.get("type") or "statute").lower(),
        law_status=law_status, is_current=is_cur,
        extra_meta={"discovery": {"method": "eli_search_inForce", "address": detail.get("address")},
                    "official_metadata": {k: detail.get(k) for k in ("type", "status", "inForce", "entryIntoForce", "validFrom", "repealDate", "keywords", "ELI", "address") if detail.get(k) is not None}},
        extra_fields={"valid_from": iso_date(detail.get("validFrom") or detail.get("entryIntoForce")),
                      "valid_to": iso_date(detail.get("repealDate")),
                      "publication_date": iso_date(detail.get("promulgation")),
                      "effective_date": iso_date(detail.get("entryIntoForce"))},
    )
    rec["metadata"]["content_type"] = fmt
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("discovered=%s already=%s", len(items), len(done))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, it, done): it for it in items}
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"identifier": str(futs[fut].get("address")), "status": "failed", "reason": repr(exc)})
            if st == "ok":
                ok += 1
            elif st == "skip":
                skip += 1
            else:
                fail += 1
            if n % 200 == 0:
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY, source="Sejm ELI API / Dziennik Ustaw",
                    source_urls=["https://api.sejm.gov.pl/eli", "https://isap.sejm.gov.pl/"],
                    license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete", notes="in-force DU only; HTML then PDF; resume-safe",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and (ok + skip) >= len(items) else "catalog-backed incomplete"
    write_summary(
        CC, country=COUNTRY, source="Sejm ELI API / Dziennik Ustaw",
        source_urls=["https://api.sejm.gov.pl/eli", "https://eli.gov.pl/", "https://isap.sejm.gov.pl/"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage,
        notes="National in-force acts from Dziennik Ustaw (publisher=DU, inForce=1). Monitor Polski excluded. Texts from official ELI HTML or PDF.",
        last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
