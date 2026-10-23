#!/usr/bin/env python3
"""Bolivia: Gaceta Oficial de Bolivia (HTTP; HTTPS TLS often fails) + Wayback."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "bo", "Bolivia", "es"
SOURCE_TYPE = "gaceta_oficial_bo"
LICENSE = (
    "Official Gazette of the Plurinational State of Bolivia "
    "(gacetaoficialdebolivia.gob.bo). Authentic Gaceta text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.gacetaoficialdebolivia.gob.bo/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("bo")
HOME = "http://www.gacetaoficialdebolivia.gob.bo/"


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0]
        if not url.startswith("http"):
            url = urljoin(HOME, url)
        if url in seen:
            return
        ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-")[:160]
        seen.add(url)
        items.append((ident, url))
    add("http://www.gacetaoficialdebolivia.gob.bo/app/webroot/archivos/CONSTITUCION.pdf")
    try:
        r = http_get(HOME, ua=UA, sleep=0.3)
        if r.status_code == 200:
            for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text or "", re.I):
                add(href)
    except Exception as exc:
        log.info("home %s", exc)
    for h in cdx_urls("gacetaoficialdebolivia.gob.bo/", limit=env_int("CDX_LIMIT", 300), match_type="prefix",
                      extra_filters=["mimetype:application/pdf"]):
        orig = h.get("original") or ""
        if orig and orig.lower().endswith(".pdf"):
            add(orig)
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 50)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=120)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bo.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s", ident[:70], got.get("method"))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Gaceta Oficial de Bolivia",
        source_urls=["http://www.gacetaoficialdebolivia.gob.bo/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (HTTP PDFs + Wayback)",
        notes="HTTPS TLS often fails; HTTP and Wayback of official URLs. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
