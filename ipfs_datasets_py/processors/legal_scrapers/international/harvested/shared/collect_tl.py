#!/usr/bin/env python3
"""Timor-Leste: Jornal da República Serie I/II PDFs (mj.gov.tl/jornal).

Official only:
  https://www.mj.gov.tl/jornal/
  Serie I index ?q=node/27 ; Serie II ?q=node/28
  PDFs under /jornal/public/docs/{YYYY}/serie_{1|2}/…

Honor robots.txt Crawl-delay: 10. No WAF bypass. Not legal advice.
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

CC = "tl"
COUNTRY = "Timor-Leste"
SOURCE_TYPE = "mj_gov_tl_jornal"
LICENSE = (
    "Official texts of the Democratic Republic of Timor-Leste as published in the "
    "Jornal da República (Ministry of Justice, mj.gov.tl/jornal). The authentic "
    "gazette text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.mj.gov.tl/jornal/"
BASE = "https://www.mj.gov.tl/jornal/"
SERIE_I = urljoin(BASE, "?q=node/27")
SERIE_II = urljoin(BASE, "?q=node/28")
# robots Crawl-delay: 10
SLEEP = float(os.environ.get("SLEEP", "10.0"))
MIN_TEXT = 80
log = logging.getLogger("tl")

ART_TL = re.compile(
    r"(?im)^\s*((?:Artigo|Art\.|ARTICLE|Article|Capítulo|CAPÍTULO|Secção|Secao)\s+[\dIVXLCDMºª°]+[A-Za-z]?)\b"
)
PDF_HREF = re.compile(r'(?:href=["\']([^"\']+\.pdf)["\']|(public/docs/[^"\'<>\s]+\.pdf)|((?:files/)[^"\'<>\s]+\.pdf))', re.I)
NODE_RE = re.compile(r'[?&]q=node/(\d+)')


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


def polite_get(url: str, *, timeout=(20, 120), retries: int = 3):
    return http_get(
        url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries,
        headers={"Accept": "text/html,application/pdf,*/*", "Referer": BASE},
    )


def abs_pdf(href: str) -> Optional[str]:
    if not href:
        return None
    href = href.split("#")[0].strip()
    if href.startswith("http"):
        url = href
    else:
        # paths are relative to /jornal/
        url = urljoin(BASE, href.lstrip("/"))
        if "/jornal/jornal/" in url:
            url = url.replace("/jornal/jornal/", "/jornal/")
    if "mj.gov.tl" not in url.lower():
        return None
    return url


def extract_pdfs(html: str) -> list[str]:
    found = []
    for m in PDF_HREF.finditer(html or ""):
        href = m.group(1) or m.group(2) or m.group(3)
        url = abs_pdf(href)
        if url:
            found.append(url)
    return found


def title_from_url(url: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    return re.sub(r"[_-]+", " ", stem).strip()[:240] or "Jornal"


def classify(url: str) -> tuple[str, str]:
    low = url.lower()
    if "constituicao" in low or "constitui" in low:
        return "constitution", "constitution"
    if "codigo" in low or "código" in low:
        return "code", "statute"
    if "/serie_1/" in low or "serie_i" in low:
        return "serie_i", "gazette"
    if "/serie_2/" in low or "serie_ii" in low:
        return "serie_ii", "gazette"
    return "instrument", "statute"


def _normalize_catalog(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("url"):
            continue
        if it.get("identifier") and it.get("kind"):
            out.append(it)
            continue
        url = it["url"]
        stem = Path(unquote(url.split("?")[0])).stem[:160]
        ident = it.get("identifier") or it.get("doc_id") or stem
        kind, doc_type = classify(url)
        if it.get("document_type") == "constitution":
            kind, doc_type = "constitution", "constitution"
        elif it.get("document_type"):
            doc_type = it["document_type"]
        lang = "tet" if "tetum" in url.lower() else "pt"
        out.append({
            "url": url,
            "title": it.get("title") or title_from_url(url),
            "identifier": ident,
            "kind": kind,
            "document_type": doc_type,
            "language": lang,
            "series": it.get("series"),
        })
    return out


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 80 and all(
        isinstance(x, dict) and x.get("url") and (x.get("identifier") or x.get("doc_id")) for x in existing[:5]
    ):
        norm = _normalize_catalog(existing)
        log.info("resume catalog n=%s (normalized)", len(norm))
        return norm
    seed_nodes = {"27", "28"}  # serie indexes
    # Also fetch home for constitution/codes
    pages = [BASE, SERIE_I, SERIE_II]
    node_html: dict[str, str] = {}
    for url in pages:
        try:
            r = polite_get(url)
        except Exception as exc:
            log.warning("seed fail %s: %s", url, exc)
            continue
        if r.status_code == 200 and r.text:
            node_html[url] = r.text
            for nid in NODE_RE.findall(r.text):
                seed_nodes.add(nid)
            log.info("seed %s nodes_so_far=%s pdfs=%s", url, len(seed_nodes), len(extract_pdfs(r.text)))
    # Walk category nodes (bounded)
    max_nodes = int(os.environ.get("TL_MAX_NODES", "80") or "80")
    for nid in sorted(seed_nodes, key=lambda x: int(x))[:max_nodes]:
        url = urljoin(BASE, f"?q=node/{nid}")
        if url in node_html:
            continue
        try:
            r = polite_get(url)
        except Exception as exc:
            log.warning("node %s fail: %s", nid, exc)
            continue
        if r.status_code == 200 and r.text:
            node_html[url] = r.text
            log.info("node %s pdfs=%s", nid, len(set(extract_pdfs(r.text))))
    items, seen = [], set()
    for html in node_html.values():
        for url in extract_pdfs(html):
            if url in seen:
                continue
            seen.add(url)
            kind, doc_type = classify(url)
            stem = Path(unquote(url.split("?")[0])).stem[:160]
            lang = "tet" if "tetum" in url.lower() else "pt"
            items.append({
                "url": url,
                "title": title_from_url(url),
                "identifier": stem,
                "kind": kind,
                "document_type": doc_type,
                "language": lang,
            })
    save_catalog(items)
    log.info("catalog n=%s unique_pdfs", len(items))
    return items


def get_bytes(url: str) -> tuple[bytes, str]:
    try:
        r = polite_get(url, timeout=(20, 180), retries=3)
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


def split_tl(text: str, law_id: str, source_url: str) -> list[dict]:
    docs, _ = honest_split(CC, text, law_id, source_url)
    if docs:
        return docs
    docs = split_articles(text, law_id, source_url)
    if len(docs) >= 2:
        return docs
    return split_by_pattern(text, law_id, source_url, ART_TL, "article")


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
    text, backend, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="por+eng", ocr_max_pages=50)
    if len(text) < MIN_TEXT:
        # fallback eng-only OCR
        text2, backend2, pages = extract_pdf_text(body, enable_ocr=True, ocr_lang="eng", ocr_max_pages=40)
        if len(text2) > len(text):
            text, backend = text2, backend2
    if len(text) < MIN_TEXT:
        log_failure(CC, {"id": rid, "url": url, "reason": f"empty_text backend={backend}"})
        return "fail"
    title = it.get("title") or title_from_url(url)
    lang = it.get("language") or "pt"
    year_m = re.search(r"/(20\d{2}|19\d{2})/", url)
    date = f"{year_m.group(1)}-01-01" if year_m else None
    docs = split_tl(text, rid, url)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_tl.py", date=date, official_identifier=ident,
        document_type=it.get("document_type") or "gazette",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "retrieval": method, "pdf_pages": pages, "jornal_kind": it.get("kind"),
            "text_extraction": {"source": "official", "backend": backend},
            "robots_crawl_delay_s": SLEEP,
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    log.info("ok %s kind=%s method=%s chars=%s", rid[:70], it.get("kind"), method, len(text))
    return "ok"


def main():
    setup()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "0") or "0")
    max_seconds = int(os.environ.get("MAX_SECONDS", "14400") or "14400")
    t_start = time.time()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for it in items:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            log.info("time budget exhausted")
            break
        status = fetch_one(it, done)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skip += 1
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Jornal da República (mj.gov.tl/jornal)",
        source_urls=[BASE, SERIE_I, SERIE_II],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="jornal-serie-i-ii-pdfs",
        notes=(
            "Serie I/II PDFs + constitution/codes from official mj.gov.tl/jornal. "
            f"Honored robots Crawl-delay ≥{SLEEP}s. Portuguese primary; Tetum when published. "
            "Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(items))


if __name__ == "__main__":
    main()
