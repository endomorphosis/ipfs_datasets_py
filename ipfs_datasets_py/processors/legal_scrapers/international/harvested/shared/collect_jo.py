#!/usr/bin/env python3
"""Jordan: Constitution + laws from the Legislation and Opinion Bureau.

Official source only:
  https://www.lob.gov.jo  (and historical http://www.lob.gov.jo/ui/laws/)
  User-facing www.lob.jo does not resolve; lob.gov.jo is the official host.
  Law texts: /ui/laws/general_law.jsp?no=N&year=YYYY
  Index:     /ui/laws/search_no.jsp?no=N&year=YYYY
  Constitution: general_law.jsp?no=0&year=1952 (الدستور الاردني)

Live lob.gov.jo returns WAF "Request Rejected" from this host — not bypassed.
On 429/403/WAF of official URLs, archive_fallbacks.py of those official URLs only.
No commercial DBs (not Lexis Middle East).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "jo"
COUNTRY = "Jordan"
SOURCE_TYPE = "lob_jordan"
LICENSE = (
    "Official texts of the Hashemite Kingdom of Jordan as published by the "
    "Legislation and Opinion Bureau (lob.gov.jo). The Official Gazette "
    "(الجريدة الرسمية) prevails over this research snapshot. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.lob.gov.jo/"
PORTAL = "https://www.lob.gov.jo/"
WORKERS = 2
SLEEP = 0.5
log = logging.getLogger("jo")
ART_AR = re.compile(
    r"(?im)^\s*((?:المادة|مادة)\s+(?:[0-9\u0660-\u0669]+|الأولى|الثانية|الثالثة|الرابعة|الخامسة))"
)
NO_YEAR = re.compile(r"[?&]no=(\d+)&year=(\d{4})|[?&]year=(\d{4})&no=(\d+)", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def canon_lob(url: str) -> str:
    if not url:
        return url
    u = url.replace("https://www.lob.gov.jo", "http://www.lob.gov.jo")
    u = u.replace("https://lob.gov.jo", "http://www.lob.gov.jo")
    u = u.replace("http://lob.gov.jo", "http://www.lob.gov.jo")
    u = u.replace("http://www.lob.gov.jo:80", "http://www.lob.gov.jo")
    u = u.split("#")[0]
    return u


def parse_no_year(url: str) -> tuple[Optional[str], Optional[str]]:
    q = parse_qs(urlparse(url).query)
    no = (q.get("no") or [None])[0]
    year = (q.get("year") or [None])[0]
    if no is not None and year is not None:
        return str(no), str(year)
    m = NO_YEAR.search(url or "")
    if not m:
        return None, None
    if m.group(1) is not None:
        return m.group(1), m.group(2)
    return m.group(4), m.group(3)


def official_get(url: str, *, timestamp: Optional[str] = None, retries: int = 1) -> dict:
    url = canon_lob(url)
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=retries, timeout=(20, 60),
                     headers={"Accept": "text/html, application/pdf, */*",
                              "Accept-Language": "ar,en;q=0.8"})
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content:
        text = r.text or ""
        if r.content[:4] == b"%PDF":
            return {"ok": True, "content": r.content, "text": "", "method": "live",
                    "final_url": r.url or url}
        if not af.is_challenge(text, r.status_code) and "Request Rejected" not in text and len(r.content) >= 400:
            return {"ok": True, "content": r.content, "text": text, "method": "live",
                    "final_url": r.url or url}
        log.info("live challenge/WAF %s — archive of official URL", url)
    if r is not None and r.status_code == 429:
        log.info("HTTP 429 %s — archive_fallbacks", url)
    wb = af.get_wayback_content(url, timestamp=timestamp)
    if wb.get("status") == "success" and (wb.get("text") or wb.get("content")):
        return {
            "ok": True, "content": wb.get("content") or b"",
            "text": wb.get("text") or "", "method": "wayback",
            "final_url": wb.get("wayback_url") or url,
        }
    res = af.fetch_with_fallbacks(
        url, try_http=False, try_cc=False, try_archive_is=False, wayback_ts=timestamp,
    )
    if res.get("status") == "success" and (res.get("text") or res.get("content")):
        return {
            "ok": True, "content": res.get("content") or b"",
            "text": res.get("text") or "",
            "method": res.get("method") or "archive",
            "final_url": res.get("wayback_url") or url,
        }
    err = "archive_fail"
    if r is not None:
        err = f"http_{r.status_code}"
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
            "metadata": {"text_extraction": {"source": "official", "backend": "jo"}},
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
            key = f"{row.get('no')}-{row.get('year')}"
            if key in seen or not row.get("year"):
                continue
            seen.add(key)
            items.append(row)
    return items


def add_item(items, seen, row: dict):
    key = f"{row.get('no')}-{row.get('year')}"
    if not row.get("year") or key in seen:
        if key in seen and row.get("wayback_ts"):
            for it in items:
                if f"{it.get('no')}-{it.get('year')}" == key and not it.get("wayback_ts"):
                    it["wayback_ts"] = row["wayback_ts"]
                    if "general_law" in (row.get("url") or "") and "general_law" not in (it.get("url") or ""):
                        it["url"] = row["url"]
        return
    seen.add(key)
    items.append(row)
    append_catalog(CC, row)


def law_title(html: str, fallback: str) -> str:
    text = html_to_text(html or "")
    m = re.search(r"(?:اسم القانون\s*:?\s*)([^\n]{5,180})", text)
    if m:
        t = m.group(1).strip(" :")
        if t:
            return t[:220]
    # constitution
    if "الدستور الاردني" in text or "الدستور الأردني" in text:
        return "الدستور الأردني"
    m = re.search(r"(قانون[^\n]{3,160})", text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:220]
    return fallback


def discover() -> list[dict]:
    items = load_catalog()
    seen = {f"{x.get('no')}-{x.get('year')}" for x in items}
    add_item(items, seen, {
        "no": "0", "year": "1952", "kind": "constitution",
        "url": "http://www.lob.gov.jo/ui/laws/general_law.jsp?no=0&year=1952&mod=0",
        "title": "الدستور الأردني",
        "source": "known_constitution",
        "wayback_ts": "20070525005701",
    })
    if len(items) >= 80:
        log.info("resume catalog %s", len(items))
        return items
    queries = [
        ("www.lob.gov.jo/ui/laws/general_law.jsp", 900),
        ("www.lob.gov.jo/ui/laws/search_no.jsp", 900),
        ("lob.gov.jo/ui/laws/general_law.jsp", 400),
        ("www.lob.gov.jo/ui/laws/after_modification.jsp", 400),
    ]
    for prefix, lim in queries:
        recs = af.search_wayback_machine(prefix, match_type="prefix", limit=lim,
                                         extra_filters=["mimetype:text/html"])
        log.info("cdx %s n=%s", prefix, len(recs))
        for rec in recs:
            orig = canon_lob(rec.get("original") or "")
            if "laalaws" in orig or "lexis" in orig.lower():
                continue
            no, year = parse_no_year(orig)
            if no is None or year is None:
                continue
            no = re.sub(r"[^0-9].*$", "", str(no).strip())
            year = re.sub(r"[^0-9].*$", "", str(year).strip())
            if not no or not year:
                continue
            try:
                if int(year) < 1921 or int(year) > 2026:
                    continue
            except ValueError:
                continue
            kind = "constitution" if (no == "0" and year == "1952") else "statute"
            # prefer general_law fetch URL
            fetch_url = (
                f"http://www.lob.gov.jo/ui/laws/general_law.jsp?no={no}&year={year}&mod=0"
            )
            if "general_law.jsp" in orig:
                fetch_url = orig
            add_item(items, seen, {
                "no": no, "year": year, "kind": kind, "url": fetch_url,
                "wayback_ts": rec.get("timestamp"),
                "title": "", "source": "cdx",
            })
    log.info("discovered %s", len(items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    no, year = str(it.get("no")), str(it.get("year"))
    if not year:
        return "fail"
    ident = "constitution-1952" if it.get("kind") == "constitution" or (no == "0" and year == "1952") else f"law-{no}-{year}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = it.get("url") or f"http://www.lob.gov.jo/ui/laws/general_law.jsp?no={no}&year={year}&mod=0"
    url = canon_lob(url)
    got = official_get(url, timestamp=it.get("wayback_ts"))
    html = got.get("text") or ""
    if (not got.get("ok") or len(html) < 400) and "general_law" in url:
        alt = f"http://www.lob.gov.jo/ui/laws/search_no.jsp?no={no}&year={year}"
        got2 = official_get(alt, timestamp=it.get("wayback_ts"))
        if got2.get("ok") and len(got2.get("text") or "") > len(html):
            got, html, url = got2, got2.get("text") or "", alt
    if len(html) < 200:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed",
                         "reason": got.get("error") or "empty_html"})
        return "fail"
    title = law_title(html, it.get("title") or f"قانون رقم {no} لسنة {year}")
    text = html_to_text(html)
    # drop chrome
    for needle in ("المادة 1", "المادة الأولى", "مادة (1)", "نحن ", "باسم الله"):
        idx = text.find(needle)
        if idx > 0 and idx < 6000:
            text = text[idx:]
            break
    if len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed",
                         "reason": "empty_text", "title": title})
        return "fail"
    date = iso_date(f"{year}-01-01")
    docs = split_ar(text, rid, url, date)
    is_const = it.get("kind") == "constitution" or "دستور" in title
    rec = base_record(
        cc=CC, country=COUNTRY, language="ar", ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_jo.py", date=date, official_identifier=f"{no}/{year}",
        document_type="constitution" if is_const else "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": it.get("source") or "lob_cdx", "no": no, "year": year,
                          "retrieval": got.get("method")},
            "retrieval": {"method": got.get("method") or "archive",
                          "used_url": got.get("final_url") or url},
            "text_extraction": {"source": "official", "backend": f"html-{(got.get('method') or 'archive')}"},
        },
    )
    rec["languages"] = ["ar"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    def _n(v):
        s = re.sub(r"[^0-9].*$", "", str(v or "").strip())
        try:
            return int(s) if s else 0
        except ValueError:
            return 0
    items = sorted(items, key=lambda x: (
        0 if x.get("kind") == "constitution" or (str(x.get("no")) == "0" and str(x.get("year")) == "1952") else 1,
        _n(x.get("year")), _n(x.get("no")),
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
            if n % 20 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="Legislation and Opinion Bureau (lob.gov.jo)",
                    source_urls=[PORTAL, "http://www.lob.gov.jo/ui/laws/"],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Constitution + laws from official LOB URLs via live or Wayback.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "national-laws snapshot"
    notes = (
        "Constitution (1952) and national laws from official lob.gov.jo "
        "(/ui/laws/general_law.jsp). www.lob.jo does not resolve. Live site "
        "returns WAF Request Rejected from this host (not bypassed); texts via "
        "Wayback/Common Crawl of official LOB URLs. Not Lexis/commercial. "
        f"429/403 uses archive_fallbacks of official URLs. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Legislation and Opinion Bureau (lob.gov.jo)",
        source_urls=[PORTAL, "http://www.lob.gov.jo/ui/laws/",
                     "http://www.lob.gov.jo/ui/laws/general_law.jsp?no=0&year=1952&mod=0"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
