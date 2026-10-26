#!/usr/bin/env python3
"""Liechtenstein: LILEX (gesetze.li) consolidated legislation HTML + official PDFs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "li", "Liechtenstein", "de"
SOURCE_TYPE = "lilex_gesetze_li"
LICENSE = (
    "Liechtensteinische Gesetzessammlung LILEX (gesetze.li, Government Legal Services). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gesetze.li/)"
ART = re.compile(r"(?im)^\s*((?:Art\.|Artikel|§)\s*[0-9]+)\b")
log = logging.getLogger("li")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://")
        if "gesetze.li" not in url.lower():
            return
        if url in seen:
            return
        low = url.lower()
        # consolidated texts (konso) and LGBl issues
        if not ("/konso/" in low or "lgbl" in low or low.endswith(".pdf")):
            return
        if any(x in low for x in ("suche", "search", "hilfe", "help", "/en/", "impressum")):
            return
        ident = re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower())[:120].strip("-")
        if not ident:
            ident = "doc"
        seen.add(url)
        items.append((f"li-{ident}", url))
    for prefix in ("www.gesetze.li/konso/", "www.gesetze.li/lgbl/", "gesetze.li/konso/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 1200), match_type="prefix"):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    log.info("catalog %s", len(items))
    return items


def resolve_konso_pdf(url):
    """Konso landing pages are just version selectors; resolve to the PDF of
    the current consolidated text (e.g. /konso/pdf/1003001000?version=85)."""
    if "/konso/pdf/" in url.lower():
        return url
    m = re.search(r"/konso/([\d.]+)/?\s*$", url, re.I)
    if not m:
        return url
    try:
        r = live_get(url, ua=UA, timeout=(20, 60), verify=False)
        if r.status_code == 200:
            pm = re.search(r'href="(/konso/pdf/\d+\?version=\d+)"', r.text)
            if pm:
                return "https://www.gesetze.li" + pm.group(1).replace("&amp;", "&")
    except Exception as exc:
        log.warning("konso pdf resolve failed for %s: %s", url, exc)
    return url


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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_li.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="gesetze.li",
        source_urls=["https://www.gesetze.li/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (LILEX consolidated HTML + LGBl PDFs)",
        notes="Official Liechtenstein legislation. German. Signed electronic LGBl authoritative since 2013. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
