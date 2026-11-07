#!/usr/bin/env python3
"""Re-extract PDF text (IntegratedPDFProcessor-style) and honest article splits
for thin-article country corpora. Does not invent boundaries.

Usage:
  python reprocess_pdf_articles.py tn et jm fj la
  REFETCH=1 OCR=1 MAX_OCR=10 python reprocess_pdf_articles.py sv tn
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT
from pdf_extract_lib import (
    extract_pdf_text, honest_split, is_garbage_text, normalize_bidi,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reprocess")

# Jamaica: drop obvious non-law PDFs under MOJ that are forms/samples/brochures
JM_SKIP = re.compile(
    r"(sample[_\s-]?letter|brochure|vacan|career|/ATI/Access%20to%20Information%20Sample|"
    r"job[\s_-]?desc|standing%20orders|ministry%20paper|sectoral|expungement%20brochure)",
    re.I,
)


def maybe_refetch_pdf(url: str, cc: str) -> bytes:
    if not url:
        return b""
    ul = url.lower()
    if ".pdf" not in ul and "downloadpdf" not in ul and "/download/" not in ul:
        return b""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import archive_fallbacks as af
    import requests
    requests.packages.urllib3.disable_warnings()
    ua = f"legal-corpora-collector/1.0 (research; cc={cc})"
    try:
        r = requests.get(url, timeout=(12, 55), verify=False, headers={"User-Agent": ua})
        if r.status_code == 200 and r.content:
            body = r.content
            if body[:4] == b"%PDF":
                return body
            idx = body.find(b"%PDF", 0, 65536)
            if idx >= 0:
                return body[idx:]
    except Exception:
        pass
    try:
        w = af.get_wayback_content(url)
        body = w.get("content") or b""
        if w.get("status") == "success" and body:
            if isinstance(body, str):
                body = body.encode("latin-1", "replace")
            if body[:4] == b"%PDF":
                return body
            idx = body.find(b"%PDF", 0, 65536)
            if idx >= 0:
                return body[idx:]
    except Exception:
        pass
    return b""


def ocr_lang_for(cc: str) -> str:
    return {
        "sv": "spa+eng",
        "tn": "ara+fra+eng",
        "et": "amh+eng",
        "jm": "eng",
        "fj": "eng",
        "la": "eng+lao",
        "lk": "eng+sin",
        "md": "eng+fra",
        "mz": "por",
        "iq": "ara",
        "ir": "ara",
    }.get(cc, "eng")


def scrub_junk(cc: str, instr: Path) -> int:
    removed = 0
    q = ROOT / cc / "quarantine_nonlaws"
    q.mkdir(parents=True, exist_ok=True)
    for p in list(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        url = rec.get("source_url") or ""
        drop = False
        if is_garbage_text(text) and ("IHDR" in text[:120] or "\x89PNG" in text[:20]):
            drop = True
        if cc == "jm" and JM_SKIP.search(url):
            drop = True
        if cc == "tn" and url.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
            drop = True
        if drop:
            p.rename(q / p.name)
            removed += 1
            log.info("quarantine %s", p.name)
    return removed


def reprocess_cc(cc: str) -> dict:
    instr = ROOT / cc / "instruments"
    if not instr.exists():
        return {"cc": cc, "error": "no_instruments"}
    refetch = os.environ.get("REFETCH", "0") == "1"
    enable_ocr = os.environ.get("OCR", "1") == "1"
    max_ocr = int(os.environ.get("MAX_OCR", "12") or 12)
    max_refetch = int(os.environ.get("MAX_REFETCH", "40") or 40)
    removed = scrub_junk(cc, instr)
    updated = skipped = arts_total = 0
    ocr_used = refetch_n = 0
    by_method: dict[str, int] = {}
    text_improved = 0
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        url = rec.get("source_url") or ""
        rid = rec.get("id") or p.stem
        method = "existing_text"
        # Optional refetch+reextract for thin/garbage/no-structure
        docs_probe, _ = honest_split(cc, text, rid, url)
        url_l = (url or "").lower()
        looks_pdf = (
            ".pdf" in url_l
            or "/downloadpdf/" in url_l
            or "downloadpdf" in url_l
            or is_garbage_text(text) and ("%PDF" in (text[:200] if text else "") or "endobj" in (text[:400] if text else ""))
        )
        need = (
            refetch
            and refetch_n < max_refetch
            and (is_garbage_text(text) or len(docs_probe) < 2)
            and looks_pdf
        )
        if need:
            raw = maybe_refetch_pdf(url, cc)
            if raw:
                use_ocr = enable_ocr and ocr_used < max_ocr and is_garbage_text(text)
                new_text, how, pages = extract_pdf_text(
                    raw, enable_ocr=use_ocr, ocr_lang=ocr_lang_for(cc),
                    ocr_max_pages=int(os.environ.get("OCR_PAGES", "30") or 30),
                )
                refetch_n += 1
                if how.startswith("ocr"):
                    ocr_used += 1
                if new_text and len(new_text) >= 80 and (
                    len(new_text) > len(text) * 0.85 or is_garbage_text(text)
                ) and not is_garbage_text(new_text):
                    text = new_text
                    rec["text"] = text
                    method = how
                    text_improved += 1
                    meta = rec.get("metadata") or {}
                    meta["pdf_reextract"] = {"method": how, "pages": pages, "parser": "ipfs_datasets_py.IntegratedPDFProcessor"}
                    rec["metadata"] = meta
                    log.info("reextracted %s via %s chars=%s", rid[:50], how, len(text))

        if cc in ("tn", "iq", "ir"):
            from pdf_extract_lib import normalize_rtl_text
            text = normalize_rtl_text(text)
            rec["text"] = text

        docs, kind = honest_split(cc, text, rid, url)
        by_method[kind] = by_method.get(kind, 0) + 1
        old_docs = rec.get("documents") or []
        if len(docs) < 2:
            # Keep prior splits if present (do not regress); only mark missing when empty
            if old_docs and len(old_docs) >= 2:
                arts_total += len(old_docs)
                skipped += 1
                continue
            if old_docs:
                rec["documents"] = []
                rec["article_count"] = 0
                rec["article_extraction_status"] = "missing"
                meta = rec.get("metadata") or {}
                meta["article_note"] = "no_honest_heading_structure"
                meta["pdf_parser"] = "ipfs_datasets_py.IntegratedPDFProcessor"
                rec["metadata"] = meta
                p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            skipped += 1
            continue
        # Don't shrink a better existing split unless reextract improved text
        old_n = len(rec.get("documents") or [])
        if old_n >= len(docs) and method == "existing_text" and kind != "none":
            # keep existing if already as good
            skipped += 1
            arts_total += old_n
            continue
        if old_n > len(docs) and method == "existing_text":
            arts_total += old_n
            skipped += 1
            continue
        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok"
        meta = rec.get("metadata") or {}
        meta["article_split"] = {"method": kind, "count": len(docs), "text_source": method}
        meta["pdf_parser"] = "ipfs_datasets_py.IntegratedPDFProcessor"
        rec["metadata"] = meta
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1
        arts_total += len(docs)
        log.info("split %s kind=%s arts=%s (was %s)", rid[:55], kind, len(docs), old_n)

    # recount
    laws = arts = 0
    for p in instr.glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if len(rec.get("text") or "") >= 80:
            laws += 1
            arts += len(rec.get("documents") or [])
    out = {
        "cc": cc, "updated": updated, "skipped": skipped, "arts_written": arts_total,
        "by_method": by_method, "ocr_used": ocr_used, "refetch": refetch_n,
        "text_improved": text_improved, "quarantined": removed,
        "laws": laws, "arts": arts,
    }
    report = ROOT / cc / "raw" / "pdf_reprocess_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out))
    return out


def main():
    ccs = sys.argv[1:] or ["tn", "et", "jm", "fj", "la"]
    for cc in ccs:
        reprocess_cc(cc)


if __name__ == "__main__":
    main()
