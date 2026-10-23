#!/usr/bin/env python3
"""Palau: RPPL / presidential legislations from palaugov.pw.

Official only:
  https://www.palaugov.pw/document-category/rppls/
  https://www.palaugov.pw/document-category/presidential-legislations/
  PDFs under https://www.palaugov.pw/wp-content/uploads/…

Live egress often hits SiteGround sgcaptcha (HTTP 202). No captcha solve / WAF
bypass — on challenge use archive_fallbacks of the same official palaugov.pw
URLs only (Wayback / Common Crawl), parallel to collect_to.py. Not legal advice.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, split_by_pattern

CC = "pw"
COUNTRY = "Palau"
SOURCE_TYPE = "palaugov_pw"
LICENSE = (
    "Official Republic of Palau Public Laws (RPPL) and presidential legislations "
    "as published on palaugov.pw. The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.palaugov.pw/"
PORTAL = "https://www.palaugov.pw/"
SLEEP = float(os.environ.get("SLEEP", "0.6"))
MIN_TEXT = 80
log = logging.getLogger("pw")

INDEX_URLS = [
    "https://www.palaugov.pw/document-category/rppls/",
    "https://www.palaugov.pw/document-category/presidential-legislations/",
    "https://palaugov.pw/document-category/rppls/",
    "https://palaugov.pw/document-category/presidential-legislations/",
]

ART_PW = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|CHAPTER|Chapter|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)
SGCAPTCHA_RE = re.compile(r"sgcaptcha|well-known/sgcaptcha", re.I)
# Legislation PDFs only — skip forms, notices, timesheets, etc.
LEGIS_NAME_RE = re.compile(
    r"(rppl|presidential[-_ ]?proclamation|presidential[-_ ]?directive|"
    r"executive[-_ ]?order|public[-_ ]?law|\bpl[-_ ]?\d)",
    re.I,
)
SKIP_NAME_RE = re.compile(
    r"(timesheet|affidavit|payroll|passport|leave-form|notice-pcs|"
    r"15-day-notice|job[-_ ]?vacancy|flyer|brochure|budget[-_ ]?hearing)",
    re.I,
)


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


def is_sgcaptcha(status: int, body: bytes, text: str = "") -> bool:
    if status in (202, 403, 429, 503):
        blob = (text or "") + (body[:4000].decode("utf-8", "replace") if body else "")
        if SGCAPTCHA_RE.search(blob) or status == 202:
            return True
    if text and SGCAPTCHA_RE.search(text[:8000]):
        return True
    return False


def official_url(url: str) -> str:
    u = url.strip()
    u = re.sub(r":80/", "/", u)  # CDX sometimes embeds :80
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin("https://www.palaugov.pw/", u.lstrip("/"))
    u = u.replace("http://www.palaugov.pw", "https://www.palaugov.pw")
    u = u.replace("http://palaugov.pw", "https://www.palaugov.pw")
    u = u.replace("https://palaugov.pw", "https://www.palaugov.pw")
    u = re.sub(r"https?://(?:www\.)?palaugov\.pw:80/", "https://www.palaugov.pw/", u)
    u = u.replace("https://www.palaugov.pw:80/", "https://www.palaugov.pw/")
    m = re.search(r"https?://(?:www\.)?palaugov\.pw/[^\s\"'<>]+", u)
    if m:
        u = m.group(0)
        u = u.replace("http://", "https://").replace("https://palaugov.pw", "https://www.palaugov.pw")
    return u.split("#")[0]


def live_get(url: str, *, timeout=(20, 120), retries: int = 2):
    try:
        return http_get(
            url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries,
            headers={"Accept": "text/html,application/pdf,*/*", "Referer": PORTAL},
        )
    except Exception as exc:
        log.info("live exception %s: %s", url, exc)
        return None


def get_html(url: str) -> tuple[str, str]:
    official = official_url(url)
    r = live_get(official)
    if r is not None:
        text = ""
        ctype = (r.headers.get("content-type") or "").lower()
        if r.content and ("html" in ctype or "text/" in ctype or not ctype) and r.content[:4] != b"%PDF":
            text = r.content.decode(r.encoding or "utf-8", "replace")
        if r.status_code == 200 and text and not is_sgcaptcha(r.status_code, r.content, text) and not af.is_challenge(text, r.status_code):
            return text, "live"
        if is_sgcaptcha(r.status_code, r.content or b"", text):
            log.info("sgcaptcha on %s — archive_fallbacks of official URL", official)
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
        text = ""
        if r.content and r.content[:4] != b"%PDF":
            text = r.content[:4000].decode("utf-8", "replace")
        if is_sgcaptcha(r.status_code, r.content or b"", text):
            log.info("sgcaptcha PDF %s — archive", official)
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


def is_legislation_pdf(url: str) -> bool:
    name = Path(unquote(url.split("?")[0])).name
    if SKIP_NAME_RE.search(name):
        return False
    return bool(LEGIS_NAME_RE.search(name) or LEGIS_NAME_RE.search(url))


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = stem.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip()[:240] or "Palau instrument"


def kind_from_url(url: str) -> tuple[str, str]:
    low = url.lower()
    name = Path(unquote(url.split("?")[0])).name.lower()
    if "rppl" in name or "public-law" in name or re.search(r"\bpl[-_]?\d", name):
        return "rppl", "statute"
    if "executive-order" in name or "executive_order" in name:
        return "executive_order", "executive_order"
    if "presidential" in name:
        return "presidential", "presidential_instrument"
    return "legislation", "statute"


def add_pdf(items: dict, url: str, *, source: str, wayback_ts: str | None = None) -> None:
    url = official_url(url)
    if "palaugov.pw" not in url.lower():
        return
    if ".pdf" not in url.lower():
        return
    if not is_legislation_pdf(url):
        return
    path = unquote(url.split("?")[0])
    stem = Path(path).stem
    key = stem.lower()
    kind, doc_type = kind_from_url(url)
    cand = {
        "url": url, "title": title_from_url(url), "identifier": stem[:160],
        "source": source, "kind": kind, "document_type": doc_type,
        "wayback_ts": wayback_ts,
    }
    prev = items.get(key)
    if prev is None or (wayback_ts and not prev.get("wayback_ts")) or (
        wayback_ts and prev.get("wayback_ts") and wayback_ts > prev["wayback_ts"]
    ):
        if prev and prev.get("wayback_ts") and not wayback_ts:
            cand["wayback_ts"] = prev.get("wayback_ts")
        items[key] = cand


def discover_from_html(html: str, base: str, items: dict, source: str) -> None:
    for href in PDF_HREF.findall(html or ""):
        url = urljoin(base, href.split("#")[0])
        add_pdf(items, url, source=source)
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or ""):
        if not href or href.startswith("#") or "javascript:" in href.lower():
            continue
        full = official_url(urljoin(base, href))
        if "palaugov.pw" not in full.lower():
            continue
        if "/document/" in full.lower() or "/document-category/" in full.lower():
            items.setdefault(("__page__", full.lower()), {"url": full, "kind": "page", "title": full})


def discover_cdx(items: dict) -> None:
    limit = int(os.environ.get("PW_CDX_LIMIT", "800") or "800")
    recs = af.search_wayback_machine(
        "www.palaugov.pw/wp-content/uploads/",
        match_type="prefix",
        limit=limit,
        extra_filters=["mimetype:application/pdf"],
    )
    # also bare palaugov.pw host
    recs2 = af.search_wayback_machine(
        "palaugov.pw/wp-content/uploads/",
        match_type="prefix",
        limit=limit,
        extra_filters=["mimetype:application/pdf"],
    )
    all_recs = recs + recs2
    log.info("cdx uploads pdfs raw=%s", len(all_recs))
    kept = 0
    for rec in all_recs:
        orig = rec.get("original") or ""
        if orig and is_legislation_pdf(orig):
            add_pdf(items, orig, source="cdx", wayback_ts=rec.get("timestamp") or None)
            kept += 1
    log.info("cdx legislation-ish kept≈%s catalog_keys=%s", kept, len(items))


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 30:
        log.info("resume catalog n=%s", len(existing))
        return existing
    bag: dict = {}
    pages_to_fetch = list(INDEX_URLS)
    fetched_pages = set()
    for url in pages_to_fetch:
        if url in fetched_pages:
            continue
        fetched_pages.add(url)
        html, method = get_html(url)
        log.info("index %s method=%s bytes=%s", url, method, len(html or ""))
        if not html:
            continue
        discover_from_html(html, url, bag, method)
    child_pages = [
        v["url"] for k, v in list(bag.items())
        if isinstance(k, tuple) and k[0] == "__page__" and v.get("kind") == "page"
    ]
    for k in [k for k in bag if isinstance(k, tuple) and k[0] == "__page__"]:
        del bag[k]
    max_children = int(os.environ.get("PW_MAX_CHILD_PAGES", "30") or "30")
    for url in child_pages[:max_children]:
        if url in fetched_pages:
            continue
        fetched_pages.add(url)
        html, method = get_html(url)
        if html:
            discover_from_html(html, url, bag, method)
            log.info("child %s method=%s pdfs_so_far=%s", url[-60:], method, len(bag))
    discover_cdx(bag)
    items = [v for k, v in bag.items() if not (isinstance(k, tuple) and k[0] == "__page__")]
    # Prefer RPPL first
    items.sort(key=lambda it: (0 if it.get("kind") == "rppl" else 1, it.get("url") or ""))
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_pw(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_PW, "section")


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
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=40)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    year_m = re.search(r"/(20\d{2}|19\d{2})/", url) or re.search(r"(20\d{2}|19\d{2})", title)
    date = None
    if year_m:
        y = year_m.group(0).strip("/")
        if re.match(r"^\d{4}$", y):
            date = f"{y}-01-01"
    docs = split_pw(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_pw.py", date=date, official_identifier=ident,
        document_type=it.get("document_type") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "pw_kind": it.get("kind"),
            "text_extraction": {"source": "official", "backend": backend},
            "sgcaptcha_policy": "archive_fallbacks_of_official_urls_only",
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
        0 if it.get("kind") == "rppl" else 1,
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
        CC, country=COUNTRY, source="Palau Government (palaugov.pw) RPPL / presidential legislations",
        source_urls=[PORTAL] + INDEX_URLS[:2],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="palaugov-rppl-presidential-archive-backed",
        notes=(
            "Official palaugov.pw RPPL and presidential-legislation PDFs under wp-content/uploads. "
            "Live SiteGround sgcaptcha (HTTP 202) from this egress — no captcha solve; "
            "archive_fallbacks of official palaugov.pw URLs only (Wayback/CC). Not PacLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
