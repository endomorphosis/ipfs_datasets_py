#!/usr/bin/env python3
"""Serbia: Pravno-informacioni sistem ELI (Sluzbeni glasnik). SPA live; Wayback of official ELI URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "rs", "Serbia", "sr"
SOURCE_TYPE = "pis_slglasnik"
LICENSE = (
    "Official Gazette of the Republic of Serbia / Legal Information System "
    "(pravno-informacioni-sistem.rs, JP Sluzbeni glasnik). Authentic gazette text prevails. "
    "Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://pravno-informacioni-sistem.rs/)"
ART2 = re.compile(r"(?m)^\s*((?:Члан|Član)\s+[0-9]+[а-еa-z]?)\b")
log = logging.getLogger("rs")
SEEDS = [
    "https://www.pravno-informacioni-sistem.rs/SlGlasnikPortal/eli/rep/sgrs/skupstina/zakon/2013/45/4/reg",
    "https://www.pravno-informacioni-sistem.rs/SlGlasnikPortal/eli/rep/sgrs/skupstina/ustav/2006/98/1/reg",
]


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("?")[0]
        m = re.search(r"/eli/(.+)$", url)
        ident = m.group(1).strip("/") if m else url
        ident = ident.replace("/", "-")
        if ident in seen:
            return
        seen.add(ident)
        if not url.endswith("/reg") and "/eli/" in url:
            url = re.sub(r"/(sg|html|pdf)$", "", url.rstrip("/")) + "/reg"
        items.append((ident, url))
    for u in SEEDS:
        add(u)
    for h in cdx_urls(
        "pravno-informacioni-sistem.rs/SlGlasnikPortal/eli/",
        limit=env_int("CDX_LIMIT", 400),
        match_type="prefix",
    ):
        orig = h.get("original") or ""
        if "/eli/" not in orig:
            continue
        if any(x in orig.lower() for x in (".css", ".js", ".png", ".jpg", "/overview")):
            continue
        add(orig.replace("http://", "https://"))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
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
        got = fetch_official(url, ua=UA, min_text=180)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_rs.py",
            article_re=ART2, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:60], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="PIS / Sluzbeni glasnik ELI",
        source_urls=["https://pravno-informacioni-sistem.rs/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official ELI URLs; live SPA shell)",
        notes="Official PIS ELI only. No commercial consolidators. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
