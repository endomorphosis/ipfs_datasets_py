#!/usr/bin/env python3
"""Pakistan: Federal Acts + Constitution from Pakistan Code (Ministry of Law).

Official source only:
  https://pakistancode.gov.pk  (Ministry of Law and Justice)
  Catalog: /english/sHyuRiF.php (chronological Code listing)
  Act pages: /english/UY2FqaJw1-...  with official PDFs under /pdffiles/

Federal Code consolidations (Acts + Constitution) first. Provincial law is
out of scope. Does not use Pakistan Law Site, vLex, Eastlaw, or other
commercial databases. No WAF bypass. robots.txt Disallow /pdffiles/ is
googlebot-only; collector UA is not googlebot.

On HTTP 429/403 of official URLs, archive_fallbacks.py (Wayback / Common Crawl
of those official URLs only).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "pk"
COUNTRY = "Pakistan"
SOURCE_TYPE = "pakistancode"
LICENSE = (
    "Official Pakistan Code texts (Ministry of Law and Justice, "
    "pakistancode.gov.pk). Authentic Gazette of Pakistan prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://pakistancode.gov.pk/"
PORTAL = "https://pakistancode.gov.pk/"
EN = "https://pakistancode.gov.pk/english/"
CATALOG = EN + "sHyuRiF.php"
CONST_PATH = "sHyuRiF.php"
WORKERS = 4
SLEEP = 0.45
log = logging.getLogger("pk")

LAW_HREF = re.compile(r'href=["\'](UY2FqaJw1[^"\']+)["\'][^>]*>([\s\S]*?)</a>', re.I)
PDF_HREF = re.compile(r'href=["\'](https?://[^"\']+\.pdf[^"\']*|[^"\']*pdffiles[^"\']+\.pdf[^"\']*)["\']', re.I)
YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2}|20\d{2})\b")
ART_PK = re.compile(r"(?im)^\s*((?:Section|Article|CHAPTER)\s+[\dIVXLCDM]+[A-Za-z]?)\b")


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
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_custom(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if docs:
        return docs
    if not text or len(text) < 40:
        return []
    matches = list(ART_PK.finditer(text))
    if len(matches) < 2:
        return []
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
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


def official_get(url: str, *, binary: bool = False, retries: int = 5):
    """Live GET; on 429/403/challenge use Wayback of the official URL (not CC-first)."""
    import time as _t
    import requests as _req
    headers = {"Accept": "application/pdf, */*" if binary else "text/html, */*", "User-Agent": UA}
    last = None
    for attempt in range(1, retries + 1):
        _t.sleep(SLEEP)
        for verify in (True, False):
            try:
                r = get_session(UA).get(url, timeout=(25, 90), headers=headers, verify=verify)
            except _req.RequestException as exc:
                last = exc
                log.info("live SSL/net %s verify=%s attempt=%s: %s", url, verify, attempt, exc)
                continue
            last = r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                _t.sleep(min(20, 2 ** attempt))
                break
            if r.status_code == 200 and r.content:
                if binary or len(r.content) > 8000 or not af.is_challenge(r.text or "", r.status_code):
                    return {"ok": True, "content": r.content,
                            "text": "" if binary else (r.text or ""),
                            "method": "live", "status": 200, "verify": verify}
            if r.status_code in (404, 410):
                return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code, "method": "live"}
            if r.status_code in (429, 403) or (not binary and af.is_challenge(r.text or "", r.status_code)):
                break
            break
    # 429/SSL: Wayback of official URL only (skip Common Crawl SSL storms)
    res = af.get_wayback_content(url)
    if res.get("status") == "success" and (res.get("content") or res.get("text")):
        return {"ok": True, "content": res.get("content") or b"", "text": res.get("text") or "",
                "method": "wayback", "archive": res}
    res2 = af.fetch_with_fallbacks(url, try_http=False, try_cc=False, try_archive_is=False)
    if res2.get("status") == "success" and (res2.get("content") or res2.get("text")):
        return {"ok": True, "content": res2.get("content") or b"", "text": res2.get("text") or "",
                "method": res2.get("method") or "archive", "archive": res2}
    err = "archive_fail"
    if isinstance(last, _req.Response):
        err = f"http_{last.status_code}"
    elif last:
        err = str(last)[:200]
    return {"ok": False, "error": err}


def clean_title(raw: str) -> str:
    t = re.sub(r"<[^>]+>", " ", raw or "")
    t = html_to_text(t) if "<" in (raw or "") else t
    t = re.sub(r"\s+", " ", t).replace("&amp;", "&").strip()
    return t


def is_repealed_stub(title: str) -> bool:
    t = title or ""
    return bool(re.search(r"\(Repeal by|\(repealed by|Repealed by", t, re.I))


def classify(title: str) -> tuple[str, str]:
    t = title or ""
    if re.search(r"^Constitution of the Islamic Republic of Pakistan$|\bConstitution of the Islamic Republic of Pakistan\b", t, re.I) and "Extension of Provisions" not in t and "Judges" not in t:
        return "constitution", "constitution"
    if re.search(r"\bAct\b", t, re.I):
        return "statute", "act"
    if re.search(r"\bOrdinance\b", t, re.I):
        return "statute", "ordinance"
    if re.search(r"\bOrder\b", t, re.I):
        return "instrument", "order"
    return "statute", "other"


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 50:
        return []
    items = []
    seen = set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            key = row.get("slug") or row.get("url")
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(row)
    return items


def discover() -> list[dict]:
    existing = load_catalog()
    if len(existing) >= 200:
        log.info("resume catalog %s", len(existing))
        return existing
    got = official_get(CATALOG)
    html = (got.get("text") or "") if got.get("ok") else ""
    if not html:
        log.warning("catalog live failed; trying index")
        got = official_get(EN + "index.php")
        html = (got.get("text") or "") if got.get("ok") else ""
    items = []
    seen = set()
    for href, title in LAW_HREF.findall(html or ""):
        href = href.split("#")[0]
        title = clean_title(title)
        if not href or href in seen:
            continue
        seen.add(href)
        url = urljoin(EN, href)
        kind, subtype = classify(title)
        ym = YEAR_RE.findall(title)
        year = ym[-1] if ym else None
        row = {
            "slug": href,
            "url": url,
            "title": title,
            "kind": kind,
            "subtype": subtype,
            "year": year,
            "repealed_stub": is_repealed_stub(title),
            "source": "sHyuRiF",
        }
        items.append(row)
        append_catalog(CC, row)
    log.info("discovered %s from catalog", len(items))
    return items


def extract_pdf_url(html: str, page_url: str) -> Optional[str]:
    for href in PDF_HREF.findall(html or ""):
        href = href.strip()
        if "pdffiles" in href.lower() or href.lower().endswith(".pdf"):
            return urljoin(page_url, href)
    return None


def fetch_one(it: dict, done: set[str]) -> str:
    title = it.get("title") or ""
    url = it.get("url") or ""
    slug = it.get("slug") or urlparse(url).path.rsplit("/", 1)[-1]
    # Federal Acts + Constitution first; keep Code ordinances (many principal laws).
    if it.get("repealed_stub"):
        return "skip"
    rid = slug_id(CC, slug)
    if rid in done:
        return "skip"
    page = official_get(url)
    if not page.get("ok"):
        log_failure(CC, {"identifier": slug, "source_url": url, "status": "failed",
                         "reason": page.get("error") or "page_fail", "title": title})
        return "fail"
    html = page.get("text") or ""
    pdf_url = extract_pdf_url(html, url)
    text = ""
    backend = page.get("method") or "live"
    used_url = url
    if pdf_url:
        used_url = pdf_url
        pdf = official_get(pdf_url, binary=True)
        if pdf.get("ok"):
            text = pdf_to_text(pdf.get("content") or b"")
            backend = f"pdf-{(pdf.get('method') or 'live')}"
        elif pdf.get("error"):
            log.info("pdf fail %s %s", pdf_url, pdf.get("error"))
    if len(text) < 80 and html:
        body = html_to_text(html)
        # drop chrome
        if "Pakistan Code" in body:
            # keep from first Section/Ordinance/Act heading if present
            m = re.search(r"(AN\s+ACT|AN\s+ORDINANCE|THE CONSTITUTION|Section\s+1\b)", body, re.I)
            if m:
                body = body[m.start():]
        if len(body) > len(text):
            text = body
            backend = f"html-{(page.get('method') or 'live')}"
    if len(text) < 80:
        log_failure(CC, {"identifier": slug, "source_url": used_url, "status": "failed",
                         "reason": "empty_text", "title": title, "backend": backend})
        return "fail"
    date = iso_date(f"{it.get('year')}-01-01") if it.get("year") else None
    docs = split_custom(text, rid, used_url, date)
    kind, subtype = it.get("kind") or "statute", it.get("subtype") or "other"
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=slug, title=title or slug,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="pk-pakistancode", eli=None, date=date,
        official_identifier=title or slug, document_type=kind,
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {
                "method": "pakistancode_catalog",
                "catalog_url": CATALOG,
                "slug": slug,
                "retrieval": page.get("method"),
                "pdf_url": pdf_url,
            },
            "official_metadata": {"subtype": subtype, "year": it.get("year")},
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["languages"] = ["en"]
    rec["canonical_title"] = title
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    # Constitution first, then Acts, then other Code instruments (ordinances).
    def rank(it):
        k = it.get("kind")
        s = it.get("subtype")
        if k == "constitution":
            return (0, it.get("title") or "")
        if s == "act":
            return (1, it.get("title") or "")
        if s == "ordinance":
            return (2, it.get("title") or "")
        return (3, it.get("title") or "")
    items = sorted(items, key=rank)
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
                    CC, country=COUNTRY, source="Pakistan Code (Ministry of Law and Justice)",
                    source_urls=[PORTAL, CATALOG], license_text=LICENSE,
                    discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                    coverage="catalog-backed incomplete",
                    notes="Federal Code. Not provincial. Not Pakistan Law Site/vLex/Eastlaw.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok + skip else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "federal-code snapshot"
    notes = (
        "Federal Acts + Constitution from the official Pakistan Code catalog "
        "(sHyuRiF.php). In-force Code ordinances included as principal federal "
        "legislation still styled Ordinance. Repealed-stub titles skipped. "
        "Official PDFs via pdftotext. 429/403 uses archive_fallbacks of official "
        "pakistancode.gov.pk URLs only. Not provincial. Not Pakistan Law Site, "
        f"vLex, or Eastlaw. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY, source="Pakistan Code (Ministry of Law and Justice)",
        source_urls=[PORTAL, CATALOG], license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
