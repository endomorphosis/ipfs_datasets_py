#!/usr/bin/env python3
"""Oman: Constitution (Basic Statute) + laws + royal decrees from MJLA.

Official source only:
  https://mjla.gov.om  (Ministry of Justice and Legal Affairs)
  Laws catalog:   /laws/1/page/N  + PDF /modules/laws/download.php?file=ID
  Decrees catalog:/decrees/1/page/N + PDF /modules/decrees/download.php?file=ID
  Basic Statute:  /decrees/1/show/951  (النظام الأساسي للدولة)

qanoon.om is a civil-society compilation, not the MJLA portal — not used.
No commercial DBs. No WAF bypass.
TLS verify=False only after SSLError (missing intermediate; not a WAF bypass).
On HTTP 429/403 of official URLs, archive_fallbacks.py of those URLs only.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
import urllib3
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

urllib3.disable_warnings()

CC = "om"
COUNTRY = "Oman"
SOURCE_TYPE = "mjla_oman"
LICENSE = (
    "Official texts of the Sultanate of Oman as published by the Ministry of "
    "Justice and Legal Affairs (mjla.gov.om). The Official Gazette "
    "(الجريدة الرسمية) prevails over this research snapshot. Not legal advice. "
    "Not qanoon.om / commercial compilations."
)
UA = DEFAULT_UA + " source=https://mjla.gov.om/"
PORTAL = "https://mjla.gov.om/"
CONST_DECREE = "951"
WORKERS = 3
SLEEP = 0.45
log = logging.getLogger("om")
ART_AR = re.compile(
    r"(?im)^\s*((?:المادة|مادة)\s+(?:[0-9\u0660-\u0669]+|الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة|التاسعة|العاشرة))"
)
ID_RE = re.compile(r"(laws|decrees)/ar/1/show/(\d+)")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


class _Tls:
    pass


_tls = _Tls()


def sess() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA, "Accept": "text/html, application/pdf, */*",
            "Accept-Language": "ar,en;q=0.8",
        })
        ad = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _tls.s = s
    return s


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


def official_get(url: str, *, retries: int = 4) -> dict:
    last = None
    for attempt in range(1, retries + 1):
        time.sleep(SLEEP)
        for verify in (True, False):
            try:
                r = sess().get(url, timeout=(20, 90), verify=verify, allow_redirects=True)
            except requests.RequestException as exc:
                last = exc
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(20, 2 ** attempt))
                last = r
                break
            if r.status_code == 200 and r.content:
                text = ""
                if r.content[:4] != b"%PDF":
                    text = r.text or ""
                    if af.is_challenge(text, r.status_code):
                        last = r
                        break
                return {
                    "ok": True, "content": r.content, "text": text,
                    "method": "live", "status": 200, "verify": verify,
                    "final_url": r.url or url,
                }
            if r.status_code in (404, 410):
                return {"ok": False, "error": f"http_{r.status_code}"}
            if r.status_code in (429, 403) or af.is_challenge(r.text or "", r.status_code):
                last = r
                break
            last = r
            break
    if isinstance(last, requests.Response) and last.status_code not in (429, 403, 502, 503, 504):
        return {"ok": False, "error": f"http_{last.status_code}"}
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=True, try_archive_is=False)
    if res.get("status") == "success" and (res.get("text") or res.get("content")):
        return {
            "ok": True, "text": res.get("text") or "",
            "content": res.get("content") or b"",
            "method": res.get("method") or "archive", "archive": res,
            "final_url": res.get("wayback_url") or url,
        }
    err = "archive_fail"
    if isinstance(last, requests.Response):
        err = f"http_{last.status_code}"
    elif last:
        err = str(last)
    return {"ok": False, "error": err}


def split_ar(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_AR.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "om"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


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
            key = f"{row.get('kind')}-{row.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            items.append(row)
    return items


def add_item(items, seen, row: dict):
    key = f"{row.get('kind')}-{row.get('id')}"
    if not row.get("id") or key in seen:
        if key in seen and row.get("title"):
            for it in items:
                if f"{it.get('kind')}-{it.get('id')}" == key and not it.get("title"):
                    it["title"] = row["title"]
        return
    seen.add(key)
    items.append(row)
    append_catalog(CC, row)


def page_title(html: str, fallback: str) -> str:
    # item heading often in h3.card-title or near تحميل
    for pat in (
        r"<h[1-3][^>]*class=\"[^\"]*card-title[^\"]*\"[^>]*>([\s\S]{3,240})</h[1-3]>",
        r"<h1[^>]*>([\s\S]{3,240})</h1>",
        r"<title>\s*([^<]+)",
    ):
        m = re.search(pat, html or "", re.I)
        if m:
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
            t = re.sub(r"^\s*(التشريعات|مكتبة الإصدارات|وزارة العدل)[^|]*\|\s*", "", t)
            if t and t not in ("التشريعات", "مكتبة الإصدارات"):
                return t[:300]
    return fallback


def parse_list(html: str, kind: str) -> list[tuple[str, str]]:
    out, seen = [], set()
    for href, title in re.findall(r'href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', html or ""):
        m = ID_RE.search(href)
        if not m:
            continue
        k, lid = m.group(1), m.group(2)
        if k != kind or lid == "0" or lid in seen:
            continue
        seen.add(lid)
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title)).strip()
        out.append((lid, t))
    return out


def discover() -> list[dict]:
    items = load_catalog()
    seen = {f"{x.get('kind')}-{x.get('id')}" for x in items}
    add_item(items, seen, {
        "id": CONST_DECREE, "kind": "constitution",
        "title": "النظام الأساسي للدولة",
        "url": urljoin(PORTAL, f"decrees/1/show/{CONST_DECREE}"),
        "pdf_url": f"https://www.mjla.gov.om/modules/decrees/download.php?file={CONST_DECREE}",
        "source": "known_constitution",
    })
    n_dec = sum(1 for x in items if x.get("kind") == "decree")
    if n_dec >= 80:
        log.info("resume catalog %s decrees=%s", len(items), n_dec)
        return items
    # laws first (in-force statutes)
    for page in range(1, 12):
        url = urljoin(PORTAL, f"laws/1/page/{page}" if page > 1 else "laws/1")
        got = official_get(url)
        if not got.get("ok"):
            log.info("laws page %s fail %s", page, got.get("error"))
            break
        found = parse_list(got.get("text") or "", "laws")
        before = len(items)
        for lid, title in found:
            if lid == CONST_DECREE:
                continue
            add_item(items, seen, {
                "id": lid, "kind": "law", "title": title,
                "url": urljoin(PORTAL, f"laws/ar/1/show/{lid}/"),
                "pdf_url": f"https://www.mjla.gov.om/modules/laws/download.php?file={lid}",
                "source": f"laws_p{page}",
            })
        log.info("laws page %s new=%s total=%s", page, len(items) - before, len(items))
        if not found:
            break
    # royal decrees
    for page in range(1, 70):
        url = urljoin(PORTAL, f"decrees/1/page/{page}" if page > 1 else "decrees/1")
        got = official_get(url)
        if not got.get("ok"):
            log.info("decrees page %s fail %s", page, got.get("error"))
            break
        found = parse_list(got.get("text") or "", "decrees")
        before = len(items)
        for lid, title in found:
            kind = "constitution" if lid == CONST_DECREE else "decree"
            add_item(items, seen, {
                "id": lid, "kind": kind, "title": title,
                "url": urljoin(PORTAL, f"decrees/ar/1/show/{lid}/"),
                "pdf_url": f"https://www.mjla.gov.om/modules/decrees/download.php?file={lid}",
                "source": f"decrees_p{page}",
            })
        log.info("decrees page %s new=%s total=%s", page, len(items) - before, len(items))
        if not found:
            break
    log.info("discovered %s", len(items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    lid = str(it.get("id") or "")
    kind = it.get("kind") or "law"
    if not lid:
        return "fail"
    ident = "constitution-basic-statute" if kind == "constitution" else f"{kind}-{lid}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    page_url = it.get("url") or urljoin(PORTAL, f"{'decrees' if kind != 'law' else 'laws'}/ar/1/show/{lid}/")
    pdf_url = it.get("pdf_url") or (
        f"https://www.mjla.gov.om/modules/{'decrees' if kind != 'law' else 'laws'}/download.php?file={lid}"
    )
    page = official_get(page_url)
    html = page.get("text") or ""
    title = page_title(html, it.get("title") or f"{kind} {lid}")
    text = ""
    backend = page.get("method") or "live"
    used = page.get("final_url") or page_url
    pdf = official_get(pdf_url)
    body = pdf.get("content") or b""
    if pdf.get("ok") and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        backend = f"pdf-{(pdf.get('method') or 'live')}"
        used = pdf.get("final_url") or pdf_url
    if len(text) < 80 and html:
        body_txt = html_to_text(html)
        m = re.search(r"(المادة|مادة|مرسوم سلطاني|النظام الأساسي|نحن )", body_txt)
        if m:
            body_txt = body_txt[m.start():]
        if len(body_txt) > len(text):
            text = body_txt
            backend = f"html-{(page.get('method') or 'live')}"
            used = page_url
    if len(text) < 80:
        log_failure(CC, {"identifier": lid, "source_url": page_url, "status": "failed",
                         "reason": "empty_text", "title": title})
        return "fail"
    date = None
    ym = re.search(r"(20\d{2}|19\d{2})\s*/\s*(\d+)", title)
    if ym:
        date = f"{ym.group(1)}-01-01"
    docs = split_ar(text, rid, used, date)
    doc_type = "constitution" if kind == "constitution" or "النظام الأساسي" in (title or "") else (
        "statute" if kind == "law" or "قانون" in (title or "") else "decree"
    )
    rec = base_record(
        cc=CC, country=COUNTRY, language="ar", ident=ident, title=title,
        text=text, source_url=page_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_om.py", date=date, official_identifier=lid,
        document_type=doc_type, law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": it.get("source") or "mjla", "id": lid, "kind": kind,
                          "pdf_url": pdf_url, "retrieval": page.get("method")},
            "retrieval": {"method": backend.split("-")[-1] if "-" in backend else backend,
                          "used_url": used, "backend": backend},
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["languages"] = ["ar"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    items = sorted(items, key=lambda x: (
        0 if x.get("kind") == "constitution" else 1 if x.get("kind") == "law" else 2,
        -int(x.get("id") or 0),
    ))
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
            if n % 25 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="Ministry of Justice and Legal Affairs (mjla.gov.om)",
                    source_urls=[PORTAL, urljoin(PORTAL, "laws/1"), urljoin(PORTAL, "decrees/1")],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="National laws + Basic Statute first, then royal decrees. Not qanoon.om.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "national-laws snapshot"
    notes = (
        "In-force laws and royal decrees from official mjla.gov.om. "
        "النظام الأساسي للدولة (decree 951) included as Constitution. "
        "qanoon.om is not the official MJLA portal and was not used. "
        "TLS verify=False only after SSLError (missing intermediate; not WAF bypass). "
        f"429/403 uses archive_fallbacks of official URLs. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Ministry of Justice and Legal Affairs (mjla.gov.om / Official Gazette)",
        source_urls=[PORTAL, urljoin(PORTAL, "laws/1"), urljoin(PORTAL, "decrees/1"),
                     urljoin(PORTAL, f"decrees/1/show/{CONST_DECREE}")],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
