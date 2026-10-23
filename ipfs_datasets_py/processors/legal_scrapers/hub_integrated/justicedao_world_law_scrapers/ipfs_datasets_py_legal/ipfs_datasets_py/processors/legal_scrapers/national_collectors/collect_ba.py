#!/usr/bin/env python3
"""Bosnia: Sluzbeni list BiH official gazette PDFs via Wayback CDX (live Docs login-walled)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ba", "Bosnia and Herzegovina", "bs"
SOURCE_TYPE = "sluzbeni_list_bih"
LICENSE = (
    "Official Gazette of Bosnia and Herzegovina (Sluzbeni glasnik BiH / sluzbenilist.ba). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.sluzbenilist.ba/)"
ART = re.compile(r"(?m)^\s*((?:Član|Clan|Члан)\s+[0-9]+[a-zа-е]?)\b")
log = logging.getLogger("ba")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("?")[0]
        if not url or url in seen:
            return
        if ".pdf" not in url.lower():
            return
        if any(x in url.lower() for x in ("book", "katalog", "privredno", "ispit")):
            return
        ident = Path(url).stem[:160]
        seen.add(url)
        items.append((ident, url))
    for prefix in (
        "sluzbenilist.ba/",
        "sllist.ba/",
        "www.sluzbenilist.ba/",
        "www.sllist.ba/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 300), match_type="prefix",
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
    max_seconds = env_int("MAX_SECONDS", 1500)
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
        if got.get("status") != "success" or text.lstrip().startswith("%PDF"):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "bad_pdf"})
            continue
        if not any(k in text for k in ("Član", "ČLAN", "Zakon", "ZAKON", "Službeni", "glasnik", "Члан")):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ba.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s bytes=%s", ident[:60], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Sluzbeni list BiH PDFs",
        source_urls=["https://www.sluzbenilist.ba/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback PDFs; live Docs login-walled)",
        notes="Official gazette PDFs only. Bookshop pages excluded. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
