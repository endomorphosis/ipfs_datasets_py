from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import anyio


TEXT_ATTACHMENT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
    ".xml",
    ".log",
}

IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".webp",
}

PDF_SUFFIXES = {".pdf"}


try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pdfplumber = None

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    fitz = None

try:
    from ipfs_datasets_py.processors.specialized.pdf import MultiEngineOCR, TesseractOCR  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    MultiEngineOCR = None
    TesseractOCR = None


def _truncate_text(text: str, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip()


def _read_text_attachment(path: Path, *, max_bytes: int) -> str:
    raw = path.read_bytes()[:max_bytes]
    return raw.decode("utf-8", errors="ignore").strip()


def _extract_pdf_text_native(path: Path, *, max_chars: int) -> str:
    if pdfplumber is None:
        return ""
    parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
            if sum(len(part) for part in parts) >= max_chars:
                break
    return _truncate_text("\n\n".join(parts), max_chars)


def _ocr_image_bytes(image_bytes: bytes) -> dict[str, Any]:
    if TesseractOCR is not None:
        try:
            engine = TesseractOCR()
            if engine.is_available():
                result = engine.extract_text(image_bytes)
                return {
                    "text": str(result.get("text") or "").strip(),
                    "engine": result.get("engine") or "tesseract",
                    "confidence": float(result.get("confidence") or 0.0),
                }
        except Exception:
            pass
    if MultiEngineOCR is None:
        return {"text": "", "engine": None, "confidence": 0.0}
    try:
        ocr = MultiEngineOCR()
        result = ocr.extract_with_ocr(
            image_data=image_bytes,
            strategy="quality_first",
            confidence_threshold=0.7,
        )
    except Exception:
        return {"text": "", "engine": None, "confidence": 0.0}
    return {
        "text": str(result.get("text") or "").strip(),
        "engine": result.get("engine"),
        "confidence": float(result.get("confidence") or 0.0),
    }


def _extract_pdf_text_with_ocr(path: Path, *, max_chars: int, max_pages: int = 5) -> dict[str, Any]:
    if fitz is None:
        return {"text": "", "engine": None, "confidence": 0.0, "pages_ocrd": 0}
    doc = fitz.open(str(path))
    parts: list[str] = []
    best_confidence = 0.0
    engine_name = None
    pages_ocrd = 0
    try:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            pix = page.get_pixmap()
            image_bytes = pix.tobytes("png")
            result = _ocr_image_bytes(image_bytes)
            text = str(result.get("text") or "").strip()
            if text:
                parts.append(text)
                pages_ocrd += 1
            confidence = float(result.get("confidence") or 0.0)
            if confidence > best_confidence:
                best_confidence = confidence
                engine_name = result.get("engine")
            if sum(len(part) for part in parts) >= max_chars:
                break
    finally:
        doc.close()
    return {
        "text": _truncate_text("\n\n".join(parts), max_chars),
        "engine": engine_name,
        "confidence": best_confidence,
        "pages_ocrd": pages_ocrd,
    }


def extract_attachment_text(
    path: str | Path,
    *,
    max_chars: int = 20_000,
    max_bytes: int = 200_000,
    use_ocr: bool = True,
) -> dict[str, Any]:
    attachment_path = Path(path).expanduser().resolve()
    suffix = attachment_path.suffix.lower()
    result: dict[str, Any] = {
        "path": str(attachment_path),
        "filename": attachment_path.name,
        "suffix": suffix,
        "text": "",
        "method": "unsupported",
        "ocr_used": False,
        "ocr_engine": None,
        "confidence": 0.0,
    }
    if not attachment_path.exists() or not attachment_path.is_file():
        result["method"] = "missing"
        return result

    try:
        if suffix in TEXT_ATTACHMENT_SUFFIXES:
            result["text"] = _truncate_text(_read_text_attachment(attachment_path, max_bytes=max_bytes), max_chars)
            result["method"] = "text"
            return result

        if suffix in IMAGE_SUFFIXES:
            if not use_ocr:
                result["method"] = "image-no-ocr"
                return result
            ocr_result = _ocr_image_bytes(attachment_path.read_bytes())
            result["text"] = _truncate_text(str(ocr_result.get("text") or ""), max_chars)
            result["method"] = "image-ocr"
            result["ocr_used"] = bool(result["text"])
            result["ocr_engine"] = ocr_result.get("engine")
            result["confidence"] = float(ocr_result.get("confidence") or 0.0)
            return result

        if suffix in PDF_SUFFIXES:
            native_text = _extract_pdf_text_native(attachment_path, max_chars=max_chars)
            if native_text:
                result["text"] = native_text
                result["method"] = "pdf-text"
                if len(native_text) >= 500 or not use_ocr:
                    return result
            if use_ocr:
                ocr_result = _extract_pdf_text_with_ocr(attachment_path, max_chars=max_chars)
                merged = "\n\n".join(part for part in [native_text, str(ocr_result.get("text") or "").strip()] if part)
                result["text"] = _truncate_text(merged, max_chars)
                result["method"] = "pdf-text+ocr" if native_text else "pdf-ocr"
                result["ocr_used"] = bool(ocr_result.get("text"))
                result["ocr_engine"] = ocr_result.get("engine")
                result["confidence"] = float(ocr_result.get("confidence") or 0.0)
            return result
    except Exception as exc:  # pragma: no cover - defensive path
        result["method"] = "error"
        result["error"] = str(exc)
        return result

    return result


async def extract_attachment_text_async(
    path: str | Path,
    *,
    max_chars: int = 20_000,
    max_bytes: int = 200_000,
    use_ocr: bool = True,
) -> dict[str, Any]:
    return await anyio.to_thread.run_sync(
        lambda: extract_attachment_text(
            path,
            max_chars=max_chars,
            max_bytes=max_bytes,
            use_ocr=use_ocr,
        )
    )


__all__ = ["extract_attachment_text", "extract_attachment_text_async"]
