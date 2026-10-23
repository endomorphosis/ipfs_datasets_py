#!/usr/bin/env python3
"""Slovenia: Uradni list RS official issue TOCs + act HTML (pisrs API is token-gated)."""
from __future__ import annotations
import json, logging, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "si", "Slovenia", "uradni_list"
LICENSE = (
    "Uradni list Republike Slovenije official gazette HTML. "
    "PISRS developer API requires a token (pisrs.si/swagger) and is not used. "
    "Reuse per UL / public-sector terms."
)
UA = DEFAULT_UA + " source=https://www.uradni-list.si/"
BASE = "https://www.uradni-list.si"
log = logging.getLogger("si")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def discover() -> list[dict]:
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    items, seen = [], set()
    if catp.exists() and catp.stat().st_size > 500:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            u = row.get("url")
            if u and u not in seen:
                seen.add(u); items.append(row)
        if items:
            log.info("resume catalog %s", len(items))
            return items
    for year in range(1991, 2027):
        misses = 0
        for n in range(1, 180):
            kazalo = f"{BASE}/glasilo-uradni-list-rs/celotno-kazalo/{year}{n}"
            r = http_get(kazalo, ua=UA, sleep=0.35, retries=2, headers={"Accept": "text/html"})
            if r.status_code != 200 or not r.content or len(r.content) < 800:
                misses += 1
                if misses >= 8:
                    break
                continue
            misses = 0
            hrefs = re.findall(r'href="([^"]*/glasilo-uradni-list-rs/vsebina/[^"]+)"', r.text)
            got = 0
            for href in hrefs:
                href = urljoin(kazalo, href)
                if href in seen:
                    continue
                seen.add(href)
                rec = {"url": href, "year": year, "issue": n, "kazalo": kazalo}
                items.append(rec); append_catalog(CC, rec); got += 1
            log.info("year %s issue %s acts=%s catalog=%s", year, n, got, len(items))
    return items


def fetch_one(row: dict, done: set[str]) -> str:
    url = row["url"]
    ident = re.sub(r"^https?://www\.uradni-list\.si/", "", url)
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    r = http_get(url, ua=UA, sleep=0.4, retries=3, headers={"Accept": "text/html"})
    if r.status_code != 200 or not r.content:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": f"http_{r.status_code}"})
        return "fail"
    text = html_to_text(r.text)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_or_chrome"})
        return "fail"
    m = re.search(r"<title>([^<]+)</title>", r.text, re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ident
    m2 = re.search(r"<h1[^>]*>([\s\S]{5,400}?)</h1>", r.text, re.I)
    if m2:
        t2 = re.sub(r"<[^>]+>", " ", m2.group(1))
        t2 = re.sub(r"\s+", " ", t2).strip()
        if len(t2) > 8:
            title = t2
    rec = base_record(
        cc=CC, country=COUNTRY, language="sl", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="si-uradni-list-html",
        eli=url, date=None, official_identifier=ident, document_type="gazette_act",
        law_status="unknown", is_current=None,
        extra_meta={"discovery": {"method": "ul_kazalo", "year": row.get("year"), "issue": row.get("issue")}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
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
            if n % 80 == 0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(items), ok, fail)
                write_summary(CC, country=COUNTRY, source="Uradni list RS",
                              source_urls=["https://www.uradni-list.si/", "https://pisrs.si/"],
                              license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="issue TOCs", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Uradni list Republike Slovenije official gazette HTML",
                  source_urls=["https://www.uradni-list.si/", "https://pisrs.si/swagger"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if items and fail == 0 else "catalog-backed incomplete",
                  notes="Issue TOCs /glasilo-uradni-list-rs/celotno-kazalo/{year}{n} then /vsebina/ act HTML. PISRS REST API is token-gated (documented blocker for consolidations).",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(items), ok, fail)


if __name__ == "__main__":
    main()
