#!/usr/bin/env python3
"""Mauritania: Journal Officiel PDFs from MSGG (msgg.gov.mr).

Official listing: https://msgg.gov.mr/fr/journal-officiel/le-journal-officiel.html
PDF base: https://msgg.gov.mr/JO/{year}/mauritanie-jo-*.pdf
Paginate ?page=N&row=1645 (pages 0..82 observed). Live first; Wayback of same URL on fail.
No Adala/Qistas. No WAF bypass. Not legal advice.
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

CC, COUNTRY, LANG = "mr", "Mauritania", "fr"
SOURCE_TYPE = "msgg_jo"
LICENSE = (
    "Official Journal Officiel of the Islamic Republic of Mauritania via MSGG "
    "(msgg.gov.mr). JO authentic text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://msgg.gov.mr/)"
LISTING = "https://msgg.gov.mr/fr/journal-officiel/le-journal-officiel.html"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+[a-zA-Z]?)\b")
PDF_RE = re.compile(
    r'href=["\']([^"\']*JO/\d{4}/mauritanie-jo-[^"\']+\.pdf)["\']',
    re.I,
)
log = logging.getLogger("mr")


def _ident_from_url(url: str) -> str:
    stem = Path(url.split("?")[0]).stem
    # mauritanie-jo-2026-1612 -> jo-2026-1612
    m = re.search(r"(mauritanie-jo-.+)$", stem, re.I)
    if m:
        return m.group(1).lower()
    return stem.lower()[:160]


def _year_from_ident(ident: str) -> str | None:
    m = re.search(r"jo-(\d{4})", ident, re.I)
    if m:
        return f"{m.group(1)}-01-01"
    return None


def discover():
    items, seen = [], set()
    max_page = env_int("MR_MAX_PAGE", 82)
    for page in range(0, max_page + 1):
        if page == 0:
            url = LISTING
        else:
            url = f"{LISTING}?page={page}&row=1645"
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 60), retries=2)
        except Exception as exc:
            log.info("listing fail page=%s: %s", page, exc)
            # Try Wayback of the same official listing URL
            got = fetch_official(url, ua=UA, verify=False, min_text=40, wayback=True)
            html = got.get("text") or ""
            # fetch_official returns text extraction; for listing we need raw HTML.
            # Fall back: stop this page if we only have plain text without hrefs.
            if "JO/" not in html and "mauritanie-jo" not in html.lower():
                time.sleep(0.5)
                continue
            body = html
        else:
            if getattr(r, "status_code", 0) != 200:
                log.info("listing http_%s page=%s", r.status_code, page)
                time.sleep(0.5)
                continue
            body = r.text or ""

        found = 0
        for href in PDF_RE.findall(body):
            pdf = urljoin(url, href.split("#")[0]).replace("http://", "https://")
            if "msgg.gov.mr" not in pdf.lower():
                continue
            if pdf in seen:
                continue
            seen.add(pdf)
            ident = _ident_from_url(pdf)
            items.append((ident, pdf))
            found += 1
        # Also catch absolute URLs without matching href= pattern edge cases
        for href in re.findall(
            r"https?://msgg\.gov\.mr/JO/\d{4}/mauritanie-jo-[^\s\"'<>]+\.pdf",
            body,
            re.I,
        ):
            pdf = href.split("#")[0]
            if pdf in seen:
                continue
            seen.add(pdf)
            items.append((_ident_from_url(pdf), pdf))
            found += 1
        log.info("page=%s pdfs=%s total=%s", page, found, len(items))
        if page > 0 and found == 0:
            # Empty page beyond known range — stop early
            if page > 5:
                break
        time.sleep(0.5)
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    items = discover()
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
        title = next(
            (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
            f"Journal Officiel — {ident}",
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
            collector="collect_mr.py",
            date=_year_from_ident(ident),
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
        source="MSGG Journal Officiel de la République Islamique de Mauritanie",
        source_urls=[LISTING, "https://msgg.gov.mr/JO/"],
        license_text=LICENSE,
        discovered=len(items),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="JO issue PDFs from MSGG listing (paginated); incomplete vs full archive",
        notes="Official MSGG JO only. FR listing. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s discovered=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
