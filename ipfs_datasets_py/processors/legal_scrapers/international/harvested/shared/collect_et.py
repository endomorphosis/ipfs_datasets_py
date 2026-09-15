#!/usr/bin/env python3
"""Ethiopia: Federal Negarit Gazette via Ministry of Justice / HoPR official sites."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "et", "Ethiopia", "am"
SOURCE_TYPE = "negarit_gazette"
LICENSE = (
    "Federal Negarit Gazette of the Federal Democratic Republic of Ethiopia as published "
    "via justice.gov.et / hopr.gov.et. Authentic gazette text prevails. Not legal advice. "
    "Not LawEthiopia commercial archive."
)
UA = "legal-corpora-collector/1.0 (research; source=https://justice.gov.et/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("et")
HOMES = [
    "https://justice.gov.et/en/",
    "https://www.hopr.gov.et/",
    "https://www.fsc.gov.et/Digital-Law-Library/Federal-Laws",
]


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0]
        if not url.startswith("http"):
            return
        if url in seen:
            return
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-").replace("?", "-")[:160]
        seen.add(url)
        items.append((ident, url))
    for home in HOMES:
        try:
            r = http_get(home, ua=UA, sleep=0.4)
            if r.status_code != 200:
                continue
            for href in re.findall(r'href="([^"]+)"', r.text or ""):
                full = urljoin(home, href)
                if any(k in full.lower() for k in ("pdf", "negarit", "proclamation", "jet_download", "gazette")):
                    add(full)
        except Exception as exc:
            log.info("home %s %s", home, exc)
    for prefix in (
        "justice.gov.et/",
        "www.hopr.gov.et/",
        "www.fsc.gov.et/Digital-Law-Library/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix"):
            orig = h.get("original") or ""
            if orig and any(k in orig.lower() for k in ("pdf", "negarit", "proclamation", "jet_download")):
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
        got = fetch_official(url, ua=UA, min_text=120)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_et.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:70], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Federal Negarit Gazette (justice.gov.et / hopr.gov.et)",
        source_urls=["https://justice.gov.et/", "https://www.hopr.gov.et/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Official MoJ/HoPR/FSC only. Not LawEthiopia. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
