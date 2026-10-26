#!/usr/bin/env python3
"""Morocco: Constitution + dahirs/lois from SGG Bulletin Officiel.

Official source only:
  https://www.sgg.gov.ma  (Secrétariat Général du Gouvernement)
  Constitution PDF: /Portals/1/lois/constitution_2011_Ar.pdf
  Individual texts: /Portals/1/lois/*.pdf  (dahirs, lois, décrets as published)
  Consolidated index: /arabe/textesconsolides.aspx
  Official Arabic/French as published on SGG.

Live TLS from this host often EOFs; on live failure / HTTP 429 of official
URLs, archive_fallbacks.py of those official URLs only (HTTP Wayback via curl).
Many Portals/1/lois PDFs are image scans — pdftotext empty → tesseract ara+fra.
Not Adala commercial (adala.ai / juritheque).
No WAF bypass. No commercial DBs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ma"
COUNTRY = "Morocco"
SOURCE_TYPE = "sgg_bo"
LICENSE = (
    "Official texts of the Kingdom of Morocco as published by the Secrétariat "
    "Général du Gouvernement (sgg.gov.ma) in the Bulletin Officiel "
    "(الجريدة الرسمية). The Bulletin Officiel prevails over this research "
    "snapshot. Not legal advice. Not Adala commercial compilations."
)
UA = DEFAULT_UA + " source=https://www.sgg.gov.ma/"
SGG = "https://www.sgg.gov.ma/"
CONST_AR = "http://www.sgg.gov.ma/Portals/1/lois/constitution_2011_Ar.pdf"
CONST_FR_BO = "http://www.sgg.gov.ma/BO/bulletin/FR/2011/BO_5964-Bis_Fr.pdf"
CONSOL = "http://www.sgg.gov.ma/arabe/textesconsolides.aspx"
WORKERS = 2
SLEEP = 0.5
log = logging.getLogger("ma")
ART_AR = re.compile(
    r"(?im)^\s*((?:المادة|مادة|الفصل|Article)\s+(?:[0-9\u0660-\u0669]+|[0-9]+(?:-[0-9]+)?|الأول(?:ى)?|الثاني(?:ة)?))"
)
PDF_NAME = re.compile(r"/Portals/1/lois/([^/?#]+\.pdf)", re.I)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


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
            text = proc.stdout.decode("utf-8", "replace")
            # strip form-feeds / NUL — image-only PDFs yield only \f
            text = "".join(ch for ch in text if ch not in "\x0c\x00").strip()
            return text
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def ocr_pdf(raw: bytes) -> str:
    """OCR scanned SGG PDFs (Arabic + French). Cap pages for throughput."""
    if not raw or raw[:4] != b"%PDF":
        return ""
    max_pages = env_int("MAX_OCR_PAGES", 12)
    dpi = env_int("OCR_DPI", 150)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                [
                    "pdftoppm", "-png", "-r", str(dpi),
                    "-f", "1", "-l", str(max_pages),
                    str(pdf), str(Path(td) / "p"),
                ],
                check=False, capture_output=True, timeout=300,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", "replace")[:200]
                log.info("pdftoppm fail: %s", err)
                return ""
            chunks = []
            for img in sorted(Path(td).glob("p*.png")):
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "ara+fra", "--psm", "6"],
                    check=False, capture_output=True, timeout=180,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def canon_sgg(url: str) -> str:
    if not url:
        return url
    u = url.replace("https://www.sgg.gov.ma", "http://www.sgg.gov.ma")
    u = u.replace("https://sgg.gov.ma", "http://www.sgg.gov.ma")
    u = u.replace("http://sgg.gov.ma", "http://www.sgg.gov.ma")
    u = u.replace("http://www.sgg.gov.ma:80", "http://www.sgg.gov.ma")
    u = u.split("#")[0]
    # Keep ?ver= DNN cache-busters — many Wayback PDF captures exist ONLY
    # with the query string (CDX original includes ?ver=...).
    return u


def resolve_wayback_capture(url: str, preferred_ts: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Return (timestamp, original_url_with_query) for Wayback replay.

    SGG DNN ?ver= query strings are required for many captures.
    """
    try:
        path_only = url.split("?", 1)[0]
        # prefix match (no trailing *) finds ?ver= DNN variants
        recs = af.search_wayback_machine(path_only, match_type="prefix", limit=25)
        if not recs:
            recs = af.search_wayback_machine(path_only, match_type="exact", limit=10)
    except Exception as exc:
        log.info("cdx resolve fail %s: %s", url, exc)
        return preferred_ts, url
    best = None
    for rec in recs:
        sc = str(rec.get("statuscode") or rec.get("status") or "")
        mime = (rec.get("mimetype") or rec.get("mime") or "").lower()
        if sc and sc not in ("200", "226"):
            continue
        if mime and "pdf" not in mime and "octet" not in mime:
            continue
        orig = canon_sgg(rec.get("original") or "")
        ts = rec.get("timestamp")
        if not ts:
            continue
        if preferred_ts and ts == preferred_ts and orig:
            return ts, orig
        if best is None:
            best = (ts, orig or url)
    if best:
        return best
    if preferred_ts:
        return preferred_ts, url
    return None, url


def official_get(url: str, *, timestamp: Optional[str] = None, retries: int = 2) -> dict:
    url = canon_sgg(url)
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=retries, timeout=(15, 60),
                     headers={"Accept": "application/pdf, text/html, */*"})
    except Exception as exc:
        log.info("live fail %s: %s — archive of official URL", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content:
        body = r.content
        text = ""
        if body[:4] != b"%PDF":
            text = r.text or ""
            if af.is_challenge(text, r.status_code) or len(body) < 200:
                r = None
            else:
                return {"ok": True, "content": body, "text": text, "method": "live",
                        "final_url": r.url or url}
        else:
            return {"ok": True, "content": body, "text": "", "method": "live",
                    "final_url": r.url or url}
    if r is not None and r.status_code == 429:
        log.info("HTTP 429 %s — archive_fallbacks", url)

    ts, wb_url = resolve_wayback_capture(url, timestamp)
    # Prefer HTTP Wayback curl; use CDX original (often includes ?ver=).
    tried = set()
    for try_url, try_ts in ((wb_url or url, ts), (url, timestamp), (url, ts)):
        key = (try_url, try_ts)
        if not try_url or key in tried:
            continue
        tried.add(key)
        wb = af.get_wayback_content(try_url, timestamp=try_ts)
        if wb.get("status") == "success" and (wb.get("content") or wb.get("text")):
            return {
                "ok": True, "content": wb.get("content") or b"",
                "text": wb.get("text") or "",
                "method": "wayback",
                "final_url": wb.get("wayback_url") or try_url,
            }
    # No CC (slow / empty for these PDFs). Wayback-only fallbacks.
    res = af.fetch_with_fallbacks(
        url, try_http=False, try_cc=False, try_archive_is=False, wayback_ts=ts,
    )
    if res.get("status") == "success" and (res.get("content") or res.get("text")):
        return {
            "ok": True, "content": res.get("content") or b"",
            "text": res.get("text") or "",
            "method": res.get("method") or "archive",
            "final_url": res.get("wayback_url") or url,
        }
    err = "archive_fail"
    if r is not None:
        err = f"http_{r.status_code}"
    elif wb.get("error"):
        err = f"wayback_{wb.get('error')}"
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
            "metadata": {"text_extraction": {"source": "official", "backend": "ma"}},
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
            key = (row.get("id") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(row)
    return items


def add_item(items, seen, row: dict):
    key = (row.get("id") or "").lower()
    if not key or key in seen:
        return
    seen.add(key)
    items.append(row)
    append_catalog(CC, row)


def pdf_id(url: str) -> str:
    m = PDF_NAME.search(url.replace("\\", "/"))
    if m:
        return unquote(m.group(1))
    name = Path(urlparse(url).path).name
    return unquote(name) or "unknown.pdf"


def classify(name: str, title: str = "") -> tuple[str, str]:
    n = (name or "") + " " + (title or "")
    nl = n.lower()
    if "constitution" in nl or "دستور" in n:
        return "constitution", "constitution"
    if re.search(r"\d+\.\d+\.\d+", name) or name.startswith("2."):
        return "decree", name
    return "statute", name


def discover() -> list[dict]:
    items = load_catalog()
    seen = {(x.get("id") or "").lower() for x in items}
    add_item(items, seen, {
        "id": "constitution_2011_Ar.pdf", "kind": "constitution", "lang": "ar",
        "url": CONST_AR + "?ver=2012-11-15-130948-000",
        "wayback_ts": "20190820011042",
        "title": "دستور المملكة المغربية 2011",
        "source": "known_constitution",
    })
    add_item(items, seen, {
        "id": "BO_5964-Bis_Fr.pdf", "kind": "constitution", "lang": "fr",
        "url": CONST_FR_BO, "wayback_ts": "20131102041635",
        "title": "Constitution du Royaume du Maroc 2011 (BO 5964 bis FR)",
        "source": "known_constitution_fr",
    })
    if len(items) >= 80:
        log.info("resume catalog %s", len(items))
        return items
    prefixes = [
        "www.sgg.gov.ma/Portals/1/lois/",
        "sgg.gov.ma/Portals/1/lois/",
        "www.sgg.gov.ma/arabe/textesconsolides.aspx",
    ]
    for prefix in prefixes:
        recs = af.search_wayback_machine(
            prefix, match_type="prefix", limit=700,
            extra_filters=["mimetype:application/pdf"] if "/lois/" in prefix else None,
        )
        log.info("cdx %s n=%s", prefix, len(recs))
        for rec in recs:
            orig = canon_sgg(rec.get("original") or "")
            if not orig or "adala" in orig.lower():
                continue
            if "/Portals/1/lois/" in orig and orig.lower().endswith(".pdf"):
                name = pdf_id(orig)
                if name.lower() in {"thumbs.db"}:
                    continue
                kind, _ = classify(name)
                add_item(items, seen, {
                    "id": name, "kind": kind, "lang": "ar" if "_fr" not in name.lower() else "fr",
                    "url": orig, "wayback_ts": rec.get("timestamp"),
                    "title": name.replace(".pdf", "").replace("_", " "),
                    "source": "cdx_lois",
                })
    got = official_get(CONSOL)
    html = got.get("text") or ""
    for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        from urllib.parse import urljoin
        orig = canon_sgg(urljoin("http://www.sgg.gov.ma/", href))
        if "/Portals/" not in orig and "/BO/" not in orig:
            continue
        name = pdf_id(orig)
        add_item(items, seen, {
            "id": name, "kind": classify(name)[0], "lang": "ar",
            "url": orig, "title": name, "source": "textesconsolides",
        })
    log.info("discovered %s", len(items))
    return items


def instrument_id(it: dict) -> str:
    name = it.get("id") or "unknown"
    ident = name.replace(".pdf", "").replace(".PDF", "")
    if it.get("kind") == "constitution" and "constitution_2011_Ar" in name:
        ident = "constitution-2011-ar"
    elif it.get("kind") == "constitution":
        ident = f"constitution-2011-{it.get('lang') or 'fr'}"
    return slug_id(CC, ident), ident


def fetch_one(it: dict, done: set[str]) -> str:
    name = it.get("id") or "unknown"
    rid, ident = instrument_id(it)
    if rid in done:
        return "skip"
    url = canon_sgg(it.get("url") or "")
    got = official_get(url, timestamp=it.get("wayback_ts"))
    body = got.get("content") or b""
    text = ""
    backend = got.get("method") or "archive"
    used = got.get("final_url") or url
    if got.get("ok") and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        backend = f"pdf-{(got.get('method') or 'archive')}"
        if len(text) < 80:
            # Image-scan PDFs dominate empty_text failures — OCR ara+fra
            ocr = ocr_pdf(body)
            if len(ocr) >= 80:
                text = ocr
                backend = f"pdf-ocr-{(got.get('method') or 'archive')}"
    elif got.get("ok") and got.get("text"):
        text = html_to_text(got.get("text") or "")
        backend = f"html-{(got.get('method') or 'archive')}"
    if len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed",
                         "reason": got.get("error") or "empty_text"})
        return "fail"
    title = it.get("title") or ident
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 12 and not line.lower().startswith("%"):
            if any(k in line for k in ("دستور", "ظهير", "قانون", "مرسوم", "Constitution", "Dahir", "Loi", "مرسوم", "مشروع")):
                title = line[:220]
                break
    lang = it.get("lang") or ("fr" if "_fr" in name.lower() or "/FR/" in url else "ar")
    date = "2011-07-29" if "constitution" in (it.get("kind") or "") else None
    ym = re.search(r"(19\d{2}|20\d{2})", name)
    if not date and ym:
        date = f"{ym.group(1)}-01-01"
    docs = split_ar(text, rid, used, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ma.py", date=date, official_identifier=ident,
        document_type=it.get("kind") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": it.get("source") or "sgg", "file": name,
                          "retrieval": got.get("method")},
            "retrieval": {"method": got.get("method") or "archive", "used_url": used,
                          "backend": backend},
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["languages"] = [lang]
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    t_start = time.time()
    max_new = env_int("MAX_NEW", 400)
    max_seconds = env_int("MAX_SECONDS", 14400)
    items = discover()
    items = sorted(items, key=lambda x: (
        0 if x.get("kind") == "constitution" else 1 if x.get("kind") == "statute" else 2,
        0 if x.get("wayback_ts") else 1,
        str(x.get("id") or ""),
    ))
    done = existing_ids(CC)
    # Prefer pending only
    pending = []
    for it in items:
        rid, _ = instrument_id(it)
        if rid not in done:
            pending.append(it)
    pending = pending[:max_new]
    log.info(
        "queue pending=%s/%s already=%s MAX_NEW=%s MAX_SECONDS=%s",
        len(pending), len(items), len(done), max_new, max_seconds,
    )
    ok = skip = fail = 0
    # Sequential-ish with small pool; OCR is CPU-heavy
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {}
        for it in pending:
            if time.time() - t_start >= max_seconds:
                log.info("MAX_SECONDS reached before submit")
                break
            futs[ex.submit(fetch_one, it, done)] = it
        n = 0
        total = len(futs)
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
            if n % 10 == 0 or n == total:
                log.info(
                    "progress %s/%s ok=%s skip=%s fail=%s elapsed=%.0fs",
                    n, total, ok, skip, fail, time.time() - t_start,
                )
                write_summary(
                    CC, country=COUNTRY,
                    source="SGG Bulletin Officiel (sgg.gov.ma)",
                    source_urls=[SGG, CONST_AR, CONSOL],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Constitution + dahirs/lois PDFs from official SGG. Not Adala commercial.",
                    last_run=utcnow(),
                )
            if time.time() - t_start >= max_seconds:
                log.info("MAX_SECONDS reached during run — cancelling remaining")
                for f in futs:
                    f.cancel()
                break
    final_done = existing_ids(CC)
    skip = max(0, len(final_done) - ok)  # prior instruments + this-run ok ≈ done set
    coverage = "snapshot" if (ok or final_done) else "empty"
    if items and fail == 0 and len(final_done) >= len(items):
        coverage = "national-laws snapshot"
    notes = (
        "Constitution 2011 (Arabic official PDF; French BO 5964 bis) plus "
        "individual dahirs/lois PDFs from sgg.gov.ma/Portals/1/lois. "
        "Live TLS often fails from this host; texts via live when possible "
        "else HTTP Wayback curl of official SGG URLs. Image-scan PDFs use "
        "tesseract ara+fra OCR. Weekly historic BO issues (1913–) not ingested "
        "as whole books — national statute PDFs first. Not Adala commercial. "
        f"MAX_NEW={max_new} MAX_SECONDS={max_seconds}. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Secrétariat Général du Gouvernement / Bulletin Officiel (sgg.gov.ma)",
        source_urls=[SGG, CONST_AR, CONST_FR_BO, CONSOL],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items),
        "instruments": len(final_done), "coverage": coverage,
        "max_new": max_new, "max_seconds": max_seconds,
    }, indent=2) + "\n", encoding="utf-8")
    log.info(
        "done ok=%s fail=%s instruments=%s coverage=%s",
        ok, fail, len(final_done), coverage,
    )


if __name__ == "__main__":
    main()
