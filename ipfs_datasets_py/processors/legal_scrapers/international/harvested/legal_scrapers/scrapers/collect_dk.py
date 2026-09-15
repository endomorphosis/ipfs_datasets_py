#!/usr/bin/env python3
"""Denmark: Retsinformation ELI sitemap + XML/HTML documents (Lovtidende A)."""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "dk"
COUNTRY = "Denmark"
SOURCE_TYPE = "retsinformation"
LICENSE = (
    "Retsinformation open data as stated at https://www.retsinformation.dk/api "
    "(Civilstyrelsen). Official statutes are public; reuse subject to the terms "
    "published on retsinformation.dk/api and eli/about."
)
UA = DEFAULT_UA + " source=https://www.retsinformation.dk/eli"
log = logging.getLogger("dk")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def sitemap_locs() -> list[str]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    if cat.exists() and cat.stat().st_size > 1000:
        locs = []
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    locs.append(json.loads(line)["loc"])
                except Exception:
                    continue
        if locs:
            return locs
    import json as _json
    r = http_get("https://www.retsinformation.dk/eli/sitemap.xml", ua=UA, sleep=0.2)
    pages = re.findall(r"<loc>([^<]+)</loc>", r.text)
    locs = []
    seen = set()
    targets = pages or ["https://www.retsinformation.dk/eli/sitemap.xml?page=1"]
    for i, page in enumerate(targets, 1):
        pr = http_get(page, ua=UA, sleep=0.25)
        for loc in re.findall(r"<loc>([^<]+)</loc>", pr.text):
            # national legislation in Lovtidende A (lta) and accession (accn) consolidations
            if "/eli/lta/" not in loc and "/eli/accn/" not in loc:
                continue
            if loc in seen:
                continue
            seen.add(loc)
            locs.append(loc)
            append_catalog(CC, {"loc": loc})
        log.info("sitemap page %s/%s locs=%s", i, len(targets), len(locs))
    return locs


def fetch_one(loc: str, done: set[str]) -> str:
    loc = loc.replace("http://", "https://")
    ident = loc.split("/eli/", 1)[-1].strip("/")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    xml_url = loc.rstrip("/") + "/xml"
    html_url = loc.rstrip("/") + "/rawhtml"
    json_url = loc.rstrip("/") + "/json"
    title = ident
    date = None
    eli = loc
    try:
        jr = http_get(json_url, ua=UA, sleep=0.3, headers={"Accept": "application/json"})
        if jr.status_code == 200 and jr.content.startswith(b"{") or jr.content.startswith(b"["):
            meta = jr.json()
            if isinstance(meta, dict):
                title = meta.get("title") or meta.get("shortName") or title
                date = iso_date(meta.get("date") or meta.get("publicationDate") or meta.get("issued"))
                eli = meta.get("id") or loc
    except Exception:
        pass
    text = ""
    r = http_get(xml_url, ua=UA, sleep=0.3)
    if r.status_code == 200 and r.content and b"<" in r.content[:80]:
        text = xml_to_text(r.text)
        if not title or title == ident:
            m = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.I)
            if m:
                title = html_unescape(m.group(1))
    if not text:
        r2 = http_get(html_url, ua=UA, sleep=0.3)
        if r2.status_code == 200 and r2.content:
            text = html_to_text(r2.text)
    if not text:
        r3 = http_get(loc, ua=UA, sleep=0.3)
        if r3.status_code == 200:
            text = html_to_text(r3.text)
            m = re.search(r"<title>([^<]+)</title>", r3.text, re.I)
            if m and (not title or title == ident):
                title = html_unescape(m.group(1))
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": loc, "status": "failed", "reason": "empty_text"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="da", ident=ident, title=title, text=text,
        source_url=loc, source_type=SOURCE_TYPE, license_text=LICENSE, collector="dk-retsinformation-eli",
        eli=eli if str(eli).startswith("http") else loc, date=date,
        official_identifier=ident, document_type="statute",
        law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "eli_sitemap"}},
    )
    write_instrument(CC, rec)
    return "ok"


def html_unescape(s: str) -> str:
    import html as _html
    return _html.unescape(s).strip()


def main():
    setup()
    t0 = utcnow()
    locs = sitemap_locs()
    done = existing_ids(CC)
    ok = skip = fail = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_one, loc, done) for loc in locs]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 200 == 0:
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(locs), ok, skip, fail)
                write_summary(CC, country=COUNTRY, source="Retsinformation ELI",
                              source_urls=["https://www.retsinformation.dk/", "https://www.retsinformation.dk/api"],
                              license_text=LICENSE, discovered=len(locs), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="ELI sitemap lta+accn", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Retsinformation (Civilstyrelsen) ELI channels",
                  source_urls=["https://www.retsinformation.dk/eli/sitemap.xml", "https://www.retsinformation.dk/api"],
                  license_text=LICENSE, discovered=len(locs), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if fail == 0 else "catalog-backed incomplete",
                  notes="Lovtidende A (lta) and accession-number (accn) ELI documents from official sitemap. Folketing bills (ft) excluded.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    import json
    main()
