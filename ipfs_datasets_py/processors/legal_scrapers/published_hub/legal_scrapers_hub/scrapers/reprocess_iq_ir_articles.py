#!/usr/bin/env python3
"""Reprocess Iraq/Iran instruments: RTL-normalize, honest article splits, optional OCR.

Official sources only (moj.gov.iq / dotic.ir via existing source_url / Wayback).
Does NOT package or upload to Hugging Face.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT
from pdf_extract_lib import (
    extract_pdf_text,
    honest_split,
    is_garbage_text,
    normalize_rtl_text,
)
from reprocess_pdf_articles import maybe_refetch_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reprocess_iq_ir")

BIDI_OR_CTRL = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\x00-\x08\x0b\x0e-\x1f]")


def count_cc(cc: str) -> dict:
    instr = ROOT / cc / "instruments"
    laws = arts = with_docs = garb_titles = 0
    for p in instr.glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        text = rec.get("text") or ""
        if len(text) < 80:
            continue
        laws += 1
        docs = rec.get("documents") or []
        arts += len(docs)
        if len(docs) >= 2:
            with_docs += 1
        if title_looks_bad(rec.get("title") or ""):
            garb_titles += 1
    return {"laws": laws, "arts": arts, "with_docs": with_docs, "bad_titles": garb_titles}


def title_looks_bad(title: str) -> bool:
    if not title or len(title.strip()) < 4:
        return True
    arabic = sum(1 for ch in title if "\u0600" <= ch <= "\u06FF")
    if arabic >= 6:
        # still bad if mostly bidi/controls wrapped around short stem
        cleaned = BIDI_OR_CTRL.sub("", title).strip()
        if len(cleaned) < 4:
            return True
        return False
    if "(cid:" in title or title.count("@") >= 2:
        return True
    ctrl = sum(1 for ch in title if ord(ch) < 32)
    if ctrl >= 2:
        return True
    # latin mojibake titles
    if arabic == 0 and re.search(r"[\\x00-\\x08]", title):
        return True
    if arabic == 0 and sum(ord(ch) < 128 and ch.isalpha() for ch in title) >= 8:
        # could be English; only flag if looks like mojibake soup
        if re.search(r"[^\w\s\-.,:;()/'\"\u0600-\u06FF]", title) and " " not in title.strip()[:20]:
            return True
    return arabic == 0 and any(ord(ch) < 32 for ch in title)


def title_from_url(url: str) -> str | None:
    if not url:
        return None
    try:
        stem = Path(unquote(url.split("?")[0])).stem
    except Exception:
        return None
    stem = stem.strip().strip("_-")
    arabic = sum(1 for ch in stem if "\u0600" <= ch <= "\u06FF")
    if arabic >= 4:
        return stem[:240]
    return None


def better_title(rec: dict, text: str) -> str | None:
    cur = rec.get("title") or ""
    if not title_looks_bad(cur):
        # still strip bidi for cleanliness when Arabic is good
        cleaned = normalize_rtl_text(cur).strip()
        if cleaned and cleaned != cur.strip():
            return cleaned[:240]
        return None
    url_title = title_from_url(rec.get("source_url") or "")
    if url_title:
        return url_title
    norm = normalize_rtl_text(text or "")
    for line in norm.splitlines():
        s = line.strip()
        if len(s) < 12:
            continue
        arabic = sum(1 for ch in s if "\u0600" <= ch <= "\u06FF")
        if arabic >= 8 and "(cid:" not in s and s.count("@") < 2:
            return s[:240]
    ident = rec.get("official_identifier") or rec.get("identifier") or rec.get("id") or ""
    return str(ident)[:240] if ident else None


def reprocess_cc(cc: str) -> dict:
    instr = ROOT / cc / "instruments"
    refetch = os.environ.get("REFETCH", "1") == "1"
    enable_ocr = os.environ.get("OCR", "1") == "1"
    max_ocr = int(os.environ.get("MAX_OCR", "18") or 18)
    max_refetch = int(os.environ.get("MAX_REFETCH", "40") or 40)
    ocr_pages = int(os.environ.get("OCR_PAGES", "35") or 35)
    ocr_lang = "ara"  # Persian tessdata unavailable; ara closest for IR

    before = count_cc(cc)
    updated = skipped = arts_written = 0
    ocr_used = refetch_n = text_improved = titles_fixed = 0
    by_method: dict[str, int] = {}

    # Prefer OCR for largest garbage PDFs first
    files = []
    for p in instr.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        files.append((p, rec, len(text), is_garbage_text(text)))
    files.sort(key=lambda x: (not x[3], -x[2]))  # garbage first, then longest

    for p, rec, _, _ in files:
        text = rec.get("text") or ""
        url = rec.get("source_url") or ""
        rid = rec.get("id") or p.stem
        method = "existing_text"

        docs_probe, _ = honest_split(cc, text, rid, url)
        url_l = (url or "").lower()
        looks_pdf = ".pdf" in url_l
        need = (
            refetch
            and refetch_n < max_refetch
            and looks_pdf
            and (is_garbage_text(text) or len(docs_probe) < 2)
            and (is_garbage_text(text) or len(text) < 5000 or cc == "iq")
        )
        # For IR, only refetch when garbage; existing Persian text often splits after normalize
        if cc == "ir" and not is_garbage_text(text) and len(docs_probe) >= 2:
            need = False
        if cc == "ir" and not is_garbage_text(text):
            need = False

        if need:
            raw = maybe_refetch_pdf(url, cc)
            if raw:
                use_ocr = enable_ocr and ocr_used < max_ocr and (
                    is_garbage_text(text) or len(docs_probe) < 2
                )
                new_text, how, pages = extract_pdf_text(
                    raw,
                    enable_ocr=use_ocr,
                    ocr_lang=ocr_lang,
                    ocr_max_pages=ocr_pages,
                )
                refetch_n += 1
                if how.startswith("ocr"):
                    ocr_used += 1
                if new_text and len(new_text) >= 80 and not is_garbage_text(new_text):
                    if is_garbage_text(text) or len(new_text) > len(text) * 0.5:
                        text = new_text
                        rec["text"] = text
                        method = how
                        text_improved += 1
                        meta = rec.get("metadata") or {}
                        meta["pdf_reextract"] = {
                            "method": how,
                            "pages": pages,
                            "parser": "ipfs_datasets_py.IntegratedPDFProcessor",
                        }
                        rec["metadata"] = meta
                        log.info("reextracted %s via %s chars=%s", rid[:55], how, len(text))

        text_n = normalize_rtl_text(text)
        if text_n != text:
            text = text_n
            rec["text"] = text

        docs, kind = honest_split(cc, text, rid, url)
        by_method[kind] = by_method.get(kind, 0) + 1
        old_docs = rec.get("documents") or []

        new_title = better_title(rec, text)
        if new_title and new_title != (rec.get("title") or ""):
            rec["title"] = new_title
            titles_fixed += 1

        if len(docs) < 2:
            if old_docs and len(old_docs) >= 2:
                arts_written += len(old_docs)
                skipped += 1
                if new_title:
                    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                continue
            rec["documents"] = []
            rec["article_count"] = 0
            rec["article_extraction_status"] = "missing"
            meta = rec.get("metadata") or {}
            meta["article_note"] = "no_honest_heading_structure"
            rec["metadata"] = meta
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            skipped += 1
            continue

        old_n = len(old_docs)
        if old_n >= len(docs) and method == "existing_text" and old_n >= 2:
            skipped += 1
            arts_written += old_n
            if new_title:
                p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue

        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok"
        meta = rec.get("metadata") or {}
        meta["article_split"] = {"method": kind, "count": len(docs), "text_source": method}
        rec["metadata"] = meta
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated += 1
        arts_written += len(docs)
        log.info("split %s kind=%s arts=%s (was %s)", rid[:55], kind, len(docs), old_n)

    after = count_cc(cc)
    out = {
        "cc": cc,
        "before": before,
        "after": after,
        "updated": updated,
        "skipped": skipped,
        "arts_written": arts_written,
        "by_method": by_method,
        "ocr_used": ocr_used,
        "refetch": refetch_n,
        "text_improved": text_improved,
        "titles_fixed": titles_fixed,
    }
    report = ROOT / cc / "raw" / "iq_ir_article_reprocess.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return out


def main():
    ccs = sys.argv[1:] or ["ir", "iq"]
    t0 = time.time()
    for cc in ccs:
        reprocess_cc(cc)
    log.info("all done in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
