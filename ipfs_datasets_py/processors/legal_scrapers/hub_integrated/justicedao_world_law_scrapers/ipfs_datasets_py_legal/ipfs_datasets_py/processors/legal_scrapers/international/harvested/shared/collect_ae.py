#!/usr/bin/env python3
"""UAE: Federal laws + Constitution from UAE Legislation.

Official sources only:
  https://uaelegislation.gov.ae  (General Secretariat of the UAE Cabinet)
  List API: POST /en/legislations/list
  Item:     /en/legislations/{id}
  PDF:      /en/legislations/{id}/download
  Constitution id=1000

Federal laws (Federal Law / Federal Decree-Law) first. Cabinet resolutions
and ministerial circulars are out of scope. No commercial compilations.
No WAF bypass.

On HTTP 429/403 of official URLs, archive_fallbacks.py of those URLs only.
"""
from __future__ import annotations

import json
import logging
import re
import time
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ae"
COUNTRY = "United Arab Emirates"
SOURCE_TYPE = "uaelegislation"
LICENSE = (
    "Official UAE Legislation texts (uaelegislation.gov.ae / UAE Cabinet). "
    "Authentic Official Gazette prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://uaelegislation.gov.ae/"
PORTAL = "https://uaelegislation.gov.ae/"
LIST = "https://uaelegislation.gov.ae/en/legislations/list"
BROWSE = "https://uaelegislation.gov.ae/en/legislations"
CONST_ID = "1000"
WORKERS = 3
SLEEP = 0.5
log = logging.getLogger("ae")

FED_RE = re.compile(
    r"Federal(?:\s+Decree[-\s]?Law|\s+Law)\b|^Constitution\b|The Constitution of the United Arab Emirates",
    re.I,
)
SKIP_RE = re.compile(r"Cabinet Resolution|Ministerial|Circular|Administrative Decision", re.I)
ART_AE = re.compile(r"(?im)^\s*((?:Article|المادة)\s+[0-9\u0660-\u0669]+)\b")
ID_RE = re.compile(r"/en/legislations/(\d+)(?:/|$|\?)")


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


def official_get(url: str, *, binary: bool = False, retries: int = 4) -> dict:
    headers = {"Accept": "application/pdf, */*" if binary else "text/html, application/json, */*"}
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=retries, timeout=(20, 90), headers=headers)
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content:
        if binary or not af.is_challenge(r.text or "", r.status_code):
            return {"ok": True, "content": r.content, "text": "" if binary else (r.text or ""),
                    "method": "live", "status": 200}
    if r is not None and r.status_code in (404, 410):
        return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code}
    need = r is None or r.status_code in (429, 403, 503, 502, 504)
    if r is not None and not binary and af.is_challenge(r.text or "", r.status_code):
        need = True
    if need:
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=True, try_archive_is=False)
        if res.get("status") == "success" and (res.get("content") or res.get("text")):
            return {"ok": True, "content": res.get("content") or b"", "text": res.get("text") or "",
                    "method": res.get("method") or "archive", "archive": res}
        return {"ok": False, "error": (res or {}).get("error") or "archive_fail"}
    return {"ok": False, "error": f"http_{getattr(r, 'status_code', 0)}"}


def session_token() -> tuple[object, str]:
    sess = get_session(UA, pool=WORKERS)
    r = sess.get(BROWSE, timeout=(20, 60), headers={"User-Agent": UA, "Accept": "text/html"})
    m = re.search(r'_token:\s*"([^"]+)"', r.text or "")
    token = m.group(1) if m else ""
    # also csrf cookie
    if not token:
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text or "")
        token = m.group(1) if m else ""
    return sess, token


def list_page(sess, token: str, page: int, law_types: list) -> dict:
    payload = {
        "_token": token,
        "page": page,
        "paginateBy": 50,
        "year": None,
        "lawTypes": law_types,
        "subject": "",
    }
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BROWSE,
    }
    time.sleep(SLEEP)
    r = sess.post(LIST, json=payload, headers=headers, timeout=(20, 90))
    if r.status_code in (429, 403, 503):
        log.info("list HTTP %s page=%s — archive not used for POST body", r.status_code, page)
        return {}
    if r.status_code != 200:
        log.info("list HTTP %s page=%s", r.status_code, page)
        return {}
    try:
        return r.json()
    except Exception:
        return {}


def parse_list_payload(js: dict) -> list[dict]:
    items = []
    blob = json.dumps(js, ensure_ascii=False)
    html = js.get("html") or js.get("view") or js.get("content") or ""
    # data array
    data = js.get("data") or js.get("legislations") or js.get("items") or []
    if isinstance(data, dict):
        data = data.get("data") or data.get("items") or []
    if isinstance(data, list):
        for rec in data:
            if not isinstance(rec, dict):
                continue
            lid = rec.get("id") or rec.get("legislation_id") or rec.get("legislationId")
            title = rec.get("title") or rec.get("name") or rec.get("title_en") or ""
            if lid:
                items.append({
                    "id": str(lid),
                    "title": re.sub(r"\s+", " ", str(title)).strip(),
                    "year": rec.get("year") or rec.get("issue_year"),
                    "law_type": rec.get("law_type") or rec.get("type"),
                    "source": "list_json",
                })
    for lid in ID_RE.findall(html + "\n" + blob):
        items.append({"id": lid, "title": "", "source": "list_html"})
    # titles next to ids in HTML
    for lid, title in re.findall(
        r'href="[^"]*/en/legislations/(\d+)[^"]*"[^>]*>\s*([^<]{3,220})\s*<', html
    ):
        items.append({"id": lid, "title": re.sub(r"\s+", " ", title).strip(), "source": "list_anchor"})
    return items


def load_catalog() -> list[dict]:
    p = ROOT / CC / "raw" / "catalog.jsonl"
    if not p.exists() or p.stat().st_size < 50:
        return []
    items, seen = [], set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            lid = str(row.get("id") or "")
            if not lid or lid in seen:
                continue
            seen.add(lid)
            items.append(row)
    return items


def add_item(items, seen, row):
    lid = str(row.get("id") or "")
    if not lid or lid in seen:
        if lid in seen and row.get("title"):
            for it in items:
                if str(it.get("id")) == lid and not it.get("title"):
                    it["title"] = row["title"]
        return
    seen.add(lid)
    row["url"] = f"https://uaelegislation.gov.ae/en/legislations/{lid}"
    row["pdf_url"] = f"https://uaelegislation.gov.ae/en/legislations/{lid}/download"
    items.append(row)
    append_catalog(CC, row)


def is_federal(title: str, lid: str) -> bool:
    if lid == CONST_ID:
        return True
    t = title or ""
    if SKIP_RE.search(t):
        return False
    if not t:
        return True
    if FED_RE.search(t) or "قانون اتحادي" in t or "مرسوم بقانون" in t:
        return True
    # type-2/3/14 catalog ids are federal even when title is Arabic-only
    return True


def discover() -> list[dict]:
    items = load_catalog()
    seen = {str(x.get("id")) for x in items}
    add_item(items, seen, {
        "id": CONST_ID,
        "title": "The Constitution of the United Arab Emirates",
        "kind": "constitution",
        "source": "known",
    })
    if len(items) >= 80:
        log.info("resume catalog %s", len(items))
        return items
    sess, token = session_token()
    if not token:
        log.warning("no csrf token; list API may fail")
    # 14 Constitution, 2 Federal Law, 3 Federal Decree-Law. Type 1 is Cabinet Resolutions.
    for types in ([14], [2], [3]):
        js0 = list_page(sess, token, 1, types)
        total = int(js0.get("total") or 0)
        pages = int(js0.get("pages") or 1)
        log.info("list types=%s total=%s pages=%s", types, total, pages)
        for rec in parse_list_payload(js0):
            add_item(items, seen, rec)
        for p in range(2, min(pages, 40) + 1):
            js = list_page(sess, token, p, types)
            if not js:
                break
            before = len(items)
            for rec in parse_list_payload(js):
                add_item(items, seen, rec)
            log.info("page %s types=%s new_total=%s", p, types, len(items))
            if len(items) == before and p > 2:
                break
        # collect all three federal families
    log.info("discovered %s", len(items))
    return items


def page_title(html: str, fallback: str) -> str:
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"^United Arab Emirates Legislations\s*[|:—-]+\s*", "", t, flags=re.I)
        if t:
            return t
    m = re.search(r"<h1[^>]*>([\s\S]{3,240})</h1>", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        if t:
            return t
    return fallback


def fetch_one(it: dict, done: set[str]) -> str:
    lid = str(it.get("id") or "")
    if not lid:
        return "fail"
    rid = slug_id(CC, f"leg-{lid}")
    if rid in done:
        return "skip"
    url = it.get("url") or f"https://uaelegislation.gov.ae/en/legislations/{lid}"
    pdf_url = it.get("pdf_url") or f"{url}/download"
    page = official_get(url)
    html = page.get("text") or ""
    title = page_title(html, it.get("title") or f"Legislation {lid}")
    if not is_federal(title, lid):
        return "skip"
    text = ""
    backend = page.get("method") or "live"
    pdf = official_get(pdf_url, binary=True)
    if pdf.get("ok"):
        text = pdf_to_text(pdf.get("content") or b"")
        backend = f"pdf-{(pdf.get('method') or 'live')}"
    if len(text) < 80 and html:
        body = html_to_text(html)
        m = re.search(r"(Article\s+1\b|المادة|We, |WE, |The President)", body)
        if m:
            body = body[m.start():]
        if len(body) > len(text):
            text = body
            backend = f"html-{(page.get('method') or 'live')}"
    if len(text) < 80:
        log_failure(CC, {"identifier": lid, "source_url": url, "status": "failed",
                         "reason": "empty_text", "title": title})
        return "fail"
    docs = split_articles(text, rid, url, None)
    if not docs:
        matches = list(ART_AE.finditer(text))
        if len(matches) >= 2:
            docs = []
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                chunk = text[start:end].strip()
                num = re.sub(r"\s+", " ", m.group(1)).strip()
                aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
                docs.append({
                    "id": f"{rid}-{aid}"[:180], "title": chunk.split("\n", 1)[0][:200],
                    "text": chunk, "document_number": num, "source_url": url,
                    "record_type": "article", "article_number": num, "law_identifier": rid,
                    "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
                })
    kind = "constitution" if lid == CONST_ID or re.search(r"Constitution of the United Arab Emirates", title, re.I) else "statute"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=f"leg-{lid}", title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="ae-uaelegislation", date=iso_date(str(it.get("year"))) if it.get("year") else None,
        official_identifier=lid, document_type=kind,
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": "uaelegislation_list", "id": lid, "pdf_url": pdf_url,
                          "retrieval": page.get("method")},
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["languages"] = ["en"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    items = sorted(items, key=lambda x: (0 if str(x.get("id")) == CONST_ID else 1, int(x.get("id") or 0)))
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue %s already=%s", len(items), len(done))
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
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 20 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="UAE Legislation (General Secretariat of the UAE Cabinet)",
                    source_urls=[PORTAL, BROWSE], license_text=LICENSE,
                    discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="Federal laws + Constitution. Not commercial compilations.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "federal-laws snapshot"
    notes = (
        "Federal Law / Federal Decree-Law / Constitution from official "
        "uaelegislation.gov.ae list API and PDF downloads. Cabinet resolutions "
        "excluded. 429/403 uses archive_fallbacks of official URLs. Started "
        f"{t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="UAE Legislation (General Secretariat of the UAE Cabinet)",
        source_urls=[PORTAL, BROWSE, f"https://uaelegislation.gov.ae/en/legislations/{CONST_ID}"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
