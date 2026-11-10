#!/usr/bin/env python3
"""Stronger OCR + honest-split deepen for SV/TN/ET/FJ/LA/LK.

1) Quarantine obvious non-laws / garbage
2) Re-apply honest splits on existing text (no invent)
3) For remaining PDF candidates: refetch + extract (OCR when native weak)
4) Accept only non-garbage improvements; never shrink good splits without better text

Usage:
  MAX_OCR=40 MAX_REFETCH=60 OCR_PAGES=30 /workspace/hf-venv/bin/python scrapers/ocr_deepen_pass.py sv tn et fj la lk
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT
from pdf_extract_lib import (
    extract_pdf_text, honest_split, is_garbage_text, normalize_bidi, split_by_pattern,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ocr_deepen")

# Extra TN pattern: الفصل / المادة may sit mid-line in multi-column JO text
TN_EXTRA = re.compile(r"(?m)((?:الفصل|المادة)\s+\S+)")

# LA: quarantine site chrome / annex listings that aren't statutory bodies
LA_JUNK_TITLE = re.compile(r"(Laogazette|ໜ້າຫຼັກ|ເອກະສານຊ້ອນທ້າຍ|Sawn wood)", re.I)
FJ_HINDI = re.compile(r"hindi|हिन्दी", re.I)


def ocr_lang_for(cc: str) -> str:
    return {
        "sv": "spa+eng",
        "tn": "ara+fra+eng",
        "et": "amh+eng",
        "fj": "eng",
        "la": "lao+eng",
        "lk": "eng+sin",
    }.get(cc, "eng")


def maybe_refetch_pdf(url: str, cc: str) -> bytes:
    if not url or ".pdf" not in url.lower():
        return b""
    import archive_fallbacks as af
    import requests
    requests.packages.urllib3.disable_warnings()
    ua = f"legal-corpora-collector/1.0 (research; cc={cc}; ocr-deepen)"
    try:
        r = requests.get(url, timeout=(12, 70), verify=False, headers={"User-Agent": ua})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content
    except Exception as exc:
        log.debug("live fail %s: %s", url[:80], exc)
    try:
        w = af.get_wayback_content(url)
        body = w.get("content") or b""
        if w.get("status") == "success" and body[:4] == b"%PDF":
            return body
    except Exception as exc:
        log.debug("wb fail %s: %s", url[:80], exc)
    return b""


def tn_split(text: str, law_id: str, source_url: str):
    text_n = normalize_bidi(text)
    docs, kind = honest_split("tn", text_n, law_id, source_url)
    if docs:
        return docs, kind
    # mid-line fasl fallback (JO multi-column); still require >=2
    docs = split_by_pattern(text_n, law_id, source_url, TN_EXTRA, "article", min_chunk=40)
    if docs:
        return docs, "fasl_inline"
    return [], "none"


def split_cc(cc: str, text: str, law_id: str, source_url: str):
    if cc == "tn":
        return tn_split(text, law_id, source_url)
    return honest_split(cc, text, law_id, source_url)


def scrub(cc: str, instr: Path) -> int:
    q = ROOT / cc / "quarantine_nonlaws"
    q.mkdir(parents=True, exist_ok=True)
    removed = 0
    for p in list(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        url = (rec.get("source_url") or "")
        title = rec.get("title") or ""
        drop = False
        reason = ""
        if is_garbage_text(text) and ("IHDR" in text[:120] or text.lstrip().startswith("%PDF") or "\x89PNG" in text[:20]):
            drop, reason = True, "binary_garbage"
        if cc == "tn" and url.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
            drop, reason = True, "image_url"
        if cc == "la" and (LA_JUNK_TITLE.search(title) or LA_JUNK_TITLE.search(text[:400]) or "Laogazette" in text[:80]):
            drop, reason = True, "la_site_chrome_or_annex"
        if cc == "fj" and FJ_HINDI.search(url) and is_garbage_text(text):
            drop, reason = True, "fj_hindi_garbage_scan"
        # SV spaced OCR historical already handled elsewhere; drop pure garbage
        if cc == "sv" and is_garbage_text(text) and len(text) > 5000:
            # keep unless clearly binary; deepen_sv handled 1847s
            if sum(1 for ch in text[:2000] if ord(ch) < 9) > 40:
                drop, reason = True, "sv_control_garbage"
        if drop:
            dest = q / p.name
            if dest.exists():
                dest = q / f"{p.stem}-{int(time.time())}.json"
            p.rename(dest)
            removed += 1
            log.info("quarantine %s (%s)", p.name, reason)
    return removed


def needs_ocr_candidate(cc: str, rec: dict) -> bool:
    text = rec.get("text") or ""
    url = rec.get("source_url") or ""
    docs = rec.get("documents") or []
    if ".pdf" not in url.lower():
        return False
    if is_garbage_text(text):
        return True
    if len(text) < 900:
        return True
    if len(docs) < 2:
        return True
    # ET: broken encoding / control chars even when long
    if cc == "et":
        ctrls = sum(1 for ch in text[:3000] if ord(ch) < 9)
        if ctrls > 20:
            return True
        # mostly private-use / replacement
        if text.count("\ufffd") > 30:
            return True
    if cc == "lk" and len(docs) < 2:
        return True
    return False


def deepen_cc(cc: str) -> dict:
    instr = ROOT / cc / "instruments"
    if not instr.exists():
        return {"cc": cc, "error": "no_instruments"}
    enable_ocr = os.environ.get("OCR", "1") == "1"
    max_ocr = int(os.environ.get("MAX_OCR", "40") or 40)
    max_refetch = int(os.environ.get("MAX_REFETCH", "60") or 60)
    ocr_pages = int(os.environ.get("OCR_PAGES", "30") or 30)
    force_ocr_always = os.environ.get("FORCE_OCR", "0") == "1"

    quarantined = scrub(cc, instr)
    updated_split = updated_text = skipped = 0
    ocr_used = refetch_n = 0
    by_method: dict[str, int] = {}
    text_improved = 0

    # Pass 1: honest re-split on existing text
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if cc == "tn":
            text = normalize_bidi(text)
            rec["text"] = text
        url = rec.get("source_url") or ""
        rid = rec.get("id") or p.stem
        docs, kind = split_cc(cc, text, rid, url)
        by_method[kind] = by_method.get(kind, 0) + 1
        old_n = len(rec.get("documents") or [])
        if len(docs) >= 2 and len(docs) > old_n:
            rec["documents"] = docs
            rec["article_count"] = len(docs)
            rec["article_extraction_status"] = "ok"
            meta = rec.get("metadata") or {}
            meta["article_split"] = {"method": kind, "count": len(docs), "pass": "ocr_deepen_resplit"}
            rec["metadata"] = meta
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            updated_split += 1
            log.info("resplit %s kind=%s arts=%s (was %s)", rid[:55], kind, len(docs), old_n)
        else:
            skipped += 1

    # Pass 2: refetch + OCR for remaining candidates
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not needs_ocr_candidate(cc, rec) and not force_ocr_always:
            continue
        if refetch_n >= max_refetch:
            break
        text = rec.get("text") or ""
        url = rec.get("source_url") or ""
        rid = rec.get("id") or p.stem
        old_docs = rec.get("documents") or []
        raw = maybe_refetch_pdf(url, cc)
        refetch_n += 1
        if not raw:
            log.info("refetch_fail %s", rid[:55])
            continue
        # Prefer native first; OCR if garbage/thin/force or still no splits after native
        from pdf_extract_lib import extract_ocr
        new_text, how, pages = extract_pdf_text(
            raw, enable_ocr=False, ocr_lang=ocr_lang_for(cc), ocr_max_pages=ocr_pages,
        )
        broken_native = False
        if cc == "et" and new_text:
            broken_native = sum(1 for ch in new_text[:3000] if ord(ch) < 9) > 20
        # Probe whether native text already splits honestly
        probe_docs, _ = split_cc(cc, new_text or "", rid, url)
        use_ocr = enable_ocr and ocr_used < max_ocr and (
            force_ocr_always
            or is_garbage_text(new_text)
            or len(new_text or "") < 200
            or broken_native
            or (len(old_docs) < 2 and is_garbage_text(text))
            or (cc in ("et", "lk", "la", "sv", "fj") and len(probe_docs) < 2 and len(old_docs) < 2)
        )
        if use_ocr:
            try:
                ocr_text, ocr_pages_n = extract_ocr(raw, lang=ocr_lang_for(cc), max_pages=ocr_pages)
                ocr_how = "ocr_tesseract"
                ocr_used += 1
            except Exception as exc:
                log.warning("ocr fail %s: %s", rid[:40], exc)
                ocr_text, ocr_how, ocr_pages_n = "", "ocr_fail", pages
            cand = []
            if new_text and not broken_native and not is_garbage_text(new_text):
                cand.append((new_text, how, pages))
            if ocr_text and not is_garbage_text(ocr_text):
                cand.append((ocr_text, ocr_how, ocr_pages_n))
            elif ocr_text and len(ocr_text) > len(new_text or ""):
                cand.append((ocr_text, ocr_how, ocr_pages_n))
            if not cand and new_text:
                cand.append((new_text, how, pages))
            cand.sort(key=lambda x: (0 if is_garbage_text(x[0]) else 1, len(x[0])), reverse=True)
            if cand:
                new_text, how, pages = cand[0]
        if not new_text or len(new_text) < 80 or is_garbage_text(new_text):
            log.info("extract_weak %s how=%s chars=%s", rid[:50], how, len(new_text or ""))
            continue
        improved = (
            is_garbage_text(text)
            or len(new_text) > len(text) * 1.05
            or (len(old_docs) < 2 and len(new_text) >= 80)
        )
        if not improved and how.startswith("ocr") and len(new_text) > len(text) * 0.9:
            improved = True
        if not improved:
            # still try split on new text if better structure
            docs_try, _ = split_cc(cc, new_text, rid, url)
            if len(docs_try) > len(old_docs):
                improved = True
            else:
                continue
        if cc == "tn":
            new_text = normalize_bidi(new_text)
        docs, kind = split_cc(cc, new_text, rid, url)
        # Don't regress article count unless replacing garbage text
        if len(old_docs) >= 2 and len(docs) < len(old_docs) and not is_garbage_text(text):
            # keep old docs, maybe still take better text if much longer
            if len(new_text) > len(text) * 1.2:
                rec["text"] = new_text
                meta = rec.get("metadata") or {}
                meta["pdf_reextract"] = {"method": how, "pages": pages, "parser": "ipfs_datasets_py.IntegratedPDFProcessor", "pass": "ocr_deepen"}
                rec["metadata"] = meta
                p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                updated_text += 1
                text_improved += 1
            continue
        rec["text"] = new_text
        if len(docs) >= 2:
            rec["documents"] = docs
            rec["article_count"] = len(docs)
            rec["article_extraction_status"] = "ok"
        elif is_garbage_text(text) or not old_docs:
            rec["documents"] = []
            rec["article_count"] = 0
            rec["article_extraction_status"] = "missing"
        meta = rec.get("metadata") or {}
        meta["pdf_reextract"] = {"method": how, "pages": pages, "parser": "ipfs_datasets_py.IntegratedPDFProcessor", "pass": "ocr_deepen"}
        meta["article_split"] = {"method": kind, "count": len(docs), "pass": "ocr_deepen"}
        rec["metadata"] = meta
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated_text += 1
        text_improved += 1
        by_method[kind] = by_method.get(kind, 0) + 1
        log.info("reextract %s via %s chars=%s arts=%s (was %s)", rid[:50], how, len(new_text), len(docs), len(old_docs))

    laws = arts = 0
    ocr_meta = 0
    for p in instr.glob("*.json"):
        rec = json.loads(p.read_text(encoding="utf-8"))
        if len(rec.get("text") or "") >= 80:
            laws += 1
            arts += len(rec.get("documents") or [])
        pe = (rec.get("metadata") or {}).get("pdf_reextract") or {}
        if str(pe.get("method") or "").startswith("ocr"):
            ocr_meta += 1
    out = {
        "cc": cc,
        "quarantined": quarantined,
        "updated_split": updated_split,
        "updated_text": updated_text,
        "text_improved": text_improved,
        "ocr_used": ocr_used,
        "refetch": refetch_n,
        "by_method": by_method,
        "laws": laws,
        "arts": arts,
        "ocr_meta": ocr_meta,
    }
    report = ROOT / cc / "raw" / "ocr_deepen_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out))
    return out


def main():
    ccs = sys.argv[1:] or ["sv", "tn", "et", "fj", "la", "lk"]
    for cc in ccs:
        log.info("=== deepen %s ===", cc)
        deepen_cc(cc)


if __name__ == "__main__":
    main()
