#!/usr/bin/env python3
"""Saudi Arabia: in-force laws (الأنظمة) from Bureau of Experts at the Council of Ministers.

Official portal https://laws.boe.gov.sa/ currently fails TLS from this environment.
Collector uses Wayback CDX of official laws.boe.gov.sa URLs only (no Cloudflare
browser rendering, no WAF bypass, no commercial aggregators).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
from archive_fallbacks import get_wayback_content, search_wayback_machine

CC = "sa"
COUNTRY = "Saudi Arabia"
SOURCE_TYPE = "boe_laws"
LICENSE = (
    "Research snapshot of official Saudi Bureau of Experts (هيئة الخبراء بمجلس الوزراء) "
    "law texts. Reuse is governed by BOE / Saudi government terms. license: other. "
    "Not legal advice; the official BOE / Umm Al-Qura text prevails."
)
UA = DEFAULT_UA + " source=https://laws.boe.gov.sa/"
WORKERS = 3
SLEEP = 0.5
log = logging.getLogger("sa")
GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
ART_AR = re.compile(r"(?im)^\s*((?:المادة|مادة)\s+(?:الأولى|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة|التاسعة|العاشرة|الحادية عشرة|[0-9\u0660-\u0669]+))")
STATUS_CURRENT = re.compile(r"ساري(?:\s+المفعول)?")
STATUS_REPEALED = re.compile(r"ملغ[ىي]|لاغي")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def dump_jsonl(path: Path, rows):
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def load_jsonl(path: Path):
    if not path.exists() or path.stat().st_size < 20:
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def extract_guid(url: str) -> Optional[str]:
    m = GUID_RE.search(unquote(url or ""))
    return m.group(1).lower() if m else None


def lang_from_url(url: str) -> str:
    u = unquote(url or "").rstrip("/")
    if u.endswith("/2"):
        return "en"
    return "ar"


def discover() -> list[dict]:
    dest = ROOT / CC / "raw" / "catalog.jsonl"
    cached = load_jsonl(dest)
    if cached:
        log.info("resume catalog %s", len(cached))
        return cached
    recs = search_wayback_machine(
        "https://laws.boe.gov.sa/BoeLaws/Laws/LawDetails/",
        match_type="prefix", limit=1200, collapse="urlkey",
        extra_filters=["mimetype:text/html"],
    )
    log.info("wayback cdx rows=%s", len(recs))
    best = {}
    for rec in recs:
        orig = rec.get("original") or ""
        guid = extract_guid(orig)
        if not guid:
            continue
        lang = lang_from_url(orig)
        key = (guid, lang)
        try:
            length = int(rec.get("length") or 0)
        except Exception:
            length = 0
        ts = rec.get("timestamp") or ""
        prev = best.get(key)
        score = (length, ts)
        if prev is None or score > (prev["length"], prev["timestamp"]):
            best[key] = {
                "guid": guid, "lang": lang, "original": orig,
                "timestamp": ts, "length": length,
                "wayback_url": rec.get("wayback_url"),
                "mimetype": rec.get("mimetype"),
            }
    items = list(best.values())
    # Arabic in-force pages first
    items.sort(key=lambda x: (0 if x["lang"] == "ar" else 1, -x["length"]))
    dump_jsonl(dest, items)
    log.info("unique law versions %s", len(items))
    return items


def parse_title(html: str) -> str:
    m = re.search(r"<title>\s*([^<]+)", html, re.I)
    title = (m.group(1) if m else "").strip()
    title = re.sub(r"\s+", " ", title)
    if title and title not in ("تفاصيل النظام", "Law Details", "BOE"):
        return title
    for pat in (r'class="[^"]*law-title[^"]*"[^>]*>([^<]{5,200})',
                r"<h1[^>]*>([^<]{5,200})</h1>",
                r"<h2[^>]*>([^<]{5,200})</h2>"):
        m = re.search(pat, html, re.I)
        if m:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            if t:
                return t
    return ""


def law_status(html: str) -> tuple[str, Optional[bool]]:
    # Look near الحالة
    head = html[:25000]
    if STATUS_REPEALED.search(head) and not STATUS_CURRENT.search(head):
        return "repealed", False
    if "ساري" in head:
        return "current", True
    return "unknown", None


def split_ar(text, law_id, source_url, date):
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_AR.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i+1].start() if i+1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({"id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
                    "date_filed": date, "document_number": num, "source_url": source_url,
                    "record_type": "article", "article_number": num, "law_identifier": law_id,
                    "metadata": {"text_extraction": {"source": "official", "backend": "wayback-boe"}}})
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def fetch_one(it: dict, done: set) -> str:
    guid = it.get("guid")
    lang = it.get("lang") or "ar"
    ident = f"{guid}-{lang}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    orig = it.get("original") or f"https://laws.boe.gov.sa/BoeLaws/Laws/LawDetails/{guid}/1"
    ts = it.get("timestamp")
    res = get_wayback_content(orig, timestamp=ts)
    html = ""
    src = orig
    if res.get("status") == "success":
        html = res.get("text") or ""
        src = res.get("wayback_url") or orig
    if len(html) < 400:
        log_failure(CC, {"identifier": ident, "source_url": orig, "status": "failed", "reason": "empty_wayback"})
        return "fail"
    text = html_to_text(html)
    if len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": orig, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = parse_title(html) or ident
    st, is_cur = law_status(html)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title, text=text,
        source_url=orig, source_type=SOURCE_TYPE, license_text=LICENSE, collector="sa-boe",
        official_identifier=guid, document_type="statute", law_status=st, is_current=is_cur,
        documents=split_ar(text, rid, orig, None),
        extra_meta={"discovery": {"method": "wayback_cdx", "timestamp": ts, "guid": guid},
                    "archive": {"wayback_url": src, "capture_timestamp": ts},
                    "text_extraction": {"source": "archive-of-official", "backend": "wayback"}},
    )
    rec["canonical_law_url"] = orig
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    # Arabic first; skip tiny shells
    items = [x for x in items if x.get("length", 0) >= 4000 or x.get("lang") == "ar"]
    done = existing_ids(CC)
    ok = skip = fail = 0
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
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 25 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(CC, country=COUNTRY, source="BOE laws.boe.gov.sa via Wayback of official URLs",
                              source_urls=["https://laws.boe.gov.sa/", "https://www.boe.gov.sa/"],
                              license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="Wayback of official LawDetails", last_run=utcnow())
    notes = (
        "Official BOE portal laws.boe.gov.sa TLS-failed from this collector host. "
        "Harvested Wayback CDX of official LawDetails URLs only (no commercial DBs, no WAF bypass). "
        "Arabic (/1) preferred; English (/2) kept when archived. Live portal not crawled. "
        "In-force (ساري) inferred from archived HTML when present."
    )
    write_summary(CC, country=COUNTRY, source="Bureau of Experts at the Council of Ministers (Wayback of official URLs)",
                  source_urls=["https://laws.boe.gov.sa/", "https://laws.boe.gov.sa/BoeLaws/Laws/Search"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="wayback-of-official snapshot", notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
