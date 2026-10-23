#!/usr/bin/env python3
"""Bangladesh: Acts + Constitution from Laws of Bangladesh (LPAD).

Official source only:
  http://bdlaws.minlaw.gov.bd  (Legislative and Parliamentary Affairs Division)
  Chronological index, volume lists, act-details / act-print pages.

Does not use commercial DBs. No WAF bypass. HTTPS on this host often EOF;
HTTP is the official scheme. Pages may be UTF-16.

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
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "bd"
COUNTRY = "Bangladesh"
SOURCE_TYPE = "bdlaws"
LICENSE = (
    "Official Laws of Bangladesh texts (Legislative and Parliamentary Affairs "
    "Division, bdlaws.minlaw.gov.bd). Authentic Gazette of Bangladesh prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=http://bdlaws.minlaw.gov.bd/"
PORTAL = "http://bdlaws.minlaw.gov.bd/"
CHRONO = PORTAL + "laws-of-bangladesh-chronological-index.html"
ALPHA = PORTAL + "laws-of-bangladesh-alphabetical-index.html"
WORKERS = 4
SLEEP = 0.4
log = logging.getLogger("bd")

ACT_ID_RE = re.compile(r"act(?:-details|-print|-pdf)?-(\d+)\.html", re.I)
ART_BD = re.compile(r"(?im)^\s*((?:Section|Article)\s+\d+[A-Za-z]?)\b")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def decode_body(raw: bytes, header_ctype: str = "") -> str:
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    if "utf-16" in (header_ctype or "").lower():
        try:
            return raw.decode("utf-16", "replace")
        except Exception:
            pass
    if len(raw) > 8 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        try:
            return raw.decode("utf-16le", "replace")
        except Exception:
            pass
    for enc in ("utf-8", "utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def official_get(url: str, retries: int = 4) -> dict:
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=retries, timeout=(20, 90),
                     headers={"Accept": "text/html, */*"})
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content:
        text = decode_body(r.content, r.headers.get("content-type") or "")
        if text and not af.is_challenge(text, r.status_code):
            return {"ok": True, "text": text, "content": r.content, "method": "live", "status": 200}
    need = r is None or (r is not None and r.status_code in (429, 403, 503, 502, 504))
    if r is not None and r.status_code in (404, 410):
        return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code}
    if r is not None and af.is_challenge(decode_body(r.content or b"", r.headers.get("content-type") or ""), r.status_code):
        need = True
    if need:
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=True, try_archive_is=False)
        if res.get("status") == "success" and (res.get("text") or res.get("content")):
            text = res.get("text") or decode_body(res.get("content") or b"")
            return {"ok": True, "text": text, "content": res.get("content") or b"",
                    "method": res.get("method") or "archive", "archive": res}
        return {"ok": False, "error": (res or {}).get("error") or "archive_fail"}
    return {"ok": False, "error": f"http_{getattr(r, 'status_code', 0)}"}


def parse_act_links(html: str, base: str) -> list[dict]:
    out = []
    seen = set()
    for href, title in re.findall(r'href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', html or ""):
        m = ACT_ID_RE.search(href)
        if not m:
            continue
        aid = m.group(1)
        if aid in seen:
            continue
        seen.add(aid)
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title)).strip()
        out.append({
            "act_id": aid,
            "url": urljoin(base, f"act-details-{aid}.html"),
            "print_url": urljoin(base, f"act-print-{aid}.html"),
            "title": t,
        })
    return out


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
            aid = str(row.get("act_id") or "")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            items.append(row)
    return items


def add_item(items, seen, row):
    aid = str(row.get("act_id") or "")
    if not aid or aid in seen:
        return
    seen.add(aid)
    if not row.get("url"):
        row["url"] = urljoin(PORTAL, f"act-details-{aid}.html")
    if not row.get("print_url"):
        row["print_url"] = urljoin(PORTAL, f"act-print-{aid}.html")
    items.append(row)
    append_catalog(CC, row)


def discover() -> list[dict]:
    items = load_catalog()
    seen = {str(x.get("act_id")) for x in items}
    if len(items) >= 400:
        log.info("resume catalog %s", len(items))
        return items
    pages = [CHRONO, ALPHA, PORTAL + "laws-of-bangladesh.html"]
    for n in range(1, 55):
        pages.append(PORTAL + f"act-index-volume-{n}.html")
        pages.append(PORTAL + f"volume-{n}.html")
    for url in pages:
        got = official_get(url, retries=3)
        if not got.get("ok"):
            log.info("skip page %s %s", url, got.get("error"))
            continue
        html = got.get("text") or ""
        found = parse_act_links(html, PORTAL)
        before = len(items)
        for row in found:
            add_item(items, seen, row)
        log.info("page %s new=%s total=%s", url.rsplit("/", 1)[-1], len(items) - before, len(items))
    # Constitution is act 367
    add_item(items, seen, {
        "act_id": "367",
        "title": "The Constitution of the People's Republic of Bangladesh",
        "kind": "constitution",
    })
    log.info("discovered %s", len(items))
    return items


def extract_title(html: str, fallback: str) -> str:
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"^\s*Laws of Bangladesh\s*[-|:]*\s*", "", t, flags=re.I)
        if t and t.lower() not in {"laws of bangladesh", "404"}:
            return t
    m = re.search(r"<h1[^>]*>([\s\S]{3,200})</h1>", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        if t:
            return t
    return fallback


def fetch_one(it: dict, done: set[str]) -> str:
    aid = str(it.get("act_id") or "")
    if not aid:
        return "fail"
    rid = slug_id(CC, f"act-{aid}")
    if rid in done:
        return "skip"
    print_url = it.get("print_url") or urljoin(PORTAL, f"act-print-{aid}.html")
    details_url = it.get("url") or urljoin(PORTAL, f"act-details-{aid}.html")
    got = official_get(print_url)
    html = got.get("text") or ""
    method = got.get("method") or "live"
    if not got.get("ok") or len(html) < 200:
        got2 = official_get(details_url)
        if got2.get("ok") and len(got2.get("text") or "") > len(html):
            html = got2.get("text") or ""
            method = got2.get("method") or method
            print_url = details_url
    if len(html) < 200:
        log_failure(CC, {"identifier": aid, "source_url": print_url, "status": "failed",
                         "reason": got.get("error") or "empty_html"})
        return "fail"
    title = extract_title(html, it.get("title") or f"Act {aid}")
    text = html_to_text(html)
    # trim chrome
    for needle in ("Section 1", "Preamble", "BISMILLAH", "The Constitution"):
        idx = text.find(needle)
        if idx > 0 and idx < 2500:
            text = text[idx:]
            break
    if len(text) < 80:
        log_failure(CC, {"identifier": aid, "source_url": print_url, "status": "failed",
                         "reason": "empty_text", "title": title})
        return "fail"
    docs = split_articles(text, rid, print_url, None)
    if not docs:
        matches = list(ART_BD.finditer(text))
        if len(matches) >= 2:
            docs = []
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                chunk = text[start:end].strip()
                num = re.sub(r"\s+", " ", m.group(1)).strip()
                aidn = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
                docs.append({
                    "id": f"{rid}-{aidn}"[:180], "title": chunk.split("\n", 1)[0][:200],
                    "text": chunk, "document_number": num, "source_url": print_url,
                    "record_type": "article", "article_number": num, "law_identifier": rid,
                    "metadata": {"text_extraction": {"source": "official", "backend": "collector"}},
                })
    is_const = aid == "367" or re.search(r"^The Constitution of the People", title, re.I)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=f"act-{aid}", title=title,
        text=text, source_url=details_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="bd-bdlaws", date=None, official_identifier=f"Act {aid}",
        document_type="constitution" if is_const else "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": "bdlaws_index", "act_id": aid, "print_url": print_url,
                          "retrieval": method},
            "text_extraction": {"source": "official", "backend": f"html-{method}"},
        },
    )
    rec["languages"] = ["en"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    items = sorted(items, key=lambda x: (0 if str(x.get("act_id")) == "367" else 1, int(x.get("act_id") or 0)))
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
                    source="Laws of Bangladesh (Legislative and Parliamentary Affairs Division)",
                    source_urls=[PORTAL, CHRONO], license_text=LICENSE,
                    discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="Acts + Constitution from bdlaws.minlaw.gov.bd. Not commercial DBs.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "acts-constitution snapshot"
    notes = (
        "Acts + Constitution from the official Laws of Bangladesh portal "
        "(bdlaws.minlaw.gov.bd / LPAD). Print views preferred. UTF-16 pages decoded. "
        "429/403 uses archive_fallbacks of official URLs only. Started "
        f"{t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Laws of Bangladesh (Legislative and Parliamentary Affairs Division)",
        source_urls=[PORTAL, CHRONO], license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
