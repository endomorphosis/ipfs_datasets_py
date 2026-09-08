#!/usr/bin/env python3
"""PDF text extraction helpers mirroring ipfs_datasets_py IntegratedPDFProcessor.

Prefer pdfplumber -> pymupdf -> pdftotext; OCR (tesseract) only when text layer
is missing or garbage. Honest article splits require >=2 heading matches.
"""
from __future__ import annotations

import io
import logging
import re
import subprocess
import tempfile
from typing import Optional

log = logging.getLogger("pdf_extract_lib")

# Spaced-out OCR garbage like "D  IA     R       IO"
_GARBAGE_SPACING = re.compile(r"(?:^[A-Za-z]\s+){6,}", re.M)


def is_garbage_text(text: str) -> bool:
    if not text or len(text) < 40:
        return True
    if text.lstrip().startswith("%PDF") or "endobj" in text[:200]:
        return True
    if "IHDR" in text[:120] or text[:8].startswith("\x89PNG") or "PNG" in text[:20] and "IHDR" in text[:80]:
        return True
    sample = text[:8000]
    # Broken ToUnicode / CID font dumps from Arabic/Persian PDFs
    if sample.count("(cid:") >= 8:
        return True
    arabic = sum(1 for ch in sample if "\u0600" <= ch <= "\u06FF")
    ctrl = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\n\r\t\x0c")
    n = max(1, len(sample))
    # Encoding-corrupt Arabic/Persian PDFs: many controls / almost no Arabic script
    if len(sample) > 500 and (ctrl / n) > 0.04 and (arabic / n) < 0.05:
        return True
    if len(sample) > 800 and arabic < 80 and sample.count("@") > 30:
        return True
    letters = sum(ch.isalpha() for ch in sample)
    spaces = sample.count(" ")
    if letters < 80 and arabic < 40:
        return True
    # Mojibake Latin stand-in for Arabic (common in old MoJ PDFs)
    ascii_letters = sum(ch.isalpha() and ord(ch) < 128 for ch in sample)
    if len(sample) > 500 and arabic < 20 and ascii_letters > 400:
        return True
    if spaces > letters * 1.8 and _GARBAGE_SPACING.search(sample):
        return True
    singles = len(re.findall(r"(?m)^\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]\s*$", sample))
    if singles > 30 and singles > letters * 0.15:
        return True
    return False


def extract_pdfplumber(raw: bytes, max_pages: int = 200) -> tuple[str, int]:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        n = len(pdf.pages)
        parts = []
        for page in pdf.pages[:max_pages]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
    text = "\n".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, n


def extract_pymupdf(raw: bytes, max_pages: int = 200) -> tuple[str, int]:
    import pymupdf
    doc = pymupdf.open(stream=raw, filetype="pdf")
    n = doc.page_count
    parts = [page.get_text() for page in doc[:max_pages]]
    text = "\n".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, n


def extract_pdftotext(raw: bytes) -> str:
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


def extract_ocr(raw: bytes, lang: str = "eng", max_pages: int = 40, dpi: int = 120) -> tuple[str, int]:
    """Render pages with pymupdf and OCR via tesseract CLI."""
    import pymupdf
    doc = pymupdf.open(stream=raw, filetype="pdf")
    n = doc.page_count
    parts = []
    mat = pymupdf.Matrix(dpi / 72, dpi / 72)
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=mat, alpha=False)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img:
            pix.save(img.name)
            img_path = img.name
        try:
            env = dict(**__import__("os").environ)
            env["OMP_THREAD_LIMIT"] = "1"
            env["TESSDATA_PREFIX"] = env.get("TESSDATA_PREFIX", "/usr/share/tesseract-ocr/5/tessdata")
            proc = subprocess.run(
                ["tesseract", img_path, "stdout", "-l", lang, "--psm", "6"],
                capture_output=True, text=True, timeout=180, env=env,
            )
            if proc.returncode == 0 and proc.stdout:
                parts.append(proc.stdout)
        except Exception as exc:
            log.debug("ocr page %s: %s", i, exc)
        finally:
            try:
                import os
                os.unlink(img_path)
            except Exception:
                pass
    text = "\n".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, n


def extract_pdf_text(
    raw: bytes,
    *,
    enable_ocr: bool = True,
    ocr_lang: str = "eng",
    ocr_max_pages: int = 40,
) -> tuple[str, str, int]:
    """Return (text, method, page_count). Mirrors IntegratedPDFProcessor order."""
    if not raw:
        return "", "not_pdf", 0
    if raw[:4] != b"%PDF":
        idx = raw.find(b"%PDF", 0, 65536)
        if idx < 0:
            return "", "not_pdf", 0
        raw = raw[idx:]
    best_text, best_method, pages = "", "failed", 0
    for name, fn in (
        ("pdfplumber", lambda: extract_pdfplumber(raw)),
        ("pymupdf", lambda: extract_pymupdf(raw)),
    ):
        try:
            text, pages = fn()
            if text and not is_garbage_text(text) and len(text) >= 80:
                return text, name, pages
            if len(text) > len(best_text):
                best_text, best_method = text, name
        except Exception as exc:
            log.debug("%s failed: %s", name, exc)
    try:
        text = extract_pdftotext(raw)
        if text and not is_garbage_text(text) and len(text) >= 80:
            return text, "pdftotext", pages
        if len(text) > len(best_text):
            best_text, best_method = text, "pdftotext"
    except Exception:
        pass
    if enable_ocr and (is_garbage_text(best_text) or len(best_text) < 120):
        try:
            text, pages = extract_ocr(raw, lang=ocr_lang, max_pages=ocr_max_pages)
            if text and len(text) >= 80 and not is_garbage_text(text):
                return text, "ocr_tesseract", pages
            if len(text) > len(best_text):
                best_text, best_method = text, "ocr_tesseract"
        except Exception as exc:
            log.debug("ocr failed: %s", exc)
    return best_text, best_method if best_text else "failed", pages


def normalize_bidi(text: str) -> str:
    return re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u200c\u200d\ufeff]", "", text or "")


_EASTERN_DIGITS = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9",
    "01234567890123456789",
)


def normalize_rtl_text(text: str) -> str:
    """Strip bidi marks and map Arabic/Persian digits to ASCII for heading regexes."""
    t = normalize_bidi(text or "")
    t = re.sub(r"[\u00ad\u200b]", "", t)
    return t.translate(_EASTERN_DIGITS)



def split_by_pattern(
    text: str,
    law_id: str,
    source_url: str,
    pat: re.Pattern,
    record_type: str = "article",
    min_chunk: int = 40,
    max_docs: int = 4000,
) -> list[dict]:
    matches = list(pat.finditer(text or ""))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < min_chunk:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^\w\u0600-\u06FF\u1200-\u137F]+", "-", num.lower(), flags=re.U).strip("-")[:80]
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": None,
            "document_number": num,
            "source_url": source_url,
            "record_type": record_type,
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {
                    "source": "official",
                    "backend": "honest_heading_split",
                    "parser": "ipfs_datasets_py.IntegratedPDFProcessor+heading_split",
                    "pattern": pat.pattern[:100],
                }
            },
        })
        if len(docs) >= max_docs:
            break
    return docs if len(docs) >= 2 else []


# Country-specific honest patterns (tried in order)
COUNTRY_PATTERNS: dict[str, list[tuple[str, re.Pattern, str]]] = {
    "sv": [
        ("articulo", re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.)?|ART[IÍ]CULO)\s+\d+[º°a-z.]*)"), "article"),
    ],
    "tn": [
        ("fasl", re.compile(r"(?m)^\s*((?:الفصل|المادة)\s+\S+)"), "article"),
        ("article", re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+)"), "article"),
    ],
    "et": [
        ("article_heading", re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+\.?)\s*(?:[.\-–—:]|\s+[A-Z\"“])"), "article"),
        ("article_loose", re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+)"), "article"),
        ("article_inline", re.compile(r"(?im)((?:Article|Art\.)\s+\d+)(?![\d])"), "article"),
        ("anqets", re.compile(r"(?m)^\s*((?:አንቀጽ|አንቀፅ)\s*[/\.]?\s*\d+)"), "article"),
        ("anqets_inline", re.compile(r"(?m)((?:አንቀጽ|አንቀፅ)\s*[/.]?\s*\d+)"), "article"),
    ],
    "jm": [
        ("section", re.compile(r"(?im)^\s*((?:Section|SECTION)\s+\d+[A-Za-z]?\.?)"), "section"),
        ("part", re.compile(r"(?im)^\s*((?:PART|Part)\s+[IVXLC\d]+)"), "section"),
    ],
    "fj": [
        ("numbered_emdash", re.compile(r"(?m)^\s*((?:\d+)\.—)"), "article"),
        ("section", re.compile(r"(?im)^\s*((?:Section|SECTION|Article|ARTICLE)\s+\d+)"), "article"),
        ("chapter", re.compile(r"(?im)^\s*((?:CHAPTER|Chapter)\s+\d+)"), "section"),
    ],
    "la": [
        ("article", re.compile(r"(?im)^\s*((?:Article|Art\.|ມາດຕາ)\s*\d+)"), "article"),
    ],
    "lk": [
        ("section", re.compile(r"(?im)^\s*((?:Section|SECTION)\s+\d+[A-Za-z]?)"), "section"),
        ("article", re.compile(r"(?im)^\s*((?:Article|ARTICLE)\s+\d+)"), "article"),
    ],
    "md": [
        ("articolul", re.compile(r"(?im)^\s*((?:Articolul|Art\.)\s*\d+(?:\^[0-9]+)?)"), "article"),
        ("articolul_inline", re.compile(r"(?im)((?:Articolul|Art\.)\s*\d+(?:\^[0-9]+)?)\s*[.\-–—:]"), "article"),
    ],
    "iq": [
        ("mada", re.compile(r"(?m)^\s*((?:المادة|مادة)\s*[-–—:]*\s*\d+)(?!\d)"), "article"),
        ("mada_ocr", re.compile(r"(?m)^\s*((?:المادة|مادة)\s*[-–—:\s]*\d+)(?!\d)"), "article"),
        ("fasl", re.compile(r"(?m)^\s*((?:الفصل|الباب)\s+\S+)"), "section"),
        ("article_en", re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+)(?!\d)"), "article"),
    ],
    "ir": [
        ("mada", re.compile(r"(?m)^\s*((?:ماده)\s*(?:واحده|\d+))(?!\d)"), "article"),
        ("mada_prefixed", re.compile(
            r"(?m)^\s*(?:\d+[\-–—ـ.)\]]*\s*)?((?:ماده)\s*(?:واحده|\d+))(?!\d)"
        ), "article"),
        ("fasl_bab", re.compile(
            r"(?m)^\s*((?:فصل|باب)\s*(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|\d+))"
        ), "section"),
        ("article_en", re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+\d+)(?!\d)"), "article"),
    ],
    "mz": [
        ("artigo", re.compile(r"(?im)^\s*((?:Artigo|Art\.|ARTIGO)\s+\d+[ºªo°a-zA-Z]?)"), "article"),
    ],
}


def honest_split(cc: str, text: str, law_id: str, source_url: str) -> tuple[list[dict], str]:
    if cc in ("tn", "iq", "ir", "dz", "lb", "ma", "eg", "sa", "ae"):
        text_n = normalize_rtl_text(text)
    else:
        text_n = text
    for name, pat, rtype in COUNTRY_PATTERNS.get(cc, []):
        docs = split_by_pattern(text_n, law_id, source_url, pat, rtype)
        if docs:
            return docs, name
    # shared fallback
    from common import split_articles
    docs = split_articles(text_n, law_id, source_url)
    if len(docs) >= 2:
        return docs, "common_article_split"
    return [], "none"
