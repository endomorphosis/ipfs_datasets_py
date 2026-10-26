#!/usr/bin/env python3
"""Tonga: Acts / gazettes from Attorney General’s Office (ago.gov.to/cms).

Official only:
  https://ago.gov.to/cms/
  https://ago.gov.to/cms/legislation/…
  PDFs under https://ago.gov.to/cms/images/LEGISLATION/…

Live egress often hits SiteGround sgcaptcha (HTTP 202). No captcha solve / WAF
bypass — on challenge use archive_fallbacks of the same official ago.gov.to URLs
only (Wayback / Common Crawl), parallel to kz 429 handling. Not legal advice.
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

CC = "to"
COUNTRY = "Tonga"
SOURCE_TYPE = "ago_gov_to_cms"
LICENSE = (
    "Official Laws of Tonga / Government Gazettes as published by the Attorney "
    "General's Office (ago.gov.to). The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://ago.gov.to/cms/"
PORTAL = "https://ago.gov.to/cms/"
SLEEP = float(os.environ.get("SLEEP", "0.6"))
MIN_TEXT = 80
log = logging.getLogger("to")

INDEX_URLS = [
    "https://ago.gov.to/cms/",
    "https://ago.gov.to/cms/legislation/current-revised-edition.html",
    "https://ago.gov.to/cms/legislation/current-revised-edition.html?view=acts_alpha",
    "https://ago.gov.to/cms/legislation/current-revised-edition/by-title.html",
    "https://ago.gov.to/cms/legislation/current-revised-edition/by-category.html",
    "https://ago.gov.to/cms/legislation/acts-by-year.html",
    "https://ago.gov.to/cms/legislation/gazettes/gazettes-by-year.html",
    "https://ago.gov.to/cms/legislation/regs-made-by-year.html",
]

ART_TO = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)
SGCAPTCHA_RE = re.compile(r"sgcaptcha|well-known/sgcaptcha", re.I)


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
    """Normalize to https://ago.gov.to/..."""
    u = url.strip()
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin("https://ago.gov.to/", u.lstrip("/"))
    u = u.replace("http://ago.gov.to", "https://ago.gov.to")
    # strip wayback wrapper if any leaked in
    m = re.search(r"https?://ago\.gov\.to/[^\s\"'<>]+", u)
    if m:
        u = m.group(0)
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
    """Return (html, method). On sgcaptcha → archive of official URL only."""
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
    # Direct wayback replay of known good timestamps as last resort for indexes
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
    # Prefer timestamped Wayback replay of the official URL (no captcha solve)
    for ts in (wayback_ts, None):
        wb = af.get_wayback_content(official, timestamp=ts)
        body = wb.get("content") or b""
        if wb.get("status") == "success" and body[:4] == b"%PDF":
            return body, "wayback"
    # Avoid per-URL CC fan-out (slow / empty for ago.gov.to); try archive.is last
    res = af.fetch_with_fallbacks(official, try_http=False, try_cc=False, try_archive_is=True)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def prefer_english(url: str) -> bool:
    """Tongan language PDFs often end with x.pdf (e.g. Lao…_3x.pdf)."""
    name = Path(unquote(url.split("?")[0])).name.lower()
    if name.endswith("x.pdf") and not name.endswith("ex.pdf"):
        # e.g. something_3x.pdf
        if re.search(r"\d+x\.pdf$", name) or name.endswith("_x.pdf"):
            return False
    if "filenotavailable" in name:
        return False
    return True


def revision_score(url: str) -> tuple:
    name = Path(unquote(url.split("?")[0])).stem
    m = re.search(r"_(\d+)$", name)
    rev = int(m.group(1)) if m else 0
    eng = 1 if prefer_english(url) else 0
    principal = 1 if "/PRINCIPAL/" in url else 0
    return (eng, principal, rev, len(name))


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = re.sub(r"_\d+$", "", stem)
    stem = stem.replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip()[:240] or "Act"


def add_pdf(items: dict, url: str, *, source: str, wayback_ts: str | None = None) -> None:
    url = official_url(url)
    if "ago.gov.to" not in url.lower():
        return
    if ".pdf" not in url.lower():
        return
    if "filenotavailable" in url.lower():
        return
    # collapse by directory+base without revision suffix / language twin
    path = unquote(url.split("?")[0])
    # group key: folder + base name without _N / _Nx
    parent = str(Path(path).parent)
    stem = Path(path).stem
    base = re.sub(r"_\d+x?$", "", stem, flags=re.I)
    base = re.sub(r"x$", "", base) if base.lower().endswith("x") and len(base) > 3 else base
    key = (parent.lower(), base.lower())
    prev = items.get(key)
    cand = {"url": url, "title": title_from_url(url), "identifier": stem[:160], "source": source, "kind": "act", "wayback_ts": wayback_ts}
    if "/GAZETTE" in path.upper() or "/gazettes/" in path.lower():
        cand["kind"] = "gazette"
        cand["document_type"] = "gazette"
    elif "/AMENDING/" in path:
        cand["kind"] = "amendment"
        cand["document_type"] = "statute"
    else:
        cand["document_type"] = "statute"
    if prev is None or revision_score(url) > revision_score(prev["url"]) or (
        revision_score(url) == revision_score(prev["url"]) and wayback_ts and not prev.get("wayback_ts")
    ):
        if prev and prev.get("wayback_ts") and not wayback_ts:
            cand["wayback_ts"] = prev.get("wayback_ts")
        items[key] = cand


def discover_from_html(html: str, base: str, items: dict, source: str) -> None:
    for href in PDF_HREF.findall(html or ""):
        url = urljoin(base, href.split("#")[0])
        add_pdf(items, url, source=source)
    # year / gazette subpages
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or ""):
        if not href or href.startswith("#") or "javascript:" in href.lower():
            continue
        full = official_url(urljoin(base, href))
        if "ago.gov.to" not in full.lower():
            continue
        if "/legislation/" in full.lower() and full.endswith((".html", "/")):
            # record for second-pass crawl
            items.setdefault(("__page__", full.lower()), {"url": full, "kind": "page", "title": full})


def discover_cdx(items: dict) -> None:
    limit = int(os.environ.get("TO_CDX_LIMIT", "800") or "800")
    recs = af.search_wayback_machine(
        "ago.gov.to/cms/images/LEGISLATION/",
        match_type="prefix",
        limit=limit,
        extra_filters=["mimetype:application/pdf"],
    )
    log.info("cdx LEGISLATION pdfs=%s", len(recs))
    for rec in recs:
        orig = rec.get("original") or ""
        if orig:
            add_pdf(items, orig, source="cdx", wayback_ts=rec.get("timestamp") or None)


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 50:
        log.info("resume catalog n=%s", len(existing))
        return existing
    bag: dict = {}
    # Live or archive HTML indexes
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
        # follow a bounded set of year/gazette child pages discovered
    child_pages = [
        v["url"] for k, v in list(bag.items())
        if isinstance(k, tuple) and k[0] == "__page__" and v.get("kind") == "page"
    ]
    for k in [k for k in bag if isinstance(k, tuple) and k[0] == "__page__"]:
        del bag[k]
    max_children = int(os.environ.get("TO_MAX_CHILD_PAGES", "40") or "40")
    for url in child_pages[:max_children]:
        if url in fetched_pages:
            continue
        fetched_pages.add(url)
        html, method = get_html(url)
        if html:
            discover_from_html(html, url, bag, method)
            log.info("child %s method=%s pdfs_so_far=%s", url[-60:], method, len(bag))
    # CDX sweep of official LEGISLATION PDF tree
    discover_cdx(bag)
    # drop page markers if any remain
    items = [v for k, v in bag.items() if not (isinstance(k, tuple) and k[0] == "__page__")]
    # Prefer English: already scored in add_pdf
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_to(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_TO, "section")


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
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=50)
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    lang = "to" if not prefer_english(url) else "en"
    year_m = re.search(r"/(19|20)\d{2}/", url) or re.search(r"(19|20)\d{2}", title)
    date = None
    if year_m:
        y = year_m.group(0).strip("/")
        if re.match(r"^\d{4}$", y):
            date = f"{y}-01-01"
    docs = split_to(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_to.py", date=date, official_identifier=ident,
        document_type=it.get("document_type") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "ago_kind": it.get("kind"),
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
    items = sorted(items, key=lambda it: (0 if it.get("wayback_ts") else 1, it.get("url") or ""))
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
        CC, country=COUNTRY, source="AGO Laws of Tonga (ago.gov.to/cms)",
        source_urls=[PORTAL] + INDEX_URLS[:4],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="ago-cms-acts-archive-backed",
        notes=(
            "Official ago.gov.to Acts/gazettes. Live SiteGround sgcaptcha (HTTP 202) "
            "from this egress — no captcha solve; archive_fallbacks of official URLs only "
            "(Wayback/CC of ago.gov.to/cms/images/LEGISLATION/). English PRINCIPAL preferred "
            "over Tongan _x twins when both exist. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
