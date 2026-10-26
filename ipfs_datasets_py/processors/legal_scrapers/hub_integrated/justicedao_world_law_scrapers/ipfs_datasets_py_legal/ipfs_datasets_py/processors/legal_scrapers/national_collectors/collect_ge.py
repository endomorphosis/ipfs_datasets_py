#!/usr/bin/env python3
"""Georgia: Legislative Herald (matsne.gov.ge). Live often Access Denied; Wayback of official URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ge", "Georgia", "ka"
SOURCE_TYPE = "matsne"
LICENSE = (
    "Official texts of the Legislative Herald of Georgia (matsne.gov.ge). "
    "Authentic Matsne publication prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://matsne.gov.ge/)"
ART = re.compile(r"(?m)^\s*((?:მუხლი|Article)\s+[0-9]+[A-Za-zა-ჰ]?)\b")
log = logging.getLogger("ge")
SEED = [31702, 31752, 32764, 30346, 11598, 19300, 90034, 205044, 5827307, 6087464]


def discover():
    items, seen = [], set()
    def add(i):
        i = str(i)
        if i in seen:
            return
        seen.add(i)
        items.append((i, f"https://matsne.gov.ge/ka/document/view/{i}"))
    for i in SEED:
        add(i)
    for h in cdx_urls("matsne.gov.ge/ka/document/view/", limit=env_int("CDX_LIMIT", 350), match_type="prefix"):
        orig = h.get("original") or ""
        m = re.search(r"/document/view/(\d+)", orig)
        if m:
            add(m.group(1))
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
        if got.get("status") != "success":
            pdf = f"https://matsne.gov.ge/ka/document/download/{ident}/published/ka/pdf"
            got = fetch_official(pdf, ua=UA, min_text=150)
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
            title=title or f"Matsne {ident}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ge.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident, got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="matsne.gov.ge Legislative Herald",
        source_urls=["https://matsne.gov.ge/"], license_text=LICENSE,
        discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official Matsne URLs; live WAF Access Denied)",
        notes="No WAF bypass. Official Matsne URLs only via live or Wayback. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
