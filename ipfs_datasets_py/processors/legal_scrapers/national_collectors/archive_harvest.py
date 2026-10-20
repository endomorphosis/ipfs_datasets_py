#!/usr/bin/env python3
"""Generic ARCHIVE-ONLY law harvester for countries without a live collector.

Enumerates archived official PDFs via Wayback CDX (world_lib.cdx_urls) on the
given official hosts, fetches them via archive_fallbacks (Common Crawl WARC ->
Wayback replay -> archive.today) with try_http=False (never touches live
sites), extracts text via pdf_extract_lib (pdfplumber -> PyMuPDF -> pdftotext
-> tesseract OCR), filters with language-aware law markers, and saves via
save_instrument. Idempotent via existing_ids().

Usage:
  archive_harvest.py --cc sd --country Sudan --lang ar \\
      --hosts moj.gov.sd --license "..." \\
      [--max-new 200] [--max-seconds 3600] [--cdx-limit 220]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_fallbacks import fetch_with_fallbacks
from common import existing_ids, log_failure, utcnow, write_summary
from pdf_extract_lib import extract_pdf_text
from world_lib import cdx_urls, env_int, save_instrument, setup_log, slug_id

log = logging.getLogger("archive_harvest")

# Language-aware law markers (head-of-document heuristics).
LAW_MARKS = {
    "ar": re.compile(r"(قانون|مرسوم|قرار|الجريدة الرسمية|مادة\s*\(?\d+|المادة)", re.I),
    "en": re.compile(
        r"(AN?\s+ACT\b|A\s+BILL\b|Short title|This Act may be cited|"
        r"ENACTED by|GOVERNMENT GAZETTE|Statutory Instrument|"
        r"^\s*(Section|Sec\.)\s+\d+)",
        re.I | re.M,
    ),
    "fr": re.compile(
        r"(LOI\b|DÉCRET\b|ARRÊTÉ|Journal officiel|Article\s+\d+|"
        r"^\s*Article\s+premier)",
        re.I | re.M,
    ),
    "pt": re.compile(
        r"(LEI\b|DECRETO|Diário da República|Artigo\s+\d+|"
        r"A Assembleia|O Presidente)",
        re.I | re.M,
    ),
    "es": re.compile(
        r"(LEY\b|DECRETO|Gaceta Oficial|Boletín Oficial|Artículo\s+\d+|"
        r"^\s*Artículo\s+1)",
        re.I | re.M,
    ),
    "ru": re.compile(r"(ЗАКОН|УКАЗ|ПОСТАНОВЛЕНИЕ|Статья\s+\d+)", re.I),
    "fa": re.compile(r"(قانون|مصوبه|آیین‌نامه|ماده\s+\d+)", re.I),
    "am": re.compile(r"(አዋጅ|ደንብ|መመሪያ|ህግ)", re.I),
    "so": re.compile(r"(XEER|SHARCI|WAREEGTO|QODOB)", re.I),
}

ART_RES = {
    "ar": re.compile(r"(?im)^\s*((?:مادة|المادة)\s*\(?\d+\)?)"),
    "en": re.compile(r"(?im)^\s*((?:Section|Sec\.|Article|Art\.)\s+\d+[A-Za-z]?)"),
    "fr": re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+[A-Za-z]?)"),
    "pt": re.compile(r"(?im)^\s*((?:Artigo|Art\.)\s+\d+[ºªo°a-zA-Z]?)"),
    "es": re.compile(r"(?im)^\s*((?:Artículo|Art\.)\s+\d+[ºªo°a-zA-Z]?)"),
    "ru": re.compile(r"(?im)^\s*((?:Статья)\s+\d+)"),
    "fa": re.compile(r"(?im)^\s*((?:ماده)\s+\d+)"),
    "am": re.compile(r"(?im)^\s*((?:አንቀጽ)\s+\d+)"),
    "so": re.compile(r"(?im)^\s*((?:Qodobka)\s+\d+)"),
}

PDF_NAME_OK = re.compile(r"\.(pdf)(\?|$)", re.I)
SKIP_NAME = re.compile(
    r"(press.?release|newsletter|brochure|advert|vacancy|tender|annual.?report|"
    r"speech|statement|form|manual|directory|factsheet|poster)",
    re.I,
)


def _looks_like_law(text: str, lang: str) -> bool:
    if not text or len(text) < 200:
        return False
    mark = LAW_MARKS.get(lang) or LAW_MARKS["en"]
    head = text[:8000]
    if mark.search(head):
        return True
    art = ART_RES.get(lang) or ART_RES["en"]
    return len(art.findall(text[:20000])) >= 5


def _ident_from_url(url: str, cc: str) -> str:
    path = urlsplit(url).path.rsplit("/", 1)[-1]
    ident = re.sub(r"\.[a-z0-9]+$", "", path, flags=re.I)
    ident = re.sub(r"[^a-z0-9]+", "-", ident.lower()).strip("-")
    return ident or f"{cc}-doc"


def discover(hosts: list[str], cdx_limit: int) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for host in hosts:
        try:
            hits = cdx_urls(
                f"https://{host}/",
                limit=cdx_limit,
                match_type="domain",
                extra_filters=["mimetype:application/pdf", "statuscode:200"],
            )
        except Exception as exc:
            log.info("cdx err %s: %s", host, exc)
            continue
        n = 0
        for h in hits:
            url = h.get("url") or h.get("original") or ""
            if not url or not PDF_NAME_OK.search(url):
                continue
            if SKIP_NAME.search(url):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append((url, url, h.get("timestamp")))
            n += 1
        log.info("cdx %s -> %d pdf urls (total %d)", host, n, len(out))
    return out


def fetch_archive_only(url: str, ts: str | None, lang: str, ocr_lang: str) -> dict:
    got = fetch_with_fallbacks(url, wayback_ts=ts, try_http=False, try_archive_is=False)
    if got.get("status") != "success":
        return got
    text = got.get("text") or ""
    content = got.get("content") or b""
    if not text and content[:4] == b"%PDF":
        enable_ocr = not bool(env_int("SKIP_OCR", 0)) and bool(env_int("ALLOW_OCR", 1))
        text, method, _pages = extract_pdf_text(
            content, enable_ocr=enable_ocr, ocr_lang=ocr_lang
        )
        got["text"] = text
        got["method"] = f"{got.get('method')}+{method}"
    return got


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", required=True)
    ap.add_argument("--country", required=True)
    ap.add_argument("--lang", required=True, help="ISO 639-1-ish code for markers")
    ap.add_argument("--ocr-lang", default=None, help="tesseract lang (default: lang)")
    ap.add_argument("--hosts", required=True, help="comma-separated official hosts")
    ap.add_argument("--license", default="")
    ap.add_argument("--source-type", default="official_gazette_archive")
    ap.add_argument("--max-new", type=int, default=None)
    ap.add_argument("--max-seconds", type=int, default=None)
    ap.add_argument("--cdx-limit", type=int, default=220)
    args = ap.parse_args()

    cc = args.cc
    setup_log(f"archive_{cc}")
    t0 = utcnow()
    max_new = args.max_new or env_int("MAX_NEW", 200)
    max_seconds = args.max_seconds or env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    ocr_lang = args.ocr_lang or args.lang
    done = existing_ids(cc)
    ok = skip = fail = 0
    for url, _u2, ts in discover(hosts, args.cdx_limit):
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        ident = _ident_from_url(url, cc)
        rid = slug_id(cc, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_archive_only(url, ts, args.lang, ocr_lang)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if not _looks_like_law(text, args.lang):
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": url, "reason": "not_law_like"})
            continue
        title = (text.strip().split("\n")[0] or ident)[:200]
        art_re = ART_RES.get(args.lang) or ART_RES["en"]
        if save_instrument(
            cc=cc,
            country=args.country,
            language=args.lang,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=args.source_type,
            license_text=args.license,
            collector="archive_harvest.py",
            article_re=art_re,
            extra_meta={"fetch_method": got.get("method"), "archive_only": True},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident[:70], len(text), got.get("method"))
        else:
            fail += 1
    write_summary(
        cc,
        country=args.country,
        source=f"{args.country} official portals via web archives (archive-only)",
        source_urls=[f"https://{h}/" for h in hosts],
        license_text=args.license,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="archive-only harvest; no live collector in tree",
        notes="Generic archive-only harvester. Not legal advice.",
        last_run=t0,
    )
    log.info("done cc=%s ok=%s skip=%s fail=%s", cc, ok, skip, fail)


if __name__ == "__main__":
    main()
