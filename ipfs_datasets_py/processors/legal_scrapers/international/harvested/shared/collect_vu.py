#!/usr/bin/env python3
"""Vanuatu: Parliament bills PDFs from parliament.gov.vu.

Official only:
  https://parliament.gov.vu/index.php/parliamentary-business/bills
  PDFs under https://parliament.gov.vu/images/Bills/…

Consolidations thin — bills/gazettes only; PacLII Acts excluded as primary.
TLS chain may be broken from this egress (use verify=False for live only;
no captcha/WAF bypass). Archive_fallbacks of the same official parliament.gov.vu
URLs when live fails. Not legal advice.
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

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, split_by_pattern

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CC = "vu"
COUNTRY = "Vanuatu"
SOURCE_TYPE = "parliament_gov_vu_bills"
LICENSE = (
    "Official Parliament of Vanuatu bill texts as published on parliament.gov.vu. "
    "The authentic official text prevails. Not legal advice. Bills corpus only — "
    "not consolidated Acts."
)
UA = DEFAULT_UA + " source=https://parliament.gov.vu/"
PORTAL = "https://parliament.gov.vu/"
BILLS_INDEX = "https://parliament.gov.vu/index.php/parliamentary-business/bills"
SLEEP = float(os.environ.get("SLEEP", "0.6"))
MIN_TEXT = 80
log = logging.getLogger("vu")

INDEX_URLS = [
    BILLS_INDEX,
    "https://parliament.gov.vu/index.php/parliamentary-business/bills?limit=0",
    "https://www.parliament.gov.vu/index.php/parliamentary-business/bills",
]

ART_VU = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|CHAPTER|Chapter|SCHEDULE|Schedule|"
    r"Clause|CLAUSE)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)
FRENCH_BILL_RE = re.compile(r"projet\s*de\s*loi|projet%20de%20loi", re.I)


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


def official_url(url: str) -> str:
    u = url.strip()
    u = re.sub(r":80/", "/", u)
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin("https://parliament.gov.vu/", u.lstrip("/"))
    u = u.replace("http://www.parliament.gov.vu", "https://parliament.gov.vu")
    u = u.replace("https://www.parliament.gov.vu", "https://parliament.gov.vu")
    u = u.replace("http://parliament.gov.vu", "https://parliament.gov.vu")
    m = re.search(r"https?://(?:www\.)?parliament\.gov\.vu/[^\s\"'<>]+", u)
    if m:
        u = m.group(0).replace("http://", "https://").replace("https://www.", "https://")
    return u.split("#")[0]


def live_get(url: str, *, timeout=(20, 120), retries: int = 2):
    """Live GET with TLS verify disabled (broken chain on parliament.gov.vu)."""
    last = None
    for attempt in range(1, retries + 1):
        try:
            if SLEEP:
                time.sleep(SLEEP)
            resp = requests.get(
                url, timeout=timeout, verify=False,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/html,application/pdf,*/*",
                    "Referer": PORTAL,
                },
            )
            return resp
        except Exception as exc:
            last = exc
            log.info("live exception attempt=%s %s: %s", attempt, url, exc)
            time.sleep(min(8, 1.5 * attempt))
    log.info("live failed %s: %s", url, last)
    return None


def get_html(url: str) -> tuple[str, str]:
    official = official_url(url)
    r = live_get(official)
    if r is not None:
        text = ""
        ctype = (r.headers.get("content-type") or "").lower()
        if r.content and ("html" in ctype or "text/" in ctype or not ctype) and r.content[:4] != b"%PDF":
            text = r.content.decode(r.encoding or "utf-8", "replace")
        if r.status_code == 200 and text and not af.is_challenge(text, r.status_code):
            return text, "live"
        log.info("live html status=%s — archive %s", r.status_code, official)
    res = af.fetch_with_fallbacks(official, try_http=False)
    if res.get("status") == "success":
        text = res.get("text") or ""
        if not text and res.get("content"):
            text = res["content"].decode("utf-8", "replace")
        if text and not af.is_challenge(text, 200):
            return text, res.get("method") or "archive"
    wb = af.get_wayback_content(official)
    if wb.get("status") == "success" and (wb.get("text") or ""):
        return wb["text"], "wayback"
    return "", "failed"


def get_pdf(url: str, wayback_ts: str | None = None) -> tuple[bytes, str]:
    official = official_url(url)
    r = live_get(official, timeout=(20, 180), retries=1)
    if r is not None:
        if r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
            return r.content, "live"
        log.info("live pdf status=%s — archive %s", getattr(r, "status_code", "?"), official[-80:])
    for ts in (wayback_ts, None):
        wb = af.get_wayback_content(official, timestamp=ts)
        body = wb.get("content") or b""
        if wb.get("status") == "success" and body[:4] == b"%PDF":
            return body, "wayback"
    res = af.fetch_with_fallbacks(official, try_http=False, try_cc=False, try_archive_is=True)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def is_english_bill(url: str) -> bool:
    return not bool(FRENCH_BILL_RE.search(unquote(url)))


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = stem.replace("_", " ").replace("%20", " ")
    return re.sub(r"\s+", " ", stem).strip()[:240] or "Bill"


def bill_group_key(url: str) -> str:
    """Collapse EN/FR twins of the same bill folder."""
    path = unquote(url.split("?")[0])
    parent = str(Path(path).parent).lower()
    return parent


def add_pdf(items: dict, url: str, *, source: str, wayback_ts: str | None = None) -> None:
    url = official_url(url)
    if "parliament.gov.vu" not in url.lower():
        return
    if ".pdf" not in url.lower():
        return
    # Bills / gazette agency paths under images/
    low = url.lower()
    if "/images/" not in low:
        return
    path = unquote(url.split("?")[0])
    stem = Path(path).stem
    key = bill_group_key(url)
    eng = is_english_bill(url)
    cand = {
        "url": url, "title": title_from_url(url), "identifier": stem[:160],
        "source": source, "kind": "bill", "document_type": "bill",
        "wayback_ts": wayback_ts, "english": eng,
    }
    if "gazette" in low:
        cand["kind"] = "gazette"
        cand["document_type"] = "gazette"
    prev = items.get(key)
    if prev is None:
        items[key] = cand
        return
    # Prefer English over French; prefer newer wayback_ts
    prev_eng = prev.get("english", True)
    if eng and not prev_eng:
        if prev.get("wayback_ts") and not wayback_ts:
            cand["wayback_ts"] = prev["wayback_ts"]
        items[key] = cand
    elif eng == prev_eng and wayback_ts and (
        not prev.get("wayback_ts") or wayback_ts > prev.get("wayback_ts", "")
    ):
        items[key] = cand


def discover_from_html(html: str, base: str, items: dict, source: str) -> None:
    for href in PDF_HREF.findall(html or ""):
        url = urljoin(base, href.split("#")[0])
        add_pdf(items, url, source=source)


def discover_cdx(items: dict) -> None:
    limit = int(os.environ.get("VU_CDX_LIMIT", "400") or "400")
    for prefix in (
        "parliament.gov.vu/images/Bills/",
        "parliament.gov.vu/images/Bills%20",
        "parliament.gov.vu/images/",
    ):
        recs = af.search_wayback_machine(
            prefix, match_type="prefix", limit=limit,
            extra_filters=["mimetype:application/pdf"],
        )
        log.info("cdx %s pdfs=%s", prefix[-40:], len(recs))
        for rec in recs:
            orig = rec.get("original") or ""
            if orig and (".pdf" in orig.lower()) and (
                "/bills" in orig.lower() or "/images/bills" in orig.lower()
                or "bill" in Path(unquote(orig)).name.lower()
                or "projet" in Path(unquote(orig)).name.lower()
            ):
                add_pdf(items, orig, source="cdx", wayback_ts=rec.get("timestamp") or None)


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 40:
        log.info("resume catalog n=%s", len(existing))
        return existing
    bag: dict = {}
    for url in INDEX_URLS:
        html, method = get_html(url)
        log.info("index %s method=%s bytes=%s", url, method, len(html or ""))
        if html:
            discover_from_html(html, url, bag, method)
    # Also use local probe body if present (same official host HTML snapshot)
    probe = Path(__file__).resolve().parent / "logs" / "ap_probe_raw" / "pacific_islands" / "vu_bills_k.body"
    if probe.exists():
        try:
            html = probe.read_text(encoding="utf-8", errors="replace")
            discover_from_html(html, BILLS_INDEX, bag, "probe_snapshot")
            log.info("probe snapshot pdfs_so_far=%s", len(bag))
        except Exception as exc:
            log.info("probe snapshot skip: %s", exc)
    discover_cdx(bag)
    items = list(bag.values())
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_vu(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_VU, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    url = official_url(it["url"])
    ident = it.get("identifier") or Path(unquote(url.split("?")[0])).stem
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    body, method = get_pdf(url, wayback_ts=it.get("wayback_ts"))
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng+fra", ocr_max_pages=40)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    lang = "en" if it.get("english", True) else "fr"
    year_m = re.search(r"(20\d{2}|19\d{2})", unquote(url) + " " + title)
    date = f"{year_m.group(1)}-01-01" if year_m else None
    docs = split_vu(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_vu.py", date=date, official_identifier=ident,
        document_type=it.get("document_type") or "bill",
        law_status="proposed", is_current=False, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "vu_kind": it.get("kind"),
            "text_extraction": {"source": "official", "backend": backend},
            "tls_policy": "verify_false_live_broken_chain",
            "corpus_note": "bills_only_not_consolidations",
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
    max_seconds = int(os.environ.get("MAX_SECONDS", "10800") or "10800")
    t_start = time.time()
    items = discover()
    items = sorted(items, key=lambda it: (
        0 if it.get("english") else 1,
        0 if it.get("wayback_ts") else 1,
        it.get("url") or "",
    ))
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
        CC, country=COUNTRY, source="Parliament of Vanuatu bills (parliament.gov.vu)",
        source_urls=[PORTAL, BILLS_INDEX],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="parliament-bills-only-thin-consolidations",
        notes=(
            "Official parliament.gov.vu bill PDFs under /images/Bills/. "
            "Consolidations thin — bills only; PacLII Acts not used as primary. "
            "Live TLS may need verify=False; archive_fallbacks of official URLs on fail. "
            "English bills preferred over French Projet de Loi twins. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
