#!/usr/bin/env python3
"""FSM (Micronesia): Congress Public Law PDFs (cfsm.gov.fm).

Official only:
  https://www.cfsm.gov.fm/fsm-congress-public-laws/
  Session pages e.g. /24th-public-laws/, /23rd-cfsm-public-laws/, …

Wave1 prefers recent Congresses (24th/23rd…). No PacLII. Not legal advice.
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

CC = "fm"
COUNTRY = "Federated States of Micronesia"
SOURCE_TYPE = "cfsm_gov_fm_public_laws"
LICENSE = (
    "Official Public Laws of the Congress of the Federated States of Micronesia "
    "as published on cfsm.gov.fm. The authentic official text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.cfsm.gov.fm/"
HUB = "https://www.cfsm.gov.fm/fsm-congress-public-laws/"
SLEEP = float(os.environ.get("SLEEP", "0.55"))
MIN_TEXT = 80
log = logging.getLogger("fm")
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|PART|Part|SCHEDULE|Schedule)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'href=["\']([^"\']+\.pdf)["\']', re.I)
# Prefer recent congresses first; env FM_SESSIONS can override (comma URLs)
DEFAULT_SESSIONS = [
    "https://www.cfsm.gov.fm/24th-public-laws/",
    "https://www.cfsm.gov.fm/23rd-cfsm-public-laws/",
    "https://www.cfsm.gov.fm/22nd-public-laws/",
    "https://www.cfsm.gov.fm/21st-cfsm-public-laws/",
    "https://www.cfsm.gov.fm/20th-cfsm-public-laws/",
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
    return re.sub(r"\s+", " ", stem).strip()[:240] or "Public Law"


def session_list() -> list[str]:
    env = os.environ.get("FM_SESSIONS", "").strip()
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    return list(DEFAULT_SESSIONS)


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 150:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items, seen = [], set()
    for page in session_list():
        try:
            r = http_get(
                page, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=3,
                headers={"Accept": "text/html,*/*", "Referer": HUB},
            )
        except Exception as exc:
            log.error("session fail %s: %s", page, exc)
            continue
        if r.status_code != 200 or not r.text:
            log.error("session HTTP %s %s", r.status_code, page)
            continue
        n_before = len(items)
        for href in PDF_HREF.findall(r.text):
            url = urljoin(page, href.split("#")[0])
            if "cfsm.gov.fm" not in url.lower():
                continue
            if "PUBLIC-LAW" not in url.upper() and "public-law" not in url.lower() and "PUBLIC_LAW" not in url.upper():
                # still accept congress law PDFs under uploads
                if "/wp-content/uploads/" not in url.lower():
                    continue
            if url in seen:
                continue
            seen.add(url)
            title = title_from_url(url)
            ident = Path(unquote(url.split("?")[0])).stem[:160]
            items.append({
                "url": url, "title": title, "identifier": ident,
                "kind": "public_law", "session": page,
            })
        log.info("session %s +%s total=%s", page.rstrip("/").rsplit("/", 1)[-1], len(items) - n_before, len(items))
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def get_bytes(url: str) -> tuple[bytes, str]:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=3,
            headers={"Accept": "application/pdf,*/*", "Referer": HUB},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live"
    res = af.fetch_with_fallbacks(url, try_http=False)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        return body, res.get("method") or "archive"
    return b"", "failed"


def split_fm(text: str, law_id: str, source_url: str) -> list[dict]:
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
    body, method = get_bytes(url)
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
    docs = split_fm(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_fm.py", date=date, official_identifier=ident,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "session": it.get("session"),
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
        CC, country=COUNTRY, source="Congress of the FSM Public Laws (cfsm.gov.fm)",
        source_urls=[HUB] + session_list()[:3],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="cfsm-public-laws-recent-congresses",
        notes=(
            "Public Law PDFs from official cfsm.gov.fm Congress session pages. "
            "Not PacLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
