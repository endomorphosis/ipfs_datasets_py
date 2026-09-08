#!/usr/bin/env python3
"""Mongolia: legalinfo.mn official legal acts (HTML detail pages + CDX PDFs)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "mn", "Mongolia", "mn"
SOURCE_TYPE = "legalinfo_mn"
LICENSE = (
    "Legalinfo.mn — Legal Information Integrated System of Mongolia (Ministry of Justice). "
    "Official texts prevail. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://legalinfo.mn/)"
ART = re.compile(r"(?im)^\s*((?:\d+\s*дугаар\s*зүйл|Зүйл\s*\d+|Article\s+\d+))\b")
log = logging.getLogger("mn")


def discover():
    items, seen = [], set()
    # CDX PDFs on legalinfo / government domains
    for prefix in (
        "legalinfo.mn/law/",
        "legalinfo.mn/attach/",
        "legalinfo.mn/files/",
        "www.legalinfo.mn/law/",
        "legalinfo.mn/pdf/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 120), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if not orig or ".pdf" not in orig.lower():
                continue
            url = orig.replace("http://", "https://")
            if url in seen:
                continue
            ident = Path(url.split("?")[0]).stem[:160]
            seen.add(url)
            items.append((ident, url, "pdf"))
    # HTML category pages may embed law links; also try detail?lawId=N sweep of recent IDs via latestlaw + law cats
    for cat in (26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 180, 390):
        try:
            r = live_get(f"https://legalinfo.mn/mn/law/{cat}", ua=UA, timeout=(15, 40))
        except Exception:
            continue
        for lid in re.findall(r"lawId[=:](\d+)", r.text or ""):
            url = f"https://legalinfo.mn/mn/detail?lawId={lid}"
            if url in seen:
                continue
            seen.add(url)
            items.append((lid, url, "html"))
        for path in re.findall(r'href="([^"]*detail[^"]*lawId=\d+[^"]*)"', r.text or ""):
            url = urljoin("https://legalinfo.mn", path)
            lid = re.search(r"lawId=(\d+)", url)
            ident = lid.group(1) if lid else Path(url).name
            if url not in seen:
                seen.add(url)
                items.append((ident, url, "html"))
    # Try a modest lawId sweep for pages that return substantive text
    for lid in list(range(1, 80)) + list(range(1000, 1080)) + list(range(16000, 16080)):
        url = f"https://legalinfo.mn/mn/detail?lawId={lid}"
        if url in seen:
            continue
        seen.add(url)
        items.append((str(lid), url, "html"))
        if len(items) >= env_int("ITEM_LIMIT", 250):
            break
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
    for ident, url, kind in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=250)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Filter SPA shells / nav-only pages
        if "Эрх зүйн акт дэлгэрэнгүй" in text and len(text) < 800:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "spa_shell"})
            continue
        title = None
        for line in text.splitlines():
            s = line.strip()
            if len(s) > 15 and "legalinfo" not in s.lower():
                title = s[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_mn.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "kind": kind},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s kind=%s", ident, len(text), kind)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="legalinfo.mn",
        source_urls=["https://legalinfo.mn/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="CDX PDFs + detail pages incomplete",
        notes="Official Legalinfo portal. SPA shells filtered. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
