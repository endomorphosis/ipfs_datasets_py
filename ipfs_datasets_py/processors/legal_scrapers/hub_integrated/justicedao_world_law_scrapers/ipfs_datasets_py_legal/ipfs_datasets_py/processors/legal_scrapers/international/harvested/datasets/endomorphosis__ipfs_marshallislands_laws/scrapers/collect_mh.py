#!/usr/bin/env python3
"""Marshall Islands: Nitijela Acts from rmiparliament.org (iLAWS).

Official only:
  https://rmiparliament.org/cms/
  https://rmiparliament.org/cms/legislation/acts-of-nitijela/…
  PDFs under https://rmiparliament.org/cms/images/LEGISLATION/…

Live egress often hits SiteGround sgcaptcha (HTTP 202). No captcha solve / WAF
bypass — on challenge use archive_fallbacks of the same official
rmiparliament.org URLs only (Wayback / Common Crawl), parallel to collect_to.py.
Not legal advice. Not PacLII.
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

CC = "mh"
COUNTRY = "Marshall Islands"
SOURCE_TYPE = "rmiparliament_ilaws"
LICENSE = (
    "Official Acts of the Nitijela (Parliament of the Marshall Islands) as published "
    "on rmiparliament.org. The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://rmiparliament.org/cms/"
PORTAL = "https://rmiparliament.org/cms/"
SLEEP = float(os.environ.get("SLEEP", "0.6"))
MIN_TEXT = 80
log = logging.getLogger("mh")

INDEX_URLS = [
    "https://rmiparliament.org/cms/",
    "https://rmiparliament.org/cms/legislation/acts-of-nitijela/by-alphabetical-order.html",
    "https://rmiparliament.org/cms/legislation/acts-of-nitijela/by-year.html",
    "https://www.rmiparliament.org/cms/legislation/acts-of-nitijela/by-alphabetical-order.html",
]

ART_MH = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|CHAPTER|Chapter|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
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
    u = url.strip()
    u = re.sub(r":80/", "/", u)  # CDX sometimes embeds :80 on http URLs
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin("https://rmiparliament.org/", u.lstrip("/"))
    u = u.replace("http://www.rmiparliament.org", "https://rmiparliament.org")
    u = u.replace("https://www.rmiparliament.org", "https://rmiparliament.org")
    u = u.replace("http://rmiparliament.org", "https://rmiparliament.org")
    m = re.search(r"https?://(?:www\.)?rmiparliament\.org/[^\s\"'<>]+", u)
    if m:
        u = m.group(0).replace("http://", "https://").replace("https://www.", "https://")
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


def prefer_english(url: str) -> bool:
    name = Path(unquote(url.split("?")[0])).name.lower()
    if name.endswith("x.pdf") and not name.endswith("ex.pdf"):
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
    if "rmiparliament.org" not in url.lower():
        return
    if ".pdf" not in url.lower():
        return
    if "filenotavailable" in url.lower():
        return
    if "/cms/images/LEGISLATION/" not in url and "/cms/images/legislation/" not in url.lower():
        # still allow if clearly legislation path
        if "/LEGISLATION/" not in url:
            return
    path = unquote(url.split("?")[0])
    parent = str(Path(path).parent)
    stem = Path(path).stem
    base = re.sub(r"_\d+x?$", "", stem, flags=re.I)
    key = (parent.lower(), base.lower())
    cand = {
        "url": url, "title": title_from_url(url), "identifier": stem[:160],
        "source": source, "kind": "act", "wayback_ts": wayback_ts,
        "document_type": "statute",
    }
    if "/GAZETTE" in path.upper() or "/gazettes/" in path.lower():
        cand["kind"] = "gazette"
        cand["document_type"] = "gazette"
    elif "/AMENDING/" in path:
        cand["kind"] = "amendment"
    prev = items.get(key)
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
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or ""):
        if not href or href.startswith("#") or "javascript:" in href.lower():
            continue
        full = official_url(urljoin(base, href))
        if "rmiparliament.org" not in full.lower():
            continue
        if "/legislation/" in full.lower() and full.endswith((".html", "/")):
            items.setdefault(("__page__", full.lower()), {"url": full, "kind": "page", "title": full})


def discover_cdx(items: dict) -> None:
    limit = int(os.environ.get("MH_CDX_LIMIT", "600") or "600")
    for prefix in (
        "rmiparliament.org/cms/images/LEGISLATION/PRINCIPAL/",
        "rmiparliament.org/cms/images/LEGISLATION/",
    ):
        recs = af.search_wayback_machine(
            prefix, match_type="prefix", limit=limit,
            extra_filters=["mimetype:application/pdf"],
        )
        log.info("cdx %s pdfs=%s", prefix[-40:], len(recs))
        for rec in recs:
            orig = rec.get("original") or ""
            if orig:
                add_pdf(items, orig, source="cdx", wayback_ts=rec.get("timestamp") or None)


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 40:
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
        if html:
            discover_from_html(html, url, bag, method)
    child_pages = [
        v["url"] for k, v in list(bag.items())
        if isinstance(k, tuple) and k[0] == "__page__" and v.get("kind") == "page"
    ]
    for k in [k for k in bag if isinstance(k, tuple) and k[0] == "__page__"]:
        del bag[k]
    max_children = int(os.environ.get("MH_MAX_CHILD_PAGES", "30") or "30")
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
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_mh(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_MH, "section")


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
    year_m = re.search(r"/(19|20)\d{2}/", url) or re.search(r"(19|20)\d{2}", title)
    date = None
    if year_m:
        y = year_m.group(0).strip("/")
        if re.match(r"^\d{4}$", y):
            date = f"{y}-01-01"
    docs = split_mh(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_mh.py", date=date, official_identifier=ident,
        document_type=it.get("document_type") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "mh_kind": it.get("kind"),
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
        0 if "/PRINCIPAL/" in (it.get("url") or "") else 1,
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
        CC, country=COUNTRY, source="Nitijela Acts (rmiparliament.org/cms)",
        source_urls=[PORTAL] + INDEX_URLS[:2],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="rmiparliament-acts-archive-backed",
        notes=(
            "Official rmiparliament.org Nitijela Acts under /cms/images/LEGISLATION/. "
            "Live SiteGround sgcaptcha (HTTP 202) from this egress — no captcha solve; "
            "archive_fallbacks of official rmiparliament.org URLs only. Not PacLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
