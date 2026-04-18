"""Scan HACC PDF trees for likely court filings and package them as docket datasets."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional OCR dependency
    fitz = None

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional OCR dependency
    Image = None

try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover - optional OCR dependency
    pytesseract = None

from ..legal_data import export_docket_dataset_single_parquet, ingest_docket_dataset
from ..legal_data.case_knowledge import build_case_knowledge_graph, summarize_case_graph
from ..legal_data.document_structure import build_document_knowledge_graph, parse_legal_document
from ..legal_data.docket_dataset import _extract_case_number_from_text, _extract_text_from_pdf, _normalize_case_number_text

logger = logging.getLogger(__name__)

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    ".tools",
    ".venv",
    ".venv-pacer-test",
    "__pycache__",
    "node_modules",
    "site-packages",
    "tmp",
}
_SKIP_DIR_PREFIXES = (
    ".git",
    ".venv",
    "complaint-site-playwright-",
    "pytest-",
    "pytest-of-",
    "tmp_live_",
)

_COURT_HEADER_PATTERNS = [
    re.compile(r"\bIN THE UNITED STATES DISTRICT COURT\b", re.IGNORECASE),
    re.compile(r"\bUNITED STATES DISTRICT COURT\b", re.IGNORECASE),
    re.compile(r"\bUNITED STATES BANKRUPTCY COURT\b", re.IGNORECASE),
    re.compile(r"\bUNITED STATES COURT OF APPEALS\b", re.IGNORECASE),
    re.compile(r"\bIN THE CIRCUIT COURT OF THE STATE OF [A-Z\s]+\b", re.IGNORECASE),
    re.compile(r"\bIN THE (?:CIRCUIT|SUPERIOR|PROBATE|DISTRICT|JUVENILE|MUNICIPAL) COURT OF [A-Z\s,]+\b", re.IGNORECASE),
    re.compile(r"\bFOR THE COUNTY OF [A-Z\s]+\b", re.IGNORECASE),
    re.compile(r"\bPROBATE DEPARTMENT\b", re.IGNORECASE),
    re.compile(r"\bIN THE [A-Z][A-Z\s]+(?:DISTRICT|CIRCUIT|SUPERIOR|PROBATE|APPEALS|SUPREME) COURT\b", re.IGNORECASE),
]
_STYLE_LINE_PATTERN = re.compile(r"(?:\bv(?:s)?\.?\s+\S+)|(?:\bversus\b)|(?:\bin re\b)", re.IGNORECASE)
_PROBATE_CAPTION_PATTERN = re.compile(r"^in the matter of:?$", re.IGNORECASE)


@dataclass
class HACCCourtPDFScanResult:
    path: str
    relative_path: str
    is_likely_court_case: bool
    case_number: str = ""
    court: str = ""
    case_name: str = ""
    title: str = ""
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    extraction_method: str = ""
    text_length: int = 0
    matched_court_headers: List[str] = field(default_factory=list)
    style_lines: List[str] = field(default_factory=list)
    document_knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    document_knowledge_graph_summary: Dict[str, Any] = field(default_factory=dict)
    parsed_document: Dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if not self.text:
            payload.pop("text", None)
        return payload


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


def _utc_now_isoformat() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _has_ocr_support() -> bool:
    return bool(_ocr_support_summary().get("available"))


def _ocr_support_summary() -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "available": False,
        "fitz": bool(fitz),
        "pillow": bool(Image),
        "pytesseract": bool(pytesseract),
        "tesseract_command": "",
        "tesseract_version": "",
        "languages": [],
    }
    if not (fitz and Image and pytesseract):
        return summary

    configured_command = str(getattr(getattr(pytesseract, "pytesseract", None), "tesseract_cmd", "") or "tesseract").strip()
    resolved_command = shutil.which(configured_command) or (configured_command if configured_command and Path(configured_command).exists() else "")
    summary["tesseract_command"] = resolved_command or configured_command
    try:
        summary["tesseract_version"] = str(pytesseract.get_tesseract_version())
    except Exception as exc:  # pragma: no cover - environment-dependent
        summary["error"] = str(exc)
        return summary

    try:
        summary["languages"] = [str(item).strip() for item in pytesseract.get_languages(config="") if str(item).strip()]
    except Exception as exc:  # pragma: no cover - environment-dependent
        summary["languages_error"] = str(exc)

    supports_english = True
    if summary["languages"]:
        supports_english = "eng" in {str(item).lower() for item in summary["languages"]}
    summary["available"] = bool(resolved_command and summary["tesseract_version"] and supports_english)
    return summary


def _is_likely_scanned_pdf_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if len(normalized) < 80:
        return True
    word_count = len(re.findall(r"\b\w+\b", normalized))
    alpha_ratio = sum(ch.isalpha() for ch in normalized) / max(len(normalized), 1)
    return word_count < 25 or alpha_ratio < 0.45


def _extract_pdf_ocr_text(path: Path, *, max_pages: int = 5) -> str:
    if not _has_ocr_support():
        return ""
    text_parts: List[str] = []
    try:
        document = fitz.open(str(path))
        try:
            for page_index in range(min(len(document), max_pages)):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                page_text = str(pytesseract.image_to_string(image, lang="eng") or "").strip()
                if page_text:
                    text_parts.append(page_text)
        finally:
            document.close()
    except Exception as exc:  # pragma: no cover - OCR errors are environment-dependent
        logger.warning("OCR extraction failed for %s: %s", path, exc)
    return "\n\n".join(text_parts).strip()


def _pdf_page_count(path: Path) -> int:
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name, fromlist=["PdfReader"])
            reader_cls = getattr(module, "PdfReader", None)
            if reader_cls is None:
                continue
            reader = reader_cls(str(path))
            return len(list(getattr(reader, "pages", []) or []))
        except Exception:
            continue
    return 0


def _file_metadata(path: Path) -> Dict[str, Any]:
    stats = path.stat()
    return {
        "file_name": path.name,
        "file_size_bytes": int(stats.st_size),
        "modified_at": datetime.fromtimestamp(stats.st_mtime, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "suffix": path.suffix.lower(),
        "page_count": _pdf_page_count(path),
    }


def _extract_text_from_pdf_with_ocr(path: Path, *, max_ocr_pages: int = 5) -> tuple[str, str]:
    extracted = _extract_text_from_pdf(path)
    if extracted and not _is_likely_scanned_pdf_text(extracted):
        return extracted, "pypdf"

    ocr_text = _extract_pdf_ocr_text(path, max_pages=max_ocr_pages)
    if len(ocr_text) > len(extracted):
        return ocr_text, "ocr"
    if extracted:
        return extracted, "pypdf"
    return ocr_text, "ocr" if ocr_text else "unavailable"


def _matched_court_headers(lines: Sequence[str]) -> List[str]:
    matches: List[str] = []
    for line in lines:
        stripped = str(line or "").strip()
        if not stripped:
            continue
        if any(pattern.search(stripped) for pattern in _COURT_HEADER_PATTERNS):
            matches.append(stripped)
    return matches


def _validated_case_number(value: str) -> str:
    text = _normalize_case_number_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"order", "re", "in", "d", "mixes", "relies"}:
        return ""
    digit_count = sum(ch.isdigit() for ch in text)
    alpha_count = sum(ch.isalpha() for ch in text)
    if digit_count == 0:
        return ""
    if ":" in text or "-" in text or "/" in text:
        return text
    if alpha_count > 0 and digit_count >= 4:
        return text
    if alpha_count == 0 and digit_count >= 4:
        return text
    return ""


def _matter_of_case_name(lines: Sequence[str]) -> str:
    cleaned_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    for index, line in enumerate(cleaned_lines):
        if not _PROBATE_CAPTION_PATTERN.match(line):
            continue
        caption_parts = ["In the Matter of"]
        for next_line in cleaned_lines[index + 1 : index + 4]:
            if _COURT_HEADER_PATTERNS[0].search(next_line) or next_line.lower().startswith("case no"):
                break
            caption_parts.append(next_line.rstrip(","))
            if next_line.endswith("."):
                break
        return " ".join(part.strip(" ,") for part in caption_parts if part).strip()
    return ""


def _style_lines(lines: Sequence[str]) -> List[str]:
    return [str(line).strip() for line in lines if _STYLE_LINE_PATTERN.search(str(line or ""))]


def _best_case_name(parsed: Any, lines: Sequence[str], path: Path) -> str:
    matter_of_name = _matter_of_case_name(lines)
    if matter_of_name:
        return matter_of_name
    header = getattr(parsed, "header", None)
    if header:
        for line in list(getattr(header, "party_lines", []) or []):
            stripped = str(line).strip()
            if _STYLE_LINE_PATTERN.search(stripped):
                return stripped
    for line in lines:
        stripped = str(line).strip()
        if _STYLE_LINE_PATTERN.search(stripped):
            return stripped
    candidate = str(getattr(parsed, "title", "") or "").strip()
    if candidate:
        return candidate
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.name


def _relative_copy_path(scan_root: Path, source_path: Path, target_root: Path) -> Path:
    try:
        relative = source_path.relative_to(scan_root)
    except ValueError:
        relative = Path(source_path.name)
    return target_root / relative


def _should_skip_pdf_path(scan_root: Path, pdf_path: Path) -> bool:
    try:
        relative_parts = pdf_path.relative_to(scan_root).parts[:-1]
    except ValueError:
        relative_parts = pdf_path.parts[:-1]
    for part in relative_parts:
        if part in _SKIP_DIR_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in _SKIP_DIR_PREFIXES):
            return True
    return False


def load_scan_manifest(path: str | Path) -> Dict[str, Any]:
    manifest_path = Path(path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def summarize_scan_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    cases = list(manifest.get("cases") or [])
    sample_cases: List[Dict[str, Any]] = []
    for case in cases[:10]:
        sample_cases.append(
            {
                "status": str(case.get("status") or ""),
                "case_number": str(case.get("case_number") or ""),
                "case_name": str(case.get("case_name") or ""),
                "court": str(case.get("court") or ""),
                "document_count": int(case.get("document_count") or 0),
                "matched_relative_paths": list(case.get("matched_relative_paths") or []),
            }
        )
    return {
        "scan_status": str(manifest.get("scan_status") or ""),
        "scan_started_at": str(manifest.get("scan_started_at") or ""),
        "scan_completed_at": str(manifest.get("scan_completed_at") or ""),
        "scan_root": str(manifest.get("scan_root") or ""),
        "output_dir": str(manifest.get("output_dir") or ""),
        "manifest_path": str(manifest.get("manifest_path") or ""),
        "pdf_count": int(manifest.get("pdf_count") or 0),
        "matched_pdf_count": int(manifest.get("matched_pdf_count") or 0),
        "skipped_pdf_count": int(manifest.get("skipped_pdf_count") or 0),
        "candidate_case_count": int(manifest.get("candidate_case_count") or 0),
        "ocr_available": bool(manifest.get("ocr_available")),
        "sample_cases": sample_cases,
    }


def _build_case_graph_summary(results: Sequence[HACCCourtPDFScanResult], *, case_number: str, court: str, case_name: str) -> Dict[str, Any]:
    entities: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    case_entity_id = f"case:{_safe_identifier(case_number or case_name)}"
    entities.append(
        {
            "id": case_entity_id,
            "type": "case",
            "label": case_name or case_number,
            "properties": {"case_number": case_number, "court": court},
        }
    )
    for result in results:
        document_entity_id = f"document:{_safe_identifier(result.relative_path)}"
        entities.append(
            {
                "id": document_entity_id,
                "type": "document",
                "label": result.title or Path(result.path).name,
                "properties": {
                    "path": result.path,
                    "case_number": result.case_number,
                    "court": result.court,
                    "extraction_method": result.extraction_method,
                    "confidence": result.confidence,
                },
            }
        )
        relationships.append(
            {
                "id": f"rel:{_safe_identifier(result.relative_path)}",
                "source": document_entity_id,
                "target": case_entity_id,
                "type": "FILED_IN",
                "properties": {"relative_path": result.relative_path},
            }
        )
    graph = build_case_knowledge_graph(
        entities=entities,
        relationships=relationships,
        source="hacc_court_pdf_scan",
        properties={"case_number": case_number, "court": court, "case_name": case_name},
    )
    return {
        "knowledge_graph": graph.to_dict(),
        "summary": summarize_case_graph(graph),
    }


def _build_case_preview(results: Sequence[HACCCourtPDFScanResult], *, case_number: str) -> Dict[str, Any]:
    court = next((item.court for item in results if item.court), "")
    case_name = next((item.case_name for item in results if item.case_name), case_number)
    confidences = [float(item.confidence or 0.0) for item in results]
    return {
        "case_number": case_number,
        "case_name": case_name,
        "court": court,
        "document_count": len(results),
        "matched_relative_paths": [item.relative_path for item in results],
        "scan_confidence_summary": {
            "max_confidence": max(confidences) if confidences else 0.0,
            "min_confidence": min(confidences) if confidences else 0.0,
            "average_confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
        },
        "status": "candidate",
    }


def analyze_pdf_for_court_case(path: str | Path, *, max_ocr_pages: int = 5) -> HACCCourtPDFScanResult:
    source_path = Path(path)
    text, extraction_method = _extract_text_from_pdf_with_ocr(source_path, max_ocr_pages=max_ocr_pages)
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    parsed = parse_legal_document(text) if text else None
    parsed_header = getattr(parsed, "header", None)
    case_number = _validated_case_number(
        (getattr(parsed_header, "case_number", "") if parsed_header else "")
        or _extract_case_number_from_text(text)
    )
    court_lines = list(getattr(parsed_header, "court_lines", []) or []) if parsed_header else []
    matched_headers = _matched_court_headers(lines[:80])
    if not matched_headers and court_lines:
        matched_headers = _matched_court_headers(court_lines)
    style_matches = _style_lines(lines[:120])
    if not style_matches and parsed_header:
        style_matches = _style_lines(list(getattr(parsed_header, "party_lines", []) or []))

    reasons: List[str] = []
    if case_number:
        reasons.append(f"case_number:{case_number}")
    if matched_headers:
        reasons.append(f"court_header:{matched_headers[0]}")
    if style_matches:
        reasons.append(f"style_line:{style_matches[0]}")

    has_court_header = bool(matched_headers or court_lines)
    has_style_line = bool(style_matches)
    is_likely_court_case = bool(case_number and has_court_header)
    confidence = 0.0
    if is_likely_court_case:
        confidence = 0.95 if has_style_line else 0.85
    elif case_number or has_court_header or has_style_line:
        confidence = 0.45

    court = str((court_lines[0] if court_lines else (matched_headers[0] if matched_headers else "")) or "").strip()
    case_name = _best_case_name(parsed, lines, source_path) if text else source_path.name
    title = str(getattr(parsed, "title", "") or case_name or source_path.stem).strip()
    document_graph = build_document_knowledge_graph(parsed, graph_id=_safe_identifier(source_path.stem)) if parsed else {}
    document_graph_summary = dict((document_graph or {}).get("summary") or {})

    return HACCCourtPDFScanResult(
        path=str(source_path),
        relative_path=source_path.name,
        is_likely_court_case=is_likely_court_case,
        case_number=case_number,
        court=court,
        case_name=case_name,
        title=title,
        confidence=confidence,
        reasons=reasons,
        extraction_method=extraction_method,
        text_length=len(text or ""),
        matched_court_headers=matched_headers,
        style_lines=style_matches,
        document_knowledge_graph=document_graph,
        document_knowledge_graph_summary=document_graph_summary,
        parsed_document=parsed.to_dict() if parsed else {},
        text=text,
    )


def scan_hacc_pdfs_for_dockets(
    scan_root: str | Path,
    *,
    output_dir: str | Path,
    glob_pattern: str = "*.pdf",
    max_ocr_pages: int = 5,
    include_knowledge_graph: bool = True,
    include_bm25: bool = True,
    include_vector_index: bool = True,
    include_formal_logic: bool = True,
    include_router_enrichment: bool = True,
) -> Dict[str, Any]:
    root = Path(scan_root)
    if not root.exists():
        raise FileNotFoundError(f"Scan root not found: {root}")
    if not root.is_dir():
        raise ValueError(f"Scan root is not a directory: {root}")

    destination_root = Path(output_dir)
    destination_root.mkdir(parents=True, exist_ok=True)
    collected_root = destination_root / "collected_pdfs"
    datasets_root = destination_root / "docket_datasets"
    collected_root.mkdir(parents=True, exist_ok=True)
    datasets_root.mkdir(parents=True, exist_ok=True)
    manifest_path = destination_root / "scan_manifest.json"
    scan_started_at = _utc_now_isoformat()
    skipped_pdf_count = 0
    ocr_support = _ocr_support_summary()

    all_results: List[HACCCourtPDFScanResult] = []
    grouped: Dict[str, List[HACCCourtPDFScanResult]] = defaultdict(list)

    def _build_manifest(*, status: str) -> Dict[str, Any]:
        preview_cases = [
            _build_case_preview(results, case_number=case_number)
            for case_number, results in sorted(grouped.items())
        ]
        return {
            "scan_status": status,
            "scan_started_at": scan_started_at,
            "scan_completed_at": _utc_now_isoformat() if status == "completed" else "",
            "scan_root": str(root),
            "output_dir": str(destination_root),
            "manifest_path": str(manifest_path),
            "scan_parameters": {
                "glob_pattern": glob_pattern,
                "max_ocr_pages": int(max_ocr_pages),
                "include_knowledge_graph": bool(include_knowledge_graph),
                "include_bm25": bool(include_bm25),
                "include_vector_index": bool(include_vector_index),
                "include_formal_logic": bool(include_formal_logic),
                "include_router_enrichment": bool(include_router_enrichment),
            },
            "pdf_count": len(all_results),
            "matched_pdf_count": sum(1 for item in all_results if item.is_likely_court_case and item.case_number),
            "skipped_pdf_count": skipped_pdf_count,
            "candidate_case_count": len(case_outputs) if status == "completed" else len(grouped),
            "ocr_available": bool(ocr_support.get("available")),
            "ocr_support": dict(ocr_support),
            "cases": case_outputs if status == "completed" else preview_cases,
            "pdf_results": [item.to_dict() for item in all_results],
        }

    def _write_manifest(*, status: str) -> None:
        manifest_path.write_text(json.dumps(_build_manifest(status=status), indent=2, sort_keys=True), encoding="utf-8")

    case_outputs: List[Dict[str, Any]] = []
    _write_manifest(status="running")

    for pdf_path in sorted(root.rglob(glob_pattern)):
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            continue
        if _should_skip_pdf_path(root, pdf_path):
            skipped_pdf_count += 1
            continue
        result = analyze_pdf_for_court_case(pdf_path, max_ocr_pages=max_ocr_pages)
        try:
            result.relative_path = str(pdf_path.relative_to(root))
        except ValueError:
            result.relative_path = pdf_path.name
        all_results.append(result)
        if result.is_likely_court_case and result.case_number:
            grouped[result.case_number].append(result)

        if len(all_results) % 100 == 0:
            _write_manifest(status="running")

    for case_number, results in sorted(grouped.items()):
        case_slug = _safe_identifier(case_number)
        case_collect_root = collected_root / case_slug
        case_collect_root.mkdir(parents=True, exist_ok=True)
        court = next((item.court for item in results if item.court), "")
        case_name = next((item.case_name for item in results if item.case_name), case_number)
        copied_paths: List[str] = []
        copied_relative_paths: List[str] = []
        documents: List[Dict[str, Any]] = []
        for index, result in enumerate(results, start=1):
            source_path = Path(result.path)
            source_file_metadata = _file_metadata(source_path)
            copied_path = _relative_copy_path(root, source_path, case_collect_root)
            copied_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, copied_path)
            copied_paths.append(str(copied_path))
            copied_relative_paths.append(str(copied_path.relative_to(case_collect_root)))
            documents.append(
                {
                    "id": f"{case_slug}_{index}",
                    "title": result.title or source_path.stem,
                    "text": result.text,
                    "source_url": str(source_path),
                    "document_type": "pdf",
                    "case_number": result.case_number,
                    "metadata": {
                        "source_path": str(source_path),
                        "relative_path": result.relative_path,
                        "source_file": source_file_metadata,
                        "collected_path": str(copied_path),
                        "collected_relative_path": copied_relative_paths[-1],
                        "scan_detection": {
                            "confidence": result.confidence,
                            "is_likely_court_case": result.is_likely_court_case,
                            "reasons": list(result.reasons),
                            "matched_court_headers": list(result.matched_court_headers),
                            "style_lines": list(result.style_lines),
                            "text_length": result.text_length,
                            "header_match_count": len(result.matched_court_headers),
                            "style_line_count": len(result.style_lines),
                        },
                        "text_extraction": {
                            "source": "hacc_pdf_scan",
                            "backend": result.extraction_method,
                            "ocr_attempted": result.extraction_method == "ocr",
                            "max_ocr_pages": int(max_ocr_pages),
                        },
                        "case_detection": {
                            "case_number": result.case_number,
                            "court": result.court,
                            "case_name": result.case_name,
                        },
                        "parsed_legal_document": dict(result.parsed_document),
                        "document_knowledge_graph": dict(result.document_knowledge_graph),
                        "document_knowledge_graph_summary": dict(result.document_knowledge_graph_summary),
                    },
                }
            )

        case_graph_summary = _build_case_graph_summary(results, case_number=case_number, court=court, case_name=case_name)
        dataset = ingest_docket_dataset(
            {
                "docket_id": case_number,
                "case_name": case_name,
                "court": court,
                "case_number": case_number,
                "source_type": "hacc_pdf_scan",
                "documents": documents,
                "metadata": {
                    "scan_root": str(root),
                    "scan_started_at": scan_started_at,
                    "case_number": case_number,
                    "case_slug": case_slug,
                    "scan_glob_pattern": glob_pattern,
                    "max_ocr_pages": int(max_ocr_pages),
                    "scan_status": "completed",
                    "collected_pdf_count": len(copied_paths),
                    "collected_pdf_paths": copied_paths,
                    "collected_pdf_relative_paths": copied_relative_paths,
                    "matched_source_paths": [item.path for item in results],
                    "matched_relative_paths": [item.relative_path for item in results],
                    "scan_confidence_summary": {
                        "max_confidence": max(item.confidence for item in results),
                        "min_confidence": min(item.confidence for item in results),
                        "average_confidence": sum(item.confidence for item in results) / len(results),
                    },
                    "scan_case_graph": case_graph_summary,
                },
            },
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
            include_formal_logic=include_formal_logic,
            include_router_enrichment=include_router_enrichment,
        )
        parquet_export = export_docket_dataset_single_parquet(dataset, datasets_root / f"{case_slug}.parquet")
        case_outputs.append(
            {
                "status": "completed",
                "case_number": case_number,
                "case_name": case_name,
                "court": court,
                "document_count": len(results),
                "dataset_path": str(parquet_export.get("parquet_path") or ""),
                "dataset_format": "parquet",
                "dataset_row_count": int(parquet_export.get("row_count") or 0),
                "dataset_section_counts": dict(parquet_export.get("section_counts") or {}),
                "collected_pdf_root": str(case_collect_root),
                "matched_relative_paths": [item.relative_path for item in results],
                "scan_confidence_summary": {
                    "max_confidence": max(item.confidence for item in results),
                    "min_confidence": min(item.confidence for item in results),
                    "average_confidence": sum(item.confidence for item in results) / len(results),
                },
                "scan_case_graph_summary": case_graph_summary.get("summary") or {},
            }
        )
        _write_manifest(status="running")

    manifest = _build_manifest(status="completed")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a HACC PDF tree for likely court filings and emit docket datasets.")
    parser.add_argument("scan_root", nargs="?", help="Directory to scan recursively for PDF files.")
    parser.add_argument("--output-dir", help="Directory where collected PDFs, datasets, and the manifest will be written.")
    parser.add_argument("--glob-pattern", default="*.pdf", help="Glob pattern to match PDFs under the scan root.")
    parser.add_argument("--max-ocr-pages", type=int, default=5, help="Maximum number of pages to OCR for weakly extracted PDFs.")
    parser.add_argument("--no-knowledge-graph", action="store_true", help="Disable dataset-level knowledge graph generation.")
    parser.add_argument("--no-bm25", action="store_true", help="Disable dataset BM25 index generation.")
    parser.add_argument("--no-vector-index", action="store_true", help="Disable dataset vector index generation.")
    parser.add_argument("--no-formal-logic", action="store_true", help="Disable docket formal-logic enrichment.")
    parser.add_argument("--no-router-enrichment", action="store_true", help="Disable router enrichment.")
    parser.add_argument("--manifest-path", help="Read an existing scan manifest instead of running a new scan.")
    parser.add_argument("--summary-only", action="store_true", help="When reading --manifest-path, print only a condensed status summary.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.manifest_path:
        manifest = load_scan_manifest(args.manifest_path)
        payload = summarize_scan_manifest(manifest) if args.summary_only else manifest
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if not args.scan_root:
        parser.error("scan_root is required unless --manifest-path is provided")
    if not args.output_dir:
        parser.error("--output-dir is required unless --manifest-path is provided")
    manifest = scan_hacc_pdfs_for_dockets(
        args.scan_root,
        output_dir=args.output_dir,
        glob_pattern=args.glob_pattern,
        max_ocr_pages=max(1, int(args.max_ocr_pages or 1)),
        include_knowledge_graph=not args.no_knowledge_graph,
        include_bm25=not args.no_bm25,
        include_vector_index=not args.no_vector_index,
        include_formal_logic=not args.no_formal_logic,
        include_router_enrichment=not args.no_router_enrichment,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())