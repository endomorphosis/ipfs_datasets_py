#!/usr/bin/env python3
"""Iceland: Alþingi Lagasafn consolidated HTML laws (althingi.is)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "is", "Iceland", "is"
SOURCE_TYPE = "althingi_lagasafn"
LICENSE = (
    "Alþingi Lagasafn (althingi.is). Official consolidated Icelandic legislation. "
    "Authentic Alþingi text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.althingi.is/lagasafn/)"
ART = re.compile(r"(?im)^\s*((?:\d+\.\s*gr\.|Grein\s+\d+|Art(?:icle|\.)?\s*\d+))\b")
EDITION = "157c"
CATALOG = f"https://www.althingi.is/lagasafn/"
log = logging.getLogger("is")


def discover():
    items, seen = [], set()
    r = live_get(CATALOG, ua=UA)
    html = r.text or ""
    # Prefer current edition paths
    links = re.findall(r'href="(/lagas/%s/\d+\.html)"' % EDITION, html)
    if len(links) < 50:
        links = re.findall(r'href="(/lagas/\d+[a-z]?/\d+\.html)"', html)
    for path in links:
        url = urljoin("https://www.althingi.is", path)
        if url in seen:
            continue
        m = re.search(r"/(\d+)\.html$", path)
        ident = m.group(1) if m else Path(path).stem
        seen.add(url)
        items.append((ident, url))
    log.info("catalog %s edition=%s", len(items), EDITION)
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=200)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Drop nav chrome: keep from law title line if present
        title = None
        for line in text.splitlines():
            s = line.strip()
            if re.search(r"\d{4}\s*nr\.|\d+/\d{4}|Lög\s+um", s) and len(s) > 12:
                title = s[:240]
                break
            if len(s) > 20 and "Alþingi" not in s and title is None:
                title = s[:240]
        year = None
        if len(ident) >= 4 and ident[:4].isdigit():
            year = f"{ident[:4]}-01-01"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"Lög {ident}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_is.py",
            date=year, article_re=ART, extra_meta={"fetch_method": got.get("method"), "edition": EDITION},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Alþingi Lagasafn",
        source_urls=["https://www.althingi.is/lagasafn/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage=f"catalog-backed incomplete (edition {EDITION})",
        notes="Official consolidated HTML laws from Alþingi. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
