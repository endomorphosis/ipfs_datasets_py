#!/usr/bin/env python3
"""Sri Lanka: official Acts PDFs from documents.gov.lk + parliament.lk (Wayback).

Uses pdf_extract_lib (pdfplumber first, OCR if image-only). Honest Section splits only.
"""
from __future__ import annotations
import json, logging, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_instrument, write_summary, base_record, slug_id
from world_lib import cdx_urls, env_int, setup_log
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split, is_garbage_text

CC, COUNTRY, LANG = "lk", "Sri Lanka", "en"
SOURCE_TYPE = "documents_gov_lk"
LICENSE = (
    "Government of Sri Lanka — documents.gov.lk / parliament.lk. "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.documents.gov.lk/)"
log = logging.getLogger("lk")


def fetch_pdf(url: str, ts: str | None = None) -> tuple[bytes, str]:
    import requests
    requests.packages.urllib3.disable_warnings()
    try:
        r = requests.get(url, timeout=(15, 60), verify=False, headers={"User-Agent": UA})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content, "http_pdf"
    except Exception:
        pass
    if ts:
        w = af.get_wayback_content(url, timestamp=ts)
        body = w.get("content") or b""
        if w.get("status") == "success" and body[:4] == b"%PDF":
            return body, "wayback_pdf"
    w = af.get_wayback_content(url)
    body = w.get("content") or b""
    if w.get("status") == "success" and body[:4] == b"%PDF":
        return body, "wayback_pdf"
    return b"", "fail"


def discover():
    items, seen = [], set()
    def add(url, ts=None):
        url = (url or "").split("#")[0].split("?")[0]
        low = url.lower()
        if ".pdf" not in low:
            return
        if not any(h in low for h in ("documents.gov.lk", "parliament.lk")):
            return
        # Prefer English acts / constitution
        if re.search(r"\([st]\)|_s\.pdf|_t\.pdf", low) and "_e.pdf" not in low and "(e)" not in low:
            # skip pure Sinhala/Tamil duplicates when English exists pattern — still allow if no E
            if "/files/act/" in low and not low.endswith("_e.pdf"):
                return
        key = low.replace("http://", "https://")
        if key in seen:
            return
        seen.add(key)
        stem = Path(unquote(urlparse(url).path)).stem[:140] or "lk-doc"
        items.append((stem, url, ts))
    for prefix in (
        "www.documents.gov.lk/files/act/",
        "documents.gov.lk/files/act/",
        "documents.gov.lk/Acts/",
        "www.parliament.lk/about_us/constitution",
        "www.parliament.lk/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 80), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            add(h.get("original") or "", h.get("timestamp"))
    # Prefer constitution first
    items.sort(key=lambda x: (0 if "constitution" in x[1].lower() else 1, x[0]))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    # register META later in world_package if missing
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 35)
    max_seconds = env_int("MAX_SECONDS", 1800)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        raw, method = fetch_pdf(url, ts)
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "fetch_fail"})
            continue
        text, how, pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=env_int("OCR_PAGES", 20),
        )
        if how.startswith("ocr"):
            ocr_used += 1
        if not text or len(text) < 100 or is_garbage_text(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"thin:{how}"})
            continue
        docs, kind = honest_split(CC, text, rid, url)
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 12:
                title = line.strip()[:240]
                break
        rec = base_record(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_lk.py",
            documents=docs,
            extra_meta={
                "fetch_method": method, "extract_method": how, "pages": pages,
                "pdf_parser": "ipfs_datasets_py.IntegratedPDFProcessor",
                "article_split": {"method": kind, "count": len(docs)},
                "wayback_ts": ts,
            },
        )
        write_instrument(CC, rec)
        ok += 1
        done.add(rid)
        log.info("ok %s extract=%s arts=%s chars=%s", ident[:60], how, len(docs), len(text))
    write_summary(
        CC, country=COUNTRY, source="documents.gov.lk / parliament.lk",
        source_urls=["https://www.documents.gov.lk/", "https://www.parliament.lk/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official Act PDFs)",
        notes=f"OCR used on {ocr_used} image-heavy Acts when text layer missing. Honest Section splits. Not legal advice.",
        last_run=t0,
    )
    laws = arts = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        rec = json.loads(p.read_text())
        if len(rec.get("text") or "") >= 80:
            laws += 1
            arts += len(rec.get("documents") or [])
    print(json.dumps({"ok": ok, "skip": skip, "fail": fail, "ocr_used": ocr_used, "laws": laws, "arts": arts}))


if __name__ == "__main__":
    main()
