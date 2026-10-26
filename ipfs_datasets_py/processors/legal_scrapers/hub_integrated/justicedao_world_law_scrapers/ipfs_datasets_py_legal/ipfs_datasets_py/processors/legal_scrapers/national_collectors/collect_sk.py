#!/usr/bin/env python3
"""Slovakia: Slov-lex static mirror (JS-free Collection of Laws)."""
from __future__ import annotations
import logging, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "sk", "Slovakia", "slovlex"
LICENSE = "Official Collection of Laws (Zbierka zákonov) via slov-lex.sk / static.slov-lex.sk; public administration texts."
UA = DEFAULT_UA + " source=https://static.slov-lex.sk/"
STATIC = "https://static.slov-lex.sk/static/SK/ZZ"
CANON = "https://www.slov-lex.sk/pravne-predpisy/SK/ZZ"
log = logging.getLogger("sk")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def year_numbers(year: int) -> list[int]:
    r = http_get(f"{STATIC}/{year}/", ua=UA, sleep=0.3, retries=3, headers={"Accept": "text/html"})
    nums = []
    if r.status_code == 200:
        nums = sorted({int(x) for x in re.findall(r'href=["\'](\d+)/["\']', r.text)})
    return nums


def latest_html(year: int, n: int) -> tuple[str, str]:
    """Return (url, html) of the current in-force static version."""
    index = f"{STATIC}/{year}/{n}/"
    r = http_get(index, ua=UA, sleep=0.25, retries=2, headers={"Accept": "text/html"})
    dates = []
    if r.status_code == 200:
        dates = re.findall(r'href=["\'](\d{8}\.html)["\']', r.text)
    if dates:
        fname = sorted(dates)[-1]
        url = index + fname
    else:
        url = index + "vyhlasene_znenie.html"
    rr = http_get(url, ua=UA, sleep=0.3, retries=3, headers={"Accept": "text/html"})
    if rr.status_code == 200 and rr.content and len(rr.content) > 500:
        return url, rr.text
    return url, ""


def fetch_one(year: int, n: int, done: set[str]) -> str:
    ident = f"{year}-{n}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url, html = latest_html(year, n)
    text = html_to_text(html) if html else ""
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = ident
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    # better heading
    m2 = re.search(r"<h1[^>]*>([\s\S]{5,300}?)</h1>", html, re.I)
    if m2:
        t2 = re.sub(r"<[^>]+>", " ", m2.group(1))
        t2 = re.sub(r"\s+", " ", t2).strip()
        if len(t2) > 8:
            title = t2
    eli = f"{CANON}/{year}/{n}/"
    rec = base_record(
        cc=CC, country=COUNTRY, language="sk", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="sk-slovlex-static",
        eli=eli, date=f"{year}-01-01", official_identifier=f"{n}/{year} Z. z.",
        document_type="statute", law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "static_year_listing"}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    done = existing_ids(CC)
    catalog = []
    for year in range(1993, 2027):
        nums = year_numbers(year)
        log.info("year %s n=%s", year, len(nums))
        for n in nums:
            catalog.append((year, n))
            append_catalog(CC, {"year": year, "n": n})
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch_one, y, n, done) for y, n in catalog]
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
                log.info("progress %s/%s ok=%s fail=%s", n, len(catalog), ok, fail)
                write_summary(CC, country=COUNTRY, source="SLOV-LEX static ZZ",
                              source_urls=["https://www.slov-lex.sk/", "https://static.slov-lex.sk/"],
                              license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="static year dirs, latest dated HTML", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="SLOV-LEX (Ministry of Justice) Collection of Laws static mirror",
                  source_urls=["https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/", "https://static.slov-lex.sk/static/SK/ZZ/"],
                  license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if catalog and fail == 0 else "catalog-backed incomplete",
                  notes="National ZZ 1993–present via official static.slov-lex.sk (JS-free). Current in-force HTML = latest YYYYMMDD.html per act.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(catalog), ok, fail)


if __name__ == "__main__":
    main()
