#!/usr/bin/env python3
"""Iceland: Althingi official lagasafn (consolidated Icelandic laws)."""
from __future__ import annotations
import logging, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "is", "Iceland", "althingi_lagasafn"
LICENSE = (
    "Icelandic legislation as published by Althingi (althingi.is lagasafn). "
    "Official texts; reuse per Althingi public-sector terms. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.althingi.is/lagasafn/"
BASE = "https://www.althingi.is"
INDEX = f"{BASE}/lagasafn/"
log = logging.getLogger("is")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def discover() -> list[dict]:
    r = http_get(INDEX, ua=UA, sleep=0.3, retries=4)
    if r.status_code != 200:
        log.error("index HTTP %s", r.status_code)
        return []
    hrefs = re.findall(r'href="(/lagas/[^"]+\.html)"', r.text)
    items, seen = [], set()
    for href in hrefs:
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        m = re.search(r"/lagas/([^/]+)/(\d{4})(\d{3})\.html", href)
        ident = f"{int(m.group(3))}/{m.group(2)}" if m else href
        edition = m.group(1) if m else ""
        year = m.group(2) if m else None
        items.append({"url": url, "ident": ident, "edition": edition, "year": year})
        append_catalog(CC, items[-1])
    log.info("discovered %s", len(items))
    return items


def fetch_one(item: dict, done: set[str]) -> str:
    ident = item["ident"]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    r = http_get(item["url"], ua=UA, sleep=0.25, retries=3)
    if r.status_code != 200 or not r.content:
        log_failure(CC, {"identifier": ident, "source_url": item["url"], "status": "failed", "reason": f"http_{r.status_code}"})
        return "fail"
    raw = r.text
    title = ident
    m = re.search(r"<title>([^<]+)</title>", raw, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).split("|")[0].strip()
    text = html_to_text(raw)
    # drop chrome
    for marker in ("Valmynd", "Lagasafn. Íslensk lög"):
        if marker in text:
            text = text.split(marker, 1)[-1]
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": item["url"], "status": "failed", "reason": "empty_text"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="is", ident=ident, title=title, text=text,
        source_url=item["url"], source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="is-althingi-lagasafn", eli=None, date=item.get("year"),
        official_identifier=ident, document_type="statute", law_status="current",
        extra_meta={"discovery": {"method": "lagasafn_index", "edition": item.get("edition")}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 50 == 0:
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
    write_summary(CC, country=COUNTRY, source="Althingi lagasafn (althingi.is)",
                  source_urls=[INDEX], license_text=LICENSE, discovered=len(items),
                  fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed current consolidations (lagasafn index)",
                  notes="Official Althingi HTML consolidations. Zip bulk dump 404 at scrape time; HTML index used. Not legal advice.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(items), ok, skip, fail)


if __name__ == "__main__":
    main()
