#!/usr/bin/env python3
"""Nepal: lawcommission.gov.np / Nepal Law Commission official acts (HTML/PDF)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "np", "Nepal", "ne"
SOURCE_TYPE = "nepal_law_commission"
LICENSE = (
    "Nepal Law Commission (lawcommission.gov.np). Official texts prevail. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.lawcommission.gov.np/)"
ART = re.compile(r"(?im)^\s*((?:\d+\.\s*|Section\s+\d+|दफा\s*\d+))\b")
log = logging.getLogger("np")


def discover():
    items, seen = [], set()
    seeds = [
        "https://www.lawcommission.gov.np/en/",
        "https://www.lawcommission.gov.np/np/",
        "https://www.lawcommission.gov.np/en/archives/category/documents/prevailing-law",
        "https://www.lawcommission.gov.np/en/category/prevailing-laws/",
    ]
    for su in seeds:
        try:
            r = live_get(su, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("seed fail %s: %s", su, exc)
            continue
        for href in re.findall(r'href="([^"]+)"', r.text or ""):
            full = urljoin(su, href)
            if "lawcommission.gov.np" not in full:
                continue
            if any(x in full.lower() for x in [".pdf", "/archives/", "/documents/", "prevailing", "act", "statute"]):
                if full in seen:
                    continue
                seen.add(full)
                ident = Path(full.rstrip("/").split("?")[0]).stem[:140] or re.sub(r"\W+", "-", full)[-80:]
                items.append((ident, full))
    for prefix in (
        "www.lawcommission.gov.np/wp-content/uploads/",
        "lawcommission.gov.np/wp-content/uploads/",
        "www.lawcommission.gov.np/en/wp-content/uploads/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 150), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = (h.get("original") or "").replace("http://", "https://")
            if not orig or orig in seen:
                continue
            seen.add(orig)
            items.append((Path(orig).stem[:140], orig))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 2000)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=200)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Skip pure index pages
        if text.count("\n") < 5 and len(text) < 500:
            fail += 1
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_np.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident[:60], len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Nepal Law Commission",
        source_urls=["https://www.lawcommission.gov.np/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="uploads/archives incomplete",
        notes="Official Nepal Law Commission documents. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
