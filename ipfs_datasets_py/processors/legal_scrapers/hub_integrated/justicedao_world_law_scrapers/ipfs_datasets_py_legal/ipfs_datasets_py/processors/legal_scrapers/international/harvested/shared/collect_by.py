#!/usr/bin/env python3
"""Belarus: pravo.by official normative documents / codes."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "by", "Belarus", "ru"
SOURCE_TYPE = "pravo_by"
LICENSE = (
    "Национальный правовой Интернет-портал Республики Беларусь (pravo.by). "
    "Official texts prevail. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://pravo.by/)"
ART = re.compile(r"(?im)^\s*((?:Статья|Статья\s+)\s*\d+[^\n]{0,30})\b")
# Known code document IDs on pravo.by (guid+p0 patterns vary; use list pages + CDX)
SEED = [
    "https://pravo.by/document/?guid=3871&p0=Hk9800218",  # often Constitution-related listings
]
log = logging.getLogger("by")


def discover():
    items, seen = [], set()
    list_urls = [
        "https://pravo.by/pravovaya-informatsiya/normativnye-dokumenty/kodeksy-respubliki-belarus/",
        "https://pravo.by/pravovaya-informatsiya/normativnye-dokumenty/",
        "https://pravo.by/",
    ]
    for lu in list_urls:
        try:
            r = live_get(lu, ua=UA, timeout=(20, 50))
        except Exception as exc:
            log.info("list fail %s: %s", lu, exc)
            continue
        for href in re.findall(r'href="([^"]*document/\?[^"]+)"', r.text or ""):
            url = urljoin("https://pravo.by", href.replace("&amp;", "&"))
            if url in seen:
                continue
            seen.add(url)
            ident = re.sub(r"\W+", "-", url.split("p0=")[-1] if "p0=" in url else url)[:120]
            items.append((ident, url))
        for href in re.findall(r'href="([^"]+\.pdf)"', r.text or "", re.I):
            url = urljoin("https://pravo.by", href)
            if url in seen:
                continue
            seen.add(url)
            items.append((Path(url).stem[:120], url))
    for prefix in ("pravo.by/document/", "pravo.by/upload/", "www.pravo.by/upload/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 100), match_type="prefix"):
            orig = (h.get("original") or "").replace("http://", "https://")
            if not orig or orig in seen:
                continue
            if ".pdf" in orig.lower() or "document/?" in orig:
                seen.add(orig)
                ident = Path(orig.split("?")[0]).stem[:100] or re.sub(r"\W+", "-", orig)[-80:]
                items.append((ident, orig))
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
        got = fetch_official(url, ua=UA, min_text=300)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 20:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_by.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident[:60], len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="pravo.by National Legal Internet Portal",
        source_urls=["https://pravo.by/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="codes/documents incomplete",
        notes="Official pravo.by documents. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
