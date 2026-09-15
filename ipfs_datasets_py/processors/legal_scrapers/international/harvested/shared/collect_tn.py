#!/usr/bin/env python3
"""Tunisia: Journal Officiel (iort.gov.tn / legislation.tn). TLS often fails; Wayback of official URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "tn", "Tunisia", "ar"
SOURCE_TYPE = "iort_jo"
LICENSE = (
    "Journal Officiel de la République Tunisienne (iort.gov.tn / legislation.tn). "
    "Authentic JO text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.iort.gov.tn/)"
ART = re.compile(r"(?im)^\s*((?:الفصل|Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("tn")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0]
        if url in seen:
            return
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-")[:160]
        seen.add(url)
        items.append((ident, url))
    for prefix in (
        "www.iort.gov.tn/",
        "iort.gov.tn/",
        "www.legislation.tn/sites/default/files/",
        "legislation.tn/fr/content/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix"):
            orig = h.get("original") or ""
            if orig and any(k in orig.lower() for k in (".pdf", "jort", "loi", "constitution", "code")):
                add(orig)
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=120)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 12:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_tn.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:70], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="IORT / legislation.tn Journal Officiel",
        source_urls=["http://www.iort.gov.tn/", "http://www.legislation.tn/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official JO URLs)",
        notes="Live TLS often fails. Official IORT/legislation.tn only. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
