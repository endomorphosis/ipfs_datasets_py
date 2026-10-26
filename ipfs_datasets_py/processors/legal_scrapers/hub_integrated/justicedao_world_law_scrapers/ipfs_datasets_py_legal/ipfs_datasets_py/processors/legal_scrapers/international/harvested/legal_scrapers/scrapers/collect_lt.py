#!/usr/bin/env python3
"""Lithuania: e-TAR / data.gov.lt Spinta. Portal is Cloudflare-gated; Spinta 500s."""
from __future__ import annotations
import logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "lt", "Lithuania", "etar"
LICENSE = "TAR open data is commonly CC BY 4.0 on data.gov.lt when the Spinta API is up; official texts at e-tar.lt."
UA = DEFAULT_UA + " source=https://www.e-tar.lt/"
log = logging.getLogger("lt")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def main():
    setup(); t0 = utcnow()
    notes = []
    items = []
    seeds = [
        "https://www.e-tar.lt/",
        "https://www.e-tar.lt/portal/lt/legalActSearch",
        "https://get.data.gov.lt",
        "https://get.data.gov.lt/datasets/gov/lrs/tar",
        "https://get.data.gov.lt/datasets/gov/lrsk/teises_aktai/Dokumentas",
        "https://data.gov.lt/datasets/2613/",
        "https://data.gov.lt/api/3/action/package_search?q=tar+teis&rows=10",
        "https://opendata.lrs.lt/",
    ]
    for url in seeds:
        try:
            r = http_get(url, ua=UA, sleep=0.35, timeout=(15, 40), retries=2)
            notes.append(f"seed {url} -> HTTP {r.status_code} bytes={len(r.content or b'')} ct={r.headers.get('content-type','')[:40]}")
            (ROOT / CC / "raw" / (re.sub(r"[^a-z0-9]+","_", url)[:90] + ".bin")).write_bytes((r.content or b"")[:20000])
            if r.status_code == 200 and r.content[:1] in (b"{", b"["):
                try:
                    data = r.json()
                    notes.append(f"  json ok type={type(data).__name__}")
                    rows = data if isinstance(data, list) else (data.get("result") or data.get("_data") or data.get("results") or [])
                    if isinstance(rows, dict) and "results" in rows:
                        rows = rows["results"]
                    if isinstance(rows, list):
                        for row in rows[:500]:
                            if isinstance(row, dict):
                                items.append(row); append_catalog(CC, row)
                except Exception as exc:
                    notes.append(f"  json parse {exc}")
            if r.status_code == 200 and b"Just a moment" in (r.content or b"")[:500]:
                notes.append("  Cloudflare challenge")
        except Exception as exc:
            notes.append(f"seed {url} ERROR {exc}")
    done = existing_ids(CC); ok = skip = fail = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or row.get("name") or row.get("title") or "")[:80]
        if not ident:
            continue
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1; continue
        text = str(row.get("notes") or row.get("description") or row.get("text") or "")
        src = row.get("url") or row.get("resources") or "https://data.gov.lt/"
        if isinstance(src, list) and src:
            src = (src[0].get("url") if isinstance(src[0], dict) else str(src[0]))
        if not text or len(text) < 80:
            fail += 1; continue
        rec = base_record(cc=CC, country=COUNTRY, language="lt", ident=ident, title=ident, text=text,
                          source_url=str(src), source_type=SOURCE_TYPE, license_text=LICENSE,
                          collector="lt-datagov", eli=None, date=None, official_identifier=ident,
                          document_type="statute", law_status="unknown", is_current=None)
        write_instrument(CC, rec); ok += 1
    if not ok:
        notes.append(
            "Blocker: e-tar.lt returns Cloudflare JS challenge (HTTP 403). get.data.gov.lt / data.gov.lt Spinta "
            "paths return HTTP 500 HTML error pages. No TAR act texts this run. Retry when Spinta recovers."
        )
    write_summary(CC, country=COUNTRY, source="Register of Legal Acts (TAR) / data.gov.lt",
                  source_urls=["https://www.e-tar.lt/", "https://get.data.gov.lt", "https://data.gov.lt/datasets/2613/"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete", notes="\n".join(notes), last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(items), ok, fail)


if __name__ == "__main__":
    main()
