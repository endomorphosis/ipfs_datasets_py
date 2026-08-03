"""
Compact synthetic PDF generators for PATLAW-004 OCR / coverage tests.

Produces minimal multi-page PDFs that exercise:
  - native-text pages
  - scanned (image-only) pages
  - rotated scanned pages
  - mixed native + embedded-image pages

Canary strings are synthetic and not real confidential matter; security tests
treat them as private markers that must not appear in disclosure sinks.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Optional, Union

try:
    import fitz  # PyMuPDF
except ImportError as e:  # pragma: no cover
    fitz = None
    _FITZ_ERROR = e
else:
    _FITZ_ERROR = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageFont = None
    _PIL_ERROR = e
else:
    _PIL_ERROR = None

# Synthetic canaries — not real USPTO content
SCANNED_CANARY = "SYNTHETIC-SCANNED-OFFICE-ACTION-REQ-112"
ROTATED_CANARY = "SYNTHETIC-ROTATED-SCAN-PAGE-CLAIM-1"
CONFIDENTIAL_CANARY = "SYNTHETIC-CONFIDENTIAL-PRIVATE-PDF-BODY-DO-NOT-LOG"
NATIVE_CANARY = "SYNTHETIC-NATIVE-TEXT-ABSTRACT-PARAGRAPH"


def _require_deps() -> None:
    if fitz is None:
        raise RuntimeError(f"PyMuPDF required for fixtures: {_FITZ_ERROR}")
    if Image is None:
        raise RuntimeError(f"Pillow required for fixtures: {_PIL_ERROR}")


def _text_image(
    text: str,
    *,
    width: int = 420,
    height: int = 560,
    rotate: int = 0,
) -> bytes:
    """Render text onto a compact white JPEG (optionally rotated) for image-only pages."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    # Default font is fine for OCR smoke tests
    y = 40
    for line in text.split("\n"):
        draw.text((20, y), line, fill="black")
        y += 28
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor="white")
    buf = io.BytesIO()
    # JPEG keeps fixtures small (admission budgets / no bulk goldens)
    img.save(buf, format="JPEG", quality=55, optimize=True)
    return buf.getvalue()


def _write_pdf(path: Path, builder) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        builder(doc)
        doc.save(str(path))
    finally:
        doc.close()
    return path


def build_native_text_pdf(path: Union[str, Path], text: str = NATIVE_CANARY) -> Path:
    """Single-page PDF with extractable native text."""
    _require_deps()

    def build(doc):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "UNITED STATES PATENT AND TRADEMARK OFFICE", fontsize=11)
        page.insert_text((72, 100), text, fontsize=12)
        page.insert_text((72, 140), "This page has a selectable text layer.", fontsize=11)

    return _write_pdf(Path(path), build)


def build_scanned_image_only_pdf(
    path: Union[str, Path],
    text: str = SCANNED_CANARY,
) -> Path:
    """Image-only PDF (no native text layer) simulating a scanned office action."""
    _require_deps()
    png = _text_image(
        f"USPTO OFFICE ACTION\nApplication 16/000,001\n{text}\nReject under 35 U.S.C. 112",
        rotate=0,
    )

    def build(doc):
        page = doc.new_page(width=612, height=792)
        rect = fitz.Rect(0, 0, 612, 792)
        page.insert_image(rect, stream=png)

    return _write_pdf(Path(path), build)


def build_rotated_scanned_pdf(
    path: Union[str, Path],
    text: str = ROTATED_CANARY,
    rotation: int = 90,
) -> Path:
    """Scanned image-only page with /Rotate set (common scanner defect)."""
    _require_deps()
    # Draw text upright in the image; page rotation metadata forces display rotation
    png = _text_image(
        f"ROTATED SCAN FIXTURE\n{text}\nClaim 1 is rejected.",
        rotate=0,
    )

    def build(doc):
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(0, 0, 612, 792), stream=png)
        page.set_rotation(int(rotation) % 360)

    return _write_pdf(Path(path), build)


def build_mixed_native_and_image_pdf(
    path: Union[str, Path],
    native_text: str = NATIVE_CANARY,
    image_text: str = SCANNED_CANARY,
) -> Path:
    """Two-page PDF: native text page + scanned image-only page."""
    _require_deps()
    png = _text_image(f"SCANNED EXHIBIT\n{image_text}")

    def build(doc):
        p0 = doc.new_page(width=612, height=792)
        p0.insert_text((72, 72), native_text, fontsize=12)
        p1 = doc.new_page(width=612, height=792)
        p1.insert_image(fitz.Rect(0, 0, 612, 792), stream=png)

    return _write_pdf(Path(path), build)


def build_confidential_scanned_pdf(
    path: Union[str, Path],
    canary: str = CONFIDENTIAL_CANARY,
) -> Path:
    """Scanned PDF whose body is treated as private for non-disclosure tests."""
    return build_scanned_image_only_pdf(path, text=canary)


def fixture_manifest(directory: Optional[Path] = None) -> Dict[str, Any]:
    """Return a compact recipe manifest (paths + digests) without bulk golden text."""
    directory = Path(directory or Path(__file__).resolve().parent)
    directory.mkdir(parents=True, exist_ok=True)
    recipes = {
        "native_text.pdf": lambda p: build_native_text_pdf(p),
        "scanned_office_action.pdf": lambda p: build_scanned_image_only_pdf(p),
        "rotated_scanned_page.pdf": lambda p: build_rotated_scanned_pdf(p),
        "mixed_native_and_scan.pdf": lambda p: build_mixed_native_and_image_pdf(p),
        "confidential_scanned.pdf": lambda p: build_confidential_scanned_pdf(p),
    }
    entries = []
    for name, builder in recipes.items():
        out = directory / name
        builder(out)
        data = out.read_bytes()
        entries.append(
            {
                "name": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "synthetic": True,
            }
        )
    return {
        "version": 1,
        "description": "Synthetic USPTO-style PDF fixtures for PATLAW-004",
        "fixtures": entries,
    }


if __name__ == "__main__":
    import json

    man = fixture_manifest()
    print(json.dumps({"fixture_count": len(man["fixtures"]), "version": man["version"]}))
