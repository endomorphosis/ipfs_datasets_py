#!/usr/bin/env python3
"""Ghana: Constitution + Acts of Parliament from official hosts.

Official only:
  - Parliament of Ghana https://www.parliament.gh/docs?type=Acts  (public catalog)
  - Judicial Service constitution HTML https://judicial.gov.gh/index.php/the-constitution
  - Act PDFs are served from https://www.parliament.gh/epanel/docs/bills/...
    robots.txt Disallow: /epanel/ — live fetch of that path is skipped.
    archive_fallbacks (Wayback / Common Crawl) of those official PDF URLs only.

Not GhanaLII as primary. Not commercial databases. No WAF bypass.
glc.gov.gh is the General Legal Council (profession regulator), not a general Acts host.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "gh"
COUNTRY = "Ghana"
SOURCE_TYPE = "ghana_official"
LICENSE = (
    "Official texts of the Republic of Ghana as published by Parliament of Ghana "
    "and the Judicial Service. The Ghana Gazette (Ghana Publishing Company) authentic "
    "text prevails. Not legal advice. Not GhanaLII as source of record."
)
UA = DEFAULT_UA + " source=https://www.parliament.gh/"
PARL = "https://www.parliament.gh"
ACTS = f"{PARL}/docs?OT=&type=Acts"
CONST = "https://judicial.gov.gh/index.php/the-constitution"
CONST_FEED = (
    "https://judicial.gov.gh/index.php?option=com_content&view=category"
    "&id=111&format=feed&type=rss"
)
EPANEL = f"{PARL}/epanel/docs/"  # robots Disallow: /epanel/ — archive only
SLEEP = 0.5
log = logging.getLogger("gh")
SHOWPDF = re.compile(r"showPDF\('([^']+)'\s*,\s*'([^']*)'\)")
ART_GH = re.compile(
    r"(?im)^\s*((?:Article|Section|CHAPTER)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
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


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def get_official(url: str, *, timeout=(20, 120), retries: int = 3, allow_epanel_live: bool = False) -> dict:
    if "/epanel/" in url and not allow_epanel_live:
        log.info("robots Disallow /epanel/ — wayback of official URL %s", url)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s — archive of official URL", url, exc)
        res = af.fetch_with_fallbacks(url, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "",
            "content_type": ctype or "application/pdf", "original_url": url,
            "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype):
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 429:
        log.info("HTTP 429 %s — archive_fallbacks", url)
        res = af.fetch_with_fallbacks(url, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and body:
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    res = af.fetch_with_fallbacks(url, try_http=False)
    res.setdefault("retrieval", "archive")
    return res


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def extract_article(html: str) -> str:
    m = re.search(r"<article\b[^>]*>(.*)</article>", html or "", re.I | re.S)
    chunk = m.group(1) if m else (html or "")
    chunk = re.sub(r"<script\b[^>]*>.*?</script>", " ", chunk, flags=re.I | re.S)
    chunk = re.sub(r"<style\b[^>]*>.*?</style>", " ", chunk, flags=re.I | re.S)
    return html_to_text(chunk).strip()


def constitution_chapter_urls() -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for start in range(0, 80, 10):
        u = f"{CONST_FEED}&limitstart={start}&limit=10"
        res = get_official(u)
        html = res.get("text") or ""
        items = re.findall(r"<item>(.*?)</item>", html, re.S)
        if not items:
            break
        for it in items:
            link = re.search(r"<link>(.*?)</link>", it, re.S)
            if not link:
                continue
            href = (link.group(1) or "").strip()
            if "judicial.gov.gh" not in href or href in seen:
                continue
            seen.add(href)
            urls.append(href)
    log.info("judicial constitution chapters n=%s", len(urls))
    return urls


def fetch_constitution_text() -> tuple[str, str, list[str]]:
    chapters = constitution_chapter_urls()
    if not chapters:
        chapters = [CONST, "https://judicial.gov.gh/index.php/preamble"]
    parts: list[tuple[int, str]] = []
    used: list[str] = []
    for href in chapters:
        res = get_official(href)
        html = res.get("text") or ""
        text = extract_article(html)
        if len(text) < 80:
            continue
        if "I accept cookies" in text and "CHAPTER" not in text and "PREAMBLE" not in text.upper() and "Sovereignty" not in text:
            continue
        m = re.search(r"CHAPTER\s+0*(\d+)", text)
        if m:
            order = int(m.group(1))
        elif re.search(r"PREAMBLE", text, re.I):
            order = 0
        elif re.search(r"FIRST SCHEDULE", text, re.I):
            order = 90
        elif re.search(r"SECOND SCHEDULE", text, re.I):
            order = 91
        else:
            order = 50
        parts.append((order, text))
        used.append(href)
    parts.sort(key=lambda x: x[0])
    # de-dupe identical chapter numbers keeping longest
    best: dict[int, str] = {}
    for order, text in parts:
        if order not in best or len(text) > len(best[order]):
            best[order] = text
    body = "\n\n".join(best[k] for k in sorted(best))
    return body, "live", used


def parse_acts_page(html: str) -> list[dict]:
    items = []
    seen = set()
    for path, title in SHOWPDF.findall(html or ""):
        if not path.lower().startswith("bills/"):
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        pdf_url = EPANEL + path.replace(" ", "%20")
        items.append({
            "url": pdf_url,
            "path": path,
            "title": title or Path(path).stem,
            "kind": "act",
        })
    return items


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 5:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items: list[dict] = [{
        "url": CONST,
        "title": "Constitution of the Republic of Ghana 1992",
        "kind": "constitution",
    }]
    seen = {CONST}
    res = get_official(ACTS)
    html = res.get("text") or ""
    page_items = parse_acts_page(html)
    log.info("parliament acts page n=%s retrieval=%s", len(page_items), res.get("retrieval"))
    for it in page_items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        items.append(it)
    # Wayback of official parliament Act PDFs (not live /epanel/)
    recs = af.search_wayback_machine(
        "https://www.parliament.gh/epanel/docs/bills/",
        match_type="prefix", limit=400,
        extra_filters=["mimetype:application/pdf"],
    )
    log.info("wayback parliament epanel bills cdx=%s", len(recs))
    for rec in recs:
        orig = rec.get("original") or ""
        if "/epanel/docs/bills/" not in orig.lower():
            continue
        if orig in seen:
            continue
        seen.add(orig)
        stem = Path(orig.split("?")[0]).stem.replace("%20", " ")
        items.append({
            "url": orig, "title": stem, "kind": "act",
            "wayback_ts": rec.get("timestamp"), "cdx_original": orig,
        })
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_gh(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_GH.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "gh"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def fetch_one(it: dict, done: set[str]) -> str:
    kind = it.get("kind")
    url = it["url"]
    if kind == "constitution":
        ident = "gh-constitution-1992"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
        text, retrieval, used_urls = fetch_constitution_text()
        if len(text) < 20000:
            log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "constitution_incomplete", "chars": len(text)})
            return "fail"
        rec = base_record(
            cc=CC, country=COUNTRY, language="en", ident=ident,
            title="Constitution of the Republic of Ghana 1992", text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_gh.py", date="1993-01-07",
            official_identifier="Constitution of the Republic of Ghana 1992",
            document_type="constitution", law_status="current", is_current=True,
            documents=split_gh(text, rid, url, "1993-01-07", True),
            extra_meta={
                "discovery": {"method": "judicial_service_constitution_chapters", "chapter_urls": used_urls},
                "retrieval": {"method": retrieval},
                "text_extraction": {"source": "official", "backend": "html-article"},
                "gaps": "Official Judicial Service HTML chapters (Joomla category 111). Authentic Gazette text prevails.",
            },
        )
        rec["id"] = rid
        write_instrument(CC, rec)
        done.add(rid)
        return "ok"
    ident = "gh-act-" + re.sub(r"[^a-zA-Z0-9]+", "-", Path(it.get("path") or url).stem)[:80]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    res = get_official(url)
    body = res.get("content") or b""
    retrieval = res.get("retrieval") or res.get("method") or "archive"
    used = res.get("final_url") or res.get("wayback_url") or url
    text = ""
    if body[:4] == b"%PDF":
        text = pdf_to_text(body)
    elif res.get("text"):
        text = html_to_text(res.get("text") or "")
    if len(text) < 120:
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "empty_pdf"})
        return "fail"
    title = it.get("title") or ident
    head = text[:2000]
    m = re.search(r"(?im)^(AN ACT[^\n]+|[A-Z][A-Za-z0-9 ,.'()]{8,140} ACT,?\s+\d{4})", head)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_gh.py", date=None, official_identifier=title,
        document_type="statute", law_status="current", is_current=True,
        documents=split_gh(text, rid, url, None, False),
        extra_meta={
            "discovery": {"method": "parliament_docs_acts", "cdx_original": it.get("cdx_original")},
            "retrieval": {"method": retrieval, "used_url": used, "robots": "epanel_archive_only"},
            "text_extraction": {"source": "official", "backend": "pdftotext"},
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Constitution from Judicial Service of Ghana official HTML. Acts catalog from "
        "parliament.gh/docs?type=Acts (robots allow /docs; Disallow /epanel/). Act PDF "
        "bodies via Wayback/Common Crawl of official parliament.gh/epanel/docs/bills/ URLs "
        "only (no live /epanel/ crawl). Not GhanaLII. Gazette authentic text (Ghana "
        "Publishing Company) prevails. glc.gov.gh is the General Legal Council, not used "
        "as a general Acts host. " + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="Parliament of Ghana + Judicial Service (official hosts)",
        source_urls=[ACTS, CONST, PARL + "/", "https://ghanapublishing.gov.gh/"],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s", len(items), len(done))
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 10 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
    cov = "partial-official-fulltext"
    if counters["ok"] + counters["skip"] >= 1:
        cov = "official-hosted-snapshot"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s", counters)


if __name__ == "__main__":
    main()
