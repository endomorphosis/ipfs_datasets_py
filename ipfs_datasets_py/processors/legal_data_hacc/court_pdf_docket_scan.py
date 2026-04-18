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

from ..legal_data import ingest_docket_dataset
from ..legal_data.case_knowledge import build_case_knowledge_graph, summarize_case_graph
from ..legal_data.document_structure import build_document_knowledge_graph, parse_legal_document
from ..legal_data.docket_dataset import _extract_case_number_from_text, _extract_text_from_pdf, _normalize_case_number_text

logger = logging.getLogger(__name__)

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".tools",
    ".venv",
    ".venv-pacer-test",
    "__pycache__",
    "node_modules",
    "site-packages",
}

_COURT_HEADER_PATTERNS = [
    re.compile(r"\bIN THE UNITED STATES DISTRICT COURT\b", re.IGNORECASE),
    re.compile(r"\bUNITED STATES DISTRICT COURT\b", re.IGNORECASE),
    re.compile(r"\bUNITED STATES BANKRUPTCY COURT\b", re.IGNORECASE),
    re.compile(r"\bUNITED STATES COURT OF APPEALS\b", re.IGNORECASE),
    re.compile(r"\bIN THE [A-Z][A-Z\s]+(?:DISTRICT|CIRCUIT|SUPERIOR|PROBATE|APPEALS|SUPREME) COURT\b", re.IGNORECASE),
]
_STYLE_LINE_PATTERN = re.compile(r"(?:\bv(?:s)?\.?\s+\S+)|(?:\bversus\b)|(?:\bin re\b)", re.IGNORECASE)


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
    return bool(fitz and pytesseract and Image)


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


def _style_lines(lines: Sequence[str]) -> List[str]:
    return [str(line).strip() for line in lines if _STYLE_LINE_PATTERN.search(str(line or ""))]


def _best_case_name(parsed: Any, lines: Sequence[str], path: Path) -> str:
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
        if part.startswith(".git") or part.startswith(".venv"):
            return True
    return False


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


def analyze_pdf_for_court_case(path: str | Path, *, max_ocr_pages: int = 5) -> HACCCourtPDFScanResult:
    source_path = Path(path)
    text, extraction_method = _extract_text_from_pdf_with_ocr(source_path, max_ocr_pages=max_ocr_pages)
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    parsed = parse_legal_document(text) if text else None
    parsed_header = getattr(parsed, "header", None)
    case_number = _normalize_case_number_text(
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
    include_vector_index: bool = False,
    include_formal_logic: bool = False,
    include_router_enrichment: bool = False,
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
    scan_started_at = _utc_now_isoformat()
    skipped_pdf_count = 0

    all_results: List[HACCCourtPDFScanResult] = []
    grouped: Dict[str, List[HACCCourtPDFScanResult]] = defaultdict(list)
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

    case_outputs: List[Dict[str, Any]] = []
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
                        "collected_path": str(copied_path),
                        "collected_relative_path": copied_relative_paths[-1],
                        "scan_detection": {
                            "confidence": result.confidence,
                            "is_likely_court_case": result.is_likely_court_case,
                            "reasons": list(result.reasons),
                            "matched_court_headers": list(result.matched_court_headers),
                            "style_lines": list(result.style_lines),
                            "text_length": result.text_length,
                        },
                        "text_extraction": {
                            "source": "hacc_pdf_scan",
                            "backend": result.extraction_method,
                            "ocr_attempted": result.extraction_method == "ocr",
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
        dataset_path = dataset.write_json(datasets_root / f"{case_slug}.json")
        case_outputs.append(
            {
                "case_number": case_number,
                "case_name": case_name,
                "court": court,
                "document_count": len(results),
                "dataset_path": str(dataset_path),
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

    manifest = {
        "scan_started_at": scan_started_at,
        "scan_completed_at": _utc_now_isoformat(),
        "scan_root": str(root),
        "output_dir": str(destination_root),
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
        "candidate_case_count": len(case_outputs),
        "ocr_available": _has_ocr_support(),
        "cases": case_outputs,
        "pdf_results": [item.to_dict() for item in all_results],
    }
    manifest_path = destination_root / "scan_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a HACC PDF tree for likely court filings and emit docket datasets.")
    parser.add_argument("scan_root", help="Directory to scan recursively for PDF files.")
    parser.add_argument("--output-dir", required=True, help="Directory where collected PDFs, datasets, and the manifest will be written.")
    parser.add_argument("--glob-pattern", default="*.pdf", help="Glob pattern to match PDFs under the scan root.")
    parser.add_argument("--max-ocr-pages", type=int, default=5, help="Maximum number of pages to OCR for weakly extracted PDFs.")
    parser.add_argument("--no-knowledge-graph", action="store_true", help="Disable dataset-level knowledge graph generation.")
    parser.add_argument("--no-bm25", action="store_true", help="Disable dataset BM25 index generation.")
    parser.add_argument("--include-vector-index", action="store_true", help="Enable dataset vector index generation.")
    parser.add_argument("--include-formal-logic", action="store_true", help="Enable docket formal-logic enrichment.")
    parser.add_argument("--include-router-enrichment", action="store_true", help="Enable router enrichment.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = scan_hacc_pdfs_for_dockets(
        args.scan_root,
        output_dir=args.output_dir,
        glob_pattern=args.glob_pattern,
        max_ocr_pages=max(1, int(args.max_ocr_pages or 1)),
        include_knowledge_graph=not args.no_knowledge_graph,
        include_bm25=not args.no_bm25,
        include_vector_index=bool(args.include_vector_index),
        include_formal_logic=bool(args.include_formal_logic),
        include_router_enrichment=bool(args.include_router_enrichment),
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())