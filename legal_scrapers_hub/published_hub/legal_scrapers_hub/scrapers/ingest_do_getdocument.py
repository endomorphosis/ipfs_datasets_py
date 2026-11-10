#!/usr/bin/env python3
"""Ingest consultoria.gov.do Documents/GetDocument PDFs discovered via Wayback CDX."""
from __future__ import annotations
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "do", "Dominican Republic", "es"
SOURCE_TYPE = "consultoria_congreso_do"
LICENSE = (
    "Consultoría Jurídica del Poder Ejecutivo (consultoria.gov.do) / "
    "Biblioteca del Congreso Nacional (bibliotecadelcongreso.gob.do). "
    "Official Gaceta Oficial / legal texts. Authentic government text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.consultoria.gov.do/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("do_gd")
URLS = Path("/workspace/legal_scrapers/logs/do_wayback_extra_urls.txt")
MIN_TEXT = 200
# skip obvious non-law chrome
JUNK = re.compile(r"(?i)(nomina|nómina|carta.?compromiso|satisfacci[oó]n|formulario|logo)")


def normalize(url: str) -> str:
    url = url.replace("http://www.consultoria.gov.do:80/", "https://www.consultoria.gov.do/")
    url = url.replace("http://consultoria.gov.do:80/", "https://consultoria.gov.do/")
    url = url.replace("http://", "https://")
    return url


def ident_of(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    ref = (q.get("reference") or [""])[0]
    if ref:
        return f"GetDocument-{ref}"[:160]
    stem = Path(unquote(urlparse(url).path)).stem
    return (stem or "doc")[:160]


def main() -> None:
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 3600)
    target = env_int("TARGET_LAWS", 429)
    done = existing_ids(CC)
    urls = [normalize(u.strip()) for u in URLS.read_text().splitlines() if u.strip()]
    # dedupe by reference
    seen_ref, ordered = set(), []
    for u in urls:
        ref = ident_of(u).lower()
        if ref in seen_ref:
            continue
        seen_ref.add(ref)
        ordered.append(u)
    log.info("start candidates=%s ids=%s target=%s", len(ordered), len(done), target)
    ok = skip = fail = 0
    t_start = time.time()
    from common import ROOT
    corpus = lambda: sum(1 for _ in (ROOT / CC / "instruments").glob("*.json"))
    laws0 = corpus()

    for url in ordered:
        if ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if corpus() >= target and ok >= 1:
            log.info("target reached %s", corpus())
            break
        ident = ident_of(url)
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, wayback=False, min_text=MIN_TEXT)
        text = got.get("text") or ""
        if len(text) < MIN_TEXT:
            got2 = fetch_official(url, ua=UA, verify=False, wayback=True, min_text=MIN_TEXT)
            if len(got2.get("text") or "") > len(text):
                got, text = got2, got2.get("text") or ""
        if len(text) < MIN_TEXT:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "short", "portal": "getdocument"})
            continue
        title = None
        for line in text.splitlines():
            s = line.strip()
            if 12 <= len(s) <= 240:
                title = s
                break
        title = title or ident
        if JUNK.search(title) or JUNK.search(text[:800]):
            skip += 1
            log.info("skip junk %s", ident[:50])
            continue
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="ingest_do_getdocument.py", article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "discovery": "wayback_cdx_getdocument"},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s corpus=%s chars=%s", ident[:60], got.get("method"), corpus(), len(text))
        else:
            fail += 1
        time.sleep(0.25)

    laws = corpus()
    write_summary(
        CC, country=COUNTRY, source="Consultoria GetDocument + prior",
        source_urls=["https://www.consultoria.gov.do/", "https://bibliotecadelcongreso.gob.do/"],
        license_text=LICENSE, discovered=len(ordered), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes=f"GetDocument ingest. Before {laws0} after {laws}. Started {t0}.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s corpus=%s->%s", ok, skip, fail, laws0, laws)
    print({"ok": ok, "skip": skip, "fail": fail, "laws0": laws0, "laws": laws})


if __name__ == "__main__":
    main()
