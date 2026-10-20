#!/usr/bin/env python3
"""North Korea (DPRK): no official online law portal; uses 38 North NK TechLab
law database (HTML, Korean + English translations) as the practical corpus.

NOTE: The DPRK publishes no searchable official legislation database online.
This collector harvests the 38 North law database (mid-2024 snapshot of the
official DPRK law compendium app) as a best-effort corpus.
"""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "kp", "North Korea", "ko"
SOURCE_TYPE = "38north_nk_techlab"
LICENSE = (
    "DPRK law texts via 38 North NK TechLab Law Database (mirror of official compendium). "
    "No official online source exists. Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.38north.org/)"
ART = re.compile(r"(?im)^\s*((?:Article|Section|Chapter|제)\s*[0-9]+)\b")
INDEX_URL = "https://www.38north.org/2025/07/nk-techlab-law-database/"
# The actual law database lives here (linked from the 38 North article but
# hosted on a different domain): direct PDF downloads, Korean + English.
NKTECHLAB_URL = "https://www.nktechlab.org/north-korean-law-database/"
log = logging.getLogger("kp")


def nktechlab_pdfs():
    """Harvest direct PDF links from the NK TechLab law database page.
    Returns list of (ident, url, title, lang, date_iso)."""
    items = []
    try:
        r = live_get(NKTECHLAB_URL, ua=UA, timeout=(20, 60))
        if r.status_code != 200:
            log.warning("nktechlab index fetch failed: %s", r.status_code)
            return items
        html = r.text
        seen = set()
        for m in re.finditer(r'href="([^"]+\.pdf)"', html, re.I):
            href = m.group(1)
            if href.startswith("/"):
                href = "https://www.nktechlab.org" + href
            if "nktechlab.org" not in href.lower():
                continue
            if href in seen:
                continue
            seen.add(href)
            fname = href.rsplit("/", 1)[-1]
            # e.g. 231214-Accident-Prevention-Law-사고방지법-_ENG.pdf
            base = fname[:-4]
            lang = "en" if base.upper().endswith("_ENG") else ("ko" if base.upper().endswith("_KOR") else "ko")
            base = re.sub(r"_ENG$|_KOR$", "", base, flags=re.I)
            date_iso = ""
            dm = re.match(r"(\d{2})(\d{2})(\d{2})-(.*)", base)
            if dm:
                yy, mm, dd, rest = dm.groups()
                date_iso = f"20{yy}-{mm}-{dd}"
            else:
                rest = base
            title_core = re.sub(r"-[가-힣_]+$", "", rest)  # strip trailing Korean tag
            title = title_core.replace("-", " ").strip() or base
            ident = "kp-nktechlab-" + re.sub(r"[^a-z0-9]+", "-", title.lower())[:100].strip("-") + "-" + lang
            items.append((ident, href, title, lang, date_iso))
    except Exception as exc:
        log.warning("nktechlab crawl failed: %s", exc)
    log.info("nktechlab catalog %s", len(items))
    return items


def discover():
    items, seen = [], set()
    def add(url, title_hint=""):
        url = url.split("#")[0]
        if url in seen:
            return
        if "38north.org" not in url.lower():
            return
        low = url.lower()
        if not ("/database/" in low or "/nk-techlab" in low or "law" in low):
            return
        if any(x in low for x in ("2025/07/nk-techlab-law-database", "/wp-content/uploads")):
            return
        ident = re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower())[:120].strip("-")
        if not ident:
            ident = "law"
        seen.add(url)
        items.append((f"kp-{ident}", url, title_hint))
    # 1) Crawl the index article for law links
    try:
        r = live_get(INDEX_URL, ua=UA, timeout=(20, 60))
        if r.status_code == 200:
            html = r.text
            for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]{8,160})<', html):
                href, label = m.group(1), m.group(2).strip()
                if href.startswith("/"):
                    href = "https://www.38north.org" + href
                if "38north.org" in href and re.search(r"law|database|techlab", href, re.I):
                    add(href, label)
    except Exception as exc:
        log.warning("index crawl failed: %s", exc)
    # 2) Wayback CDX as backup
    for h in cdx_urls("www.38north.org/database", limit=env_int("CDX_LIMIT", 300), match_type="prefix"):
        orig = h.get("original") or ""
        if orig:
            add(orig)
    log.info("catalog %s", len(items))
    return items, nktechlab_pdfs()


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    articles, pdfs = discover()
    work = [(ident, url, hint, LANG, "") for ident, url, hint in articles] + \
           [(ident, url, title, lang, date_iso) for ident, url, title, lang, date_iso in pdfs]
    for ident, url, hint, lang, date_iso in work:
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
        title = hint or None
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if save_instrument(
            cc=CC, country=COUNTRY, language=lang, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_kp.py",
            article_re=ART, date=date_iso or None,
            extra_meta={"fetch_method": got.get("method"), "mirror": True},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="38 North NK TechLab Law Database",
        source_urls=[INDEX_URL, NKTECHLAB_URL],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="best-effort mirror corpus (33 DPRK laws, Korean + English); no official online source exists",
        notes="DPRK has no official online legislation database. Corpus from 38 North mirror of official compendium. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
