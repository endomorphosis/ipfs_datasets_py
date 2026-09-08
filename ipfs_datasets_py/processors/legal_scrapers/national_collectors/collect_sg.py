#!/usr/bin/env python3
"""Singapore: current Acts from Singapore Statutes Online (AGC Legislation Division).

Official only:
  https://sso.agc.gov.sg/
  Browse: https://sso.agc.gov.sg/Browse/Act/Current
  Act pages: https://sso.agc.gov.sg/Act/{code}  e.g. /Act/CoA1967

robots.txt: Disallow: /search ; crawl-delay: 6
This collector never hits /search. No Cloudflare browser rendering.

Live CloudFront often blocks the collector UA (403/429). Fallback is
ipfs_datasets_py-style archives of official sso.agc.gov.sg URLs only:
  Common Crawl WARC -> Wayback replay -> archive.is
Never letter-by-letter Wayback CDX (A-Z prefix loop).
SSO is an unofficial reproduction; printed Gazette / AGC official text prevails.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "sg"
COUNTRY = "Singapore"
SOURCE_TYPE = "sso_agc_html"
LICENSE = (
    "Singapore Statutes Online (sso.agc.gov.sg) is an unofficial reproduction "
    "published by the Legislation Division of the Attorney-General's Chambers. "
    "The printed Gazette and AGC official text prevail. Research snapshot with "
    "provenance. Not legal advice."
)
UA = DEFAULT_UA + " source=https://sso.agc.gov.sg/"
PORTAL = "https://sso.agc.gov.sg/"
BROWSE = "https://sso.agc.gov.sg/Browse/Act/Current"
ACT_RE = re.compile(
    r"^https://sso\.agc\.gov\.sg/Act/([A-Za-z][A-Za-z0-9]{1,60}\d{4})$"
)
ACT_FROM_PATH = re.compile(
    r"https://sso\.agc\.gov\.sg/Act/([A-Za-z][A-Za-z0-9]{1,60}\d{4})(?:/|$)",
    re.I,
)
WORKERS = 4
SLEEP = 6.0
EXPECTED_ACTS = 524
log = logging.getLogger("sg")
_live_blocked = threading.Event()


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def normalize_act_url(url: str) -> Optional[str]:
    if not url:
        return None
    raw = (url or "").split("?")[0].split("#")[0].rstrip("/")
    raw = raw.replace("http://", "https://")
    if "/Historical" in raw or "/Act-Rev" in raw:
        return None
    m = ACT_FROM_PATH.search(raw)
    if not m:
        return None
    return f"https://sso.agc.gov.sg/Act/{m.group(1)}"


def act_code_from_url(url: str) -> Optional[str]:
    nu = normalize_act_url(url)
    if not nu:
        return None
    m = ACT_RE.match(nu)
    return m.group(1) if m else None


def live_get(url: str) -> Optional[str]:
    if _live_blocked.is_set():
        return None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=1,
                     headers={"Accept": "text/html, */*"})
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        return None
    if r.status_code in (403, 429) or af.is_challenge(r.text or "", r.status_code):
        _live_blocked.set()
        log.info("live blocked HTTP %s %s — skip further live fetches", r.status_code, url)
        return None
    if r.status_code != 200 or not r.text:
        log.info("live HTTP %s %s", r.status_code, url)
        return None
    return r.text


def parse_act_links(html: str) -> list[str]:
    urls = []
    seen = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or ""):
        if href.startswith("/Act/"):
            href = "https://sso.agc.gov.sg" + href
        nu = normalize_act_url(href)
        if nu and nu not in seen:
            seen.add(nu)
            urls.append(nu)
    return urls


def slim_cc_record(rec: dict) -> Optional[dict]:
    fn = rec.get("filename") or rec.get("warc_filename")
    if not fn:
        return None
    return {
        "filename": fn,
        "offset": rec.get("offset") or rec.get("warc_offset"),
        "length": rec.get("length") or rec.get("warc_length"),
        "timestamp": rec.get("timestamp"),
        "url": rec.get("url") or rec.get("original"),
        "original": rec.get("original") or rec.get("url"),
    }


def add_item(items: list[dict], seen: dict, url: str, extra: dict) -> bool:
    nu = normalize_act_url(url)
    code = act_code_from_url(nu or "")
    if not nu or not code:
        return False
    key = nu.lower()
    prev = seen.get(key)
    if prev is None:
        row = {"code": code, "url": nu, **extra}
        items.append(row)
        seen[key] = row
        append_catalog(CC, {k: v for k, v in row.items() if k != "cc_record"})
        return True
    if extra.get("cdx_ts") and not prev.get("cdx_ts"):
        prev["cdx_ts"] = extra["cdx_ts"]
    if extra.get("cc_record") and not prev.get("cc_record"):
        prev["cc_record"] = extra["cc_record"]
    if extra.get("wayback_url") and not prev.get("wayback_url"):
        prev["wayback_url"] = extra["wayback_url"]
    return False


def load_catalog() -> tuple[list[dict], dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    seen: dict = {}
    if not cat.exists() or cat.stat().st_size < 200:
        return items, seen
    with cat.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            nu = normalize_act_url(row.get("url") or "")
            code = row.get("code") or act_code_from_url(nu or "")
            if not nu or not code or not re.search(r"\d{4}$", str(code)):
                continue
            key = nu.lower()
            if key in seen:
                prev = seen[key]
                if row.get("cdx_ts") and not prev.get("cdx_ts"):
                    prev["cdx_ts"] = row["cdx_ts"]
                if row.get("cc_record") and not prev.get("cc_record"):
                    prev["cc_record"] = row["cc_record"]
                continue
            row["code"] = code
            row["url"] = nu
            items.append(row)
            seen[key] = row
    return items, seen


def rewrite_catalog(items: list[dict]) -> None:
    path = ROOT / CC / "raw" / "catalog.jsonl"
    slim = []
    for it in items:
        row = {k: v for k, v in it.items() if k != "cc_record"}
        cr = slim_cc_record(it.get("cc_record") or {})
        if cr:
            row["cc_record"] = cr
        slim.append(row)
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in slim))


def expand_catalog_once(items: list[dict], seen: dict) -> None:
    """ONE Common Crawl index search + ONE Wayback prefix query. Not A-Z letters."""
    log.info("catalog needs more unique=%s expected~%s; one CC + one Wayback prefix",
             len(items), EXPECTED_ACTS)
    time.sleep(8.0)
    cc_hits = []
    try:
        cc_hits = af.search_common_crawl("sso.agc.gov.sg/Act*", limit=800)
        log.info("common crawl hits=%s", len(cc_hits))
    except Exception as exc:
        log.warning("cc search: %s", exc)
    added_cc = 0
    for rec in cc_hits:
        orig = rec.get("original") or rec.get("url") or ""
        extra = {"source": "common_crawl"}
        cr = slim_cc_record(rec)
        if cr:
            extra["cc_record"] = cr
            extra["cc_index"] = rec.get("cc_index")
        if add_item(items, seen, orig, extra):
            added_cc += 1
        elif cr:
            nu = normalize_act_url(orig)
            if nu and seen.get(nu.lower()) is not None and not seen[nu.lower()].get("cc_record"):
                seen[nu.lower()]["cc_record"] = cr
    log.info("cc extra new=%s total=%s", added_cc, len(items))

    time.sleep(12.0)
    recs = []
    try:
        recs = af.search_wayback_machine(
            "sso.agc.gov.sg/Act/",
            match_type="prefix",
            limit=800,
            collapse="urlkey",
            filter_status="200",
            extra_filters=["original:.*sso.agc.gov.sg/Act/[A-Za-z][A-Za-z0-9]*[0-9]{4}$"],
        )
    except Exception as exc:
        log.warning("wayback prefix: %s", exc)
    added_wb = 0
    for rec in recs:
        orig = rec.get("original") or ""
        extra = {
            "source": "wayback_prefix",
            "cdx_ts": rec.get("timestamp"),
            "wayback_url": rec.get("wayback_url"),
        }
        if add_item(items, seen, orig, extra):
            added_wb += 1
    log.info("wayback prefix new=%s hits=%s total=%s", added_wb, len(recs), len(items))


def discover() -> list[dict]:
    items, seen = load_catalog()
    if items:
        log.info("resume catalog unique=%s (letter-CDX will not run)", len(items))
        if len(items) < 200:
            expand_catalog_once(items, seen)
            rewrite_catalog(items)
        return items
    for page in range(0, 40):
        url = f"https://sso.agc.gov.sg/Browse/Act/Current/All/{page}?PageSize=20"
        html = live_get(url)
        if not html:
            if page == 0:
                html = live_get(BROWSE)
            if not html:
                break
        newc = 0
        for href in parse_act_links(html):
            if add_item(items, seen, href, {"source": "live_browse"}):
                newc += 1
        log.info("live browse page=%s new=%s total=%s", page, newc, len(items))
        if newc == 0 and page > 0:
            break
    if len(items) < EXPECTED_ACTS:
        expand_catalog_once(items, seen)
    rewrite_catalog(items)
    log.info("catalog discovered %s", len(items))
    return items


def extract_provisions(html: str, law_id: str, source_url: str, date: Optional[str]) -> tuple[str, list[dict], str]:
    title = ""
    m = re.search(r"<title>\s*([^<]+?)\s*-\s*Singapore Statutes Online", html, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    if not title:
        m = re.search(r'class="legis-title"[^>]*>([^<]{3,200})', html, re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
    docs = []
    parts = []
    blocks = re.findall(
        r'(<div[^>]*class="[^"]*prov1[^"]*"[^>]*>[\s\S]*?)(?=<div[^>]*class="[^"]*prov1[^"]*"|$)',
        html, re.I,
    )
    if not blocks:
        blocks = re.findall(
            r'(<div[^>]*class="[^"]*prov1Hdr[^"]*"[^>]*>[\s\S]*?)(?=<div[^>]*class="[^"]*prov1Hdr[^"]*"|$)',
            html, re.I,
        )
    seen = set()
    for i, block in enumerate(blocks):
        hdr_m = re.search(r'class="[^"]*prov1Hdr[^"]*"[^>]*>([\s\S]*?)</div>', block, re.I)
        hdr = html_to_text(hdr_m.group(1) if hdr_m else "")
        body = html_to_text(block)
        if not body or len(body) < 8:
            continue
        parts.append(body)
        nm = re.match(r"^\s*(\d+[A-Za-z]?)", hdr or body)
        num = nm.group(1) if nm else str(i + 1)
        heading = (hdr or body.split("\n", 1)[0])[:200]
        aid = re.sub(r"[^a-z0-9]+", "-", f"s{num}").strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{i+1}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id, "title": heading, "text": body, "date_filed": date,
            "document_number": num, "source_url": source_url, "record_type": "article",
            "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "sso_prov1_html"}},
        })
        if len(docs) >= 4000:
            break
    text = "\n\n".join(parts)
    if not text or len(text) < 80:
        cleaned = re.sub(r"(?is)<nav\b.*?</nav>", " ", html)
        cleaned = re.sub(r"(?is)<header\b.*?</header>", " ", cleaned)
        cleaned = re.sub(r"(?is)<footer\b.*?</footer>", " ", cleaned)
        text = html_to_text(cleaned)
        if "Singapore Statutes Online" in text:
            lm = re.search(r'(<div[^>]*class="[^"]*legis[^"]*"[^>]*>[\s\S]{200,})', html, re.I)
            if lm:
                text = html_to_text(lm.group(1))
        docs = split_articles(text, law_id, source_url, date)
    return text, docs, title


def fetch_one(it: dict, done: set[str]) -> str:
    code = (it.get("code") or "").strip()
    url = it.get("url") or f"https://sso.agc.gov.sg/Act/{code}"
    url = normalize_act_url(url) or url
    if not code:
        code = act_code_from_url(url) or ""
    if not code:
        return "fail"
    rid = slug_id(CC, code)
    if rid in done:
        return "skip"
    html = live_get(url)
    method = "live"
    backend = "live"
    wb_meta: dict = {}
    if not html or af.is_spa_shell(html, html_to_text(html or "")):
        res = af.fetch_with_fallbacks(
            url,
            cc_record=it.get("cc_record"),
            wayback_ts=it.get("cdx_ts"),
            try_archive_is=True,
            try_http=False,
            try_cc=bool(it.get("cc_record")),
        )
        if res.get("status") == "success" and (res.get("text") or ""):
            html = res.get("text") or ""
            backend = res.get("method") or "archive"
            method = "archive-of-official"
            wb_meta = {
                "archive_backend": backend,
                "wayback_url": res.get("wayback_url"),
                "capture_timestamp": res.get("capture_timestamp"),
                "archive_url": res.get("archive_url") or res.get("wayback_url"),
                "cc_record": res.get("cc_record"),
            }
        else:
            log_failure(CC, {
                "identifier": code, "source_url": url, "status": "failed",
                "reason": (res or {}).get("error") or "empty_html",
            })
            return "fail"
    if not html or len(html) < 500:
        log_failure(CC, {"identifier": code, "source_url": url, "status": "failed", "reason": "empty_html"})
        return "fail"
    text, docs, title = extract_provisions(html, rid, url, None)
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": code, "source_url": url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = title or code
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=code,
        title=title, text=text, source_url=url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="sg-sso-agc",
        eli=None, date=None, official_identifier=code,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": it.get("source") or "mixed",
                "catalog_identifier": code,
                "seed_url": BROWSE,
                "retrieval": method,
                "archive_backend": backend,
                **{k: v for k, v in wb_meta.items() if v},
            },
            "official_metadata": {
                "act_code": code,
                "sso_unofficial_reproduction": True,
            },
            "text_extraction": {
                "source": "archive-of-official" if method != "live" else "official",
                "backend": f"sso_{backend}",
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": f"{title} ({code})",
            "status_source": "sso_current_acts",
            "status_confidence": "medium" if method != "live" else "high",
            "status_note": (
                "SSO is an unofficial reproduction. Printed Gazette / AGC official "
                "text prevails. robots.txt Disallow /search honoured."
            ),
        },
    )
    rec["id"] = rid
    rec["languages"] = ["en"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    live_n = sum(1 for it in items if it.get("source") == "live_browse")
    log.info("queue acts=%s already_done=%s live_listed=%s workers=%s",
             len(items), len(done), live_n, WORKERS)
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
                    source="Singapore Statutes Online (AGC Legislation Division)",
                    source_urls=[PORTAL, BROWSE],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Current Acts. No /search. No letter-CDX. Archives of official URLs if live blocked.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        "Current Acts from SSO catalog plus at most one Common Crawl index search "
        "and one Wayback prefix query of official sso.agc.gov.sg/Act/ URLs "
        "(no A-Z letter CDX). robots.txt Disallow:/search honoured "
        f"(crawl-delay 6 on live). Live 403/429 uses fetch_with_fallbacks "
        f"(CC WARC -> Wayback replay -> archive.is). Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Singapore Statutes Online (AGC Legislation Division)",
        source_urls=[PORTAL, BROWSE, "https://sso.agc.gov.sg/Act/CoA1967"],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0} live_listed={live_n}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items),
        "coverage": coverage, "live_listed": live_n,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
