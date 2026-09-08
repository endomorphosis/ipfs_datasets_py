#!/usr/bin/env python3
"""New Zealand: PCO legislation.govt.nz (official XML/HTML).

Official sources only:
  - https://www.legislation.govt.nz/  (XML by appending .xml to canonical URLs)
  - API v0 (free key): https://api.legislation.govt.nz/docs/  — used only if
    LEGISLATION_NZ_API_KEY or PCO_API_KEY is set; never invent a key.
  - Catalogue: https://catalogue.data.govt.nz/dataset/new-zealand-legislation

Live site is behind AWS WAF (x-amzn-waf-action: challenge). No WAF bypass.
Fallback: archive.org CDX of the official legislation.govt.nz URLs only
(and Common Crawl of those same official URLs). Does not scrape /subscribe
(robots historically disallows it). Does not use NZLII or commercial DBs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "nz"
COUNTRY = "New Zealand"
SOURCE_TYPE = "pco_legislation"
LICENSE = (
    "Crown copyright. New Zealand legislation on legislation.govt.nz is published "
    "by the Parliamentary Counsel Office. Reuse is typically under Creative Commons "
    "Attribution 4.0 International (CC BY 4.0) as stated on the NZ Legislation "
    "website (https://www.legislation.govt.nz/). Attribute Parliamentary Counsel "
    "Office / New Zealand Legislation. Not legal advice; official PCO text prevails."
)
UA = DEFAULT_UA + " source=https://www.legislation.govt.nz/"
PORTAL = "https://www.legislation.govt.nz"
API = "https://api.legislation.govt.nz/v0"
WORKERS = 10
SLEEP = 0.2
log = logging.getLogger("nz")

# act/public/1990/0109 or regulation/2015/0123 etc.
PATH_RE = re.compile(
    r"/((?:act/(?:public|private|local|imperial|provincial)|regulation|measure))/"
    r"(\d{4})/(\d{1,4})(?:/|$)",
    re.I,
)
KIND_RANK = {
    "act/public": 0,
    "act/private": 1,
    "act/local": 2,
    "act/imperial": 3,
    "act/provincial": 4,
    "regulation": 5,
    "measure": 6,
}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def api_key() -> Optional[str]:
    k = (os.environ.get("LEGISLATION_NZ_API_KEY") or os.environ.get("PCO_API_KEY") or "").strip()
    return k or None


def parse_path(url: str) -> Optional[dict]:
    if not url:
        return None
    m = PATH_RE.search(url)
    if not m:
        return None
    kind, year, num = m.group(1).lower(), m.group(2), m.group(3).zfill(4)
    return {
        "kind": kind,
        "year": year,
        "number": num,
        "work_key": f"{kind}/{year}/{num}",
    }


def num_variants(num: str) -> list[str]:
    """PCO paths mix 15 and 0015; try both."""
    raw = str(num or "")
    out: list[str] = []
    try:
        n = str(int(raw.lstrip("0") or "0"))
    except Exception:
        n = raw
    for x in (n, n.zfill(4), raw):
        if x and x not in out:
            out.append(x)
    return out


def xml_urls(kind: str, year: str, num: str) -> list[str]:
    urls: list[str] = []
    for n in num_variants(num):
        base = f"{PORTAL}/{kind}/{year}/{n}"
        for suffix in ("/latest/whole.xml", "/en/latest.xml", "/latest.xml", "/en/latest/whole.xml"):
            u = base + suffix
            if u not in urls:
                urls.append(u)
    return urls


def html_urls(kind: str, year: str, num: str) -> list[str]:
    urls: list[str] = []
    for n in num_variants(num):
        base = f"{PORTAL}/{kind}/{year}/{n}"
        for suffix in ("/latest/whole.html", "/en/latest/whole.html", "/latest/whole.htm"):
            u = base + suffix
            if u not in urls:
                urls.append(u)
    return urls


def canonical_url(kind: str, year: str, num: str) -> str:
    n = num_variants(num)[0]
    return f"{PORTAL}/{kind}/{year}/{n}/latest/whole.html"


def cdx_collect(prefix: str, extra_filters: list[str], limit: int) -> list[dict]:
    log.info("cdx prefix=%s filters=%s limit=%s", prefix, extra_filters, limit)
    try:
        recs = af.search_wayback_machine(
            prefix,
            match_type="prefix",
            limit=limit,
            collapse="urlkey",
            extra_filters=extra_filters,
            from_date="20180101",
        )
    except Exception as exc:
        log.warning("cdx fail %s: %s", prefix, exc)
        return []
    log.info("cdx got %s for %s", len(recs), prefix)
    return recs


def discover_via_api(key: str) -> list[dict]:
    items = []
    seen = set()
    offset = 0
    # Search for in-force acts then regulations. API is v0 and may paginate via offset.
    queries = [
        {"search": "act", "limit": 100},
        {"search": "public act", "limit": 100},
        {"search": "regulation", "limit": 100},
    ]
    for qbase in queries:
        offset = 0
        stagnant = 0
        while offset <= 5000:
            params = dict(qbase)
            params["offset"] = offset
            params["api_key"] = key
            try:
                r = http_get(f"{API}/works", ua=UA, sleep=0.25, timeout=(20, 60),
                             retries=3, params=params,
                             headers={"Accept": "application/json"})
            except Exception as exc:
                log.warning("api works fail: %s", exc)
                break
            if r.status_code in (401, 403):
                log.warning("api key rejected status=%s", r.status_code)
                return items
            if r.status_code != 200:
                log.warning("api status=%s offset=%s", r.status_code, offset)
                break
            try:
                data = r.json()
            except Exception:
                break
            results = data if isinstance(data, list) else (data.get("results") or data.get("items") or data.get("works") or [])
            if isinstance(data, dict) and "data" in data:
                results = data.get("data") or results
            if not results:
                stagnant += 1
                if stagnant >= 2:
                    break
            newc = 0
            for row in results:
                if not isinstance(row, dict):
                    continue
                url = (row.get("url") or row.get("canonical_url") or row.get("html_url")
                       or row.get("work_id") or "")
                if isinstance(url, str) and url.startswith("act_"):
                    # work_id form act_public_1990_109
                    m = re.match(r"(act)_(public|private|local|imperial)_(\d{4})_(\d+)", url, re.I)
                    if m:
                        parsed = {"kind": f"{m.group(1).lower()}/{m.group(2).lower()}",
                                  "year": m.group(3), "number": m.group(4).zfill(4),
                                  "work_key": None}
                        parsed["work_key"] = f"{parsed['kind']}/{parsed['year']}/{parsed['number']}"
                    else:
                        parsed = parse_path(str(row))
                else:
                    parsed = parse_path(str(url)) or parse_path(json.dumps(row))
                if not parsed:
                    continue
                wk = parsed["work_key"]
                if wk in seen:
                    continue
                seen.add(wk)
                rec = dict(parsed)
                rec["title"] = row.get("title") or row.get("name") or wk
                rec["discovery"] = "pco_api_v0"
                rec["wayback_ts"] = None
                items.append(rec)
                newc += 1
            log.info("api q=%s offset=%s new=%s total=%s", qbase.get("search"), offset, newc, len(items))
            if newc == 0:
                stagnant += 1
                if stagnant >= 2:
                    break
            else:
                stagnant = 0
            offset += int(qbase.get("limit") or 100)
    return items


def discover_via_cdx() -> list[dict]:
    prefixes = [
        "www.legislation.govt.nz/act/public/",
        "www.legislation.govt.nz/act/private/",
        "www.legislation.govt.nz/act/local/",
        "www.legislation.govt.nz/regulation/",
    ]
    filters_sets = [
        ["original:.*latest/whole\\.html"],
    ]
    recs = []
    for prefix in prefixes:
        for flt in filters_sets:
            recs.extend(cdx_collect(prefix, flt, 3000))
            if len(recs) >= 8000:
                break
    # Common crawl of official host, acts only
    try:
        cc_recs = af.search_common_crawl("www.legislation.govt.nz/act/public/*", limit=400)
        log.info("common crawl act/public %s", len(cc_recs))
        recs.extend(cc_recs)
    except Exception as exc:
        log.warning("cc fail: %s", exc)
    seen = {}
    for rec in recs:
        orig = rec.get("original") or rec.get("url") or ""
        parsed = parse_path(orig)
        if not parsed:
            continue
        wk = parsed["work_key"]
        ts = rec.get("timestamp") or ""
        prev = seen.get(wk)
        if prev is None or (ts and ts > (prev.get("wayback_ts") or "")):
            parsed["title"] = parsed["work_key"]
            parsed["discovery"] = rec.get("source") or "wayback_cdx"
            parsed["wayback_ts"] = ts
            parsed["original_url"] = orig
            parsed["cc_record"] = rec if rec.get("filename") or rec.get("warc_filename") else None
            seen[wk] = parsed
    items = list(seen.values())
    items.sort(key=lambda x: (KIND_RANK.get(x.get("kind"), 9), x.get("year") or "", x.get("number") or ""))
    return items


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    if cat.exists() and cat.stat().st_size > 1000:
        items = []
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog %s", len(items))
            items.sort(key=lambda x: (
                0 if "whole.html" in (x.get("original_url") or "") else 1,
                KIND_RANK.get(x.get("kind"), 9),
                x.get("year") or "",
                x.get("number") or "",
            ))
            return items
    items: list[dict] = []
    key = api_key()
    if key:
        log.info("using PCO API v0 (key present, not logged)")
        items = discover_via_api(key)
        log.info("api discovered %s", len(items))
    else:
        log.info("no PCO API key; using official XML/catalogue via Wayback CDX of legislation.govt.nz")
    if len(items) < 50:
        cdx_items = discover_via_cdx()
        seen = {it["work_key"] for it in items}
        for it in cdx_items:
            if it["work_key"] not in seen:
                seen.add(it["work_key"])
                items.append(it)
    items.sort(key=lambda x: (KIND_RANK.get(x.get("kind"), 9), x.get("year") or "", x.get("number") or ""))
    for it in items:
        append_catalog(CC, it)
    log.info("discovered %s works", len(items))
    return items


def nz_provisions(xml_raw: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    try:
        root = ET.fromstring(xml_raw)
    except ET.ParseError:
        return []
    docs = []
    seen = set()
    for el in root.iter():
        tag = localtag(el.tag).lower()
        if tag not in {"prov", "schedule", "form"}:
            continue
        if tag != "prov":
            continue
        label = ""
        heading = ""
        for child in list(el):
            ct = localtag(child.tag).lower()
            if ct == "label" and (child.text or "").strip():
                label = (child.text or "").strip()
            elif ct in {"heading", "head", "title"}:
                heading = "".join(child.itertext()).strip()
        text = xml_to_text(ET.tostring(el, encoding="unicode"))
        if not text or len(text) < 20:
            continue
        num = label or f"prov{len(docs)+1}"
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-s-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        title = (f"{num} {heading}").strip()[:500]
        docs.append({
            "id": doc_id,
            "title": title,
            "text": text,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "article_heading": heading,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "pco_xml_prov"}},
        })
        if len(docs) >= 4000:
            break
    return docs



_NZ_MONTHS = {
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
}
_NZ_SEC_RE = re.compile(r"(?m)^(\d+[A-Za-z]{0,3})\s+([A-Z][^\n]{2,160})$")
_NZ_TITLE_RE = re.compile(r"Act\s+\d{4}", re.I)


def html_page_title(text: str) -> Optional[str]:
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        ln = re.sub(r"\s*[–—-]\s*New Zealand Legislation\s*$", "", ln).strip()
        if _NZ_TITLE_RE.search(ln) and 12 <= len(ln) <= 300:
            return ln
        return None
    return None


def nz_sections_from_text(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    """Split PCO HTML-extracted text on same-line numbered headings (body, not TOC)."""
    if not text:
        return []
    start = text.find("1 Short Title")
    if start < 0:
        start = text.find("1 Title")
    body = text[start:] if start >= 0 else text
    matches = []
    for m in _NZ_SEC_RE.finditer(body):
        heading = m.group(2).strip()
        first = heading.split()[0] if heading.split() else ""
        if first in _NZ_MONTHS or heading.lower().startswith("no "):
            continue
        if heading.lower() in {"contents", "reprint", "public act"}:
            continue
        matches.append(m)
    if len(matches) < 2:
        return []
    docs = []
    seen = set()
    for i, m in enumerate(matches):
        chunk = body[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(body))].strip()
        if len(chunk) < 20:
            continue
        num = m.group(1)
        heading = m.group(2).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-s-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{i}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": f"{num} {heading}".strip()[:500],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "article_heading": heading,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "pco_html_heading"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def _decode_res(res: dict) -> str:
    raw = res.get("text") or ""
    if not raw.strip():
        body = res.get("content") or b""
        if isinstance(body, (bytes, bytearray)):
            raw = bytes(body).decode("utf-8", "replace")
    return raw or ""


def _usable(raw: str, res: dict) -> tuple[str, str]:
    """Return (text, xml_raw). xml_raw empty when the body is HTML."""
    if not raw or af.is_challenge(raw, res.get("http_status") or 200):
        return "", ""
    ctype = (res.get("content_type") or "").lower()
    if "pdf" in ctype or raw[:5] == "%PDF-":
        return "", ""
    head = raw.lstrip()[:120].lower()
    is_xml = (
        head.startswith("<?xml")
        or head.startswith("<act")
        or head.startswith("<regulation")
        or ("xml" in ctype and "html" not in ctype and "html" not in head[:80])
    )
    if is_xml:
        text = xml_to_text(raw)
        if text and len(text) >= 40:
            return text, raw
    text = html_to_text(raw)
    if text and len(text) >= 40:
        return text, ""
    return "", ""


def fetch_body(it: dict) -> tuple[str, str, str, Optional[str]]:
    """Return (text, xml_raw, source_url, method). Live site is WAF; HTML Wayback only."""
    kind, year, num = it["kind"], it["year"], it["number"]
    ts = str(it.get("wayback_ts") or "") or None
    orig = (it.get("original_url") or "").split("?")[0].strip()
    candidates: list[str] = []

    def add(u: str) -> None:
        if u and u not in candidates:
            candidates.append(u)

    # Skip PDF originals (historical scans 404 or have no text layer).
    if orig and not orig.lower().endswith(".pdf"):
        add(orig)
        if orig.startswith("http://"):
            add("https://" + orig[7:])
        elif orig.startswith("https://"):
            add("http://" + orig[8:])
    for url in html_urls(kind, year, num):
        add(url)

    tried_no_ts: set[str] = set()
    for url in candidates:
        res = af.get_wayback_content(url, timestamp=ts)
        if res.get("status") != "success" and ts:
            res = af.get_wayback_content(url)
            tried_no_ts.add(url)
        if res.get("status") != "success":
            continue
        text, xml_raw = _usable(_decode_res(res), res)
        if text:
            method = "wayback_xml" if xml_raw else (res.get("method") or "wayback")
            return text, xml_raw, url, method
    # Last resort: XML snapshots (CDX often 504; keep short).
    for url in xml_urls(kind, year, num)[:2]:
        res = af.get_wayback_content(url)
        if res.get("status") != "success":
            continue
        text, xml_raw = _usable(_decode_res(res), res)
        if text:
            return text, xml_raw, url, "wayback_xml" if xml_raw else (res.get("method") or "wayback")
    return "", "", "", None


def xml_title(xml_raw: str) -> Optional[str]:
    if not xml_raw:
        return None
    try:
        root = ET.fromstring(xml_raw)
    except ET.ParseError:
        return None
    for tag in ("title", "cover", "fulltitle", "name"):
        for el in root.iter():
            if localtag(el.tag).lower() == tag:
                t = "".join(el.itertext()).strip()
                if t and len(t) > 4:
                    return re.sub(r"\s+", " ", t)[:500]
    return None


def fetch_one(it: dict, done: set[str]) -> str:
    wk = it.get("work_key") or ""
    if not wk:
        return "fail"
    rid = slug_id(CC, wk.replace("/", "-"))
    if rid in done:
        return "skip"
    text, xml_raw, src, method = fetch_body(it)
    if not text:
        log_failure(CC, {"identifier": wk, "source_url": canonical_url(it["kind"], it["year"], it["number"]),
                         "status": "failed", "reason": "empty_text"})
        return "fail"
    title = it.get("title") if it.get("title") and it["title"] != wk else None
    title = xml_title(xml_raw) or html_page_title(text) or title or wk
    date = None
    docs = nz_provisions(xml_raw, rid, src, date) if xml_raw else []
    if len(docs) < 2:
        docs = nz_sections_from_text(text, rid, src, date)
    if len(docs) < 2:
        docs = split_articles(text, rid, src, date)
    kind = it.get("kind") or ""
    doc_type = "regulation" if kind.startswith("regulation") else "statute"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=wk.replace("/", "-"), title=title, text=text,
        source_url=src or canonical_url(it["kind"], it["year"], it["number"]),
        source_type=SOURCE_TYPE, license_text=LICENSE, collector="nz-pco-legislation",
        eli=None, date=date, official_identifier=f"{it.get('kind')} {it.get('year')} No {int(it.get('number') or 0)}",
        document_type=doc_type, law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": it.get("discovery") or "wayback_cdx",
                "catalog_identifier": wk,
                "seed_url": PORTAL,
                "wayback_ts": it.get("wayback_ts"),
                "fetch_method": method,
            },
            "official_metadata": {
                "kind": kind,
                "year": it.get("year"),
                "number": it.get("number"),
                "work_key": wk,
            },
        },
        extra_fields={
            "canonical_title": title,
            "canonical_document_url": canonical_url(it["kind"], it["year"], it["number"]),
            "information_url": f"{PORTAL}/{kind}/{it['year']}/{it['number']}/latest/",
        },
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    n_act = sum(1 for x in items if str(x.get("kind") or "").startswith("act/"))
    n_reg = sum(1 for x in items if x.get("kind") == "regulation")
    log.info("queue acts=%s regulations=%s already_done=%s", n_act, n_reg, len(done))
    source_urls = [
        "https://www.legislation.govt.nz/",
        "https://api.legislation.govt.nz/docs/",
        "https://catalogue.data.govt.nz/dataset/new-zealand-legislation",
    ]
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
                    CC, country=COUNTRY, source="Parliamentary Counsel Office / legislation.govt.nz",
                    source_urls=source_urls, license_text=LICENSE,
                    discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="Official PCO XML/HTML via Wayback CDX of legislation.govt.nz (live WAF).",
                    last_run=utcnow(),
                )
    cov = "full" if fail == 0 and items and ok + skip >= len(items) else "catalog-backed incomplete"
    notes = (
        f"PCO-drafted New Zealand legislation. Live legislation.govt.nz returned AWS WAF challenge; "
        f"bodies from archive.org CDX of official URLs (XML preferred). "
        f"No API key present so v0 API not used. /subscribe not scraped. "
        f"Catalog acts={n_act} regulations={n_reg}. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY, source="Parliamentary Counsel Office / legislation.govt.nz",
        source_urls=source_urls, license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, cov)


if __name__ == "__main__":
    main()
