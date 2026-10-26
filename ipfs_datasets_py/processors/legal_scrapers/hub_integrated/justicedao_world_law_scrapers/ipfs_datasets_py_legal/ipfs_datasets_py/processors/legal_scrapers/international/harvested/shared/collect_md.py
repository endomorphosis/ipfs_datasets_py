#!/usr/bin/env python3
"""Moldova: State Register of Legal Acts (legis.md). Live Cloudflare; Wayback of official URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "md", "Moldova", "ro"
SOURCE_TYPE = "legis_md"
LICENSE = (
    "Official State Register of Legal Acts of the Republic of Moldova (legis.md). "
    "Authentic register text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.legis.md/)"
ART = re.compile(r"(?im)^\s*((?:Articolul|Art\.?)\s+[0-9]+(?:\^[0-9]+)?)\b")
log = logging.getLogger("md")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0]
        if url in seen:
            return
        if any(x in url.lower() for x in (".css", ".js", "/login", "captcha")):
            return
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-")[:160]
        seen.add(url)
        items.append((ident, url.replace("http://", "https://")))
    for prefix in ("www.legis.md/cautare/getResults", "legis.md/cautare/", "www.legis.md/UserFiles/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 250), match_type="prefix"):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 50)
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
        got = fetch_official(url, ua=UA, min_text=150)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_md.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:70], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="legis.md State Register",
        source_urls=["https://www.legis.md/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official legis.md URLs; live Cloudflare)",
        notes="Official legis.md only. No WAF bypass. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
