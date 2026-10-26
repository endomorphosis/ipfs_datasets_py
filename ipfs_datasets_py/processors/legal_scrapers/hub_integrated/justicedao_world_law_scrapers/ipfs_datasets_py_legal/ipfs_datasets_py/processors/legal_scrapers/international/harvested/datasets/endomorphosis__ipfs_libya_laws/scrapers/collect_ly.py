#!/usr/bin/env python3
"""Libya: Official Gazette (الجريدة الرسمية) PDFs from gazette.ly.

Official portal: https://gazette.ly/ (founded Law 8/2011 per /ar/node/164).
Discover jo_*.pdf under /sites/default/files/ from homepage, /ar/node/156
(أعداد الجريدة الرسمية) and related archive pages. Live first; Wayback of same
official URL on fail. Do NOT harvest lawsociety.ly. No WAF bypass. Not legal advice.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ly", "Libya", "ar"
SOURCE_TYPE = "gazette_ly"
LICENSE = (
    "Official Libyan Official Gazette (الجريدة الرسمية الليبية) via gazette.ly "
    "(Law 8/2011). Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://gazette.ly/)"
HOME = "https://gazette.ly/"
ARCHIVE = "https://gazette.ly/ar/node/156"
RELATED = (
    "https://gazette.ly/ar",
    "https://gazette.ly/ar/node/156",
    "https://gazette.ly/ar/node/164",
)
ART = re.compile(r"(?im)^\s*((?:المادة|مادة|Article|Art\.?)\s+[0-9]+)\b")
JO_PDF_RE = re.compile(
    r'(?:href=["\'])?((?:https?://gazette\.ly)?/sites/default/files/jo_[^"\'\s<>]+\.pdf)',
    re.I,
)
log = logging.getLogger("ly")


def _norm_pdf(url: str, base: str) -> str | None:
    url = (url or "").split("#")[0].strip()
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    full = urljoin(base, url).replace("http://", "https://")
    low = full.lower()
    if "lawsociety.ly" in low:
        return None
    if "gazette.ly" not in low:
        return None
    if "/sites/default/files/jo_" not in low or not low.endswith(".pdf"):
        return None
    return full


def _ident_from_url(url: str) -> str:
    stem = Path(url.split("?")[0]).stem  # jo_120_1762531549
    return stem.lower()[:160]


def _title_from_html(body: str, pdf_path: str) -> str | None:
    # Prefer anchor text near this PDF
    esc = re.escape(pdf_path)
    m = re.search(
        rf'<a[^>]+href=["\'][^"\']*{esc}["\'][^>]*>(.*?)</a>',
        body,
        re.I | re.S,
    )
    if m:
        t = re.sub(r"<[^>]+>", "", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 4:
            return t[:240]
    return None


def _scrape_page(url: str, items: list, seen: set, titles: dict) -> int:
    found = 0
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(15, 60), retries=2)
    except Exception as exc:
        log.info("seed fail %s: %s", url, exc)
        return 0
    if getattr(r, "status_code", 0) != 200:
        log.info("seed http_%s %s", r.status_code, url)
        return 0
    body = r.text or ""
    for href in JO_PDF_RE.findall(body):
        pdf = _norm_pdf(href, url)
        if not pdf or pdf in seen:
            continue
        seen.add(pdf)
        ident = _ident_from_url(pdf)
        items.append((ident, pdf))
        path_part = "/" + pdf.split("gazette.ly/", 1)[-1]
        t = _title_from_html(body, path_part) or _title_from_html(body, pdf)
        if t:
            titles[pdf] = t
        found += 1
    log.info("scrape %s pdfs=%s total=%s", url, found, len(items))
    time.sleep(0.5)
    return found


def discover():
    items, seen, titles = [], set(), {}
    # Homepage
    _scrape_page(HOME, items, seen, titles)
    _scrape_page("https://gazette.ly/ar", items, seen, titles)
    # Archive listing with pagination (observed pages 0..3)
    max_page = env_int("LY_MAX_PAGE", 8)
    for page in range(0, max_page + 1):
        url = ARCHIVE if page == 0 else f"{ARCHIVE}?page={page}"
        n = _scrape_page(url, items, seen, titles)
        if page > 0 and n == 0:
            break
    # Related official pages (may not list jo_ PDFs)
    for url in RELATED:
        if url.rstrip("/") in (HOME.rstrip("/"), ARCHIVE.rstrip("/"), "https://gazette.ly/ar"):
            continue
        _scrape_page(url, items, seen, titles)
    log.info("catalog %s", len(items))
    return items, titles


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    items, titles = discover()
    for ident, url in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=80)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            time.sleep(0.5)
            continue
        title = titles.get(url) or next(
            (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 8),
            f"الجريدة الرسمية — {ident}",
        )
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_ly.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident, got.get("method"), len(text))
        else:
            fail += 1
        time.sleep(0.5)
    write_summary(
        CC,
        country=COUNTRY,
        source="Libyan Official Gazette (gazette.ly)",
        source_urls=[HOME, ARCHIVE, "https://gazette.ly/ar/node/164"],
        license_text=LICENSE,
        discovered=len(items),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="jo_*.pdf issues from gazette.ly homepage + أعداد الجريدة الرسمية archive",
        notes="Official gazette.ly only (not lawsociety.ly). Arabic OCR may be thin. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s discovered=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
