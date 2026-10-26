#!/usr/bin/env python3
"""Eritrea: no official online gazette; harvests FAOLEX / WIPO / IGAD law PDFs.

NOTE: Eritrea publishes no official legislation portal online (per Law Library
of Congress). This collector gathers Eritrean law texts from reputable
third-party mirrors (FAOLEX, WIPO Lex, IGAD) as a best-effort corpus.
"""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "er", "Eritrea", "en"
SOURCE_TYPE = "faolex_wipo_igad_eritrea"
LICENSE = (
    "Eritrean law texts via FAOLEX / WIPO Lex / IGAD mirrors. "
    "No official online source exists. Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research)"
ART = re.compile(r"(?im)^\s*((?:Article|Section|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("er")


def discover():
    items, seen = [], set()
    def add(url, tag):
        url = url.split("#")[0].replace("http://", "https://")
        if url in seen:
            return
        low = url.lower()
        if tag == "faolex":
            if "faolex.fao.org" not in low or not low.endswith(".pdf"):
                return
            # Eritrea PDFs use /eriNNNNNN.pdf naming
            if "/eri" not in low:
                return
        elif tag == "wipo":
            if "wipo.int" not in low:
                return
        elif tag == "igad":
            if "igad.int" not in low or not low.endswith(".pdf"):
                return
        else:
            return
        ident = re.sub(r"[^a-z0-9]+", "-", url.rstrip("/").rsplit("/", 1)[-1].lower())[:120].strip("-")
        if not ident:
            ident = "doc"
        seen.add(url)
        items.append((f"er-{tag}-{ident}", url))
    # FAOLEX Eritrea PDFs
    for h in cdx_urls("faolex.fao.org/docs/pdf/eri", limit=env_int("CDX_LIMIT", 400),
                      match_type="prefix", extra_filters=["mimetype:application/pdf"]):
        orig = h.get("original") or ""
        if orig:
            add(orig, "faolex")
    # IGAD Eritrea legislation PDFs
    for h in cdx_urls("land.igad.int/index.php/documents-1/countries/eritrea",
                      limit=env_int("CDX_LIMIT", 300), match_type="prefix"):
        orig = h.get("original") or ""
        if orig and orig.lower().endswith(".pdf"):
            add(orig, "igad")
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_er.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "mirror": True},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="FAOLEX / WIPO Lex / IGAD (mirrors)",
        source_urls=["https://faolex.fao.org/", "https://www.wipo.int/wipolex/en/members/profile/ER"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="best-effort mirror corpus; no official online source exists for Eritrea",
        notes="Eritrea has no official online legislation portal. Corpus built from FAOLEX/WIPO/IGAD mirrors. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
