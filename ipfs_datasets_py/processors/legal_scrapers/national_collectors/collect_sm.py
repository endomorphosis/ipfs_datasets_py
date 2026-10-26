#!/usr/bin/env python3
"""San Marino: Bollettino Ufficiale (bollettinoufficiale.sm) RicercaBU documents."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "sm", "San Marino", "it"
SOURCE_TYPE = "bollettino_ufficiale_sm"
LICENSE = (
    "Bollettino Ufficiale della Repubblica di San Marino (bollettinoufficiale.sm). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.bollettinoufficiale.sm/)"
ART = re.compile(r"(?im)^\s*((?:Art\.|Articolo|Titolo|Capo)\s+[0-9IVX]+)\b")
log = logging.getLogger("sm")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://")
        if "bollettinoufficiale.sm" not in url.lower():
            return
        if "getdocbu" not in url.lower():
            return
        if url in seen:
            return
        m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
        if not m:
            return
        ident = re.sub(r"[^a-z0-9_-]+", "-", m.group(1).lower())[:120].strip("-")
        seen.add(url)
        # Use the archived original URL as-is; the 200-status captures live on
        # the legacy /on-line/RicercaBU path, not the canonical /online/ one.
        items.append((f"sm-{ident}", url))
    for prefix in ("bollettinoufficiale.sm/", "www.bollettinoufficiale.sm/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 2000), match_type="domain",
                          extra_filters=["urlkey:.*getdocbu.*"]):
            orig = h.get("original") or ""
            if orig:
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
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_sm.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:40], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="bollettinoufficiale.sm",
        source_urls=["https://www.bollettinoufficiale.sm/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Bollettino Ufficiale RicercaBU documents)",
        notes="Official San Marino gazette. Italian. Documents are HTML via getDocBU. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
