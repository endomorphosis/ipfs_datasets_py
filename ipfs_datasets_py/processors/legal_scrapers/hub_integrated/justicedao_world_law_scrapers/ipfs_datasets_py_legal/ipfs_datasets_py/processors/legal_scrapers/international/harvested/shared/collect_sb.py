#!/usr/bin/env python3
"""Solomon Islands: AGC Download Monitor Acts in force (attorneygenerals.gov.sb).

Official only:
  https://attorneygenerals.gov.sb/legislation/legislation-portal/
  Category: legislation-dashboard/download-category/acts-currently-in-force/
  Download: /Download/<slug>/ → wp-content/uploads/dlm_uploads/…pdf

~224 Acts currently in force. ≤1 req/s polite. No PacLII. Not legal advice.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, split_by_pattern

CC = "sb"
COUNTRY = "Solomon Islands"
SOURCE_TYPE = "agc_gov_sb_download_monitor"
LICENSE = (
    "Official Solomon Islands legislation as published by the Attorney-General's "
    "Chambers (attorneygenerals.gov.sb). The authentic official text prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://attorneygenerals.gov.sb/"
PORTAL = "https://attorneygenerals.gov.sb/legislation/legislation-portal/"
CAT = "https://attorneygenerals.gov.sb/legislation-dashboard/download-category/acts-currently-in-force/"
SLEEP = float(os.environ.get("SLEEP", "1.0"))
MIN_TEXT = 80
log = logging.getLogger("sb")
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
INFO_HREF = re.compile(r'href=["\']([^"\']*download-info/[^"\']+)["\']', re.I)
DLPAGE_HREF = re.compile(r'href=["\']([^"\']*acts-currently-in-force[^"\']*dlpage=\d+[^"\']*)["\']', re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
        return []
    out = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def slug_from_info(url: str) -> str:
    path = unquote(url.split("?")[0].rstrip("/"))
    return path.rsplit("/", 1)[-1]


def title_from_slug(slug: str) -> str:
    t = slug.replace("-", " ").replace("_", " ")
    t = re.sub(r"\s+v\d+\b", " ", t, flags=re.I)
    t = re.sub(r"\s+as at\s+\d+", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()[:240] or "Act"


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 100:
        log.info("resume catalog n=%s", len(existing))
        return existing
    pages = [CAT]
    seen_pages = set()
    infos = {}
    max_pages = int(os.environ.get("SB_MAX_PAGES", "20") or "20")
    while pages and len(seen_pages) < max_pages:
        url = pages.pop(0)
        if url in seen_pages:
            continue
        seen_pages.add(url)
        try:
            r = http_get(
                url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=3,
                headers={"Accept": "text/html,*/*", "Referer": PORTAL},
            )
        except Exception as exc:
            log.error("cat fail %s: %s", url, exc)
            continue
        if r.status_code != 200 or not r.text:
            log.error("cat HTTP %s %s", r.status_code, url)
            continue
        for href in INFO_HREF.findall(r.text):
            full = urljoin(url, href.split("#")[0])
            if "attorneygenerals.gov.sb" not in full.lower():
                continue
            if "index-of-" in full.lower():
                continue
            slug = slug_from_info(full)
            if not slug or slug in infos:
                continue
            infos[slug] = {
                "slug": slug,
                "info_url": full,
                "url": f"https://attorneygenerals.gov.sb/Download/{slug}/",
                "title": title_from_slug(slug),
                "identifier": slug[:160],
                "kind": "act",
            }
        for href in DLPAGE_HREF.findall(r.text):
            full = urljoin(url, href.split("#")[0])
            if full not in seen_pages and full not in pages:
                pages.append(full)
        # also synthesize next pages if dlpage present
        m = re.search(r"dlpage=(\d+)", url)
        if m:
            cur = int(m.group(1))
        else:
            cur = 1
        # discover max from links
        nums = [int(x) for x in re.findall(r"dlpage=(\d+)", r.text)]
        for n in nums:
            cand = f"{CAT}?dlpage={n}"
            if cand not in seen_pages and cand not in pages:
                pages.append(cand)
        log.info("page %s infos=%s queue=%s", url[-50:], len(infos), len(pages))
    items = list(infos.values())
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def get_bytes(url: str) -> tuple[bytes, str]:
    try:
        if SLEEP:
            time.sleep(SLEEP)
        r = get_session(UA).get(
            url, timeout=(20, 180), allow_redirects=True,
            headers={
                "Accept": "application/pdf,*/*",
                "Referer": CAT,
                "User-Agent": UA,
            },
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live"
    # try archive of final URL if redirected
    if r is not None and r.url and r.url != url:
        res = af.fetch_with_fallbacks(r.url, try_http=False)
        body = res.get("content") or b""
        if res.get("status") == "success" and body[:4] == b"%PDF":
            return body, res.get("method") or "archive"
    res = af.fetch_with_fallbacks(url, try_http=False)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def split_sb(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    ident = it.get("identifier") or it.get("slug") or "act"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    body, method = get_bytes(url)
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=40)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_slug(ident)
    year_m = re.search(r"(19|20)\d{2}", title) or re.search(r"(19|20)\d{2}", ident)
    date = f"{year_m.group(0)}-01-01" if year_m else None
    docs = split_sb(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_sb.py", date=date, official_identifier=ident,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages,
            "info_url": it.get("info_url"),
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    log.info("ok %s method=%s chars=%s", rid[:70], method, len(text))
    return "ok"


def main():
    setup()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "0") or "0")
    max_seconds = int(os.environ.get("MAX_SECONDS", "7200") or "7200")
    t_start = time.time()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for it in items:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        status = fetch_one(it, done)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY,
        source="AGC Legislation Portal — Acts currently in force (attorneygenerals.gov.sb)",
        source_urls=[PORTAL, CAT],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="agc-acts-currently-in-force",
        notes=(
            "Download Monitor Acts currently in force via official AGC portal. "
            "Polite ≤1 req/s. Not PacLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
