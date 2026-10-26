#!/usr/bin/env python3
"""Botswana: ARCHIVE-ONLY harvester (never touches live sites).

collect_bw.py hangs on live-site harvesting from research egress, so this
wrapper enumerates archived official Botswana PDFs via Wayback CDX
(world_lib.cdx_urls) and fetches them via archive_fallbacks (Common Crawl
WARC -> Wayback replay -> archive.today), with try_http=False so no direct
HTTP request is ever made to the live hosts.

Writes to the same corpus layout (cc='bw') as collect_bw.py and is
idempotent via existing_ids().
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_bw as bw
from archive_fallbacks import fetch_with_fallbacks
from common import existing_ids, log_failure, utcnow, write_summary
from pdf_extract_lib import extract_pdf_text
from world_lib import cdx_urls, env_int, save_instrument, setup_log, slug_id

log = logging.getLogger("bw_archive")

# Official Botswana hosts only (same policy as collect_bw.py).
ARCHIVE_HOSTS = (
    "gov.bw",
    "parliament.gov.bw",
    "botswanaspeaks.gov.bw",
    "burs.org.bw",
    "elaws.gov.bw",
    "justice.gov.bw",
    "bob.bw",
    "bocra.org.bw",
    "bera.co.bw",
    "caab.co.bw",
    "nbfira.org.bw",
    "ppadb.co.bw",
    "competitionauthority.co.bw",
    "hrdc.org.bw",
)

PDF_NAME_OK = re.compile(r"\.(pdf)(\?|$)", re.I)


def _ident_from_url(url: str) -> str:
    path = urlsplit(url).path.rsplit("/", 1)[-1]
    ident = re.sub(r"\.[a-z0-9]+$", "", path, flags=re.I)
    ident = re.sub(r"[^a-z0-9]+", "-", ident.lower()).strip("-")
    return ident or "bw-doc"


def discover_archive_urls() -> list[tuple[str, str, str | None]]:
    """Return (ident, url, wayback_ts) from Wayback CDX of official hosts."""
    out: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    limit = env_int("CDX_LIMIT", 220)
    for host in ARCHIVE_HOSTS:
        try:
            hits = cdx_urls(
                f"https://{host}/",
                limit=limit,
                match_type="domain",
                extra_filters=["mimetype:application/pdf", "statuscode:200"],
            )
        except Exception as exc:
            log.info("cdx err %s: %s", host, exc)
            continue
        for h in hits:
            url = h.get("url") or h.get("original") or ""
            if not url or not PDF_NAME_OK.search(url):
                continue
            if bw.BLOCK_HOST.search(url) or bw.SKIP_NAME.search(url):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append((_ident_from_url(url), url, h.get("timestamp")))
        log.info("cdx %s -> %d pdf urls (total %d)", host, len([1 for _ in hits]), len(out))
    return out


def fetch_archive_only(url: str, wayback_ts: str | None) -> dict:
    got = fetch_with_fallbacks(
        url, wayback_ts=wayback_ts, try_http=False, try_archive_is=False
    )
    if got.get("status") != "success":
        return got
    text = got.get("text") or ""
    content = got.get("content") or b""
    if not text and content[:4] == b"%PDF":
        enable_ocr = not bool(env_int("SKIP_OCR", 0)) and bool(env_int("ALLOW_OCR", 1))
        text, method, _pages = extract_pdf_text(content, enable_ocr=enable_ocr)
        got["text"] = text
        got["method"] = f"{got.get('method')}+{method}"
    return got


def main() -> None:
    setup_log("bw_archive")
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids("bw")
    ok = skip = fail = 0
    for ident, url, ts in discover_archive_urls():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id("bw", ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_archive_only(url, ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure("bw", {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if not bw._looks_like_law(text):
            fail += 1
            log_failure("bw", {"identifier": ident, "source_url": url, "reason": "not_law_like"})
            continue
        title = bw._title_from_text(text, ident)
        if save_instrument(
            cc="bw",
            country=bw.COUNTRY,
            language=bw.LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=bw.SOURCE_TYPE,
            license_text=bw.LICENSE,
            collector="collect_bw_archive.py",
            article_re=bw.ART,
            extra_meta={"fetch_method": got.get("method"), "archive_only": True},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident[:70], len(text), got.get("method"))
        else:
            fail += 1
    write_summary(
        "bw",
        country=bw.COUNTRY,
        source="Botswana official portals via web archives (archive-only)",
        source_urls=[f"https://{h}/" for h in ARCHIVE_HOSTS],
        license_text=bw.LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="archive-only; live sites hang from research egress",
        notes="Archive-only Botswana harvester. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
