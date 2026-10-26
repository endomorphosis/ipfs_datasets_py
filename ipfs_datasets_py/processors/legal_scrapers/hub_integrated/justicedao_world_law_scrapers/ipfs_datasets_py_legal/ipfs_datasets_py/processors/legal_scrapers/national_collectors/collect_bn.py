#!/usr/bin/env python3
"""Brunei: AGC Laws of Brunei ACT_PDF (agc.gov.bn/AGC Images/LAWS)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "bn", "Brunei", "en"
SOURCE_TYPE = "agc_brunei_laws"
LICENSE = (
    "Laws of Brunei / Attorney General's Chambers (agc.gov.bn). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.agc.gov.bn/)"
ART = re.compile(r"(?im)^\s*((?:Section|Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("bn")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = unquote(url).lower()
        if "agc.gov.bn" not in low:
            return
        if "laws" not in low or ".pdf" not in low:
            return
        # prefer Clean version; skip Markup duplicates when both exist
        if "markup" in low:
            return
        if any(x in low for x in ("etika", "admin/", "brochure", "form")):
            return
        if url in seen:
            return
        ident = Path(unquote(url.split("?")[0])).stem[:160]
        ident = re.sub(r"[^\w.\-]+", "-", ident).strip("-")[:160]
        seen.add(url)
        items.append((ident or "act", url))
    for prefix in (
        "www.agc.gov.bn/AGC%20Images/LAWS/",
        "agc.gov.bn/AGC%20Images/LAWS/",
        "www.agc.gov.bn/agc%20images/laws/",
        "www.agc.gov.bn/AGC Images/LAWS/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 250), match_type="prefix",
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bn.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="AGC Brunei Laws",
        source_urls=["https://www.agc.gov.bn/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official AGC LAWS ACT_PDF)",
        notes="Official Laws of Brunei Cap PDFs (Clean versions). Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
