#!/usr/bin/env python3
"""South Africa: national Acts and Constitution from the official gov.za portal.

Official sources only:
  - https://www.gov.za/documents/acts
  - https://www.gov.za/documents/constitution/constitution-republic-south-africa-1996-04-feb-1997

Does NOT use SAFLII as source of record (unofficial). Does not use Sabinet.
PDFs are downloaded from gov.za /sites/default/files/gcis_document/. Honor robots.txt
(search/ is disallowed; /documents/acts is allowed). No WAF bypass.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "za"
COUNTRY = "South Africa"
SOURCE_TYPE = "govza_acts"
LICENSE = (
    "Official texts published by the Government of the Republic of South Africa "
    "(GCIS / www.gov.za). Copyright in state publications is administered under "
    "South African law; the authentic Government Gazette / signed Act prevails. "
    "Not legal advice. This snapshot is not SAFLII."
)
UA = DEFAULT_UA + " source=https://www.gov.za/documents/acts"
PORTAL = "https://www.gov.za"
ACTS = f"{PORTAL}/documents/acts"
CONSTITUTION = f"{PORTAL}/documents/constitution/constitution-republic-south-africa-1996-04-feb-1997"
CONSTITUTION_HUB = f"{PORTAL}/documents/constitution/constitution-republic-south-africa-04-feb-1997"
WORKERS = 8
SLEEP = 0.35
log = logging.getLogger("za")

ACT_NUM = re.compile(r"(?i)\bAct\s+(\d+)\s+of\s+(\d{4})")
ART_ZA = re.compile(
    r"(?im)^\s*((?:Section|Sec\.?|CHAPTER|Chapter)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
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


def split_custom(pattern, text, law_id, source_url, date):
    if not text or len(text) < 40:
        return []
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading, "text": chunk, "date_filed": date,
            "document_number": num, "source_url": source_url, "record_type": "article",
            "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=120,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def get_html(url: str) -> tuple[int, str, bytes, str]:
    r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4)
    body = r.content or b""
    text = ""
    ctype = (r.headers.get("content-type") or "").lower()
    if "html" in ctype or "xml" in ctype or "text/" in ctype or not ctype:
        text = body.decode(r.encoding or "utf-8", "replace")
    if r.status_code == 200 and text and af.is_challenge(text, r.status_code):
        wb = af.get_wayback_content(url)
        if wb.get("status") == "success":
            return 200, wb.get("text") or "", wb.get("content") or b"", wb.get("wayback_url") or url
    return r.status_code, text, body, r.url or url


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog_acts.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 200:
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


def parse_listing(html: str) -> list[dict]:
    items = []
    seen = set()
    for href, title in re.findall(
        r'href="(/documents/acts/[^"#?]+)"[^>]*>(.*?)</a>', html, re.I | re.S
    ):
        title = re.sub(r"<[^>]+>", " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        url = urljoin(PORTAL, href)
        m = ACT_NUM.search(title) or ACT_NUM.search(href.replace("-", " "))
        items.append({
            "url": url,
            "title": title,
            "act_number": m.group(1) if m else None,
            "year": m.group(2) if m else None,
            "kind": "act",
        })
    return items


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 500:
        log.info("resume catalog n=%s", len(existing))
        return existing
    status, html, _, _ = get_html(ACTS)
    if status != 200 or not html:
        raise RuntimeError(f"acts listing HTTP {status}")
    last = 0
    m = re.search(r'pager__item--last.*?page=(\d+)', html, re.S)
    if m:
        last = int(m.group(1))
    pages = sorted(set(int(x) for x in re.findall(r'[?&]page=(\d+)', html)))
    if pages:
        last = max(last, max(pages))
    log.info("acts listing last_page=%s", last)
    items: list[dict] = []
    seen = set()

    def add_page(html_page: str) -> int:
        n = 0
        for it in parse_listing(html_page):
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            items.append(it)
            n += 1
        return n

    add_page(html)
    # remaining pages
    def fetch_page(p: int) -> tuple[int, str]:
        st, body, _, _ = get_html(f"{ACTS}?page={p}")
        return p, body if st == 200 else ""

    with ThreadPoolExecutor(max_workers=min(8, max(1, last))) as ex:
        futs = [ex.submit(fetch_page, p) for p in range(1, last + 1)]
        for fut in as_completed(futs):
            p, body = fut.result()
            n = add_page(body) if body else 0
            if p % 10 == 0 or p == last:
                log.info("listing page=%s new=%s total=%s", p, n, len(items))
    save_catalog(items)
    log.info("catalog acts n=%s", len(items))
    return items


def pick_pdf(html: str, page_url: str) -> Optional[str]:
    hrefs = re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I)
    prefer = []
    for h in hrefs:
        h = h.replace("&amp;", "&")
        url = urljoin(page_url, h)
        if "gcis_document" in url or "/sites/default/files" in url:
            prefer.append(url)
    return (prefer or hrefs and [urljoin(page_url, hrefs[0].replace("&amp;", "&"))] or [None])[0]


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    num = it.get("act_number")
    year = it.get("year")
    ident = f"za-act-{year}-{num}" if num and year else url
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    try:
        st, html, _, final = get_html(url)
    except Exception as exc:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": repr(exc)})
        return "fail"
    if st != 200 or not html:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": f"http_{st}"})
        return "fail"
    title = it.get("title") or ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if h1:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h1.group(1))).strip() or title
    date = None
    dm = re.search(r"(\d{1,2}\s+\w+\s+\d{4})|(\d{4}-\d{2}-\d{2})", html)
    if dm:
        date = iso_date(dm.group(2) or "")
    pdf_url = pick_pdf(html, final)
    text = ""
    method = "html"
    if pdf_url:
        pr = http_get(pdf_url, ua=UA, sleep=SLEEP, timeout=(20, 120), retries=4)
        if pr.status_code == 200 and pr.content and pr.content[:4] == b"%PDF":
            text = pdf_to_text(pr.content)
            method = "pdf"
        elif pr.status_code != 200 or not (pr.content and pr.content[:4] == b"%PDF"):
            wb = af.get_wayback_content(pdf_url)
            if wb.get("status") == "success" and (wb.get("content") or b"")[:4] == b"%PDF":
                text = pdf_to_text(wb["content"])
                method = "pdf_wayback"
    if not text or len(text) < 80:
        text = html_to_text(html)
        method = "html"
    if not text or len(text) < 80:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    docs = split_custom(ART_ZA, text, rid, pdf_url or url, date)
    if not docs:
        docs = split_articles(text, rid, pdf_url or url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title or ident,
        text=text, source_url=pdf_url or url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="collect_govza_acts.py", date=date,
        official_identifier=f"Act {num} of {year}" if num and year else ident,
        document_type="statute", law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": "govza_acts_listing", "page_url": url},
            "text_extraction": {"source": "official", "backend": method},
            "pdf_url": pdf_url,
        },
        extra_fields={"canonical_document_url": pdf_url or url, "information_url": url},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def fetch_constitution(done: set[str]) -> str:
    ident = "za-constitution-1996"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    st, html, _, final = get_html(CONSTITUTION)
    if st != 200 or not html:
        st, html, _, final = get_html(CONSTITUTION_HUB)
    if st != 200 or not html:
        wb = af.get_wayback_content(CONSTITUTION)
        html = wb.get("text") or ""
        final = wb.get("wayback_url") or CONSTITUTION
    pdf_url = pick_pdf(html, final) if html else None
    text = ""
    if pdf_url:
        pr = http_get(pdf_url, ua=UA, sleep=SLEEP, timeout=(20, 120), retries=4)
        if pr.status_code == 200 and pr.content[:4] == b"%PDF":
            text = pdf_to_text(pr.content)
    if not text:
        # also try known official PDF on gov.za
        for cand in (
            "https://www.gov.za/sites/default/files/images/a108-96.pdf",
            pdf_url,
        ):
            if not cand:
                continue
            pr = http_get(cand, ua=UA, sleep=SLEEP, timeout=(20, 120), retries=3)
            if pr.status_code == 200 and pr.content[:4] == b"%PDF":
                text = pdf_to_text(pr.content)
                pdf_url = cand
                break
            wb = af.get_wayback_content(cand)
            if wb.get("status") == "success" and (wb.get("content") or b"")[:4] == b"%PDF":
                text = pdf_to_text(wb["content"])
                pdf_url = cand
                break
    if not text or len(text) < 200:
        text = html_to_text(html)
    if not text or len(text) < 200:
        log_failure(CC, {"id": rid, "url": CONSTITUTION, "status": "failed", "reason": "constitution_empty"})
        return "fail"
    docs = split_custom(ART_ZA, text, rid, pdf_url or CONSTITUTION, "1997-02-04")
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident,
        title="Constitution of the Republic of South Africa, 1996",
        text=text, source_url=pdf_url or CONSTITUTION, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="collect_govza_acts.py", date="1997-02-04",
        official_identifier="Constitution of the Republic of South Africa, 1996",
        document_type="constitution", law_status="current", is_current=True, documents=docs,
        extra_meta={"discovery": {"method": "govza_constitution"}},
        extra_fields={"eli": None, "information_url": CONSTITUTION},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    source_urls = [ACTS, CONSTITUTION, CONSTITUTION_HUB]
    notes = (
        "National Acts listed on www.gov.za/documents/acts plus the Constitution "
        "HTML/PDF on gov.za. SAFLII is not used as source of record. Full text "
        "from official GCIS PDFs (pdftotext) with Wayback of official gov.za URLs "
        "if live fetch fails. Amendment Acts are separate listing rows as published."
    )

    def write_progress(coverage: str, extra: str = ""):
        write_summary(
            CC, country=COUNTRY,
            source="South African Government (www.gov.za) Acts and Constitution",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items) + 1, fetched=counters["ok"], skipped=counters["skip"],
            failed=counters["fail"], coverage=coverage, notes=notes + extra,
        )

    done = existing_ids(CC)
    try:
        st = fetch_constitution(done)
        counters[st] = counters.get(st, 0) + 1
        log.info("constitution %s", st)
    except Exception as exc:
        counters["fail"] += 1
        log_failure(CC, {"id": "za-constitution-1996", "status": "failed", "reason": repr(exc)})
    log.info("queue acts=%s already_done=%s", len(items), len(done))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            counters[st] = counters.get(st, 0) + 1
            if n % 40 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), counters["ok"], counters["skip"], counters["fail"])
                write_progress("catalog-backed incomplete")
    cov = "full" if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items) else "catalog-backed incomplete"
    write_progress(cov, extra=f" Started {t0}.")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", counters["ok"], counters["skip"], counters["fail"], cov)


if __name__ == "__main__":
    main()
