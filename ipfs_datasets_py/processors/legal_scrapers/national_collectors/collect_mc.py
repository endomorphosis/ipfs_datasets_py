#!/usr/bin/env python3
"""Monaco: Legimonaco consolidated texts (HTML) + Journal de Monaco gazette PDFs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "mc", "Monaco", "fr"
SOURCE_TYPE = "legimonaco_journal_mc"
LICENSE = (
    "Principauté de Monaco: Legimonaco (legimonaco.mc) + Journal de Monaco "
    "(journaldemonaco.gouv.mc). Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://legimonaco.mc/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.|Chapitre|Titre)\s+[0-9IVX]+)\b")
log = logging.getLogger("mc")


def discover():
    items, seen = [], set()
    def add(url, tag):
        url = url.split("#")[0].replace("http://", "https://")
        if url in seen:
            return
        low = url.lower()
        if tag == "legimonaco":
            if "legimonaco.mc" not in low:
                return
            if any(x in low for x in ("recherche", "search", "contact", "mentions")):
                return
        else:
            if "journaldemonaco.gouv.mc" not in low:
                return
            if not low.endswith(".pdf"):
                return
        ident = re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower())[:120].strip("-")
        if not ident:
            ident = "doc"
        seen.add(url)
        items.append((f"mc-{tag}-{ident}", url))
    for prefix in ("legimonaco.mc/", "www.legimonaco.mc/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 800), match_type="prefix"):
            orig = h.get("original") or ""
            if orig:
                add(orig, "legimonaco")
    for prefix in ("www.journaldemonaco.gouv.mc/", "journaldemonaco.gouv.mc/"):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 800), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add(orig, "journal")
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_mc.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="legimonaco.mc + journaldemonaco.gouv.mc",
        source_urls=["https://legimonaco.mc/", "https://www.journaldemonaco.gouv.mc/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Legimonaco consolidated HTML + Journal PDFs)",
        notes="Official Monegasque law. French. Journal archive back to 1858. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
