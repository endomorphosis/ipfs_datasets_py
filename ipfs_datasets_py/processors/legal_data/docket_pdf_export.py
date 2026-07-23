"""PDF export helpers for docket datasets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic"}


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _wrap_text(text: str, max_chars: int = 100) -> List[str]:
    words = str(text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}"
    lines.append(current)
    return lines


def _draw_footer(pdf: canvas.Canvas, label: str, page_number: int) -> None:
    width, _ = letter
    pdf.setFont("Times-Roman", 9)
    pdf.drawString(0.75 * inch, 0.45 * inch, label[:95])
    pdf.drawRightString(width - 0.75 * inch, 0.45 * inch, f"Page {page_number}")


def _begin_page(pdf: canvas.Canvas, heading: str) -> float:
    width, height = letter
    left = 0.8 * inch
    top = height - 0.8 * inch
    pdf.setFont("Times-Bold", 16)
    pdf.drawString(left, top, heading[:90])
    return top - 0.35 * inch


def _append_text_sections(
    pdf: canvas.Canvas,
    *,
    heading: str,
    sections: Sequence[tuple[str, Sequence[str]]],
    footer_label: str,
    page_number: int,
) -> int:
    width, height = letter
    left = 0.8 * inch
    bottom = 0.95 * inch
    line_height = 13
    y = _begin_page(pdf, heading)
    for section_title, section_lines in sections:
        block_lines: List[str] = []
        if section_title:
            block_lines.append(section_title)
        for raw in section_lines:
            block_lines.extend(_wrap_text(str(raw or ""), max_chars=105))
        block_lines.append("")

        for idx, line in enumerate(block_lines):
            font_name = "Times-Bold" if section_title and idx == 0 else "Times-Roman"
            font_size = 12 if section_title and idx == 0 else 11
            if y < bottom:
                _draw_footer(pdf, footer_label, page_number)
                pdf.showPage()
                page_number += 1
                y = _begin_page(pdf, heading)
            pdf.setFont(font_name, font_size)
            pdf.drawString(left, y, line[:120])
            y -= line_height

    return page_number


def _append_image_page(
    pdf: canvas.Canvas,
    image_path: Path,
    *,
    heading: str,
    footer_label: str,
    page_number: int,
) -> int:
    width, height = letter
    margin = 0.55 * inch
    usable_width = width - (2 * margin)
    usable_height = height - (2 * margin) - 0.35 * inch

    y = _begin_page(pdf, heading)
    del y
    with Image.open(image_path) as img:
        rgb = img.convert("RGB")
        img_width, img_height = rgb.size
        scale = min(usable_width / img_width, usable_height / img_height)
        draw_width = img_width * scale
        draw_height = img_height * scale
        x = (width - draw_width) / 2
        y = ((height - 0.35 * inch) - draw_height) / 2
        pdf.drawImage(ImageReader(rgb), x, y, width=draw_width, height=draw_height, preserveAspectRatio=True, anchor="c")
    _draw_footer(pdf, footer_label, page_number)
    return page_number


@dataclass
class DocketPdfSourceArtifact:
    document_id: str
    title: str
    path: str
    kind: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "path": self.path,
            "kind": self.kind,
        }


def _iter_local_source_candidates(document: Mapping[str, Any]) -> Iterable[Path]:
    metadata = dict(document.get("metadata") or {})
    raw = dict(metadata.get("raw") or {})
    seen: set[str] = set()

    def emit(candidate: Any) -> Iterable[Path]:
        path_text = ""
        if isinstance(candidate, Mapping):
            path_text = str(candidate.get("path") or candidate.get("source_path") or candidate.get("local_path") or "")
        else:
            path_text = str(candidate or "")
        path_text = path_text.strip()
        if not path_text:
            return []
        if path_text in seen:
            return []
        seen.add(path_text)
        path = Path(path_text).expanduser()
        if path.exists() and path.is_file():
            return [path]
        return []

    candidates: List[Any] = []
    for key in ("source_path", "local_path"):
        candidates.append(metadata.get(key))
        candidates.append(raw.get(key))
    for key in ("attachments", "attachment_paths", "sidecar_paths", "exhibits", "files"):
        values = raw.get(key)
        if isinstance(values, list):
            candidates.extend(values)
    acquisition_candidates = list(metadata.get("acquisition_candidates") or [])
    candidates.extend(acquisition_candidates)

    for candidate in candidates:
        for path in emit(candidate):
            yield path


def _collect_source_artifacts(documents: Sequence[Mapping[str, Any]]) -> List[DocketPdfSourceArtifact]:
    artifacts: List[DocketPdfSourceArtifact] = []
    seen_paths: set[str] = set()
    for document in documents:
        document_id = str(document.get("document_id") or document.get("id") or "")
        title = str(document.get("title") or document_id or "Document").strip()
        for path in _iter_local_source_candidates(document):
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            suffix = path.suffix.lower()
            kind = "pdf" if suffix == ".pdf" else "image" if suffix in SUPPORTED_IMAGE_SUFFIXES else "file"
            artifacts.append(
                DocketPdfSourceArtifact(
                    document_id=document_id,
                    title=title,
                    path=resolved,
                    kind=kind,
                )
            )
    return artifacts


def export_docket_dataset_single_pdf(
    dataset: Any,
    output_path: str | Path,
    *,
    title: Optional[str] = None,
    include_source_files: bool = True,
) -> Dict[str, Any]:
    """Export a docket dataset into a readable PDF binder."""

    dataset_payload = dataset.to_dict() if hasattr(dataset, "to_dict") else dict(dataset)
    documents = [dict(item) for item in list(dataset_payload.get("documents") or []) if isinstance(item, Mapping)]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    case_name = str(dataset_payload.get("case_name") or "Docket Dataset").strip()
    docket_id = str(dataset_payload.get("docket_id") or "").strip()
    court = str(dataset_payload.get("court") or "").strip()
    heading = title or case_name or "Docket Dataset Export"

    source_artifacts = _collect_source_artifacts(documents) if include_source_files else []
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    page_number = 1

    intro_sections = [
        ("Dataset Summary", [
            f"Case Name: {case_name}",
            f"Docket ID: {docket_id}",
            f"Court: {court}",
            f"Document Count: {len(documents)}",
            f"Bundled Local Source Files: {len(source_artifacts)}",
        ]),
    ]
    page_number = _append_text_sections(
        pdf,
        heading=heading,
        sections=intro_sections,
        footer_label="Docket Dataset Summary",
        page_number=page_number,
    )

    for index, document in enumerate(documents, start=1):
        _draw_footer(pdf, "Docket Dataset Summary", page_number)
        pdf.showPage()
        page_number += 1

        document_id = str(document.get("document_id") or document.get("id") or f"document_{index}")
        metadata = dict(document.get("metadata") or {})
        source_paths = [artifact.path for artifact in source_artifacts if artifact.document_id == document_id]
        metadata_json = json.dumps(_jsonable(metadata), indent=2, ensure_ascii=False)
        sections = [
            ("Document", [
                f"Document ID: {document_id}",
                f"Title: {str(document.get('title') or '').strip()}",
                f"Document Number: {str(document.get('document_number') or '').strip()}",
                f"Date Filed: {str(document.get('date_filed') or '').strip()}",
                f"Source URL: {str(document.get('source_url') or '').strip()}",
                f"Attached Local Sources: {len(source_paths)}",
            ]),
            ("Text", _wrap_text(str(document.get("text") or "").strip() or "[No document text available]", max_chars=105)),
        ]
        if metadata:
            sections.append(("Metadata", metadata_json.splitlines()))
        if source_paths:
            sections.append(("Local Source Paths", source_paths))
        page_number = _append_text_sections(
            pdf,
            heading=f"{heading} - Document {index}",
            sections=sections,
            footer_label=str(document.get("title") or document_id or f"Document {index}"),
            page_number=page_number,
        )

    for artifact in source_artifacts:
        _draw_footer(pdf, str(documents[-1].get("title") or "Docket Document") if documents else "Docket Dataset", page_number)
        pdf.showPage()
        page_number += 1

        artifact_path = Path(artifact.path)
        if artifact.kind == "image":
            page_number = _append_image_page(
                pdf,
                artifact_path,
                heading=f"{heading} - Source Image",
                footer_label=f"{artifact.title} - source image",
                page_number=page_number,
            )
            continue
        page_number = _append_text_sections(
            pdf,
            heading=f"{heading} - Source Reference",
            sections=[
                ("Source File", [
                    f"Document ID: {artifact.document_id}",
                    f"Title: {artifact.title}",
                    f"Path: {artifact.path}",
                    f"Kind: {artifact.kind}",
                    (
                        "This referenced PDF was recorded in the export metadata but not inlined; "
                        "use the path above to retrieve the native filing."
                        if artifact.kind == "pdf"
                        else "This file type is referenced in the export but was not inlined into the PDF binder."
                    ),
                ])
            ],
            footer_label=f"{artifact.title} - source reference",
            page_number=page_number,
        )

    final_footer_label = f"{heading} - source reference" if source_artifacts else (
        str(documents[-1].get("title") or "Docket Document") if documents else "Docket Dataset Summary"
    )
    _draw_footer(pdf, final_footer_label, page_number)
    pdf.save()
    return {
        "pdf_path": str(output_path),
        "page_count": int(page_number),
        "document_count": len(documents),
        "source_artifact_count": len(source_artifacts),
        "included_source_files": bool(include_source_files),
        "source_artifacts": [artifact.to_dict() for artifact in source_artifacts],
        "sha256": _digest_file(output_path),
        "file_size": output_path.stat().st_size,
        "title": heading,
    }


__all__ = ["export_docket_dataset_single_pdf"]
