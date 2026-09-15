#!/usr/bin/env python3
"""Nigeria: Constitution + Acts of the National Assembly from official hosts.

Official only:
  - Federal Ministry of Justice constitution PDF (justice.gov.ng)
  - National Assembly hosted Act PDFs (nass.gov.ng/documents/download/...)
  - National Human Rights Commission constitution PDF (nigeriarights.gov.ng) as
    a second official government copy if FMOJ fetch fails
  - Wayback / Common Crawl of those same official URLs on HTTP 429

Not used as source of record: LawNigeria, LawPavilion, Legalpedia, NigeriaLII,
PLAC compilations. gazettes.africa is not crawled (robots.txt Disallow: /gazettes/
and Disallow: /).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ng"
COUNTRY = "Nigeria"
SOURCE_TYPE = "nigeria_official"
LICENSE = (
    "Official texts of the Federal Republic of Nigeria as published by the "
    "Federal Ministry of Justice, the National Assembly, and (where used) other "
    "federal government hosts. The Official Gazette of the Federal Republic of "
    "Nigeria prevails over this research snapshot. Not legal advice. Not "
    "LawNigeria / LawPavilion / Legalpedia."
)
UA = DEFAULT_UA + " source=https://nass.gov.ng/"
FMOJ_CONST = "https://justice.gov.ng/wp-content/uploads/2020/09/Nigerian-Constitution.pdf"
FMOJ_CONST_PAGE = "https://justice.gov.ng/nigerian-constitution/"
NASS = "https://nass.gov.ng/"
NHRC_CONST = "https://nigeriarights.gov.ng/files/constitution.pdf"
SLEEP = 0.4
log = logging.getLogger("ng")

SEC_RE = re.compile(
    r"(?im)^\s*((?:Section|SECTION)\s+\d+[A-Z]?|[0-9]+\.—|[0-9]+\.\s+[A-Z])"
)
ART_RE = re.compile(r"(?im)^\s*((?:Chapter|CHAPTER|Part|PART)\s+[IVXLCDM0-9]+|[0-9]+\.\s+[A-Z])")


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


def wayback_only(url: str, timestamp: Optional[str] = None) -> dict:
    res = af.get_wayback_content(url, timestamp=timestamp)
    res.setdefault("retrieval", "archive")
    return res


def get_official(url: str, *, timeout=(20, 120), retries: int = 3, accept: Optional[str] = None) -> dict:
    headers = {}
    if accept:
        headers["Accept"] = accept
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries, headers=headers or None)
    except Exception as exc:
        log.info("live fail %s: %s — wayback of official URL", url, exc)
        return wayback_only(url)
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype) and body[:4] != b"%PDF":
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 200 and body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "", "content_type": ctype or "application/pdf",
            "original_url": url, "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if status == 200 and body and len(body) >= 500:
        # Prefer live official HTML/PDF even if challenge regex is noisy on SPA chrome.
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    if status == 429:
        log.info("HTTP 429 %s — archive_fallbacks wayback", url)
        return wayback_only(url)
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    log.info("HTTP %s %s — wayback of official URL", status, url)
    return wayback_only(url)


def split_ng(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    pat = ART_RE if constitution else SEC_RE
    matches = list(pat.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "ng"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def write_law(*, ident, title, text, source_url, date, doc_type, extra_meta, official=None) -> str:
    rid = slug_id(CC, ident)
    if rid in existing_ids(CC):
        return "skip"
    if len(text or "") < 120:
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ng.py", date=date, official_identifier=official or ident,
        document_type=doc_type, law_status="current", is_current=True,
        documents=split_ng(text, rid, source_url, date, constitution=(doc_type == "constitution")),
        extra_meta=extra_meta,
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    return "ok"


def parse_nass_homepage(html: str) -> list[dict]:
    items = []
    seen = set()
    for href, inner in re.findall(
        r'href="(https://nass\.gov\.ng/documents/download/\d+)"[^>]*>(.*?)</a>', html, re.S | re.I
    ):
        if href in seen:
            continue
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        if not title or title.lower().startswith("read act"):
            continue
        seen.add(href)
        did = href.rstrip("/").rsplit("/", 1)[-1]
        items.append({"url": href, "title": title, "download_id": did, "kind": "nass_act"})
    # also capture ids even without good title
    for did in re.findall(r"documents/download/(\d+)", html):
        url = f"https://nass.gov.ng/documents/download/{did}"
        if url in seen:
            continue
        seen.add(url)
        items.append({"url": url, "title": f"National Assembly document {did}",
                      "download_id": did, "kind": "nass_act"})
    return items


def discover() -> list[dict]:
    dest = ROOT / CC / "raw" / "catalog.jsonl"
    cached = []
    if dest.exists() and dest.stat().st_bytes if False else dest.exists():
        if dest.stat().st_size > 40:
            with dest.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        cached.append(json.loads(line))
                    except Exception:
                        continue
            if cached:
                log.info("resume catalog n=%s", len(cached))
                return cached
    items: list[dict] = []
    items.append({
        "url": FMOJ_CONST, "title": "Constitution of the Federal Republic of Nigeria 1999",
        "kind": "constitution", "fallback": [NHRC_CONST],
        "page": FMOJ_CONST_PAGE,
    })
    res = get_official(NASS)
    html = res.get("text") or ""
    nass_items = parse_nass_homepage(html)
    log.info("nass homepage acts=%s retrieval=%s", len(nass_items), res.get("retrieval"))
    items.extend(nass_items)
    # Wayback of official NASS download URLs only
    recs = af.search_wayback_machine(
        "https://nass.gov.ng/documents/download/",
        match_type="prefix", limit=250,
        extra_filters=["mimetype:application/pdf"],
    )
    recs += af.search_wayback_machine(
        "https://www.nass.gov.ng/documents/download/",
        match_type="prefix", limit=150,
        extra_filters=["mimetype:application/pdf"],
    )
    log.info("wayback nass download cdx=%s", len(recs))
    seen_ids = {it.get("download_id") for it in items if it.get("download_id")}
    for rec in recs:
        orig = rec.get("original") or ""
        m = re.search(r"documents/download/(\d+)", orig)
        if not m:
            continue
        did = m.group(1)
        if did in seen_ids:
            continue
        seen_ids.add(did)
        items.append({
            "url": f"https://nass.gov.ng/documents/download/{did}",
            "title": f"National Assembly Act PDF {did}",
            "download_id": did, "kind": "nass_act",
            "wayback_ts": rec.get("timestamp"),
            "cdx_original": orig,
        })
    # FMOJ other official law PDFs (constitution already listed)
    fmj = af.search_wayback_machine(
        "https://justice.gov.ng/wp-content/uploads/",
        match_type="prefix", limit=80,
        extra_filters=["mimetype:application/pdf"],
    )
    log.info("wayback fmj pdf cdx=%s", len(fmj))
    seen_pdf = {FMOJ_CONST}
    for rec in fmj:
        orig = rec.get("original") or ""
        if not orig.lower().endswith(".pdf"):
            continue
        low = orig.lower()
        if not any(k in low for k in ("const", "act", "lfn", "law", "order", "bill")):
            continue
        if orig in seen_pdf:
            continue
        seen_pdf.add(orig)
        items.append({
            "url": orig, "title": Path(orig.split("?")[0]).stem.replace("-", " ").replace("_", " "),
            "kind": "fmj_pdf", "wayback_ts": rec.get("timestamp"),
        })
    atomic_write(dest, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
    log.info("catalog n=%s", len(items))
    return items


def fetch_pdf_text(url: str, wayback_ts: Optional[str] = None) -> tuple[str, str, str]:
    """Return (text, retrieval, used_url)."""
    res = get_official(url, accept="application/pdf,application/octet-stream,*/*")
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        if len(text) >= 120:
            return text, res.get("retrieval") or "live", res.get("final_url") or url
    # explicit wayback of official URL
    wb = wayback_only(url, wayback_ts)
    body = wb.get("content") or b""
    if wb.get("status") == "success" and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        if len(text) >= 120:
            return text, "archive", wb.get("wayback_url") or url
    return "", res.get("retrieval") or "fail", url


def fetch_one(it: dict) -> str:
    kind = it.get("kind")
    url = it["url"]
    if kind == "constitution":
        ident = "ng-constitution-1999"
        text, retrieval, used = fetch_pdf_text(url, it.get("wayback_ts"))
        if len(text) < 200:
            for fb in it.get("fallback") or []:
                text, retrieval, used = fetch_pdf_text(fb)
                if len(text) >= 200:
                    url = fb
                    break
        title = "Constitution of the Federal Republic of Nigeria 1999"
        st = write_law(
            ident=ident, title=title, text=text, source_url=url, date="1999-05-29",
            doc_type="constitution", official="Constitution of the Federal Republic of Nigeria 1999",
            extra_meta={
                "discovery": {"method": "fmj_constitution_pdf", "page": it.get("page")},
                "retrieval": {"method": retrieval, "used_url": used},
                "text_extraction": {"source": "official", "backend": "pdftotext"},
                "gaps": "FMOJ PDF is the 2020 ministry upload of the 1999 Constitution; later Alteration Acts may not be consolidated in this file.",
            },
        )
        if st == "fail":
            log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "constitution_empty"})
        return st
    ident = f"ng-nass-{it.get('download_id')}" if it.get("download_id") else url
    text, retrieval, used = fetch_pdf_text(url, it.get("wayback_ts"))
    title = it.get("title") or ident
    # try to improve title from first lines
    if text:
        head = text[:1500]
        m = re.search(r"(?im)^(AN ACT[^\n]+|[A-Z][A-Za-z0-9 ,.'()]{10,120} ACT,?\s+\d{4})", head)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    doc_type = "constitution" if "constitution" in title.lower() else "statute"
    st = write_law(
        ident=ident, title=title, text=text, source_url=url, date=None,
        doc_type=doc_type, extra_meta={
            "discovery": {"method": it.get("kind"), "cdx_original": it.get("cdx_original")},
            "retrieval": {"method": retrieval, "used_url": used},
            "text_extraction": {"source": "official", "backend": "pdftotext"},
            "nass_download_id": it.get("download_id"),
        },
    )
    if st == "fail":
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "empty_pdf"})
    else:
        log.info("%s %s chars=%s retrieval=%s", st, ident, len(text), retrieval)
    return st


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    notes = (
        "Constitution from Federal Ministry of Justice official PDF; Acts from "
        "National Assembly nass.gov.ng/documents/download (live homepage plus "
        "Wayback CDX of those official download URLs). gazettes.africa not crawled "
        "(robots Disallow: /gazettes/). Not LawNigeria/LawPavilion/Legalpedia. "
        "NASS portal is a small SPA that currently lists only recently uploaded "
        "Acts; older LFN consolidations are not hosted as a complete public catalog "
        "on justice.gov.ng. Official Gazette prevails. "
        f"Started {t0}."
    )
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 10 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
    cov = "partial-official-fulltext"
    if counters["ok"] + counters["skip"] >= 1 and counters["fail"] == 0:
        cov = "official-hosted-snapshot"
    write_summary(
        CC, country=COUNTRY,
        source="Federal Ministry of Justice + National Assembly (official hosts)",
        source_urls=[NASS, FMOJ_CONST_PAGE, FMOJ_CONST, NHRC_CONST],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=cov, notes=notes,
    )
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s", counters)


if __name__ == "__main__":
    main()
