#!/usr/bin/env python3
"""Andorra: BOPA (Butlletí Oficial del Principat d'Andorra) official PDF issues."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ad", "Andorra", "ca"
SOURCE_TYPE = "bopa_ad"
LICENSE = (
    "Butlletí Oficial del Principat d'Andorra (bopa.ad). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.bopa.ad/)"
ART = re.compile(r"(?im)^\s*((?:Article|Secci[oó]|Cap[ií]tol)\s+[0-9]+)\b")
log = logging.getLogger("ad")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://")
        if "bopa.ad" not in url.lower():
            return
        if url in seen:
            return
        low = url.lower()
        if not (low.endswith(".pdf") or "/pdf/" in low or "document" in low):
            return
        ident = re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower())[:120].strip("-")
        if not ident:
            ident = "doc"
        seen.add(url)
        items.append((f"ad-{ident}", url))
    for prefix in ("www.bopa.ad/", "bopa.ad/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 800), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ad.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="bopa.ad",
        source_urls=["https://www.bopa.ad/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (BOPA official PDF issues via CDX/Wayback)",
        notes="Official Andorran gazette PDFs. Catalan. Electronic BOPA authoritative since 2015. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
