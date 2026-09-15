#!/usr/bin/env python3
"""Ukraine: Закони України + Конституція from official Rada sources.

Official sources only:
  https://zakon.rada.gov.ua          (Verkhovna Rada / Законодавство України)
  https://data.rada.gov.ua           (open data API of the same corpus)
  Catalog: /ogd/zak/laws/data/csv/doc.txt
  Texts:   https://data.rada.gov.ua/laws/show/{nreg}.txt  (OpenData UA)

Закони України + Конституція first — not every наказ / розпорядження.
No commercial DBs. No WAF bypass. data.rada.gov.ua requires User-Agent
containing OpenData (per official API readme).

On HTTP 429/403 of official URLs, archive_fallbacks.py of those URLs only.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ua"
COUNTRY = "Ukraine"
SOURCE_TYPE = "zakon_rada"
LICENSE = (
    "Official texts of the Verkhovna Rada of Ukraine (zakon.rada.gov.ua / "
    "data.rada.gov.ua). Authentic official publication prevails. Not legal advice."
)
UA = DEFAULT_UA + " OpenData source=https://data.rada.gov.ua/ source=https://zakon.rada.gov.ua/"
PORTAL = "https://zakon.rada.gov.ua/"
DATA = "https://data.rada.gov.ua"
DOC_CSV = DATA + "/ogd/zak/laws/data/csv/doc.txt"
SHOW = "http://data.rada.gov.ua/laws/show/"
WORKERS = 4
SLEEP = 0.55
log = logging.getLogger("ua")
import threading
_RADA_DOWN = threading.Event()
_ssl_lock = threading.Lock()
_ssl_n = [0]

CONST_NREG = "254к/96-вр"
WANT_TITLE = re.compile(
    r"^(Закон України|Конституція України|Конституція \(Основний Закон\) України)\b"
)
SKIP_TITLE = re.compile(r"^(Наказ|Розпорядження|Постанова|Указ|Рішення|Лист|Повідомлення)\b")
ART_UA = re.compile(r"(?im)^\s*((?:Стаття|Ст\.)\s+\d+[а-яa-z]?)\b")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def decode_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    # Rada OGD CSV is windows-1251; UTF-8 would mis-parse titles.
    for enc in ("cp1251", "windows-1251", "utf-8", "utf-16"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("cp1251", "replace")


def official_get(url: str, retries: int = 3) -> dict:
    """Live GET with verify=False after SSL EOF (not a WAF bypass). Wayback on 429/403 only."""
    import time as _t
    import requests as _req
    last = None
    headers = {"Accept": "text/plain, text/html, application/json, */*", "User-Agent": UA}
    for attempt in range(1, retries + 1):
        _t.sleep(SLEEP)
        for verify in (True, False):
            try:
                r = get_session(UA).get(url, timeout=(20, 60), headers=headers, verify=verify, allow_redirects=True)
            except _req.RequestException as exc:
                last = exc
                log.info("live net %s verify=%s: %s", url, verify, type(exc).__name__)
                if "SSL" in type(exc).__name__ or "SSL" in str(exc):
                    with _ssl_lock:
                        _ssl_n[0] += 1
                        if _ssl_n[0] >= 20:
                            _RADA_DOWN.set()
                            log.warning("rada TLS circuit-open after %s SSL errors", _ssl_n[0])
                continue
            last = r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                _t.sleep(min(15, 2 ** attempt))
                break
            if r.status_code == 200 and r.content:
                text = decode_bytes(r.content)
                if text and (len(r.content) > 400 or not af.is_challenge(text, r.status_code)):
                    return {"ok": True, "text": text, "content": r.content, "method": "live",
                            "status": 200, "verify": verify}
            if r.status_code in (404, 410):
                return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code}
            if r.status_code in (429, 403):
                break
            break
    # only archive official URL on 429/403, one Wayback try
    status = getattr(last, "status_code", None) if hasattr(last, "status_code") else None
    if status in (429, 403):
        res = af.get_wayback_content(url)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            text = res.get("text") or decode_bytes(res.get("content") or b"")
            return {"ok": True, "text": text, "content": res.get("content") or b"", "method": "wayback"}
        return {"ok": False, "error": (res or {}).get("error") or "archive_fail"}
    err = f"http_{status}" if status else str(last)[:160]
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
            key = row.get("nreg") or row.get("id")
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(row)
    return items


def parse_doc_txt(raw: bytes) -> list[dict]:
    text = decode_bytes(raw)
    items = []
    seen = set()
    for line in text.splitlines():
        if not line.strip() or line.startswith("nreg") or line.startswith("NREG"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            parts = re.split(r"\s{2,}|\t", line)
        if len(parts) < 3:
            continue
        internal = parts[0].strip()
        nreg = parts[1].strip()
        title = parts[2].strip()
        type_id = parts[4].strip() if len(parts) > 4 else ""
        status = parts[7].strip() if len(parts) > 7 else ""
        date = parts[8].strip() if len(parts) > 8 else (parts[-1].strip() if parts else "")
        if not nreg or not title:
            continue
        # Type 1 = Закон України (nreg like 4954-20). Type 12 are commentaries.
        # Constitution is 254к/96-вр (type 216|100|1).
        is_const = (nreg == CONST_NREG) or (
            "Конституція України" == title or title.startswith("Конституція України")
        ) and "Основний Закон" not in title
        is_law = (type_id == "1") or is_const
        if not is_law:
            continue
        if nreg.startswith("n") and not is_const:
            continue
        if SKIP_TITLE.match(title) and not is_const:
            continue
        if nreg in seen:
            continue
        seen.add(nreg)
        row = {
            "id": internal,
            "nreg": nreg,
            "title": title,
            "type_id": type_id,
            "status_code": status,
            "date": iso_date(date) if date else None,
            "kind": "constitution" if is_const else "statute",
        }
        items.append(row)
    return items


def discover() -> list[dict]:
    existing = load_catalog()
    if len(existing) >= 100:
        log.info("resume catalog %s", len(existing))
        return existing
    dest = ROOT / CC / "raw" / "doc.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        raw = dest.read_bytes()
        items = parse_doc_txt(raw)
        log.info("parsed local doc.txt laws+constitution %s", len(items))
        cat = ROOT / CC / "raw" / "catalog.jsonl"
        if cat.exists():
            cat.unlink()
        for row in items:
            append_catalog(CC, row)
        return items
    got = official_get(DOC_CSV, retries=5)
    if not got.get("ok"):
        log.warning("doc.txt fail %s — will still try constitution", got.get("error"))
        items = [{
            "nreg": CONST_NREG,
            "title": "Конституція України",
            "kind": "constitution",
            "date": "1996-06-28",
        }]
        for row in items:
            append_catalog(CC, row)
        return items
    raw = got.get("content") or (got.get("text") or "").encode("utf-8")
    dest.write_bytes(raw)
    items = parse_doc_txt(raw)
    # guarantee constitution
    if not any(x.get("nreg") == CONST_NREG or x.get("kind") == "constitution" for x in items):
        items.insert(0, {
            "nreg": CONST_NREG, "title": "Конституція України",
            "kind": "constitution", "date": "1996-06-28",
        })
    for row in items:
        append_catalog(CC, row)
    log.info("discovered laws+constitution %s from doc.txt", len(items))
    return items


def show_urls(nreg: str) -> list[str]:
    enc = quote(nreg, safe="/")
    return [
        f"{SHOW}{enc}.txt",
        f"{SHOW}{enc}",
        f"https://zakon.rada.gov.ua/laws/show/{enc}/conv",
        f"https://zakon.rada.gov.ua/laws/show/{enc}",
    ]


def official_rada_urls(nreg: str) -> list[str]:
    """Official zakon.rada.gov.ua URLs only (no Consultant, no data.rada live)."""
    enc = quote(nreg, safe="/")
    base = f"https://zakon.rada.gov.ua/laws/show/{enc}"
    return [base, f"{base}/conv"]


WAYBACK_TS = (
    "20220301000000",
    "20200201000000",
    "20250301000000",
    "20240101000000",
)
_CC_OK = [0]
_CC_MISS = [0]
_CC_DISABLE = threading.Event()
_AIS_MISS = [0]
_AIS_DISABLE = threading.Event()
_MIX = {"common_crawl": 0, "wayback": 0, "archive_is": 0}
_mix_lock = threading.Lock()


def _bump_mix(method: str) -> None:
    key = method if method in _MIX else "wayback"
    with _mix_lock:
        _MIX[key] = _MIX.get(key, 0) + 1


def looks_like_law(text: str, title: str = "") -> bool:
    if not text or len(text) < 400:
        return False
    if af.is_challenge(text):
        return False
    # 2022+ rada pages often archive as a JS shell without the body.
    if "Відбувається форматування тексту" in text:
        return False
    if "поки завантажиться повністю" in text and text.count("Стаття ") < 1:
        return False
    head = text[:2500]
    if "403 Forbidden" in head and len(text) < 800:
        return False
    n_art = text.count("Стаття ")
    if n_art >= 1 and len(text) >= 600:
        return True
    # short amending laws often have no Стаття headings
    body_markers = (
        "ЗАКОН УКРАЇНИ", "Верховна Рада України постановляє",
        "Цей Закон набирає чинності", "Президент України",
        "КОНСТИТУЦІЯ УКРАЇНИ",
    )
    if any(m in text for m in body_markers) and len(text) >= 2500:
        return True
    if title:
        t = re.sub(r"\s+", " ", title).strip()[:48]
        if t and t in text and len(text) >= 8000:
            return True
    return False


def html_or_text(body: str) -> str:
    if not body:
        return ""
    head = body[:500].lower()
    if "<html" in head or "<!doctype" in head or "<div" in head or "<p" in head:
        return html_to_text(body)
    return body.strip()


def http_wayback_once(url: str, ts: str) -> dict:
    """Single HTTP Wayback replay. No HTTPS (SSL-EOF), no 403-retry storm."""
    wb = f"http://web.archive.org/web/{ts}id_/{url}"
    af._sleep_wayback(0.35)
    try:
        r = af.session().get(wb, timeout=(20, 75), allow_redirects=True)
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
    if r.status_code != 200 or not r.content:
        return {"status": "error", "error": f"http_{r.status_code}", "http_status": r.status_code}
    body = r.content or b""
    ctype = r.headers.get("content-type") or ""
    text = ""
    if "html" in ctype or "xml" in ctype or "text/" in ctype or not ctype:
        try:
            text = body.decode(r.encoding or "utf-8", "replace")
        except Exception:
            text = decode_bytes(body)
    cap_ts = ts
    m = re.search(r"/web/(\d{14})", r.url or "")
    if m:
        cap_ts = m.group(1)
    if text and af.is_challenge(text, r.status_code):
        return {"status": "error", "error": "challenge_or_shell"}
    return {
        "status": "success", "content": body, "text": text, "content_type": ctype,
        "wayback_url": r.url, "capture_timestamp": cap_ts, "original_url": url,
        "http_status": r.status_code, "method": "wayback",
    }


def fetch_archive_official(nreg: str, title: str = "") -> dict:
    """CC then HTTP Wayback then archive.is of official zakon.rada.gov.ua URLs.

    Live rada TLS is dead from this host. HTTPS Wayback SSL-EOFs — HTTP replay
    with a 200-era timestamp (latest 2id_ is often origin 403 / JS shell).
    """
    urls = official_rada_urls(nreg)
    errors: list[str] = []
    # 1. Common Crawl (HTTP indexes; skip after consecutive empty)
    if not _CC_DISABLE.is_set():
        try:
            recs = af.search_common_crawl(urls[0], limit=3, indexes=af.cc_indexes(2))
        except Exception as exc:
            recs = []
            errors.append(f"cc:{exc}")
        else:
            recs = recs or []
        hit = False
        for rec in recs:
            res = af.fetch_common_crawl_warc(rec)
            if res.get("status") != "success":
                errors.append(f"cc:{res.get('error')}")
                continue
            body = res.get("text") or decode_bytes(res.get("content") or b"")
            text = html_or_text(body)
            if looks_like_law(text, title):
                _CC_OK[0] += 1
                return {"ok": True, "text": text, "url": urls[0], "method": "common_crawl"}
            hit = True
        if not recs:
            _CC_MISS[0] += 1
            if _CC_MISS[0] >= 8 and _CC_OK[0] == 0:
                _CC_DISABLE.set()
                log.info("common crawl disabled after %s empty queries (0 law hits)", _CC_MISS[0])
        elif not hit:
            _CC_MISS[0] += 1

    # 2. HTTP Wayback timestamp chain of official show, then /conv
    for url in urls:
        for ts in WAYBACK_TS:
            res = http_wayback_once(url, ts)
            if res.get("status") != "success":
                errors.append(f"wb{ts}:{res.get('error')}")
                continue
            body = res.get("text") or decode_bytes(res.get("content") or b"")
            text = html_or_text(body)
            if looks_like_law(text, title):
                return {
                    "ok": True, "text": text, "url": url, "method": "wayback",
                    "wayback_url": res.get("wayback_url"),
                    "capture_timestamp": res.get("capture_timestamp"),
                }

    # 3. archive.is of official show URL (disable after empty streak)
    if not _AIS_DISABLE.is_set():
        res = af.get_archive_is_content(urls[0])
        if res.get("status") == "success":
            body = res.get("text") or decode_bytes(res.get("content") or b"")
            text = html_or_text(body)
            if looks_like_law(text, title):
                return {"ok": True, "text": text, "url": urls[0], "method": "archive_is",
                        "archive_url": res.get("archive_url")}
            errors.append("archive_is:not_law_text")
            _AIS_MISS[0] += 1
        else:
            errors.append(f"archive_is:{res.get('error')}")
            _AIS_MISS[0] += 1
        if _AIS_MISS[0] >= 6:
            _AIS_DISABLE.set()
            log.info("archive.is disabled after %s misses", _AIS_MISS[0])
    return {"ok": False, "error": "; ".join(errors[-8:]) or "archive_miss", "url": urls[0]}


def split_ua(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if docs:
        return docs
    matches = list(ART_UA.finditer(text or ""))
    if len(matches) < 2:
        return []
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9а-я]+", "-", num.lower()).strip("-")
        out.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": chunk.split("\n", 1)[0][:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
        })
        if len(out) >= 4000:
            break
    return out


def fetch_one(it: dict, done: set[str]) -> str:
    nreg = it.get("nreg") or ""
    if not nreg:
        return "fail"
    rid = slug_id(CC, nreg)
    if rid in done:
        return "skip"
    title = it.get("title") or nreg
    canon = f"https://zakon.rada.gov.ua/laws/show/{quote(nreg, safe='/')}"
    got = fetch_archive_official(nreg, title=title)
    text = (got.get("text") or "").strip() if got.get("ok") else ""
    if len(text) < 120:
        log_failure(CC, {"identifier": nreg, "source_url": canon,
                         "status": "failed",
                         "reason": got.get("error") or "empty_text",
                         "title": title})
        return "fail"
    used = got.get("url") or canon
    method = got.get("method") or "wayback"
    _bump_mix(method)
    date = it.get("date")
    docs = split_ua(text, rid, used, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="uk", ident=nreg, title=title,
        text=text, source_url=canon, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="ua-zakon-rada", eli=None, date=date,
        official_identifier=nreg,
        document_type=it.get("kind") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {
                "method": "rada_ogd_doc_csv",
                "nreg": nreg,
                "text_url": used,
                "retrieval": method,
                "wayback_url": got.get("wayback_url"),
                "capture_timestamp": got.get("capture_timestamp"),
            },
            "text_extraction": {"source": "official", "backend": f"rada-{method}"},
        },
    )
    rec["languages"] = ["uk"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    items = sorted(items, key=lambda x: (0 if x.get("kind") == "constitution" else 1, x.get("nreg") or ""))
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
                log.info("progress %s/%s ok=%s skip=%s fail=%s mix=%s", n, len(items), ok, skip, fail, dict(_MIX))
                write_summary(
                    CC, country=COUNTRY,
                    source="Verkhovna Rada / Законодавство України (zakon.rada.gov.ua)",
                    source_urls=[PORTAL, DATA, DOC_CSV], license_text=LICENSE,
                    discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="Закони України + Конституція only. Not накази.",
                    last_run=utcnow(),
                )
    mix = dict(_MIX)
    n_have = ok + skip
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and n_have >= len(items):
        coverage = "zakony-plus-constitution snapshot"
    elif n_have >= 200:
        coverage = "constitution-plus-archive-partial"
    elif n_have:
        coverage = "constitution-plus-partial (archive ceiling)"
    notes = (
        "Закони України + Конституція from official data.rada.gov.ua doc.txt "
        "catalog. Live zakon.rada.gov.ua TLS is down from this host; texts filled "
        "via archive_fallbacks.py (Common Crawl then HTTP Wayback then archive.is) "
        "of official https://zakon.rada.gov.ua/laws/show/{nreg} URLs only. "
        "No Consultant, no WAF bypass, no OCR of random scans. "
        f"archive mix cc={mix.get('common_crawl',0)} wayback={mix.get('wayback',0)} "
        f"archive_is={mix.get('archive_is',0)}. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Verkhovna Rada / Законодавство України (zakon.rada.gov.ua)",
        source_urls=[PORTAL, DATA + "/", DOC_CSV], license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
        "archive_mix": mix,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
