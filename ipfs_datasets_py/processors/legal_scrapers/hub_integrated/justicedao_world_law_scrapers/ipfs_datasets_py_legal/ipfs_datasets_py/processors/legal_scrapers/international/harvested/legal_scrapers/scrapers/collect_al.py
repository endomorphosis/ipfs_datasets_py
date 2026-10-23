#!/usr/bin/env python3
"""Albania: Qendra e Botimeve Zyrtare ELI (qbz.gov.al). Live SPA; Wayback of official ELI URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "al", "Albania", "sq"
SOURCE_TYPE = "qbz_fletore"
LICENSE = (
    "Official acts of the Republic of Albania as published by Qendra e Botimeve Zyrtare "
    "(qbz.gov.al, Fletorja Zyrtare). Authentic FZ text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.qbz.gov.al/)"
ART = re.compile(r"(?m)^\s*((?:Neni|NENI|Article)\s+[0-9]+[A-Za-z]?)\b")
log = logging.getLogger("al")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("?")[0].rstrip("/")
        if not url or url in seen:
            return
        if any(x in url.lower() for x in (".css", ".js", "/faq", "/search")):
            return
        m = re.search(r"/eli/(.+)$", url)
        ident = (m.group(1) if m else url).replace("/", "-")
        seen.add(url)
        items.append((ident, url if url.startswith("http") else "https://www.qbz.gov.al/" + url.lstrip("/")))
    for h in cdx_urls("qbz.gov.al/eli/ligj/", limit=env_int("CDX_LIMIT", 350), match_type="prefix"):
        add((h.get("original") or "").replace("http://", "https://"))
    for h in cdx_urls("www.qbz.gov.al/eli/ligj/", limit=env_int("CDX_LIMIT", 200), match_type="prefix"):
        add((h.get("original") or "").replace("http://", "https://"))
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
        got = fetch_official(url, ua=UA, min_text=150)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_al.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:70], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="QBZ Fletorja Zyrtare ELI",
        source_urls=["https://www.qbz.gov.al/eli/akte"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official ELI ligj URLs; live Angular shell)",
        notes="Official QBZ ELI only. No unofficial bazaligjore. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
