#!/usr/bin/env python3
"""Qatar: in-force national laws from Al-Meezan (official legal portal).

Official sources only:
  https://www.almeezan.qa  (Qatari Legal Portal / Ministry of Justice)
  Catalog: LawsByYear.aspx?year=YYYY
  Item:    LawPage.aspx?id=N
  Text:    LawView.aspx?opt&LawID=N&language=ar  (authentic Arabic)
  Constitution typically LawPage id=2284 (Permanent Constitution 2004)

Arabic is authentic. English pages are translations when present.
TLS intermediate may be missing; verify=False after SSLError (not a WAF bypass).
No commercial DBs. No WAF bypass.

On HTTP 429/403 of official URLs, archive_fallbacks.py of those URLs only.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

urllib3.disable_warnings()

CC = "qa"
COUNTRY = "Qatar"
SOURCE_TYPE = "almeezan"
LICENSE = (
    "Official Al-Meezan texts (almeezan.qa / State of Qatar). Authentic Official "
    "Gazette prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.almeezan.qa/"
PORTAL = "https://www.almeezan.qa/"
WORKERS = 3
SLEEP = 0.5
CONST_ID = "2284"
log = logging.getLogger("qa")

LAW_ID_RE = re.compile(r"Law(?:Page|View)\.aspx\?[^\"']*id=(\d+)", re.I)
ART_QA = re.compile(r"(?im)^\s*((?:Article|المادة)\s+[0-9\u0660-\u0669]+)\b")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def qa_session() -> requests.Session:
    s = getattr(_tls_qa, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "text/html, */*", "Accept-Language": "ar,en;q=0.8"})
        ad = HTTPAdapter(pool_connections=6, pool_maxsize=6, max_retries=0)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _tls_qa.s = s
    return s


class _Tls:
    pass


_tls_qa = _Tls()


def qa_get(url: str, retries: int = 4) -> dict:
    last = None
    for attempt in range(1, retries + 1):
        time.sleep(SLEEP)
        for verify in (True, False):
            try:
                r = qa_session().get(url, timeout=(20, 90), verify=verify, allow_redirects=True)
            except requests.RequestException as exc:
                last = exc
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(20, 2 ** attempt))
                last = r
                break
            if r.status_code == 200 and r.content:
                text = r.text or ""
                if not af.is_challenge(text, r.status_code):
                    return {"ok": True, "text": text, "content": r.content, "method": "live",
                            "status": 200, "verify": verify}
            if r.status_code in (404, 410):
                return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code}
            if r.status_code in (429, 403) or af.is_challenge(r.text or "", r.status_code):
                last = r
                break
            last = r
            break
    # archive of official URL
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=True, try_archive_is=False)
    if res.get("status") == "success" and (res.get("text") or res.get("content")):
        return {"ok": True, "text": res.get("text") or "", "content": res.get("content") or b"",
                "method": res.get("method") or "archive", "archive": res}
    err = "archive_fail"
    if isinstance(last, requests.Response):
        err = f"http_{last.status_code}"
    elif last:
        err = str(last)
    return {"ok": False, "error": err}


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


def add_item(items, seen, lid: str, title: str = "", year: Optional[str] = None, source: str = ""):
    lid = str(lid)
    if not lid or lid in seen:
        if lid in seen and title:
            for it in items:
                if str(it.get("id")) == lid and not it.get("title"):
                    it["title"] = title
        return
    seen.add(lid)
    row = {
        "id": lid,
        "title": title,
        "year": year,
        "url": f"https://www.almeezan.qa/LawPage.aspx?id={lid}&language=ar",
        "view_url": f"https://www.almeezan.qa/LawView.aspx?opt&LawID={lid}&language=ar",
        "source": source,
    }
    items.append(row)
    append_catalog(CC, row)


def parse_law_ids(html: str) -> list[tuple[str, str]]:
    out = []
    seen = set()
    for href, title in re.findall(r'href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', html or ""):
        m = LAW_ID_RE.search(href) or re.search(r"[?&](?:LawID|id)=(\d+)", href, re.I)
        if not m:
            continue
        lid = m.group(1)
        if lid in seen:
            continue
        # skip cancelled-laws portal chrome
        if "CancelledLaws" in href:
            continue
        seen.add(lid)
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title)).strip()
        out.append((lid, t))
    return out


def discover() -> list[dict]:
    items = load_catalog()
    seen = {str(x.get("id")) for x in items}
    add_item(items, seen, CONST_ID, "الدستور الدائم لدولة قطر", "2004", "known_constitution")
    if len(items) >= 80:
        log.info("resume catalog %s", len(items))
        return items
    # year index (sidebar historically 1961–2014; also try through current year)
    index = qa_get("https://www.almeezan.qa/LawsByYear.aspx?language=ar")
    years = set(re.findall(r"[?&]year=(\d{4})", index.get("text") or "", re.I))
    for y in range(1961, 2027):
        years.add(str(y))
    for y in sorted(years):
        url = f"https://www.almeezan.qa/LawsByYear.aspx?year={y}&language=ar"
        got = qa_get(url, retries=3)
        if not got.get("ok"):
            log.info("year %s fail %s", y, got.get("error"))
            continue
        found = parse_law_ids(got.get("text") or "")
        before = len(items)
        for lid, title in found:
            if lid == CONST_ID or lid == "2284":
                add_item(items, seen, lid, title or "الدستور الدائم لدولة قطر", y, "year")
                continue
            add_item(items, seen, lid, title, y, "year")
        if found:
            log.info("year %s new=%s total=%s", y, len(items) - before, len(items))
    # subject index as a second official catalog
    sub = qa_get("https://www.almeezan.qa/LawsBySubject.aspx?language=ar", retries=3)
    if sub.get("ok"):
        for lid, title in parse_law_ids(sub.get("text") or ""):
            add_item(items, seen, lid, title, None, "subject")
        # subject entry pages
        hrefs = re.findall(r'href=["\']([^"\']*LawsBySubject\.aspx[^"\']+)["\']', sub.get("text") or "", re.I)
        for href in list(dict.fromkeys(hrefs))[:80]:
            u = urljoin(PORTAL, href)
            if "language=" not in u:
                u += ("&" if "?" in u else "?") + "language=ar"
            g = qa_get(u, retries=2)
            if not g.get("ok"):
                continue
            for lid, title in parse_law_ids(g.get("text") or ""):
                add_item(items, seen, lid, title, None, "subject")
    log.info("discovered %s", len(items))
    return items


def page_title(html: str, fallback: str) -> str:
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"^\s*(الميزان|Al-?Meezan)\s*[-|:]*\s*", "", t, flags=re.I)
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
    rid = slug_id(CC, f"law-{lid}")
    if rid in done:
        return "skip"
    view = it.get("view_url") or f"https://www.almeezan.qa/LawView.aspx?opt&LawID={lid}&language=ar"
    page = it.get("url") or f"https://www.almeezan.qa/LawPage.aspx?id={lid}&language=ar"
    got = qa_get(view)
    html = got.get("text") or ""
    method = got.get("method") or "live"
    used = view
    if not got.get("ok") or len(html) < 400:
        got2 = qa_get(page)
        if got2.get("ok") and len(got2.get("text") or "") > len(html):
            html = got2.get("text") or ""
            method = got2.get("method") or method
            used = page
    if len(html) < 200:
        log_failure(CC, {"identifier": lid, "source_url": view, "status": "failed",
                         "reason": got.get("error") or "empty_html"})
        return "fail"
    title = page_title(html, it.get("title") or f"قانون {lid}")
    text = html_to_text(html)
    for needle in ("المادة 1", "مادة (1)", "Article 1", "الباب الأول", "الفصل الأول"):
        idx = text.find(needle)
        if idx > 0 and idx < 4000:
            text = text[idx:]
            break
    if len(text) < 80:
        log_failure(CC, {"identifier": lid, "source_url": used, "status": "failed",
                         "reason": "empty_text", "title": title})
        return "fail"
    date = iso_date(f"{it['year']}-01-01") if it.get("year") else None
    docs = split_articles(text, rid, used, date)
    if not docs:
        matches = list(ART_QA.finditer(text))
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
                    "text": chunk, "date_filed": date, "document_number": num,
                    "source_url": used, "record_type": "article", "article_number": num,
                    "law_identifier": rid,
                    "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
                })
    is_const = lid == CONST_ID or "دستور" in title or re.search(r"Constitution", title, re.I)
    rec = base_record(
        cc=CC, country=COUNTRY, language="ar", ident=f"law-{lid}", title=title,
        text=text, source_url=page, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="qa-almeezan", date=date, official_identifier=lid,
        document_type="constitution" if is_const else "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": it.get("source") or "almeezan", "id": lid,
                          "view_url": view, "retrieval": method},
            "text_extraction": {"source": "official", "backend": f"html-{method}"},
        },
    )
    rec["languages"] = ["ar"]
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
                    CC, country=COUNTRY, source="Al-Meezan (Qatari Legal Portal)",
                    source_urls=[PORTAL, "https://www.almeezan.qa/LawsByYear.aspx"],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="National laws from official Al-Meezan. Arabic authentic.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "national-laws snapshot"
    notes = (
        "In-force national laws from official Al-Meezan (almeezan.qa). Arabic "
        "LawView/LawPage. Constitution included (id 2284 when present). TLS "
        "verify=False only after SSLError (missing intermediate; not WAF bypass). "
        f"429/403 uses archive_fallbacks of official URLs. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY, source="Al-Meezan (Qatari Legal Portal / Ministry of Justice)",
        source_urls=[PORTAL, "https://www.almeezan.qa/LawsByYear.aspx",
                     f"https://www.almeezan.qa/LawPage.aspx?id={CONST_ID}&language=ar"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
