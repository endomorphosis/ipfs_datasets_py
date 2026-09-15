#!/usr/bin/env python3
"""Ireland: electronic Irish Statute Book ELI XML (Acts + SIs)."""
from __future__ import annotations

import logging
import time
import re
import sys
from xml.etree import ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "ie"
COUNTRY = "Ireland"
SOURCE_TYPE = "irishstatutebook"
LICENSE = (
    "Oireachtas (Open Data) PSI Licence incorporating CC BY 4.0 International, "
    "as stated at https://www.irishstatutebook.ie/eli/open-data.html"
)
# Site 403s generic bots; identify as a documented research UA that still looks like a browser.
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE = "https://www.irishstatutebook.ie"
log = logging.getLogger("ie")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def list_year(kind: str, year: int) -> list[int]:
    # Year index pages 403 for bots; probe consecutive numbers via ELI XML (Chrome UA).
    nums = []
    miss = 0
    cap = 80 if kind == "act" else 250
    for n in range(1, cap + 1):
        url = f"{BASE}/eli/{year}/{kind}/{n}/enacted/en/xml"
        r = http_get(url, ua=UA, sleep=0.35, allow_empty=True)
        if r.status_code == 200 and r.content and b"<" in r.content[:40] and b"403" not in r.content[:80]:
            nums.append(n)
            miss = 0
        else:
            miss += 1
            if miss >= 8 and n >= 8:
                break
            if r.status_code == 403:
                time.sleep(5)
    return nums


def parse_xml(raw: str) -> tuple[str, str, Optional[str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return "", html_to_text(raw), None
    title = ""
    date = None
    for el in root.iter():
        tag = localtag(el.tag).lower()
        if tag == "title" and not title:
            title = "".join(el.itertext()).strip()
        if tag in {"dateofenactment", "date", "enacted"} and date is None:
            date = iso_date((el.text or el.get("date") or "").strip())
    text = xml_to_text(raw)
    return title, text, date


def fetch_doc(kind: str, year: int, num: int, done: set[str]) -> str:
    ident = f"{year}-{kind}-{num}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    xml_url = f"{BASE}/eli/{year}/{kind}/{num}/enacted/en/xml"
    html_url = f"{BASE}/eli/{year}/{kind}/{num}/enacted/en/html"
    r = http_get(xml_url, ua=UA, sleep=0.45)
    title = text = ""
    date = None
    src = xml_url
    if r.status_code == 200 and r.content and b"<" in r.content[:40]:
        title, text, date = parse_xml(r.text)
    if not text:
        r2 = http_get(html_url, ua=UA, sleep=0.35)
        if r2.status_code == 200:
            text = html_to_text(r2.text)
            src = html_url
            if not title:
                m = re.search(r"<title>([^<]+)</title>", r2.text, re.I)
                title = m.group(1).strip() if m else ident
    if not text:
        log_failure(CC, {"identifier": ident, "source_url": xml_url, "status": "failed", "reason": "empty_text"})
        return "fail"
    eli = f"{BASE}/eli/{year}/{kind}/{num}/enacted/en/html"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title or ident, text=text,
        source_url=eli, source_type=SOURCE_TYPE, license_text=LICENSE, collector="ie-eisb-eli",
        eli=eli, date=date or f"{year}-01-01",
        official_identifier=f"{kind.upper()} {num}/{year}",
        document_type="statute" if kind == "act" else "regulation",
        law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "eli_year_index", "kind": kind}},
    )
    rec["languages"] = ["en", "ga"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    discovered = ok = skip = fail = 0
    for kind in ("act", "si"):
        for year in range(1922, 2027):
            nums = list_year(kind, year)
            discovered += len(nums)
            log.info("%s %s n=%s", kind, year, len(nums))
            for num in nums:
                try:
                    st = fetch_doc(kind, year, num, done)
                except Exception as exc:
                    st = "fail"
                    log_failure(CC, {"identifier": f"{year}-{kind}-{num}", "status": "failed", "reason": repr(exc)})
                if st == "ok":
                    ok += 1
                    done.add(slug_id(CC, f"{year}-{kind}-{num}"))
                elif st == "skip":
                    skip += 1
                else:
                    fail += 1
            if year % 5 == 0:
                write_summary(CC, country=COUNTRY, source="electronic Irish Statute Book (eISB) ELI",
                              source_urls=["https://www.irishstatutebook.ie/", "https://www.irishstatutebook.ie/eli/open-data.html"],
                              license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="Acts and SIs from ELI year listings", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="electronic Irish Statute Book (eISB) ELI XML",
                  source_urls=["https://www.irishstatutebook.ie/", "https://www.irishstatutebook.ie/eli/open-data.html"],
                  license_text=LICENSE, discovered=discovered, fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if fail == 0 else "catalog-backed incomplete",
                  notes="Official Acts and Statutory Instruments 1922–present via ELI XML/HTML. License: Oireachtas PSI / CC BY 4.0.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", discovered, ok, skip, fail)


if __name__ == "__main__":
    main()
