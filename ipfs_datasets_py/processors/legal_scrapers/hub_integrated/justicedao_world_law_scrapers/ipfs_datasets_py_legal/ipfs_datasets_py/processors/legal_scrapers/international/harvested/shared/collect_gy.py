#!/usr/bin/env python3
"""Guyana: Parliament Acts PDFs (parliament.gov.gy/documents/acts) + Constitution."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "gy", "Guyana", "en"
SOURCE_TYPE = "parliament_gy"
LICENSE = (
    "Parliament of Guyana / Official Gazette of Guyana (parliament.gov.gy). "
    "Authentic official gazette/parliament text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.parliament.gov.gy/)"
)
ART = re.compile(r"(?im)^\s*((?:Section|Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("gy")
SKIP = ("minutes", "sitting", "hansard", "order-paper", "order_paper", "brochure", "newsletter")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if "parliament.gov.gy" not in low:
            return
        if ".pdf" not in low:
            return
        if any(s in low for s in SKIP):
            return
        # acts PDFs or constitution
        if "/documents/acts/" not in low and "constitution" not in low:
            return
        if url in seen:
            return
        ident = Path(url.split("?")[0]).stem[:160]
        seen.add(url)
        items.append((ident, url))
    # Constitution first
    add("https://parliament.gov.gy/Constitution of the Cooperatiive Republic of Guyana.pdf")
    for prefix in (
        "www.parliament.gov.gy/documents/acts/",
        "parliament.gov.gy/documents/acts/",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 2000),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 200)
    max_seconds = env_int("MAX_SECONDS", 3600)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=120)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_gy.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Parliament of Guyana Acts",
        source_urls=["https://www.parliament.gov.gy/publications/acts-of-parliament/", "https://officialgazette.gov.gy/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (parliament.gov.gy/documents/acts PDFs + Constitution)",
        notes="Official Parliament Acts PDFs; Official Gazette authentic text prevails. Not vLex. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
