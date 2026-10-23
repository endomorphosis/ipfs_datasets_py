#!/usr/bin/env python3
"""Laos: Lao Official Gazette (laoofficialgazette.gov.la) kcfinder PDF uploads + Wayback."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "la", "Laos", "lo"
SOURCE_TYPE = "lao_official_gazette"
LICENSE = (
    "Lao Official Gazette (laoofficialgazette.gov.la). "
    "Official gazette of the Lao PDR. Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.laoofficialgazette.gov.la/)"
ART = re.compile(r"(?im)^\s*((?:ມາດຕາ|Article|Art\.?|Maddə)\s*[0-9]+)\b")
log = logging.getLogger("la")
HOME = "https://www.laoofficialgazette.gov.la/"


def pdf_ocr_text(raw: bytes) -> str:
    from pdf_extract_lib import extract_ocr
    import os
    text, _ = extract_ocr(raw, lang="lao+eng", max_pages=int(os.environ.get("OCR_MAX_PAGES", "25") or 25))
    return text or ""


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0]
        if "laoofficialgazette.gov.la" not in url.lower():
            return
        if ".pdf" not in url.lower() and "kcfinder" not in url.lower():
            return
        if ".pdf" not in url.lower():
            return
        if url in seen:
            return
        stem = Path(unquote(url.split("?")[0])).stem[:160]
        ident = stem or re.sub(r"\W+", "-", url)[-80:]
        seen.add(url)
        items.append((ident, url.replace("http://", "https://").replace(":80/", "/")))
    try:
        r = live_get(HOME, ua=UA, verify=False, timeout=(20, 60))
        if r.status_code == 200:
            for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text or "", re.I):
                add(urljoin(HOME, href))
            for href in re.findall(r'(https?://[^"\']+laoofficialgazette\.gov\.la[^"\']+\.pdf)', r.text or "", re.I):
                add(href)
    except Exception as exc:
        log.info("home %s", exc)
    for prefix in (
        "laoofficialgazette.gov.la/kcfinder/upload/files/",
        "www.laoofficialgazette.gov.la/kcfinder/upload/files/",
        "laoofficialgazette.gov.la/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add(orig)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=120)
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
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_la.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Lao Official Gazette",
        source_urls=["https://www.laoofficialgazette.gov.la/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (kcfinder gazette PDFs)",
        notes="Official Lao Official Gazette PDFs via live/Wayback. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
