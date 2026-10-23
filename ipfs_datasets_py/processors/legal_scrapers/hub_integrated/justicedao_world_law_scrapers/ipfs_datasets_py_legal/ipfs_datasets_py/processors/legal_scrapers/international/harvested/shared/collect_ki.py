#!/usr/bin/env python3
"""Kiribati: President gazettes & instruments PDFs (president.gov.ki).

Official only:
  https://www.president.gov.ki/resources/gazettes-instruments.html
  PDFs under /images/Gazettes/… and /images/…

Deepen: live index + Wayback CDX of official president.gov.ki PDF hosts.
Optional lean PDF-prefer Common Crawl CDX pointers for the same official
hosts (individual PDF fetch via archive_fallbacks — no bulk WARC).
parliament.gov.ki unused (unreachable). No PacLII. Not legal advice.
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

CC = "ki"
COUNTRY = "Kiribati"
SOURCE_TYPE = "president_gov_ki_gazettes"
LICENSE = (
    "Official Kiribati Gazettes and Instruments as published by the Office of the "
    "President (president.gov.ki). The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.president.gov.ki/"
INDEX = "https://www.president.gov.ki/resources/gazettes-instruments.html"
SLEEP = float(os.environ.get("SLEEP", "1.0"))
MIN_TEXT = 80
USE_CC_POINTERS = os.environ.get("KI_CC_POINTERS", "1") not in ("0", "false", "False")
CDX_LIMIT = int(os.environ.get("KI_CDX_LIMIT", "2000") or "2000")
log = logging.getLogger("ki")
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)

CDX_PREFIXES = [
    "https://www.president.gov.ki/images/Gazettes/*",
    "https://president.gov.ki/images/Gazettes/*",
    "https://www.president.gov.ki/images/*",
    "https://president.gov.ki/images/*",
]


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


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = stem.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", stem).strip()[:240] or "Instrument"


def norm_url(url: str) -> str:
    u = (url or "").split("#")[0].strip()
    u = u.replace("http://", "https://")
    u = re.sub(r"https://president\.gov\.ki\b", "https://www.president.gov.ki", u, flags=re.I)
    return u


def make_item(url: str, *, source: str) -> dict | None:
    url = norm_url(url)
    if "president.gov.ki" not in url.lower() or not url.lower().endswith(".pdf"):
        return None
    low = url.lower()
    kind = "gazette" if "/gazettes/" in low else "instrument"
    return {
        "url": url,
        "title": title_from_url(url),
        "identifier": Path(unquote(url.split("?")[0])).stem[:160],
        "kind": kind,
        "document_type": "gazette" if kind == "gazette" else "statute",
        "discovery": source,
    }


def merge_item(bag: dict[str, dict], it: dict) -> None:
    key = norm_url(it["url"]).lower()
    if key not in bag:
        bag[key] = it
        return
    # prefer richer metadata
    cur = bag[key]
    if not cur.get("discovery"):
        cur["discovery"] = it.get("discovery")
    elif it.get("discovery") and it["discovery"] not in (cur.get("discovery") or ""):
        cur["discovery"] = f"{cur['discovery']}+{it['discovery']}"


def discover_live(bag: dict[str, dict]) -> int:
    try:
        r = http_get(INDEX, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4)
    except Exception as exc:
        log.error("index fail: %s", exc)
        return 0
    if r is None or r.status_code != 200 or not r.text:
        log.error("index HTTP %s", getattr(r, "status_code", None))
        return 0
    n = 0
    for href in PDF_HREF.findall(r.text):
        url = urljoin(INDEX, href.split("#")[0])
        it = make_item(url, source="live_index")
        if not it:
            continue
        before = len(bag)
        merge_item(bag, it)
        if len(bag) > before:
            n += 1
    log.info("live index new=%s bag=%s", n, len(bag))
    return n


def discover_wayback_cdx(bag: dict[str, dict]) -> int:
    n = 0
    for pref in CDX_PREFIXES:
        try:
            recs = af.search_wayback_machine(
                pref, limit=CDX_LIMIT, mime_prefix="application/pdf",
            )
        except Exception as exc:
            log.info("wayback cdx fail %s: %s", pref, exc)
            continue
        added = 0
        for r in recs or []:
            url = r.get("original") or r.get("url") or ""
            it = make_item(url, source="wayback_cdx")
            if not it:
                continue
            # stash a preferred wayback timestamp when present
            if r.get("timestamp"):
                it["wayback_ts"] = r["timestamp"]
            before = len(bag)
            merge_item(bag, it)
            if len(bag) > before:
                added += 1
                n += 1
        log.info("wayback cdx %s hits=%s new=%s bag=%s", pref[-40:], len(recs or []), added, len(bag))
    return n


def discover_cc_pointers(bag: dict[str, dict]) -> int:
    """Lean PDF-prefer CC CDX pointers on official KI hosts — no bulk WARC."""
    if not USE_CC_POINTERS:
        log.info("KI_CC_POINTERS disabled")
        return 0
    n = 0
    for pref in [
        "https://www.president.gov.ki/images/Gazettes/",
        "https://president.gov.ki/images/Gazettes/",
        "https://www.president.gov.ki/images/",
    ]:
        try:
            recs = af.search_common_crawl(pref, limit=min(120, CDX_LIMIT))
        except Exception as exc:
            log.info("cc cdx fail %s: %s", pref, exc)
            continue
        added = 0
        for r in recs or []:
            url = r.get("url") or r.get("original") or ""
            mime = str(r.get("mime") or r.get("mimetype") or "").lower()
            if not (url.lower().endswith(".pdf") or "pdf" in mime):
                continue
            it = make_item(url, source="cc_pointer")
            if not it:
                continue
            before = len(bag)
            merge_item(bag, it)
            if len(bag) > before:
                added += 1
                n += 1
        log.info("cc pointer %s hits=%s new=%s bag=%s", pref[-40:], len(recs or []), added, len(bag))
    return n


def discover() -> list[dict]:
    bag: dict[str, dict] = {}
    for it in load_catalog():
        made = make_item(it.get("url") or "", source=it.get("discovery") or "prior_catalog")
        if made:
            if it.get("wayback_ts"):
                made["wayback_ts"] = it["wayback_ts"]
            if it.get("title"):
                made["title"] = it["title"]
            merge_item(bag, made)
    log.info("prior catalog bag=%s", len(bag))
    discover_live(bag)
    discover_wayback_cdx(bag)
    # only lean CC if still thin after live+wayback
    if len(bag) < 80:
        discover_cc_pointers(bag)
    items = list(bag.values())
    # prefer gazettes/acts-like titles first
    items.sort(key=lambda it: (0 if it.get("kind") == "gazette" else 1, it.get("title") or ""))
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def get_bytes(url: str, wayback_ts: str | None = None) -> tuple[bytes, str]:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
            headers={"Accept": "application/pdf,*/*", "Referer": INDEX},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live"
    # archive_fallbacks of the same official URL (Wayback / optional CC pointer fetch)
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=USE_CC_POINTERS)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def split_ki(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    ident = it.get("identifier") or Path(unquote(url.split("?")[0])).stem
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    body, method = get_bytes(url, wayback_ts=it.get("wayback_ts"))
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=40)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    year_m = re.search(r"/(20\d{2})/", url) or re.search(r"((?:19|20)\d{2})", title)
    date = None
    if year_m:
        y = year_m.group(1)
        if re.match(r"^\d{4}$", str(y)):
            date = f"{y}-01-01"
    docs = split_ki(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ki.py", date=date, official_identifier=ident,
        document_type=it.get("document_type") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "ki_kind": it.get("kind"),
            "discovery": it.get("discovery"),
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
        source="Office of the President Gazettes & Instruments (president.gov.ki)",
        source_urls=[INDEX],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="president-gazettes-instruments-cdx-deepen",
        notes=(
            "Gazette/instrument PDFs from official president.gov.ki. Live index + "
            "Wayback CDX of /images/Gazettes and /images; optional lean CC PDF pointers "
            "on same official hosts (no bulk WARC). parliament.gov.ki unused (unreachable). "
            "Not PacLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
