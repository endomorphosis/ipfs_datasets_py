#!/usr/bin/env python3
"""Maldives: Gazette laws/regulations + GCS PDFs; optional mvlaw.gov.mv.

Official only:
  https://www.gazette.gov.mv/  (types: gaanoonu laws, gavaaidhu regulations, …)
  https://storage.googleapis.com/gazette.gov.mv/docs/gazette/{id}.pdf
  https://mvlaw.gov.mv/       (AG legislation portal; secondary PDF links)

Primary harvest: gaanoonu + gavaaidhu (+ other gazette types when listed).
No WAF bypass. Not legal advice.
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

CC = "mv"
COUNTRY = "Maldives"
SOURCE_TYPE = "gazette_gov_mv"
LICENSE = (
    "Official Gazette of the Republic of Maldives (gazette.gov.mv) and Attorney "
    "General legislation portal (mvlaw.gov.mv). The authentic gazette text prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.gazette.gov.mv/"
GAZETTE = "https://www.gazette.gov.mv/"
GCS_TMPL = "https://storage.googleapis.com/gazette.gov.mv/docs/gazette/{id}.pdf"
MVLAW = "https://mvlaw.gov.mv/"
SLEEP = float(os.environ.get("SLEEP", "0.5"))
MIN_TEXT = 60
# Primary instrument types (Dhivehi romanization used by portal)
TYPES = [
    ("gaanoonu", "law"),
    ("gavaaidhu", "regulation"),
    ("garaaru", "regulation"),
    ("usoolu", "instrument"),
    ("tax-ruling", "instrument"),
]
log = logging.getLogger("mv")
ART_MV = re.compile(
    r"(?im)^\s*((?:Section|Article|CHAPTER|Chapter|Regulation|Part)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
ITEM_RE = re.compile(
    r'href="https?://(?:www\.)?gazette\.gov\.mv/gazette/(\d+)"\s+title="([^"]*)"',
    re.I,
)
ITEM_RE2 = re.compile(
    r'href="(/gazette/(\d+))"\s+title="([^"]*)"',
    re.I,
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)


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


def guess_lang(title: str) -> str:
    if re.search(r"[\u0780-\u07bf]", title or ""):
        return "dv"
    return "en"


def get_bytes(url: str) -> tuple[bytes, str]:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
            headers={"Accept": "application/pdf,*/*", "Referer": GAZETTE},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live"
    # GCS 404/410: object never published — skip slow archive/CC fan-out
    if r is not None and r.status_code in (404, 410):
        log.info("live %s %s — no archive retry", r.status_code, url.split("/")[-1])
        return b"", "failed"
    # Official GCS PDFs are rarely in CC; prefer Wayback/archive.is only
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False, try_archive_is=True)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def parse_listing(html: str, gtype: str, doc_type: str) -> list[dict]:
    titles: dict[str, str] = {}
    for gid, title in ITEM_RE.findall(html or ""):
        titles[gid] = (title or "").strip()
    for _href, gid, title in ITEM_RE2.findall(html or ""):
        titles.setdefault(gid, (title or "").strip())
    # Also capture title= before/after bare paths
    for m in re.finditer(
        r'gazette\.gov\.mv/gazette/(\d+)["\']\s+title=["\']([^"\']*)["\']',
        html or "", re.I,
    ):
        titles.setdefault(m.group(1), m.group(2).strip())
    out, seen = [], set()
    for gid in re.findall(r'/gazette/(\d+)', html or ""):
        if gid in seen:
            continue
        seen.add(gid)
        title = titles.get(gid) or f"Gazette {gid}"
        out.append({
            "id": gid,
            "title": title,
            "url": GCS_TMPL.format(id=gid),
            "canonical_url": f"https://www.gazette.gov.mv/gazette/{gid}",
            "gazette_type": gtype,
            "document_type": doc_type,
            "kind": "gazette",
            "language": guess_lang(title),
        })
    return out


def discover_gazette() -> list[dict]:
    items: list[dict] = []
    seen_ids: set[str] = set()
    for gtype, doc_type in TYPES:
        empty = 0
        for page in range(1, 80):
            url = f"https://www.gazette.gov.mv/gazette?type={gtype}&page={page}"
            try:
                r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 60), retries=3)
            except Exception as exc:
                log.warning("list fail %s: %s", url, exc)
                empty += 1
                if empty >= 3:
                    break
                continue
            if r.status_code != 200 or not r.text:
                empty += 1
                if empty >= 3:
                    break
                continue
            batch = parse_listing(r.text, gtype, doc_type)
            if not batch:
                empty += 1
                if empty >= 2:
                    break
                continue
            empty = 0
            added = 0
            for it in batch:
                if it["id"] in seen_ids:
                    continue
                seen_ids.add(it["id"])
                items.append(it)
                added += 1
            log.info("type=%s page=%s batch=%s added=%s total=%s", gtype, page, len(batch), added, len(items))
            if added == 0 and page > 1:
                empty += 1
                if empty >= 2:
                    break
    return items


def discover_mvlaw() -> list[dict]:
    out = []
    try:
        r = http_get(MVLAW, ua=UA, sleep=SLEEP, timeout=(20, 60), retries=3)
    except Exception as exc:
        log.info("mvlaw home fail: %s", exc)
        return out
    if r.status_code != 200 or not r.text:
        return out
    for href in PDF_HREF.findall(r.text):
        url = urljoin(MVLAW, href.split("#")[0])
        if "mvlaw.gov.mv" not in url.lower() and "gazette.gov.mv" not in url.lower() and "googleapis.com" not in url.lower():
            continue
        stem = Path(unquote(url.split("?")[0])).stem[:160]
        out.append({
            "id": f"mvlaw-{stem}",
            "title": stem.replace("-", " ").replace("_", " "),
            "url": url,
            "canonical_url": url,
            "gazette_type": "mvlaw",
            "document_type": "statute",
            "kind": "mvlaw",
            "language": "dv",
        })
    log.info("mvlaw pdfs=%s", len(out))
    return out


def discover() -> list[dict]:
    existing = load_catalog()
    # Require our schema (id + kind); ignore prior stub catalogs with doc_id only
    if existing and len(existing) >= 200 and all(
        isinstance(x, dict) and x.get("id") and x.get("url") and x.get("kind") for x in existing[:5]
    ):
        log.info("resume catalog n=%s", len(existing))
        return existing
    items = discover_gazette()
    # secondary: mvlaw homepage PDFs not already covered
    seen_urls = {it["url"] for it in items}
    for it in discover_mvlaw():
        if it["url"] in seen_urls:
            continue
        items.append(it)
        seen_urls.add(it["url"])
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_mv(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_MV, "section")


def fetch_one(it: dict, done: set[str]) -> str:
    gid = str(it.get("id") or "")
    ident = f"mv-gazette-{gid}" if it.get("kind") == "gazette" else f"mv-{gid}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = it["url"]
    body, method = get_bytes(url)
    if body[:4] != b"%PDF":
        log_failure(CC, {"id": rid, "url": url, "reason": f"not_pdf method={method}"})
        return "fail"
    text, backend, pages = extract_pdf_text(
        body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=40,
    )
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or ident
    lang = it.get("language") or guess_lang(title)
    source_url = it.get("canonical_url") or url
    docs = split_mv(text, rid, source_url)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_mv.py", official_identifier=ident,
        document_type=it.get("document_type") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "pdf_url": url,
            "gazette_type": it.get("gazette_type"),
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    log.info("ok %s type=%s method=%s chars=%s", rid[:60], it.get("gazette_type"), method, len(text))
    return "ok"


def main():
    setup()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "0") or "0")
    max_seconds = int(os.environ.get("MAX_SECONDS", "10800") or "10800")
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
        CC, country=COUNTRY, source="Maldives Gazette + mvlaw.gov.mv",
        source_urls=[GAZETTE, MVLAW, "https://storage.googleapis.com/gazette.gov.mv/docs/gazette/"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="gazette-gaanoonu-gavaaidhu-and-related",
        notes=(
            "Gazette PDFs via official GCS store. Types: gaanoonu (laws), gavaaidhu "
            "(regulations), garaaru, usoolu, tax-ruling. mvlaw.gov.mv homepage PDFs as secondary. "
            "Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
