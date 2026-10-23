#!/usr/bin/env python3
"""Kenya: Laws of Kenya + Constitution from Kenya Law (National Council for Law Reporting).

Official only:
  https://new.kenyalaw.org  (also https://kenyalaw.org)
  Listing: /legislation/all  (Laws of Kenya catalog)
  Constitution: /akn/ke/act/2010/constitution

Honor robots.txt: Allow /, Disallow /search/ and /api/, Crawl-delay: 5.
No WAF bypass. No commercial databases (Eastlaw etc.).
archive_fallbacks on HTTP 429 of official kenyalaw.org URLs.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(__file__).rsplit("/", 1)[0] if False else str(__import__("pathlib").Path(__file__).resolve().parent))
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ke"
COUNTRY = "Kenya"
SOURCE_TYPE = "kenyalaw_nclr"
LICENSE = (
    "Official legislative texts published by the National Council for Law Reporting "
    "(Kenya Law, new.kenyalaw.org / kenyalaw.org). Reuse is governed by Kenya Law "
    "terms of use. The Kenya Gazette / authentic official text prevails over this "
    "research snapshot. Not legal advice."
)
UA = DEFAULT_UA + " source=https://new.kenyalaw.org/"
PORTAL = "https://new.kenyalaw.org"
LISTING = f"{PORTAL}/legislation/all"
CONSTITUTION = f"{PORTAL}/akn/ke/act/2010/constitution"
TERMS = f"{PORTAL}/terms-of-use/"
SLEEP = 5.1  # robots.txt Crawl-delay: 5
WORKERS = 1
log = logging.getLogger("ke")
_rate_lock = threading.Lock()
_last_req = 0.0

SEC_RE = re.compile(r"(?m)^\s*(\d+[A-Z]?)\.\s+(\S[^\n]{0,180})")
ART_RE = re.compile(
    r"(?im)^\s*((?:Article|Chapter)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
AKN_ACT = re.compile(r"^/akn/ke/act/(?!ln/)(\d{4}|constitution)(?:/([^/]+))?(?:/eng@([^/\"']+))?")
HREF_AKN = re.compile(r'href="(/akn/ke/act/[^"#?]+)"')


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def polite_sleep():
    global _last_req
    with _rate_lock:
        wait = SLEEP - (time.time() - _last_req)
        if wait > 0:
            time.sleep(wait)
        _last_req = time.time()


def get_official(url: str, *, timeout=(20, 90), retries: int = 4) -> dict:
    """Live GET; on 429/challenge use archive_fallbacks of the same official URL."""
    polite_sleep()
    try:
        r = http_get(url, ua=UA, sleep=0, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s — archive fallback", url, exc)
        res = af.fetch_with_fallbacks(url, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    status = r.status_code
    body = r.content or b""
    text = ""
    ctype = (r.headers.get("content-type") or "").lower()
    if "html" in ctype or "xml" in ctype or "text/" in ctype or not ctype:
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 429 or (status in (403, 503) and text and af.is_challenge(text, status)):
        log.info("HTTP %s %s — archive_fallbacks", status, url)
        res = af.fetch_with_fallbacks(url, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and text and af.is_challenge(text, status):
        res = af.fetch_with_fallbacks(url, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    if status != 200 or not body:
        if status in (404, 410):
            return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
        res = af.fetch_with_fallbacks(url, try_http=False)
        res.setdefault("retrieval", "archive")
        return res
    return {
        "status": "success",
        "content": body,
        "text": text,
        "content_type": ctype,
        "original_url": url,
        "http_status": status,
        "method": "http",
        "final_url": r.url or url,
        "retrieval": "live",
    }


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 50:
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


def work_key(path: str) -> str:
    p = path.split("?")[0]
    p = re.sub(r"/eng@.*$", "", p)
    return p.rstrip("/")


def is_principal(path: str) -> bool:
    p = path.lower()
    if "/ln/" in p:
        return False
    if "/akn/ke/act/" not in p:
        return False
    return True


def extract_title_map(html: str) -> dict[str, str]:
    out = {}
    for href, title in re.findall(
        r'href="(/akn/ke/act/[^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S
    ):
        title = re.sub(r"<[^>]+>", " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        if title and href not in out:
            out[href] = title
    return out


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 200:
        log.info("resume catalog n=%s", len(existing))
        return existing
    best: dict[str, dict] = {}
    page = 1
    empty = 0
    while page <= 40:
        url = f"{LISTING}?page={page}"
        res = get_official(url)
        html = res.get("text") or ""
        if res.get("status") != "success" or not html:
            log.warning("listing page %s failed %s", page, res.get("error") or res.get("http_status"))
            empty += 1
            if empty >= 2:
                break
            page += 1
            continue
        if "Not found" in html and "Error 404" in html:
            log.info("listing last page before %s", page)
            break
        hrefs = HREF_AKN.findall(html)
        titles = extract_title_map(html)
        added = 0
        for href in hrefs:
            if not is_principal(href):
                continue
            wk = work_key(href)
            expr = href
            ts = ""
            m = re.search(r"eng@([0-9-]+)", href)
            if m:
                ts = m.group(1)
            prev = best.get(wk)
            if prev is None or ts > (prev.get("expression_date") or ""):
                title = titles.get(href) or (prev.get("title") if prev else "") or wk.rsplit("/", 1)[-1]
                repealed = False
                if prev:
                    repealed = bool(prev.get("repealed"))
                best[wk] = {
                    "work": wk,
                    "url": urljoin(PORTAL, expr),
                    "path": expr,
                    "title": title,
                    "expression_date": ts or None,
                    "repealed": repealed,
                }
                added += 1
        log.info("listing page=%s hrefs=%s principal_added=%s unique=%s", page, len(hrefs), added, len(best))
        if not hrefs:
            empty += 1
            if empty >= 2:
                break
        else:
            empty = 0
        page += 1
    # Constitution first
    ck = "/akn/ke/act/2010/constitution"
    if ck not in best:
        best[ck] = {
            "work": ck,
            "url": CONSTITUTION,
            "path": ck,
            "title": "Constitution of Kenya",
            "expression_date": "2010-09-03",
            "repealed": False,
            "document_type": "constitution",
        }
    else:
        best[ck]["document_type"] = "constitution"
        best[ck]["title"] = best[ck].get("title") or "Constitution of Kenya"
        best[ck]["url"] = CONSTITUTION
    items = list(best.values())
    items.sort(key=lambda x: (0 if "constitution" in x["work"] else 1, x["work"]))
    save_catalog(items)
    log.info("catalog principal acts n=%s", len(items))
    return items


def extract_body(html: str) -> str:
    if not html:
        return ""
    m = re.search(r'<div[^>]+id="document-content"[^>]*>', html, re.I)
    chunk = html
    if m:
        rest = html[m.end():]
        cut = re.search(
            r'<div[^>]+id="(citations|outgoing-citations|incoming-citations|document-detail-tab)',
            rest, re.I,
        )
        chunk = rest[: cut.start()] if cut else rest[:900000]
    else:
        m = re.search(r'<div[^>]+class="[^"]*akoma-ntoso[^"]*"[^>]*>', html, re.I)
        if m:
            chunk = html[m.end(): m.end() + 900000]
    text = html_to_text(chunk)
    return text


def split_ke(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    if constitution:
        docs = []
        matches = list(ART_RE.finditer(text or ""))
        if len(matches) >= 2:
            for i, m in enumerate(matches):
                chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
                num = re.sub(r"\s+", " ", m.group(1)).strip()
                aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
                docs.append({
                    "id": f"{law_id}-{aid}"[:180],
                    "title": chunk.split("\n", 1)[0][:200],
                    "text": chunk,
                    "date_filed": date,
                    "document_number": num,
                    "source_url": source_url,
                    "record_type": "article",
                    "article_number": num,
                    "law_identifier": law_id,
                    "metadata": {"text_extraction": {"source": "official", "backend": "kenyalaw"}},
                })
                if len(docs) >= 4000:
                    break
            if len(docs) >= 2:
                return docs
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(SEC_RE.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = m.group(1)
        heading = f"{num}. {m.group(2).strip()}"
        aid = f"s-{num.lower()}"
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": heading[:200], "text": chunk, "date_filed": date,
            "document_number": num, "source_url": source_url, "record_type": "article",
            "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "kenyalaw"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def cap_from(title: str, html: str) -> Optional[str]:
    m = re.search(r"(?i)\bCap\.?\s*([0-9]+[A-Z]?)\b", title or "")
    if m:
        return f"Cap. {m.group(1)}"
    m = re.search(r"(?i)\bCAP\.?\s*([0-9]+[A-Z]?)\b", html or "")
    return f"Cap. {m.group(1)}" if m else None


def fetch_one(it: dict, done: set[str]) -> str:
    url = it["url"]
    work = it["work"]
    ident = work.lstrip("/").replace("/", "-")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    res = get_official(url)
    html = res.get("text") or ""
    final = res.get("final_url") or res.get("wayback_url") or url
    if res.get("status") != "success" or len(html) < 200:
        log_failure(CC, {"id": rid, "url": url, "status": "failed",
                         "reason": res.get("error") or "empty", "retrieval": res.get("retrieval")})
        return "fail"
    text = extract_body(html)
    if len(text) < 120:
        text = html_to_text(html)
    if len(text) < 120:
        log_failure(CC, {"id": rid, "url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = it.get("title") or ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if h1:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h1.group(1))).strip()
        if t and t.lower() not in ("kenya law", "laws of kenya"):
            title = t
    date = iso_date(it.get("expression_date") or "")
    dm = re.search(r"Commenced on\s+(\d{1,2}\s+\w+\s+\d{4})", html)
    if dm and not date:
        date = iso_date(dm.group(1))
    is_const = "constitution" in work
    docs = split_ke(text, rid, final, date, constitution=is_const)
    repealed = bool(it.get("repealed")) or bool(re.search(r"(?i)\brepealed\b", html[:8000]))
    cap = cap_from(title, html)
    official = "Constitution of Kenya, 2010" if is_const else (cap or ident)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title or ident,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ke.py", date=date, official_identifier=official,
        document_type="constitution" if is_const else "statute",
        law_status="repealed" if repealed else "current",
        is_current=False if repealed else True, documents=docs,
        extra_meta={
            "discovery": {"method": "kenyalaw_legislation_all", "work": work},
            "text_extraction": {"source": "official", "backend": "html-document-content"},
            "retrieval": {
                "method": res.get("retrieval") or res.get("method") or "live",
                "final_url": final,
            },
            "expression_date": it.get("expression_date"),
            "cap": cap,
        },
        extra_fields={"canonical_document_url": url, "information_url": url},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Laws of Kenya principal Acts plus the Constitution of Kenya 2010 from "
        "Kenya Law (National Council for Law Reporting). Catalog is /legislation/all "
        "(not /search, not /api — robots.txt disallows those). Legal notices under "
        "/akn/ke/act/ln/ are out of this snapshot. Crawl-delay 5 honoured. "
        "archive_fallbacks on HTTP 429 of official kenyalaw.org URLs. Not Eastlaw. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="Kenya Law / National Council for Law Reporting (new.kenyalaw.org)",
        source_urls=[PORTAL + "/", LISTING, CONSTITUTION, TERMS],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage,
        notes=notes,
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
        if n % 20 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot"
    if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items):
        cov = "full-principal-catalog"
    write_progress(items, counters, cov, extra=f" Started {t0}.")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", counters["ok"], counters["skip"], counters["fail"], cov)
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), "ok": counters["ok"], "skip": counters["skip"],
        "failed": counters["fail"], "coverage": cov, "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
