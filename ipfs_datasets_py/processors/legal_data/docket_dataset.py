"""Docket dataset import and indexing helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import html
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import anyio

logger = logging.getLogger(__name__)

from ...logic.deontic import DeonticGraph, DeonticGraphBuilder
from ..protocol import Entity, KnowledgeGraph, Relationship
from .document_structure import parse_legal_document, parse_legal_document_to_graph
from .docket_packaging import (
    load_packaged_docket_dataset,
    load_packaged_docket_dataset_components,
    package_docket_dataset,
)
from .formal_docket_enrichment import enrich_docket_documents_with_formal_logic
from .proof_assistant import build_docket_proof_assistant
from .rich_docket_enrichment import enrich_docket_documents_with_routers
from ..retrieval import (
    build_bm25_index,
    bm25_search_documents,
    embed_query_for_backend,
    embed_texts_with_router_or_local_chunked,
    hashed_term_projection,
    vector_dot,
)
from ..legal_data.bluebook_citation_linker import (
    BluebookCitationResolver,
    audit_bluebook_citation_resolution_for_documents,
    citation_link_to_dict,
    resolve_bluebook_citations_in_text,
)
from ..legal_data.eu_legal_citation_bridge import (
    build_eu_lookup_action_for_citation,
    extract_eu_legal_citations,
)
from ..legal_data.canonical_legal_corpora import get_canonical_legal_corpus
from ..legal_data.legal_source_recovery_promotion import (
    build_recovery_manifest_promotion_row,
    build_recovery_manifest_release_plan,
    merge_recovery_manifest_into_canonical_dataset,
    promote_recovery_manifest_to_canonical_bundle,
)
from ..legal_data.legal_source_recovery import recover_missing_legal_citation_source


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat()


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


_CASE_NUMBER_LABEL_PATTERN = re.compile(
    r"\b(?:case|cause|civil action|docket)\s*(?:no\.?|number)?\s*[:#]?\s*([A-Za-z0-9:\-\.]+)",
    re.IGNORECASE,
)
_CASE_NUMBER_TOKEN_PATTERN = re.compile(r"\b\d{1,4}:\d{2,4}[- ]?[a-z]{1,6}[- ]?\d{1,8}\b", re.IGNORECASE)
_PACER_DOCKET_ROW_PATTERN = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_PACER_DOCKET_CELL_PATTERN = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_PACER_DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _dedupe_string_sequence(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _normalize_authority_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_case_number_text(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    text = re.sub(r"^(?:case|cause|civil action|docket)\s*(?:no\.?|number)?\s*[:#]?\s*", "", text, flags=re.IGNORECASE)
    return text.strip(" .:#")


def _extract_case_number_from_text(text: str) -> str:
    if not text:
        return ""
    for line in text.splitlines()[:80]:
        stripped = str(line).strip()
        if not stripped:
            continue
        labeled = _CASE_NUMBER_LABEL_PATTERN.search(stripped)
        if labeled:
            return _normalize_case_number_text(labeled.group(1))
        token = _CASE_NUMBER_TOKEN_PATTERN.search(stripped)
        if token:
            return _normalize_case_number_text(token.group(0))
    return ""


def _html_to_text(value: Any, *, preserve_line_breaks: bool = False) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    if preserve_line_breaks:
        return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip()).strip()
    return " ".join(text.split()).strip()


def _parse_pacer_html_docket(path: Path) -> Dict[str, Any]:
    raw_html = path.read_text(encoding="utf-8", errors="ignore")
    html_lower = raw_html.lower()
    has_court_header = any(
        marker in html_lower
        for marker in ("district court", "bankruptcy court", "court of appeals")
    )
    has_docket_markers = any(
        marker in html_lower
        for marker in ("docket report", "docket sheet", "docket text", "case no.", "civil action no.")
    )
    if not has_court_header or not has_docket_markers:
        raise ValueError(f"HTML file does not appear to be a PACER docket: {path}")

    text = _html_to_text(raw_html, preserve_line_breaks=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    case_number = _extract_case_number_from_text(text)

    court = ""
    case_name = ""
    for line in lines[:80]:
        lowered = line.lower()
        if not court and ("district court" in lowered or "bankruptcy court" in lowered or "court of appeals" in lowered):
            court = line
            continue
        if case_number and case_number in line:
            continue
        if not case_name and " v. " in line:
            case_name = line
            break

    documents: List[Dict[str, Any]] = []
    entry_index = 0
    for row_match in _PACER_DOCKET_ROW_PATTERN.finditer(raw_html):
        cells = _PACER_DOCKET_CELL_PATTERN.findall(row_match.group(1))
        if len(cells) < 3:
            continue
        cell_texts = [_html_to_text(cell) for cell in cells[:3]]
        joined = " ".join(cell_texts).strip()
        if not joined:
            continue
        if "date filed" in joined.lower() and "document number" in joined.lower():
            continue
        if not _PACER_DATE_PATTERN.search(cell_texts[0]):
            continue

        entry_index += 1
        date_filed = _PACER_DATE_PATTERN.search(cell_texts[0]).group(0)
        document_number = cell_texts[1].strip()
        description = cell_texts[2].strip()
        if not description:
            continue

        documents.append(
            {
                "id": f"{path.stem}_entry_{entry_index}",
                "title": description.split(".", 1)[0][:160].strip() or f"Docket Entry {entry_index}",
                "text": description,
                "date_filed": date_filed,
                "document_number": document_number,
                "source_url": str(path),
                "document_type": "pacer_html_entry",
                "metadata": {
                    "source_path": str(path),
                    "source_suffix": path.suffix.lower(),
                    "text_extraction": {
                        "source": "pacer_html_docket",
                        "backend": "regex_html_parser",
                    },
                },
            }
        )

    if not documents:
        body_text = text[:20000].strip()
        if body_text:
            documents.append(
                {
                    "id": f"{path.stem}_html",
                    "title": case_name or path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
                    "text": body_text,
                    "source_url": str(path),
                    "document_type": "pacer_html_docket",
                    "metadata": {
                        "source_path": str(path),
                        "source_suffix": path.suffix.lower(),
                        "text_extraction": {
                            "source": "pacer_html_docket",
                            "backend": "regex_html_parser",
                        },
                    },
                }
            )

    return {
        "docket_id": case_number or path.stem,
        "case_name": case_name or path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
        "court": court,
        "documents": documents,
        "source_type": "pacer_html_file",
        "source_path": str(path),
        "case_number": case_number,
        "metadata": {
            "case_number": case_number,
            "source_path": str(path),
            "parser": "regex_html_parser",
            "document_count": len(documents),
        },
    }


def _unwrap_nested_docket_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = dict(payload)
    inherited_source_type = str(current.get("source_type") or "").strip()
    inherited_upstream_source_type = str(current.get("upstream_source_type") or "").strip()
    inherited_metadata = dict(current.get("metadata") or {})

    for key in ("result", "case", "data", "payload"):
        candidate = current.get(key)
        if not isinstance(candidate, dict):
            continue
        if any(
            candidate.get(field)
            for field in (
                "documents",
                "entries",
                "docketEntries",
                "docket_id",
                "case_id",
                "case_number",
                "caseNumber",
                "case_name",
                "caseTitle",
            )
        ) or any(isinstance(candidate.get(nested_key), dict) for nested_key in ("case", "result")):
            current = {
                **candidate,
                "metadata": {
                    **inherited_metadata,
                    **dict(candidate.get("metadata") or {}),
                },
                "source_type": str(candidate.get("source_type") or inherited_source_type or "").strip() or candidate.get("source_type"),
                "upstream_source_type": str(candidate.get("upstream_source_type") or inherited_upstream_source_type or "").strip() or candidate.get("upstream_source_type"),
            }
            return _unwrap_nested_docket_payload(current)

    if inherited_source_type and not current.get("source_type"):
        current["source_type"] = inherited_source_type
    if inherited_upstream_source_type and not current.get("upstream_source_type"):
        current["upstream_source_type"] = inherited_upstream_source_type
    if inherited_metadata and not current.get("metadata"):
        current["metadata"] = inherited_metadata
    return current


def _extract_text_from_pdf(path: Path) -> str:
    errors: List[str] = []
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name, fromlist=["PdfReader"])
            reader_cls = getattr(module, "PdfReader", None)
            if reader_cls is None:
                continue
            reader = reader_cls(str(path))
            pages = []
            for page in list(getattr(reader, "pages", []) or []):
                try:
                    pages.append(str(page.extract_text() or ""))
                except Exception as exc:
                    errors.append(f"{module_name}:page:{exc}")
            text = "\n".join(page for page in pages if page.strip()).strip()
            if text:
                return text
        except Exception as exc:
            errors.append(f"{module_name}:{exc}")
    if errors:
        logger.warning("Failed to extract PDF text from %s: %s", path, "; ".join(errors))
    return ""


def _local_only_bluebook_resolver() -> BluebookCitationResolver:
    return BluebookCitationResolver(allow_hf_fallback=False)


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _formal_logic_enrichment_enabled() -> bool:
    return not _truthy_env(os.getenv("IPFS_DATASETS_PY_DISABLE_DOCKET_FORMAL_LOGIC"))


def _router_enrichment_enabled() -> bool:
    return not (
        _truthy_env(os.getenv("IPFS_DATASETS_PY_DISABLE_DOCKET_ROUTER_ENRICHMENT"))
        or _truthy_env(os.getenv("IPFS_DATASETS_PY_DISABLE_EMBEDDINGS_ROUTER"))
    )


_LOW_VALUE_TEXT_SOURCES = {
    "courtlistener_summary_metadata",
    "synthesized_docket_summary",
    "courtlistener_entry_metadata",
    "synthesized_docket_entry",
}

_METADATA_ONLY_TEXT_SOURCES = {
    "courtlistener_metadata_only",
}

_RETRIEVAL_EVIDENCE_RANK = {
    "metadata": 0,
    "rendered": 1,
    "plain_text": 2,
    "extracted_pdf": 3,
}

_LAST_DATASET_PROGRESS: Dict[str, str] = {
    "stage": "",
    "detail": "",
}


def get_docket_dataset_progress() -> Dict[str, str]:
    return dict(_LAST_DATASET_PROGRESS)


def _document_text_source(document: "DocketDocument") -> str:
    return str((document.metadata.get("text_extraction") or {}).get("source") or "").strip()


def _normalize_document_title(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_generic_index_title(value: Any) -> bool:
    title = _normalize_document_title(value)
    if not title or title == "none":
        return True
    if title.isdigit():
        return True
    generic_titles = {
        "main document",
        "attachment",
        "attachments",
        "document",
        "exhibit",
        "exhibits",
    }
    if title in generic_titles:
        return True
    return False


def _document_rendered_row(document: "DocketDocument") -> Dict[str, Any]:
    return dict(document.metadata.get("rendered_docket_row") or {})


def _rendered_row_preferred_title(rendered_row: Mapping[str, Any]) -> str:
    title = str(rendered_row.get("title") or "").strip()
    kind = str(rendered_row.get("kind") or "").strip()
    if title and not _is_generic_index_title(title) and any(ch.isalpha() for ch in title):
        return title
    if kind and not _is_generic_index_title(kind) and any(ch.isalpha() for ch in kind):
        return kind
    return title or kind


def _document_acquisition_candidates(document: "DocketDocument") -> List[Dict[str, Any]]:
    return [dict(item) for item in list(document.metadata.get("acquisition_candidates") or []) if isinstance(item, dict)]


def _document_has_substantive_text(document: "DocketDocument") -> bool:
    text = str(document.text or "").strip()
    if not text:
        return False
    source = _document_text_source(document)
    return source not in _LOW_VALUE_TEXT_SOURCES and source not in _METADATA_ONLY_TEXT_SOURCES


def _document_retrieval_evidence_quality(document: "DocketDocument") -> str:
    source = _document_text_source(document)
    if source == "courtlistener_public_filing_pdf":
        return "extracted_pdf"
    if source == "courtlistener_public_recap_document":
        method = str((document.metadata.get("text_extraction") or {}).get("method") or "").strip().lower()
        if method in {"pdf_ocr", "pdf_text", "courtlistener_plain_text"}:
            return "plain_text"
        return "extracted_pdf"
    if source in {"courtlistener_plain_text", "pdf_text", "pdf_ocr"}:
        return "plain_text"
    if source in {"courtlistener_rendered_docket", "courtlistener_rendered_docket_page"}:
        return "rendered"
    if _document_rendered_row(document):
        return "rendered"
    return "metadata"


def _document_index_title(document: "DocketDocument") -> str:
    rendered_row = _document_rendered_row(document)
    rendered_title = _rendered_row_preferred_title(rendered_row)
    title = str(document.title or "").strip()
    if title.lower().startswith("docket entry ") and rendered_title:
        return rendered_title
    return rendered_title or title


def _document_has_meaningful_index_title(document: "DocketDocument") -> bool:
    title = _document_index_title(document)
    if _is_generic_index_title(title):
        return False
    return any(ch.isalpha() for ch in str(title or ""))


def _document_index_text(document: "DocketDocument") -> str:
    if _document_has_substantive_text(document):
        return str(document.text or "").strip()

    rendered_row = _document_rendered_row(document)
    rendered_title = _rendered_row_preferred_title(rendered_row)
    if rendered_title and _document_has_meaningful_index_title(document):
        text_lines = [
            "CourtListener rendered docket filing",
            f"Document number: {str(rendered_row.get('document_number') or document.document_number or '').strip()}",
            f"Date filed: {str(rendered_row.get('date_filed') or document.date_filed or '').strip()}",
            f"Kind: {str(rendered_row.get('kind') or '').strip()}",
            f"Description: {rendered_title}",
            "PACER purchase link available" if bool(rendered_row.get("pacer_available")) else "",
        ]
        return "\n".join(line for line in text_lines if line)

    title = _document_index_title(document)
    source = _document_text_source(document)
    if (
        source in _METADATA_ONLY_TEXT_SOURCES
        and _document_has_meaningful_index_title(document)
        and _document_acquisition_candidates(document)
    ):
        text_lines = [
            "CourtListener filing metadata",
            f"Document number: {str(document.document_number or '').strip()}",
            f"Date filed: {str(document.date_filed or '').strip()}",
            f"Description: {title}",
        ]
        if _document_acquisition_candidates(document):
            text_lines.append("Acquisition candidate available")
        return "\n".join(line for line in text_lines if line)

    if source not in _LOW_VALUE_TEXT_SOURCES and str(document.text or "").strip():
        return str(document.text or "").strip()
    return ""


def _document_index_priority(document: "DocketDocument") -> int:
    if _document_has_substantive_text(document):
        return 400
    if (
        _document_rendered_row(document)
        and _document_text_source(document) in _METADATA_ONLY_TEXT_SOURCES
        and _document_has_meaningful_index_title(document)
    ):
        return 320
    if _document_rendered_row(document) and _document_has_meaningful_index_title(document):
        return 300
    source = _document_text_source(document)
    if (
        source in _METADATA_ONLY_TEXT_SOURCES
        and _document_has_meaningful_index_title(document)
        and _document_acquisition_candidates(document)
    ):
        return 220
    if source not in _LOW_VALUE_TEXT_SOURCES and str(document.text or "").strip():
        return 200
    if source in {"courtlistener_summary_metadata", "synthesized_docket_summary"}:
        return 0
    if source in {"courtlistener_entry_metadata", "synthesized_docket_entry"}:
        title = str(document.title or "").strip().lower()
        raw = dict(document.metadata.get("raw") or {})
        raw_description = str(raw.get("description") or "").strip()
        if (
            title.startswith("docket entry ")
            and not raw_description
            and not _document_acquisition_candidates(document)
        ):
            return 0
        if not _document_has_meaningful_index_title(document) and not _document_acquisition_candidates(document):
            return 0
        return 80
    return 0


def _document_index_dedupe_key(document: "DocketDocument") -> str:
    document_number = str(document.document_number or "").strip()
    title = _normalize_document_title(_document_index_title(document))
    if document_number and title:
        return f"{document_number}::{title}"
    if document_number:
        return f"{document_number}::{_safe_identifier(_document_text_source(document) or 'document')}"
    if title:
        return title
    return str(document.document_id or "")


def _citation_recovery_candidate_from_link(document: "DocketDocument", link: Any) -> Optional[Dict[str, Any]]:
    matched = bool(getattr(link, "matched", False)) if not isinstance(link, dict) else bool(link.get("matched"))
    metadata = dict(getattr(link, "metadata", {}) or {}) if not isinstance(link, dict) else dict(link.get("metadata") or {})
    if matched or not bool(metadata.get("recovery_supported")):
        return None

    citation_text = str(getattr(link, "citation_text", "") or "") if not isinstance(link, dict) else str(link.get("citation_text") or "")
    normalized_citation = str(getattr(link, "normalized_citation", "") or citation_text) if not isinstance(link, dict) else str(link.get("normalized_citation") or citation_text)
    citation_type = str(getattr(link, "citation_type", "") or "") if not isinstance(link, dict) else str(link.get("citation_type") or "")
    corpus_key = str(getattr(link, "corpus_key", "") or metadata.get("recovery_corpus_key") or "") if not isinstance(link, dict) else str(link.get("corpus_key") or metadata.get("recovery_corpus_key") or "")
    state_code = str(metadata.get("state_code") or "")

    return {
        "citation_text": citation_text,
        "normalized_citation": normalized_citation,
        "citation_type": citation_type,
        "corpus_key": corpus_key,
        "state_code": state_code,
        "recovery_query": str(metadata.get("recovery_query") or ""),
        "preferred_dataset_ids": [str(item) for item in list(metadata.get("preferred_dataset_ids") or []) if str(item).strip()],
        "preferred_parquet_files": [str(item) for item in list(metadata.get("preferred_parquet_files") or []) if str(item).strip()],
        "candidate_corpora": [str(item) for item in list(metadata.get("candidate_corpora") or []) if str(item).strip()],
        "document_id": document.document_id,
        "document_title": document.title,
        "document_source_url": document.source_url,
    }


def _collect_document_citation_recovery_candidates(document: "DocketDocument") -> List[Dict[str, Any]]:
    link_payloads = list(document.metadata.get("citation_links") or [])
    if not link_payloads and str(document.text or "").strip():
        resolver = _local_only_bluebook_resolver()
        link_payloads = [
            {
                "citation_text": link.citation_text,
                "citation_type": link.citation_type,
                "normalized_citation": link.normalized_citation,
                "matched": bool(link.matched),
                "corpus_key": link.corpus_key,
                "metadata": dict(link.metadata),
            }
            for link in resolver.resolve_text(document.text, exhaustive=False)
        ]

    candidates: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for payload in link_payloads:
        candidate = _citation_recovery_candidate_from_link(document, payload)
        if candidate is None:
            continue
        key = (
            str(candidate.get("normalized_citation") or ""),
            str(candidate.get("corpus_key") or ""),
            str(candidate.get("state_code") or ""),
            str(candidate.get("document_id") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def collect_docket_dataset_citation_recovery_candidates(dataset: "DocketDatasetObject") -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for document in list(dataset.documents or []):
        for candidate in _collect_document_citation_recovery_candidates(document):
            dedupe_key = (
                str(candidate.get("normalized_citation") or ""),
                str(candidate.get("corpus_key") or ""),
                str(candidate.get("state_code") or ""),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(candidate)

    return {
        "dataset_id": dataset.dataset_id,
        "docket_id": dataset.docket_id,
        "result_count": len(results),
        "results": results,
        "source": "docket_dataset_citation_recovery_candidates",
    }


def collect_packaged_docket_citation_recovery_candidates(manifest_path: str | Path) -> Dict[str, Any]:
    dataset = DocketDatasetObject.from_package(manifest_path)
    result = collect_docket_dataset_citation_recovery_candidates(dataset)
    result["manifest_path"] = str(Path(manifest_path))
    result["source"] = "packaged_docket_citation_recovery_candidates"
    return result


def audit_docket_dataset_citation_sources(
    dataset: "DocketDatasetObject",
    *,
    resolver: Optional[BluebookCitationResolver] = None,
    include_eu_audit: bool = True,
    eu_language: Optional[str] = None,
    eu_max_documents: int = 120,
) -> Dict[str, Any]:
    report = audit_bluebook_citation_resolution_for_documents(
        [
            {
                "document_id": document.document_id,
                "title": document.title,
                "text": document.text,
            }
            for document in list(dataset.documents or [])
        ],
        resolver=resolver,
    )
    report["dataset_id"] = dataset.dataset_id
    report["docket_id"] = dataset.docket_id
    report["source"] = "docket_dataset_citation_source_audit"
    if include_eu_audit:
        report["eu_citation_audit"] = audit_docket_dataset_eu_citation_sources(
            dataset,
            language=eu_language,
            max_documents=eu_max_documents,
        )
    return report


def audit_packaged_docket_citation_sources(
    manifest_path: str | Path,
    *,
    resolver: Optional[BluebookCitationResolver] = None,
    include_eu_audit: bool = True,
    eu_language: Optional[str] = None,
    eu_max_documents: int = 120,
) -> Dict[str, Any]:
    dataset = DocketDatasetObject.from_package(manifest_path)
    result = audit_docket_dataset_citation_sources(
        dataset,
        resolver=resolver,
        include_eu_audit=include_eu_audit,
        eu_language=eu_language,
        eu_max_documents=eu_max_documents,
    )
    result["manifest_path"] = str(Path(manifest_path))
    result["source"] = "packaged_docket_citation_source_audit"
    return result


def audit_docket_dataset_eu_citation_sources(
    dataset: "DocketDatasetObject",
    *,
    language: Optional[str] = None,
    max_documents: int = 120,
) -> Dict[str, Any]:
    documents = list(dataset.documents or [])
    selected_documents = documents[: max(0, int(max_documents))]
    document_summaries: List[Dict[str, Any]] = []
    citations: List[Any] = []
    total_citation_count = 0

    for document in selected_documents:
        text = str(document.text or document.title or "").strip()
        if not text:
            continue
        extracted = extract_eu_legal_citations(text, language=language)
        if not extracted:
            continue
        total_citation_count += len(extracted)
        schemes = sorted({citation.scheme for citation in extracted if citation.scheme})
        member_states = sorted({citation.member_state for citation in extracted if citation.member_state})
        document_summaries.append(
            {
                "document_id": document.document_id,
                "title": document.title,
                "citation_count": len(extracted),
                "schemes": schemes,
                "member_states": member_states,
            }
        )
        citations.extend(extracted)

    unique_citations: List[Any] = []
    seen_citations: set[tuple[str, str, str, str]] = set()
    for citation in citations:
        key = (
            str(citation.scheme or ""),
            str(citation.canonical_uri or ""),
            str(citation.member_state or ""),
            str(citation.normalized_text or ""),
        )
        if key in seen_citations:
            continue
        seen_citations.add(key)
        unique_citations.append(citation)

    actions = [build_eu_lookup_action_for_citation(citation, language=language) for citation in unique_citations]
    handler_counts: Dict[str, int] = {}
    for action in actions:
        handler = str(action.handler_key or "")
        if not handler:
            continue
        handler_counts[handler] = int(handler_counts.get(handler) or 0) + 1

    schemes_count: Dict[str, int] = {}
    member_state_count: Dict[str, int] = {}
    for citation in unique_citations:
        if citation.scheme:
            schemes_count[citation.scheme] = int(schemes_count.get(citation.scheme) or 0) + 1
        if citation.member_state:
            member_state_count[citation.member_state] = int(member_state_count.get(citation.member_state) or 0) + 1

    return {
        "dataset_id": dataset.dataset_id,
        "docket_id": dataset.docket_id,
        "source": "docket_dataset_eu_citation_audit",
        "document_count": len(documents),
        "documents_analyzed": len(selected_documents),
        "documents_with_citations": len(document_summaries),
        "citation_count": total_citation_count,
        "unique_citation_count": len(unique_citations),
        "citations_by_scheme": schemes_count,
        "citations_by_member_state": member_state_count,
        "lookup_action_count": len(actions),
        "lookup_handlers": handler_counts,
        "documents": document_summaries,
        "citations": [asdict(citation) for citation in unique_citations],
        "lookup_actions": [asdict(action) for action in actions],
    }


def _build_missing_authority_follow_up_work_item(
    recovery: Dict[str, Any],
    *,
    index: int,
) -> Dict[str, Any]:
    corpus_key = str(recovery.get("corpus_key") or "").strip().lower()
    state_code = str(recovery.get("state_code") or "").strip().upper()
    corpus = None
    if corpus_key:
        try:
            corpus = get_canonical_legal_corpus(corpus_key)
        except KeyError:
            corpus = None

    preferred_state_code = state_code if corpus_key in {"state_laws", "state_admin_rules", "state_court_rules"} else None
    preferred_parquet_names = corpus.preferred_parquet_names(preferred_state_code) if corpus is not None else []
    target_parquet_path = None
    target_local_parquet_path = None
    if corpus is not None:
        target_filename = (
            corpus.state_parquet_filename(preferred_state_code)
            if preferred_state_code
            else corpus.combined_parquet_filename
        )
        target_parquet_path = f"{corpus.parquet_dir_name.strip('/')}/{target_filename}" if corpus.parquet_dir_name.strip("/") else target_filename
        target_local_parquet_path = str(corpus.parquet_dir() / target_filename)

    publish_plan = dict(recovery.get("publish_plan") or {})
    publish_report = dict(recovery.get("publish_report") or {})
    manifest_path = str(recovery.get("manifest_path") or "")
    normalized_citation = str(recovery.get("normalized_citation") or recovery.get("citation_text") or "")
    work_item_id = _safe_identifier(f"recovery_{index}_{corpus_key}_{state_code}_{normalized_citation}")
    promotion_preview = {}
    if manifest_path:
        try:
            promotion_preview = build_recovery_manifest_promotion_row(
                {
                    "citation_text": str(recovery.get("citation_text") or ""),
                    "normalized_citation": normalized_citation,
                    "corpus_key": corpus_key,
                    "hf_dataset_id": str(recovery.get("hf_dataset_id") or (corpus.hf_dataset_id if corpus is not None else "")),
                    "state_code": state_code,
                    "search_query": str(recovery.get("search_query") or ""),
                    "generated_at": "",
                    "candidates": list(recovery.get("candidates") or []),
                    "archived_sources": list(recovery.get("archived_sources") or []),
                    "manifest_path": manifest_path,
                    "manifest_directory": str(recovery.get("manifest_directory") or ""),
                }
            )
        except Exception:
            promotion_preview = {}
    release_plan_preview = {}
    if manifest_path:
        try:
            release_plan_preview = build_recovery_manifest_release_plan(
                {
                    "citation_text": str(recovery.get("citation_text") or ""),
                    "normalized_citation": normalized_citation,
                    "corpus_key": corpus_key,
                    "hf_dataset_id": str(recovery.get("hf_dataset_id") or (corpus.hf_dataset_id if corpus is not None else "")),
                    "state_code": state_code,
                    "search_query": str(recovery.get("search_query") or ""),
                    "generated_at": "",
                    "candidates": list(recovery.get("candidates") or []),
                    "archived_sources": list(recovery.get("archived_sources") or []),
                    "manifest_path": manifest_path,
                    "manifest_directory": str(recovery.get("manifest_directory") or ""),
                },
                output_dir=promotion_preview.get("promotion_output_dir") or None,
            )
        except Exception:
            release_plan_preview = {}

    stages = [
        {
            "stage": "review_recovery_manifest",
            "status": "ready" if manifest_path else "blocked",
            "manifest_path": manifest_path,
        },
        {
            "stage": "promote_canonical_rows",
            "status": "ready" if corpus is not None and manifest_path else "blocked",
            "target_hf_dataset_id": corpus.hf_dataset_id if corpus is not None else str(recovery.get("hf_dataset_id") or ""),
            "target_parquet_path": target_parquet_path,
            "target_local_parquet_path": target_local_parquet_path,
            "preferred_parquet_names": preferred_parquet_names,
            "cid_field": corpus.cid_field if corpus is not None else "",
        },
        {
            "stage": "merge_canonical_dataset",
            "status": "ready" if corpus is not None and manifest_path and target_local_parquet_path else "blocked",
            "target_hf_dataset_id": corpus.hf_dataset_id if corpus is not None else str(recovery.get("hf_dataset_id") or ""),
            "target_parquet_path": target_parquet_path,
            "target_local_parquet_path": target_local_parquet_path,
        },
        {
            "stage": "publish_recovery_manifest",
            "status": "completed" if publish_report else ("ready" if publish_plan else "blocked"),
            "repo_id": str(publish_plan.get("repo_id") or (corpus.hf_dataset_id if corpus is not None else "")),
            "path_in_repo": str(publish_plan.get("path_in_repo") or ""),
            "publish_command": str(publish_plan.get("publish_command") or ""),
        },
    ]

    return {
        "work_item_id": work_item_id,
        "job_kind": "legal_citation_recovery_follow_up",
        "citation_text": str(recovery.get("citation_text") or ""),
        "normalized_citation": normalized_citation,
        "corpus_key": corpus_key,
        "state_code": state_code,
        "hf_dataset_id": str(recovery.get("hf_dataset_id") or (corpus.hf_dataset_id if corpus is not None else "")),
        "manifest_path": manifest_path,
        "manifest_directory": str(recovery.get("manifest_directory") or ""),
        "search_query": str(recovery.get("search_query") or ""),
        "candidate_count": int(recovery.get("candidate_count") or 0),
        "archived_count": int(recovery.get("archived_count") or 0),
        "target_parquet_path": target_parquet_path,
        "target_local_parquet_path": target_local_parquet_path,
        "preferred_parquet_names": preferred_parquet_names,
        "preferred_state_code": preferred_state_code or "",
        "cid_field": corpus.cid_field if corpus is not None else "",
        "publish_plan": publish_plan,
        "publish_report": publish_report,
        "promotion_preview": promotion_preview,
        "release_plan_preview": release_plan_preview,
        "stages": stages,
    }


async def _execute_missing_authority_follow_up_work_item(
    work_item: Dict[str, Any],
    *,
    execute_publish: bool = False,
) -> Dict[str, Any]:
    manifest_value = str(work_item.get("manifest_path") or "").strip()
    manifest_path = Path(manifest_value).expanduser().resolve() if manifest_value else None
    promotion_output_dir = str((work_item.get("promotion_preview") or {}).get("promotion_output_dir") or "").strip() or None
    target_local_parquet_path = str(work_item.get("target_local_parquet_path") or "").strip() or None
    publish_plan = dict(work_item.get("publish_plan") or {})
    publish_report = dict(work_item.get("publish_report") or {})

    stage_results: List[Dict[str, Any]] = []
    promotion_result: Dict[str, Any] = {}
    merge_result: Dict[str, Any] = {}
    errors: List[str] = []

    manifest_exists = bool(manifest_path is not None and manifest_path.exists())
    stage_results.append(
        {
            "stage": "review_recovery_manifest",
            "status": "completed" if manifest_exists else "blocked",
            "manifest_path": str(manifest_path) if manifest_path is not None else "",
            "manifest_exists": manifest_exists,
            "reason": None if manifest_exists else "Recovery manifest is missing on disk.",
        }
    )

    if manifest_exists:
        try:
            promotion_result = await anyio.to_thread.run_sync(
                lambda: promote_recovery_manifest_to_canonical_bundle(
                    str(manifest_path),
                    output_dir=promotion_output_dir,
                )
            )
            stage_results.append(
                {
                    "stage": "promote_canonical_rows",
                    "status": "completed",
                    "result": promotion_result,
                }
            )
        except Exception as exc:
            errors.append(str(exc))
            stage_results.append(
                {
                    "stage": "promote_canonical_rows",
                    "status": "error",
                    "error": str(exc),
                }
            )
    else:
        stage_results.append(
            {
                "stage": "promote_canonical_rows",
                "status": "blocked",
                "reason": "Recovery manifest is missing on disk.",
            }
        )

    if manifest_exists and not errors and target_local_parquet_path:
        try:
            merge_result = await anyio.to_thread.run_sync(
                lambda: merge_recovery_manifest_into_canonical_dataset(
                    str(manifest_path),
                    output_dir=promotion_output_dir,
                    target_local_parquet_path=target_local_parquet_path,
                    write_promotion_parquet=False,
                )
            )
            stage_results.append(
                {
                    "stage": "merge_canonical_dataset",
                    "status": "completed",
                    "result": merge_result,
                }
            )
        except Exception as exc:
            errors.append(str(exc))
            stage_results.append(
                {
                    "stage": "merge_canonical_dataset",
                    "status": "error",
                    "error": str(exc),
                }
            )
    else:
        stage_results.append(
            {
                "stage": "merge_canonical_dataset",
                "status": "blocked" if not errors else "skipped",
                "target_local_parquet_path": target_local_parquet_path or "",
                "reason": "Target canonical parquet path is not available." if not target_local_parquet_path else ("Promotion stage did not complete successfully." if errors else "Recovery manifest is missing on disk."),
            }
        )

    if publish_report:
        stage_results.append(
            {
                "stage": "publish_recovery_manifest",
                "status": "completed",
                "result": publish_report,
            }
        )
    elif publish_plan and execute_publish and not errors:
        publish_command = str(publish_plan.get("publish_command") or "").strip()
        if publish_command:
            completed = await anyio.to_thread.run_sync(
                lambda: subprocess.run(
                    publish_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            )
            stage_results.append(
                {
                    "stage": "publish_recovery_manifest",
                    "status": "completed" if int(completed.returncode or 1) == 0 else "error",
                    "command": publish_command,
                    "exit_code": int(completed.returncode or 0),
                    "stdout": str(completed.stdout or ""),
                    "stderr": str(completed.stderr or ""),
                }
            )
            if int(completed.returncode or 1) != 0:
                errors.append(str(completed.stderr or publish_command))
        else:
            stage_results.append(
                {
                    "stage": "publish_recovery_manifest",
                    "status": "blocked",
                    "reason": "Publish plan is missing a publish command.",
                }
            )
    elif publish_plan:
        stage_results.append(
            {
                "stage": "publish_recovery_manifest",
                "status": "skipped",
                "command": str(publish_plan.get("publish_command") or ""),
                "reason": "Publish execution is disabled.",
            }
        )
    else:
        stage_results.append(
            {
                "stage": "publish_recovery_manifest",
                "status": "blocked",
                "reason": "No publish plan is available.",
            }
        )

    completed_stage_count = sum(1 for stage in stage_results if str(stage.get("status") or "") == "completed")
    return {
        **work_item,
        "execution": {
            "status": "success" if not errors else "error",
            "completed_stage_count": completed_stage_count,
            "stage_count": len(stage_results),
            "stages": stage_results,
            "promotion_result": promotion_result,
            "merge_result": merge_result,
            "errors": errors,
            "execute_publish": bool(execute_publish),
        },
    }


async def plan_docket_dataset_missing_authority_follow_up(
    dataset: "DocketDatasetObject",
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
) -> Dict[str, Any]:
    recovery_report = await recover_docket_dataset_missing_authorities(
        dataset,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
    )
    work_items = [
        _build_missing_authority_follow_up_work_item(dict(recovery), index=index)
        for index, recovery in enumerate(list(recovery_report.get("recoveries") or []), start=1)
    ]
    return {
        "dataset_id": dataset.dataset_id,
        "docket_id": dataset.docket_id,
        "candidate_count": int(recovery_report.get("candidate_count") or 0),
        "recovery_count": int(recovery_report.get("recovery_count") or 0),
        "work_item_count": len(work_items),
        "recoveries": list(recovery_report.get("recoveries") or []),
        "work_items": work_items,
        "publish_to_hf": bool(publish_to_hf),
        "source": "docket_dataset_missing_authority_follow_up_plan",
    }


async def plan_packaged_docket_missing_authority_follow_up(
    manifest_path: str | Path,
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
) -> Dict[str, Any]:
    dataset = DocketDatasetObject.from_package(manifest_path)
    result = await plan_docket_dataset_missing_authority_follow_up(
        dataset,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
    )
    result["manifest_path"] = str(Path(manifest_path))
    result["source"] = "packaged_docket_missing_authority_follow_up_plan"
    return result


async def execute_docket_dataset_missing_authority_follow_up(
    dataset: "DocketDatasetObject",
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
    execute_publish: bool = False,
) -> Dict[str, Any]:
    plan = await plan_docket_dataset_missing_authority_follow_up(
        dataset,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
    )
    executed_items = [
        await _execute_missing_authority_follow_up_work_item(dict(work_item), execute_publish=execute_publish)
        for work_item in list(plan.get("work_items") or [])
    ]
    error_count = sum(
        1
        for item in executed_items
        if str(((item.get("execution") or {}).get("status") or "")) == "error"
    )
    return {
        **plan,
        "status": "success" if error_count == 0 else "error",
        "work_items": executed_items,
        "executed_work_item_count": len(executed_items),
        "error_count": error_count,
        "execute_publish": bool(execute_publish),
        "source": "docket_dataset_missing_authority_follow_up_execution",
    }


async def execute_packaged_docket_missing_authority_follow_up(
    manifest_path: str | Path,
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
    execute_publish: bool = False,
) -> Dict[str, Any]:
    dataset = DocketDatasetObject.from_package(manifest_path)
    result = await execute_docket_dataset_missing_authority_follow_up(
        dataset,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
        execute_publish=execute_publish,
    )
    result["manifest_path"] = str(Path(manifest_path))
    result["source"] = "packaged_docket_missing_authority_follow_up_execution"
    return result


async def recover_docket_dataset_missing_authorities(
    dataset: "DocketDatasetObject",
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
) -> Dict[str, Any]:
    candidate_report = collect_docket_dataset_citation_recovery_candidates(dataset)
    recoveries: List[Dict[str, Any]] = []
    for candidate in list(candidate_report.get("results") or []):
        recoveries.append(
            await recover_missing_legal_citation_source(
                citation_text=str(candidate.get("citation_text") or ""),
                normalized_citation=str(candidate.get("normalized_citation") or ""),
                corpus_key=str(candidate.get("corpus_key") or "") or None,
                state_code=str(candidate.get("state_code") or "") or None,
                metadata={
                    "candidate_corpora": list(candidate.get("candidate_corpora") or []),
                },
                max_candidates=max_candidates,
                archive_top_k=archive_top_k,
                publish_to_hf=publish_to_hf,
                hf_token=hf_token,
            )
        )

    return {
        "dataset_id": dataset.dataset_id,
        "docket_id": dataset.docket_id,
        "candidate_count": int(candidate_report.get("result_count") or 0),
        "recovery_count": len(recoveries),
        "recoveries": recoveries,
        "publish_to_hf": bool(publish_to_hf),
        "source": "docket_dataset_missing_authority_recovery",
    }


async def recover_packaged_docket_missing_authorities(
    manifest_path: str | Path,
    *,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    max_candidates: int = 8,
    archive_top_k: int = 3,
) -> Dict[str, Any]:
    dataset = DocketDatasetObject.from_package(manifest_path)
    result = await recover_docket_dataset_missing_authorities(
        dataset,
        publish_to_hf=publish_to_hf,
        hf_token=hf_token,
        max_candidates=max_candidates,
        archive_top_k=archive_top_k,
    )
    result["manifest_path"] = str(Path(manifest_path))
    result["source"] = "packaged_docket_missing_authority_recovery"
    return result


def _merge_linked_authorities(
    existing_authorities: Sequence[Dict[str, Any]],
    documents: Sequence["DocketDocument"],
    *,
    resolver: Optional[BluebookCitationResolver] = None,
    state_code: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    merged: List[Dict[str, Any]] = [dict(item) for item in existing_authorities if isinstance(item, dict)]
    seen_keys: set[tuple[str, str, str]] = set()
    for item in merged:
        key = (
            str(item.get("authority_type") or item.get("citation_type") or ""),
            _normalize_authority_text(item.get("citation_text") or item.get("title") or item.get("label") or ""),
            str(item.get("source_url") or ""),
        )
        seen_keys.add(key)

    linked_count = 0
    matched_count = 0
    document_count = 0
    unresolved_count = 0
    recovery_candidates: List[Dict[str, Any]] = []
    active_resolver = resolver or _local_only_bluebook_resolver()
    citation_audit = audit_bluebook_citation_resolution_for_documents(
        [
            {
                "document_id": document.document_id,
                "title": document.title,
                "text": document.text,
            }
            for document in documents
        ],
        state_code=state_code,
        resolver=active_resolver,
        exhaustive=False,
    )
    audit_by_document_id = {
        str(item.get("document_id") or ""): item
        for item in list(citation_audit.get("documents") or [])
        if isinstance(item, dict)
    }

    for document in documents:
        text = str(document.text or "").strip()
        audit_summary = dict(audit_by_document_id.get(document.document_id) or {})
        if audit_summary:
            document.metadata["citation_resolution_summary"] = {
                "citation_count": int(audit_summary.get("citation_count") or 0),
                "matched_citation_count": int(audit_summary.get("matched_citation_count") or 0),
                "unmatched_citation_count": int(audit_summary.get("unmatched_citation_count") or 0),
                "all_citations_resolved": bool(audit_summary.get("all_citations_resolved")),
            }
        if not text:
            continue
        links = (
            active_resolver.resolve_text(text, state_code=state_code, exhaustive=False)
        )
        if not links:
            continue
        document_count += 1
        document.metadata["citation_links"] = [citation_link_to_dict(link) for link in links]
        document_recovery_candidates = [
            candidate
            for candidate in (_citation_recovery_candidate_from_link(document, link) for link in links)
            if candidate is not None
        ]
        document.metadata["citation_recovery_candidates"] = document_recovery_candidates
        recovery_candidates.extend(document_recovery_candidates)
        for index, link in enumerate(links, start=1):
            linked_count += 1
            if link.matched:
                matched_count += 1
            else:
                unresolved_count += 1
            authority_title = str(link.source_title or link.normalized_citation or link.citation_text).strip()
            authority_text = str(link.snippet or link.citation_text or authority_title).strip()
            key = (
                str(link.citation_type or ""),
                _normalize_authority_text(link.citation_text or authority_title),
                str(link.source_url or ""),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(
                {
                    "id": f"linked_authority_{_safe_identifier(link.source_document_id or link.citation_text or f'{document.document_id}_{index}')}",
                    "title": authority_title,
                    "label": authority_title,
                    "text": authority_text,
                    "authority_type": "linked_citation",
                    "citation_type": link.citation_type,
                    "citation_text": link.citation_text,
                    "normalized_citation": link.normalized_citation,
                    "matched": bool(link.matched),
                    "corpus_key": link.corpus_key,
                    "dataset_id": link.dataset_id,
                    "matched_field": link.matched_field,
                    "confidence": float(link.confidence),
                    "state_code": str((link.metadata or {}).get("state_code") or ""),
                    "source_url": str(link.source_url or ""),
                    "source_cid": str(link.source_cid or ""),
                    "source_ref": str(link.source_ref or ""),
                    "document_id": document.document_id,
                    "document_title": document.title,
                    "metadata": dict(link.metadata),
                }
            )

    return merged, {
        "linked_authority_count": linked_count,
        "matched_linked_authority_count": matched_count,
        "unmatched_linked_authority_count": unresolved_count,
        "citation_recovery_candidate_count": len(recovery_candidates),
        "citation_recovery_candidates": recovery_candidates,
        "documents_with_linked_citations": document_count,
        "citation_resolution_ratio": float(citation_audit.get("citation_resolution_ratio") or 0.0),
        "document_resolution_ratio": float(citation_audit.get("document_resolution_ratio") or 0.0),
        "fully_resolved_document_count": int(citation_audit.get("fully_resolved_document_count") or 0),
        "citation_source_audit": citation_audit,
    }


def _is_generic_dcec_formula(formula: Any) -> bool:
    text = str(formula or "").strip()
    return text.startswith("Happens(DocumentFiled(") or text.startswith("Frame(")


def _is_substantive_temporal_formula(formula: Any) -> bool:
    text = str(formula or "").strip()
    if not text:
        return False
    return any(token in text for token in ("-> O(", "-> P(", "-> F(", "O_", "P_", "F_", "By(t,", "Within(t,", "After(t,", "Before(t,", "During(t,"))


def _is_substantive_dcec_formula(formula: Any) -> bool:
    text = str(formula or "").strip()
    if not text:
        return False
    if _is_generic_dcec_formula(text):
        return False
    return any(
        token in text
        for token in (
            "-> O(",
            "-> P(",
            "-> F(",
            "HoldsAt(Obligated(",
            "HoldsAt(Permitted(",
            "HoldsAt(Forbidden(",
            "forall t (",
        )
    )


def _entity_id(payload: Any) -> str:
    return str((payload or {}).get("id") or "").strip() if isinstance(payload, dict) else ""


def _relationship_id(payload: Any) -> str:
    return str((payload or {}).get("id") or "").strip() if isinstance(payload, dict) else ""


def _is_substantive_kg_entity(entity: Any) -> bool:
    if not isinstance(entity, dict):
        return False
    entity_type = str(entity.get("type") or "").strip().lower()
    return entity_type in {"legal_actor", "court_event", "deadline", "deontic_statement", "structured_deontic_norm"}


def _is_substantive_kg_relationship(relationship: Any) -> bool:
    if not isinstance(relationship, dict):
        return False
    rel_type = str(relationship.get("type") or "").strip().upper()
    return rel_type in {
        "SUBJECT_OF",
        "NORM_SUBJECT",
        "IMPOSES_NORM",
        "HAS_DEADLINE",
        "DEADLINE_FOR",
        "IMPOSES_DEADLINE",
        "SCHEDULES",
        "GRANTS",
        "DENIES",
        "VACATES",
        "CONTINUES",
    }


@dataclass
class DocketDocument:
    """Normalized docket document record."""

    document_id: str
    docket_id: str
    title: str
    text: str
    date_filed: str = ""
    document_number: str = ""
    source_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "docket_id": self.docket_id,
            "title": self.title,
            "text": self.text,
            "date_filed": self.date_filed,
            "document_number": self.document_number,
            "source_url": self.source_url,
            "metadata": dict(self.metadata),
        }


@dataclass
class DocketDatasetObject:
    """Portable docket dataset object with deferred processing artifacts."""

    dataset_id: str
    docket_id: str
    case_name: str
    court: str
    documents: List[DocketDocument] = field(default_factory=list)
    plaintiff_docket: List[Dict[str, Any]] = field(default_factory=list)
    defendant_docket: List[Dict[str, Any]] = field(default_factory=list)
    authorities: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    deontic_graph: Dict[str, Any] = field(default_factory=dict)
    deontic_triggers: Dict[str, Any] = field(default_factory=dict)
    proof_assistant: Dict[str, Any] = field(default_factory=dict)
    bm25_index: Dict[str, Any] = field(default_factory=dict)
    vector_index: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "docket_id": self.docket_id,
            "case_name": self.case_name,
            "court": self.court,
            "documents": [document.to_dict() for document in self.documents],
            "plaintiff_docket": [dict(item) for item in self.plaintiff_docket],
            "defendant_docket": [dict(item) for item in self.defendant_docket],
            "authorities": [dict(item) for item in self.authorities],
            "knowledge_graph": dict(self.knowledge_graph),
            "deontic_graph": dict(self.deontic_graph),
            "deontic_triggers": dict(self.deontic_triggers),
            "proof_assistant": dict(self.proof_assistant),
            "bm25_index": dict(self.bm25_index),
            "vector_index": dict(self.vector_index),
            "metadata": dict(self.metadata),
        }

    def summary(self) -> Dict[str, Any]:
        metadata = dict(self.metadata or {})
        eu_audit = dict(metadata.get("eu_citation_audit") or {})
        if not eu_audit:
            eu_audit = dict((metadata.get("citation_source_audit") or {}).get("eu_citation_audit") or {})
        return {
            "dataset_id": self.dataset_id,
            "docket_id": self.docket_id,
            "case_name": self.case_name,
            "court": self.court,
            "document_count": len(self.documents),
            "knowledge_graph_entity_count": len(list((self.knowledge_graph or {}).get("entities") or [])),
            "knowledge_graph_relationship_count": len(list((self.knowledge_graph or {}).get("relationships") or [])),
            "deontic_rule_count": len(list((self.deontic_graph or {}).get("rules") or [])),
            "deontic_trigger_count": len(list((self.deontic_triggers or {}).get("entries") or [])),
            "proof_assistant_work_item_count": len(list((self.proof_assistant or {}).get("agenda") or [])),
            "bm25_document_count": int((self.bm25_index or {}).get("document_count") or 0),
            "vector_document_count": int((self.vector_index or {}).get("document_count") or 0),
            "eu_citation_count": int(eu_audit.get("citation_count") or 0),
            "eu_unique_citation_count": int(eu_audit.get("unique_citation_count") or 0),
            "eu_documents_with_citations": int(eu_audit.get("documents_with_citations") or 0),
            "metadata": dict(self.metadata),
        }

    def collect_citation_recovery_candidates(self) -> Dict[str, Any]:
        return collect_docket_dataset_citation_recovery_candidates(self)

    @classmethod
    def collect_packaged_citation_recovery_candidates(cls, manifest_path: str | Path) -> Dict[str, Any]:
        return collect_packaged_docket_citation_recovery_candidates(manifest_path)

    def audit_citation_sources(
        self,
        *,
        resolver: Optional[BluebookCitationResolver] = None,
        include_eu_audit: bool = True,
        eu_language: Optional[str] = None,
        eu_max_documents: int = 120,
    ) -> Dict[str, Any]:
        return audit_docket_dataset_citation_sources(
            self,
            resolver=resolver,
            include_eu_audit=include_eu_audit,
            eu_language=eu_language,
            eu_max_documents=eu_max_documents,
        )

    @classmethod
    def audit_packaged_citation_sources(
        cls,
        manifest_path: str | Path,
        *,
        resolver: Optional[BluebookCitationResolver] = None,
        include_eu_audit: bool = True,
        eu_language: Optional[str] = None,
        eu_max_documents: int = 120,
    ) -> Dict[str, Any]:
        return audit_packaged_docket_citation_sources(
            manifest_path,
            resolver=resolver,
            include_eu_audit=include_eu_audit,
            eu_language=eu_language,
            eu_max_documents=eu_max_documents,
        )

    async def recover_missing_authorities(
        self,
        *,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
    ) -> Dict[str, Any]:
        return await recover_docket_dataset_missing_authorities(
            self,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
        )

    async def plan_missing_authority_follow_up(
        self,
        *,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
    ) -> Dict[str, Any]:
        return await plan_docket_dataset_missing_authority_follow_up(
            self,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
        )

    async def execute_missing_authority_follow_up(
        self,
        *,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
        execute_publish: bool = False,
    ) -> Dict[str, Any]:
        return await execute_docket_dataset_missing_authority_follow_up(
            self,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
            execute_publish=execute_publish,
        )

    @classmethod
    async def recover_packaged_missing_authorities(
        cls,
        manifest_path: str | Path,
        *,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
    ) -> Dict[str, Any]:
        return await recover_packaged_docket_missing_authorities(
            manifest_path,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
        )

    @classmethod
    async def plan_packaged_missing_authority_follow_up(
        cls,
        manifest_path: str | Path,
        *,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
    ) -> Dict[str, Any]:
        return await plan_packaged_docket_missing_authority_follow_up(
            manifest_path,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
        )

    @classmethod
    async def execute_packaged_missing_authority_follow_up(
        cls,
        manifest_path: str | Path,
        *,
        publish_to_hf: bool = False,
        hf_token: Optional[str] = None,
        max_candidates: int = 8,
        archive_top_k: int = 3,
        execute_publish: bool = False,
    ) -> Dict[str, Any]:
        return await execute_packaged_docket_missing_authority_follow_up(
            manifest_path,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
            execute_publish=execute_publish,
        )

    def append_party_docket_item(self, party: str, item: Dict[str, Any]) -> None:
        normalized_party = str(party or "").strip().lower()
        if normalized_party not in {"plaintiff", "defendant"}:
            raise ValueError("party must be 'plaintiff' or 'defendant'")
        if not isinstance(item, dict):
            raise ValueError("docket item must be a dictionary")
        collection = self.plaintiff_docket if normalized_party == "plaintiff" else self.defendant_docket
        collection.append(dict(item))
        self._refresh_deontic_state()

    def append_authority(self, authority: Dict[str, Any]) -> None:
        if not isinstance(authority, dict):
            raise ValueError("authority must be a dictionary")
        self.authorities.append(dict(authority))
        self._refresh_deontic_state()

    def write_json(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return output_path

    def write_package(
        self,
        output_dir: str | Path,
        *,
        package_name: str | None = None,
        include_car: bool = True,
    ) -> Dict[str, Any]:
        return package_docket_dataset(
            self.to_dict(),
            output_dir,
            package_name=package_name,
            include_car=include_car,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocketDatasetObject":
        return cls(
            dataset_id=str(data.get("dataset_id") or ""),
            docket_id=str(data.get("docket_id") or ""),
            case_name=str(data.get("case_name") or ""),
            court=str(data.get("court") or ""),
            documents=[
                DocketDocument(
                    document_id=str(item.get("document_id") or ""),
                    docket_id=str(item.get("docket_id") or data.get("docket_id") or ""),
                    title=str(item.get("title") or ""),
                    text=str(item.get("text") or ""),
                    date_filed=str(item.get("date_filed") or ""),
                    document_number=str(item.get("document_number") or ""),
                    source_url=str(item.get("source_url") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in list(data.get("documents") or [])
                if isinstance(item, dict)
            ],
            plaintiff_docket=[dict(item) for item in list(data.get("plaintiff_docket") or []) if isinstance(item, dict)],
            defendant_docket=[dict(item) for item in list(data.get("defendant_docket") or []) if isinstance(item, dict)],
            authorities=[dict(item) for item in list(data.get("authorities") or []) if isinstance(item, dict)],
            knowledge_graph=dict(data.get("knowledge_graph") or {}),
            deontic_graph=dict(data.get("deontic_graph") or {}),
            deontic_triggers=dict(data.get("deontic_triggers") or {}),
            proof_assistant=dict(data.get("proof_assistant") or {}),
            bm25_index=dict(data.get("bm25_index") or {}),
            vector_index=dict(data.get("vector_index") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "DocketDatasetObject":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_package(cls, manifest_path: str | Path) -> "DocketDatasetObject":
        return cls.from_dict(load_packaged_docket_dataset(manifest_path))

    @classmethod
    def from_packaged_components(
        cls,
        manifest_path: str | Path,
        *,
        piece_ids: Sequence[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        return load_packaged_docket_dataset_components(manifest_path, piece_ids=piece_ids)

    def _refresh_deontic_state(self) -> None:
        graph, triggers = build_docket_deontic_artifacts(
            dataset_id=self.dataset_id,
            docket_id=self.docket_id,
            plaintiff_docket=self.plaintiff_docket,
            defendant_docket=self.defendant_docket,
            authorities=self.authorities,
        )
        self.deontic_graph = graph.to_dict()
        self.deontic_triggers = triggers
        self.proof_assistant = build_docket_proof_assistant(
            dataset_id=self.dataset_id,
            docket_id=self.docket_id,
            case_name=self.case_name,
            court=self.court,
            documents=self.documents,
            plaintiff_docket=self.plaintiff_docket,
            defendant_docket=self.defendant_docket,
            authorities=self.authorities,
            knowledge_graph=self.knowledge_graph,
            deontic_graph=self.deontic_graph,
            deontic_triggers=self.deontic_triggers,
            bm25_index=self.bm25_index,
            vector_index=self.vector_index,
        )
        artifact_status = self.metadata.setdefault("artifact_status", {})
        artifact_status["deontic_graph"] = bool(self.deontic_graph)
        artifact_status["deontic_triggers"] = bool(self.deontic_triggers)
        artifact_status["proof_assistant"] = bool(self.proof_assistant)
        self.metadata["last_deontic_refresh"] = _utc_now_isoformat()


class DocketDatasetBuilder:
    """Import an entire docket and build deferred retrieval artifacts."""

    def __init__(
        self,
        *,
        vector_dimension: int = 32,
        router_max_documents: int | None = 3,
        formal_logic_max_documents: int | None = None,
        citation_resolver: Optional[BluebookCitationResolver] = None,
        embeddings_provider: str | None = None,
        embeddings_model_name: str | None = None,
        embeddings_device: str | None = None,
        embeddings_batch_size: int = 128,
        embeddings_parallel_batches: int | None = None,
        embeddings_chunking_strategy: str | None = None,
        embeddings_chunk_size: int = 512,
        embeddings_chunk_overlap: int = 50,
    ) -> None:
        self.vector_dimension = max(8, int(vector_dimension))
        self.router_max_documents = None if router_max_documents is None else max(1, int(router_max_documents))
        self.formal_logic_max_documents = None if formal_logic_max_documents is None else max(1, int(formal_logic_max_documents))
        self.citation_resolver = citation_resolver
        self.embeddings_provider = embeddings_provider
        self.embeddings_model_name = embeddings_model_name
        self.embeddings_device = embeddings_device
        self.embeddings_batch_size = max(1, int(embeddings_batch_size or 128))
        self.embeddings_parallel_batches = None if embeddings_parallel_batches is None else max(1, int(embeddings_parallel_batches))
        self.embeddings_chunking_strategy = embeddings_chunking_strategy
        self.embeddings_chunk_size = max(16, int(embeddings_chunk_size or 512))
        self.embeddings_chunk_overlap = max(0, int(embeddings_chunk_overlap or 0))

    def build_from_docket(
        self,
        docket: Dict[str, Any],
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        include_formal_logic: bool = True,
        include_router_enrichment: bool = True,
    ) -> DocketDatasetObject:
        include_formal_logic = bool(include_formal_logic) and _formal_logic_enrichment_enabled()
        include_router_enrichment = bool(include_router_enrichment) and _router_enrichment_enabled()
        _LAST_DATASET_PROGRESS.update({"stage": "normalize_documents", "detail": ""})
        normalized_documents = self._normalize_documents(docket)
        _LAST_DATASET_PROGRESS.update({"stage": "normalize_documents", "detail": f"documents={len(normalized_documents)}"})
        docket_metadata = dict(docket.get("metadata") or {})
        detected_case_number = _normalize_case_number_text(
            docket.get("case_number")
            or docket.get("caseNumber")
            or docket_metadata.get("case_number")
            or docket.get("docket_number")
            or docket.get("docketNumber")
        )
        docket_id = str(docket.get("docket_id") or docket.get("case_id") or docket.get("id") or detected_case_number or "docket")
        case_name = str(docket.get("case_name") or docket.get("caseTitle") or docket.get("title") or docket_id)
        court = str(docket.get("court") or docket.get("courtName") or docket.get("court_full_name") or "")
        dataset_id = f"docket_dataset_{_safe_identifier(docket_id)}"
        plaintiff_docket = self._normalize_auxiliary_items(docket.get("plaintiff_docket") or docket.get("plaintiffs_docket") or [])
        defendant_docket = self._normalize_auxiliary_items(docket.get("defendant_docket") or docket.get("defendants_docket") or [])
        authorities = self._normalize_auxiliary_items(docket.get("authorities") or docket.get("authorities_list") or [])
        _LAST_DATASET_PROGRESS.update({"stage": "link_authorities", "detail": f"authorities={len(authorities)}"})
        authorities, linked_authority_summary = _merge_linked_authorities(
            authorities,
            normalized_documents,
            resolver=self.citation_resolver,
            state_code=str(docket.get("state_code") or docket.get("jurisdiction") or "").strip().upper() or None,
        )
        _LAST_DATASET_PROGRESS.update(
            {"stage": "link_authorities", "detail": f"linked={linked_authority_summary.get('linked_authority_count', 0)}"}
        )
        _LAST_DATASET_PROGRESS.update({"stage": "select_index_documents", "detail": f"documents={len(normalized_documents)}"})
        index_documents = self._select_index_documents(normalized_documents)
        _LAST_DATASET_PROGRESS.update(
            {"stage": "select_index_documents", "detail": f"selected={len(index_documents)}"}
        )

        _LAST_DATASET_PROGRESS.update({"stage": "build_knowledge_graph", "detail": f"selected={len(index_documents)}"})
        knowledge_graph = self._build_knowledge_graph(dataset_id, docket_id, case_name, court, index_documents) if include_knowledge_graph else {}
        _LAST_DATASET_PROGRESS.update(
            {
                "stage": "build_knowledge_graph",
                "detail": f"entities={len(list(knowledge_graph.get('entities') or []))} relationships={len(list(knowledge_graph.get('relationships') or []))}",
            }
        )
        _LAST_DATASET_PROGRESS.update({"stage": "build_deontic_artifacts", "detail": ""})
        deontic_graph_object, deontic_triggers = build_docket_deontic_artifacts(
            dataset_id=dataset_id,
            docket_id=docket_id,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            explicit_statements=list(docket.get("deontic_statements") or []),
        )
        _LAST_DATASET_PROGRESS.update(
            {
                "stage": "build_deontic_artifacts",
                "detail": f"rules={len(list(deontic_graph_object.rules.values()))} triggers={len(list((deontic_triggers or {}).get('entries') or []))}",
            }
        )
        _LAST_DATASET_PROGRESS.update({"stage": "build_bm25", "detail": f"selected={len(index_documents)}"})
        bm25_index = self._build_bm25_index(dataset_id, index_documents) if include_bm25 else {}
        _LAST_DATASET_PROGRESS.update(
            {"stage": "build_bm25", "detail": f"documents={int(bm25_index.get('document_count') or 0)}"}
        )
        _LAST_DATASET_PROGRESS.update({"stage": "build_vector_index", "detail": f"selected={len(index_documents)}"})
        vector_index = self._build_vector_index(dataset_id, index_documents) if include_vector_index else {}
        _LAST_DATASET_PROGRESS.update(
            {
                "stage": "build_vector_index",
                "detail": f"documents={int(vector_index.get('document_count') or 0)} vectors={int(vector_index.get('vector_count') or 0)}",
            }
        )
        _LAST_DATASET_PROGRESS.update({"stage": "build_proof_assistant", "detail": ""})
        proof_assistant = build_docket_proof_assistant(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            documents=normalized_documents,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            knowledge_graph=knowledge_graph,
            deontic_graph=deontic_graph_object.to_dict(),
            deontic_triggers=deontic_triggers,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        _LAST_DATASET_PROGRESS.update(
            {
                "stage": "build_proof_assistant",
                "detail": f"agenda={len(list((proof_assistant or {}).get('agenda') or []))}",
            }
        )
        formal_enrichment: Dict[str, Any] = {}
        if include_formal_logic:
            _LAST_DATASET_PROGRESS.update({"stage": "build_formal_logic", "detail": f"documents={len(normalized_documents)}"})
            formal_enrichment = enrich_docket_documents_with_formal_logic(
                normalized_documents,
                docket_id=docket_id,
                case_name=case_name,
                court=court,
                max_documents=self.formal_logic_max_documents,
            )
            _LAST_DATASET_PROGRESS.update(
                {
                    "stage": "build_formal_logic",
                    "detail": f"processed={int((formal_enrichment.get('summary') or {}).get('processed_document_count') or 0)}",
                }
            )
            self._merge_router_enrichment(
                documents=normalized_documents,
                knowledge_graph=knowledge_graph,
                proof_assistant=proof_assistant,
                router_enrichment=formal_enrichment,
            )
        router_enrichment: Dict[str, Any] = {}
        if include_router_enrichment:
            _LAST_DATASET_PROGRESS.update({"stage": "build_router_enrichment", "detail": f"documents={len(normalized_documents)}"})
            router_enrichment = enrich_docket_documents_with_routers(
                normalized_documents,
                docket_id=docket_id,
                case_name=case_name,
                court=court,
                max_documents=self.router_max_documents,
            )
            _LAST_DATASET_PROGRESS.update(
                {
                    "stage": "build_router_enrichment",
                    "detail": f"processed={int((router_enrichment.get('summary') or {}).get('processed_document_count') or 0)}",
                }
            )
            self._merge_router_enrichment(
                documents=normalized_documents,
                knowledge_graph=knowledge_graph,
                proof_assistant=proof_assistant,
                router_enrichment=router_enrichment,
            )
        _LAST_DATASET_PROGRESS.update({"stage": "finalize", "detail": f"documents={len(normalized_documents)}"})
        artifact_provenance = {
            "knowledge_graph": {"backend": "parsed_document_structure_graph", "is_mock": False},
            "bm25_index": {"backend": "local_bm25", "is_mock": False},
            "vector_index": {
                "backend": str(vector_index.get("backend") or "local_hashed_term_projection"),
                "provider": str(vector_index.get("provider") or ""),
                "model_name": str(vector_index.get("model_name") or ""),
                "is_mock": False,
            },
            "formal_logic": dict((formal_enrichment.get("summary") or {})),
            "router_enrichment": dict((router_enrichment.get("summary") or {})),
            "linked_authorities": {
                "backend": "bluebook_citation_linker",
                "is_mock": False,
                **linked_authority_summary,
            },
            "retrieval_index": {
                "selected_document_count": len(index_documents),
                "excluded_document_count": max(0, len(normalized_documents) - len(index_documents)),
            },
        }
        artifact_status = {
            "knowledge_graph": bool(knowledge_graph),
            "deontic_graph": bool(deontic_graph_object.rules),
            "deontic_triggers": bool((deontic_triggers or {}).get("entries")),
            "proof_assistant": bool((proof_assistant or {}).get("agenda")),
            "bm25_index": bool(bm25_index),
            "vector_index": bool(vector_index),
            "formal_logic": bool((formal_enrichment.get("summary") or {}).get("processed_document_count")),
            "router_enrichment": bool((router_enrichment.get("summary") or {}).get("processed_document_count")),
            "linked_authorities": bool(linked_authority_summary.get("linked_authority_count")),
            "retrieval_index": bool(index_documents),
        }

        return DocketDatasetObject(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            documents=normalized_documents,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            knowledge_graph=knowledge_graph,
            deontic_graph=deontic_graph_object.to_dict(),
            deontic_triggers=deontic_triggers,
            proof_assistant=proof_assistant,
            bm25_index=bm25_index,
            vector_index=vector_index,
            metadata={
                "imported_at": _utc_now_isoformat(),
                "document_count": len(normalized_documents),
                "artifact_provenance": artifact_provenance,
                "artifact_status": artifact_status,
                "source_type": str(docket.get("source_type") or "docket"),
                "case_number": detected_case_number,
                "linked_authorities": linked_authority_summary,
                **({"detected_case_numbers": docket_metadata.get("detected_case_numbers")} if docket_metadata.get("detected_case_numbers") else {}),
            },
        )

    def build_from_json_file(
        self,
        path: str | Path,
        *,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        include_formal_logic: bool = True,
        include_router_enrichment: bool = True,
    ) -> DocketDatasetObject:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Docket JSON payload must be an object")
        payload = _unwrap_nested_docket_payload(payload)
        payload.setdefault("source_type", "json_file")
        payload.setdefault("source_path", str(Path(path)))
        return self.build_from_docket(
            payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
            include_formal_logic=include_formal_logic,
            include_router_enrichment=include_router_enrichment,
        )

    def build_from_html_file(
        self,
        path: str | Path,
        *,
        docket_id: str | None = None,
        case_name: str | None = None,
        court: str | None = None,
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        include_formal_logic: bool = True,
        include_router_enrichment: bool = True,
    ) -> DocketDatasetObject:
        payload = _parse_pacer_html_docket(Path(path))
        if docket_id:
            payload["docket_id"] = docket_id
        if case_name:
            payload["case_name"] = case_name
        if court:
            payload["court"] = court
        return self.build_from_docket(
            payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
            include_formal_logic=include_formal_logic,
            include_router_enrichment=include_router_enrichment,
        )

    def preview_retrieval_index(
        self,
        docket: Dict[str, Any],
        *,
        min_evidence_quality: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_documents = self._normalize_documents(docket)
        index_documents = self._select_index_documents(normalized_documents)
        evidence_counts: Dict[str, int] = {}
        for document in index_documents:
            evidence_quality = str((document.metadata.get("retrieval_index") or {}).get("evidence_quality") or "metadata")
            evidence_counts[evidence_quality] = evidence_counts.get(evidence_quality, 0) + 1
        if min_evidence_quality is not None:
            threshold = _RETRIEVAL_EVIDENCE_RANK.get(str(min_evidence_quality).strip().lower())
            if threshold is None:
                raise ValueError("min_evidence_quality must be one of: metadata, rendered, plain_text, extracted_pdf")
            index_documents = [
                document
                for document in index_documents
                if _RETRIEVAL_EVIDENCE_RANK.get(
                    str((document.metadata.get("retrieval_index") or {}).get("evidence_quality") or "metadata"),
                    0,
                ) >= threshold
            ]
        return {
            "docket_id": str(docket.get("docket_id") or docket.get("id") or "docket"),
            "document_count": len(normalized_documents),
            "selected_document_count": len(index_documents),
            "excluded_document_count": max(0, len(normalized_documents) - len(index_documents)),
            "evidence_quality_counts": evidence_counts,
            "min_evidence_quality": min_evidence_quality,
            "documents": [document.to_dict() for document in index_documents],
        }

    def preview_retrieval_index_from_json_file(
        self,
        path: str | Path,
        *,
        min_evidence_quality: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Docket JSON payload must be an object")
        payload.setdefault("source_type", "json_file")
        payload.setdefault("source_path", str(Path(path)))
        return self.preview_retrieval_index(payload, min_evidence_quality=min_evidence_quality)

    def build_from_directory(
        self,
        directory: str | Path,
        *,
        docket_id: Optional[str] = None,
        case_name: Optional[str] = None,
        court: str = "",
        include_knowledge_graph: bool = True,
        include_bm25: bool = True,
        include_vector_index: bool = True,
        include_formal_logic: bool = True,
        include_router_enrichment: bool = True,
        glob_pattern: str = "*",
    ) -> DocketDatasetObject:
        root = Path(directory)
        if not root.exists():
            raise FileNotFoundError(f"Docket directory not found: {root}")
        if not root.is_dir():
            raise ValueError(f"Docket import path is not a directory: {root}")

        documents: List[Dict[str, Any]] = []
        supported_suffixes = {".txt", ".md", ".json", ".pdf"}
        detected_case_numbers: List[str] = []
        for path in sorted(candidate for candidate in root.rglob(glob_pattern) if candidate.is_file()):
            if path.suffix.lower() not in supported_suffixes:
                continue
            if path.suffix.lower() == ".json":
                json_payload = self._load_json_document_candidate(path)
                if json_payload is not None:
                    documents.append(json_payload)
                    detected = _normalize_case_number_text(
                        json_payload.get("case_number")
                        or _extract_case_number_from_text(str(json_payload.get("text") or ""))
                    )
                    if detected:
                        detected_case_numbers.append(detected)
                continue
            if path.suffix.lower() == ".pdf":
                text = _extract_text_from_pdf(path)
                parsed = parse_legal_document(text) if text else None
                detected = _normalize_case_number_text(
                    (parsed.header.case_number if parsed and parsed.header else "")
                    or _extract_case_number_from_text(text)
                )
                if detected:
                    detected_case_numbers.append(detected)
                if not text:
                    continue
                documents.append(
                    {
                        "id": path.stem,
                        "title": (parsed.title if parsed and parsed.title else path.stem.replace("_", " ").replace("-", " ").strip()) or path.name,
                        "text": text,
                        "source_url": str(path),
                        "document_type": "pdf",
                        "source_path": str(path),
                        "case_number": detected,
                        "metadata": {
                            "source_path": str(path),
                            "source_suffix": ".pdf",
                            "text_extraction": {
                                "source": "directory_pdf",
                                "backend": "pypdf",
                            },
                            "parsed_legal_document": parsed.to_dict() if parsed else {},
                            "detected_case_number": detected,
                        },
                    }
                )
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            detected = _extract_case_number_from_text(text)
            if detected:
                detected_case_numbers.append(detected)
            documents.append(
                {
                    "id": path.stem,
                    "title": path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
                    "text": text,
                    "source_url": str(path),
                    "document_type": path.suffix.lower().lstrip("."),
                    "source_path": str(path),
                    "case_number": detected,
                    "metadata": {
                        "source_path": str(path),
                        "source_suffix": path.suffix.lower(),
                        "detected_case_number": detected,
                    },
                }
            )

        unique_case_numbers = _dedupe_string_sequence(detected_case_numbers)
        resolved_case_number = unique_case_numbers[0] if unique_case_numbers else ""

        docket_payload = {
            "docket_id": docket_id or resolved_case_number or root.name,
            "case_name": case_name or root.name.replace("_", " ").replace("-", " "),
            "court": court,
            "documents": documents,
            "source_type": "directory",
            "source_path": str(root),
            "case_number": resolved_case_number,
            "metadata": {
                "case_number": resolved_case_number,
                "detected_case_numbers": unique_case_numbers,
            },
        }
        return self.build_from_docket(
            docket_payload,
            include_knowledge_graph=include_knowledge_graph,
            include_bm25=include_bm25,
            include_vector_index=include_vector_index,
            include_formal_logic=include_formal_logic,
            include_router_enrichment=include_router_enrichment,
        )

    def _normalize_documents(self, docket: Dict[str, Any]) -> List[DocketDocument]:
        documents_payload = list(docket.get("documents") or docket.get("entries") or docket.get("docketEntries") or [])
        docket_id = str(docket.get("docket_id") or docket.get("case_id") or docket.get("id") or docket.get("caseNumber") or "docket")
        normalized: List[DocketDocument] = []
        for index, item in enumerate(documents_payload, start=1):
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("text")
                or item.get("plain_text")
                or item.get("plainText")
                or item.get("documentText")
                or item.get("content")
                or item.get("description")
                or ""
            ).strip()
            title = str(item.get("title") or item.get("documentTitle") or item.get("description") or f"Docket document {index}").strip()
            document_id = str(item.get("document_id") or item.get("documentId") or item.get("id") or f"{docket_id}_doc_{index}")
            existing_metadata = dict(item.get("metadata") or {})
            classification = self._classify_document(title=title, text=text, item=item)
            text_extraction = dict(existing_metadata.get("text_extraction") or {})
            if not text_extraction:
                if str(item.get("document_type") or "") == "courtlistener_docket_summary":
                    text_extraction = {"source": "synthesized_docket_summary"}
                elif str(item.get("document_type") or "") == "courtlistener_docket_entry":
                    text_extraction = {"source": "synthesized_docket_entry"}
            normalized.append(
                DocketDocument(
                    document_id=document_id,
                    docket_id=docket_id,
                    title=title,
                    text=text,
                    date_filed=str(item.get("date_filed") or item.get("filed") or item.get("filedDate") or ""),
                    document_number=str(item.get("document_number") or item.get("entry_number") or item.get("docNumber") or ""),
                    source_url=str(
                        item.get("source_url")
                        or item.get("documentUrl")
                        or item.get("recap_url")
                        or item.get("docket_url")
                        or item.get("sourcePath")
                        or ""
                    ),
                    metadata={
                        **existing_metadata,
                        "document_type": item.get("document_type"),
                        "page_count": item.get("page_count"),
                        "text_extraction": text_extraction,
                        "classification": classification,
                        "raw": dict(item),
                    },
                )
            )
        return normalized

    def _classify_document(self, *, title: str, text: str, item: Dict[str, Any]) -> Dict[str, Any]:
        combined = f"{title}\n{text}".lower()
        document_type = str(item.get("document_type") or "").strip().lower()

        rules = [
            ("complaint", ("complaint", "petition")),
            ("answer", ("answer",)),
            ("motion", ("motion",)),
            ("order", ("order", "text order")),
            ("notice", ("notice",)),
            ("summons", ("summons",)),
            ("declaration", ("declaration", "affidavit")),
            ("exhibit", ("exhibit",)),
            ("memorandum", ("memorandum", "memo in support")),
        ]
        for label, keywords in rules:
            if document_type == label or any(keyword in combined for keyword in keywords):
                return {"label": label, "backend": "heuristic_legal_document_classifier", "confidence": 0.6}

        if document_type:
            return {"label": document_type, "backend": "heuristic_legal_document_classifier", "confidence": 0.5}
        return {"label": "other", "backend": "heuristic_legal_document_classifier", "confidence": 0.2}

    def _normalize_auxiliary_items(self, items: Sequence[Any]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(list(items), start=1):
            if isinstance(item, dict):
                payload = dict(item)
            else:
                payload = {"text": str(item)}
            payload.setdefault("id", f"aux_{index}")
            payload.setdefault("title", str(payload.get("label") or payload.get("title") or payload.get("text") or payload.get("id")))
            payload.setdefault("text", str(payload.get("text") or payload.get("description") or payload.get("title") or ""))
            normalized.append(payload)
        return normalized

    def _select_index_documents(self, documents: Sequence[DocketDocument]) -> List[DocketDocument]:
        best_by_key: Dict[str, tuple[int, int, DocketDocument]] = {}
        fallback_by_key: Dict[str, tuple[int, int, DocketDocument]] = {}

        for document in documents:
            index_title = _document_index_title(document)
            index_text = _document_index_text(document)
            priority = _document_index_priority(document)
            if priority <= 0:
                if not (str(index_text or "").strip() or str(index_title or "").strip()):
                    continue
                metadata = dict(document.metadata or {})
                metadata["retrieval_index"] = {
                    "selected": False,
                    "priority": priority,
                    "title": index_title,
                    "source_kind": _document_text_source(document) or "synthetic",
                    "evidence_quality": _document_retrieval_evidence_quality(document),
                    "dedupe_key": _document_index_dedupe_key(document),
                }
                candidate = DocketDocument(
                    document_id=document.document_id,
                    docket_id=document.docket_id,
                    title=index_title or document.title,
                    text=index_text,
                    date_filed=document.date_filed,
                    document_number=document.document_number,
                    source_url=document.source_url,
                    metadata=metadata,
                )
                dedupe_key = _document_index_dedupe_key(document)
                ranking = (priority, len(index_text or ""))
                existing = fallback_by_key.get(dedupe_key)
                if existing is None or ranking > existing[:2]:
                    fallback_by_key[dedupe_key] = (priority, len(index_text or ""), candidate)
                continue
            source = _document_text_source(document)
            if source in _LOW_VALUE_TEXT_SOURCES.union(_METADATA_ONLY_TEXT_SOURCES) and not str(index_text or "").strip():
                continue
            if not (str(index_text or "").strip() or str(index_title or "").strip()):
                continue

            metadata = dict(document.metadata or {})
            metadata["retrieval_index"] = {
                "selected": True,
                "priority": priority,
                "title": index_title,
                "source_kind": _document_text_source(document) or "synthetic",
                "evidence_quality": _document_retrieval_evidence_quality(document),
                "dedupe_key": _document_index_dedupe_key(document),
            }
            candidate = DocketDocument(
                document_id=document.document_id,
                docket_id=document.docket_id,
                title=index_title or document.title,
                text=index_text,
                date_filed=document.date_filed,
                document_number=document.document_number,
                source_url=document.source_url,
                metadata=metadata,
            )
            dedupe_key = _document_index_dedupe_key(document)
            ranking = (priority, len(index_text or ""))
            existing = best_by_key.get(dedupe_key)
            if existing is None or ranking > existing[:2]:
                best_by_key[dedupe_key] = (priority, len(index_text or ""), candidate)

        selected = [item[2] for item in best_by_key.values()]
        if not selected and fallback_by_key:
            selected = [item[2] for item in fallback_by_key.values()]
        selected.sort(
            key=lambda document: (
                str(document.date_filed or ""),
                str(document.document_number or ""),
                str(document.document_id or ""),
            )
        )
        return selected

    def _load_json_document_candidate(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if any(key in payload for key in {"text", "plain_text", "content", "description"}):
            text = str(
                payload.get("text")
                or payload.get("plain_text")
                or payload.get("content")
                or payload.get("description")
                or ""
            )
            detected_case_number = _normalize_case_number_text(
                payload.get("case_number")
                or _extract_case_number_from_text(text)
            )
            return {
                "id": str(payload.get("document_id") or payload.get("id") or path.stem),
                "title": str(payload.get("title") or payload.get("description") or path.stem),
                "text": text,
                "date_filed": str(payload.get("date_filed") or payload.get("filed") or ""),
                "document_number": str(payload.get("document_number") or payload.get("entry_number") or ""),
                "source_url": str(payload.get("source_url") or path),
                "document_type": str(payload.get("document_type") or "json"),
                "source_path": str(path),
                "case_number": detected_case_number,
                "metadata": {
                    **dict(payload.get("metadata") or {}),
                    "source_path": str(path),
                    "source_suffix": ".json",
                    "detected_case_number": detected_case_number,
                },
            }
        return None

    def _build_knowledge_graph(
        self,
        dataset_id: str,
        docket_id: str,
        case_name: str,
        court: str,
        documents: Sequence[DocketDocument],
    ) -> Dict[str, Any]:
        graph = KnowledgeGraph(source=dataset_id)
        docket_node_id = f"{dataset_id}:docket"
        graph.add_entity(
            Entity(
                id=docket_node_id,
                type="docket",
                label=case_name,
                properties={"docket_id": docket_id, "court": court},
            )
        )

        for document in documents:
            document_node_id = f"{dataset_id}:document:{_safe_identifier(document.document_id)}"
            graph.add_entity(
                Entity(
                    id=document_node_id,
                    type="docket_document",
                    label=document.title,
                    properties={
                        "document_id": document.document_id,
                        "docket_id": document.docket_id,
                        "date_filed": document.date_filed,
                        "document_number": document.document_number,
                        "source_url": document.source_url,
                    },
                )
            )
            graph.add_relationship(
                Relationship(
                    id=f"{dataset_id}:rel:docket_contains:{_safe_identifier(document.document_id)}",
                    source=docket_node_id,
                    target=document_node_id,
                    type="CONTAINS_DOCUMENT",
                )
            )

            if document.text:
                parsed = parse_legal_document_to_graph(document.text, graph_id=f"{dataset_id}:{_safe_identifier(document.document_id)}")
                for node in list(parsed["knowledge_graph"].get("nodes") or []):
                    graph.add_entity(
                        Entity(
                            id=str(node.get("id") or ""),
                            type=str(node.get("type") or "document_node"),
                            label=str(node.get("label") or ""),
                            properties=dict(node.get("properties") or {}),
                        )
                    )
                    graph.add_relationship(
                        Relationship(
                            id=f"{document_node_id}:rel:describes:{_safe_identifier(node.get('id'))}",
                            source=document_node_id,
                            target=str(node.get("id") or ""),
                            type="DESCRIBES",
                        )
                    )
                for edge in list(parsed["knowledge_graph"].get("edges") or []):
                    graph.add_relationship(
                        Relationship(
                            id=f"{dataset_id}:edge:{_safe_identifier(edge.get('source'))}:{_safe_identifier(edge.get('target'))}:{_safe_identifier(edge.get('type'))}",
                            source=str(edge.get("source") or ""),
                            target=str(edge.get("target") or ""),
                            type=str(edge.get("type") or "RELATED_TO").upper(),
                        )
                    )
        return graph.to_dict()

    def _merge_router_enrichment(
        self,
        *,
        documents: Sequence[DocketDocument],
        knowledge_graph: Dict[str, Any],
        proof_assistant: Dict[str, Any],
        router_enrichment: Dict[str, Any],
    ) -> None:
        analyses = dict(router_enrichment.get("document_analyses") or {})
        for document in documents:
            analysis = analyses.get(str(document.document_id))
            if analysis:
                document.metadata["rich_analysis"] = dict(analysis)
                classification = dict((analysis.get("classification") or {}))
                if classification:
                    document.metadata["classification_router"] = classification

        enrichment_kg = dict(router_enrichment.get("knowledge_graph") or {})
        knowledge_graph.setdefault("entities", [])
        knowledge_graph.setdefault("relationships", [])
        existing_entity_ids = {str(item.get("id") or "") for item in list(knowledge_graph.get("entities") or []) if isinstance(item, dict)}
        existing_rel_ids = {str(item.get("id") or "") for item in list(knowledge_graph.get("relationships") or []) if isinstance(item, dict)}
        for entity in list(enrichment_kg.get("entities") or []):
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("id") or "")
            if entity_id and entity_id not in existing_entity_ids:
                knowledge_graph["entities"].append(dict(entity))
                existing_entity_ids.add(entity_id)
        for relationship in list(enrichment_kg.get("relationships") or []):
            if not isinstance(relationship, dict):
                continue
            rel_id = str(relationship.get("id") or "")
            if rel_id and rel_id not in existing_rel_ids:
                knowledge_graph["relationships"].append(dict(relationship))
                existing_rel_ids.add(rel_id)

        proof_assistant.setdefault("metadata", {})
        proof_assistant["metadata"]["router_enrichment"] = dict(router_enrichment.get("summary") or {})
        if router_enrichment.get("deontic_conflicts"):
            proof_assistant["metadata"]["deontic_conflicts"] = list(router_enrichment.get("deontic_conflicts") or [])
        proof_store = dict(router_enrichment.get("proof_store") or {})
        if (proof_store.get("proofs") or proof_store.get("certificates")):
            proof_assistant["proof_store"] = proof_store
        temporal = proof_assistant.setdefault("temporal_fol", {})
        temporal.setdefault("formulas", [])
        substantive_temporal = list(((router_enrichment.get("temporal_fol") or {}).get("formulas") or []))
        existing_temporal = list(temporal.get("formulas") or [])
        temporal["formulas"] = _dedupe_string_sequence(substantive_temporal + existing_temporal)
        proof_assistant["deontic_temporal_first_order_logic"] = dict(temporal)
        dcec = proof_assistant.setdefault("deontic_cognitive_event_calculus", {})
        dcec.setdefault("formulas", [])
        substantive_dcec = list(((router_enrichment.get("deontic_cognitive_event_calculus") or {}).get("formulas") or []))
        existing_dcec = list(dcec.get("formulas") or [])
        substantive_dcec_non_generic = [formula for formula in substantive_dcec if _is_substantive_dcec_formula(formula)]
        substantive_dcec_generic = [formula for formula in substantive_dcec if not _is_substantive_dcec_formula(formula)]
        existing_dcec_non_generic = [formula for formula in existing_dcec if _is_substantive_dcec_formula(formula)]
        existing_dcec_generic = [formula for formula in existing_dcec if not _is_substantive_dcec_formula(formula)]
        dcec["formulas"] = _dedupe_string_sequence(
            substantive_dcec_non_generic
            + existing_dcec_non_generic
            + substantive_dcec_generic
            + existing_dcec_generic
        )
        frames = proof_assistant.setdefault("frames", {})
        substantive_frames = dict(router_enrichment.get("frame_logic") or {})
        combined_frames: Dict[str, Any] = {}
        combined_frames.update(substantive_frames)
        for frame_id, frame_payload in dict(frames).items():
            combined_frames.setdefault(frame_id, frame_payload)
        frames.clear()
        frames.update(combined_frames)
        proof_assistant["frame_logic"] = dict(frames)
        proof_kg = proof_assistant.setdefault("knowledge_graph", {})
        proof_kg.setdefault("entities", [])
        proof_kg.setdefault("relationships", [])
        proof_kg["entities"] = list(
            dict.fromkeys(
                [
                    json.dumps(item, sort_keys=True)
                    for item in list(proof_kg.get("entities") or []) + list(enrichment_kg.get("entities") or [])
                ]
            )
        )
        proof_kg["entities"] = [json.loads(item) for item in proof_kg["entities"]]
        proof_kg["relationships"] = list(
            dict.fromkeys(
                [
                    json.dumps(item, sort_keys=True)
                    for item in list(proof_kg.get("relationships") or [])
                    + list(enrichment_kg.get("relationships") or [])
                ]
            )
        )
        proof_kg["relationships"] = [json.loads(item) for item in proof_kg["relationships"]]
        metadata = proof_assistant.setdefault("metadata", {})
        prior_document_frame_logic = dict(metadata.get("document_frame_logic") or {})
        prior_substantive_views = dict(metadata.get("substantive_views") or {})
        prior_generic_views = dict(metadata.get("generic_views") or {})
        metadata["document_frame_logic"] = dict(prior_document_frame_logic)
        metadata["document_frame_logic"].update(dict(router_enrichment.get("document_frame_logic") or {}))
        combined_substantive_temporal = _dedupe_string_sequence(
            list(prior_substantive_views.get("temporal_formulas") or []) + list(substantive_temporal)
        )
        combined_substantive_dcec = _dedupe_string_sequence(
            list(prior_substantive_views.get("dcec_formulas") or []) + list(substantive_dcec_non_generic)
        )
        combined_substantive_frame_ids = _dedupe_string_sequence(
            list(prior_substantive_views.get("frame_ids") or []) + list(substantive_frames.keys())
        )
        combined_substantive_entity_ids = _dedupe_string_sequence(
            list(prior_substantive_views.get("knowledge_graph_entity_ids") or [])
            + [_entity_id(item) for item in list(enrichment_kg.get("entities") or []) if _is_substantive_kg_entity(item)]
        )
        combined_substantive_relationship_ids = _dedupe_string_sequence(
            list(prior_substantive_views.get("knowledge_graph_relationship_ids") or [])
            + [_relationship_id(item) for item in list(enrichment_kg.get("relationships") or []) if _is_substantive_kg_relationship(item)]
        )
        combined_generic_temporal = _dedupe_string_sequence(
            list(prior_generic_views.get("temporal_formulas") or [])
            + [formula for formula in list(temporal.get("formulas") or []) if not _is_substantive_temporal_formula(formula)]
        )
        combined_generic_dcec = _dedupe_string_sequence(
            list(prior_generic_views.get("dcec_formulas") or [])
            + substantive_dcec_generic
            + existing_dcec_generic
        )
        combined_generic_entity_ids = _dedupe_string_sequence(
            list(prior_generic_views.get("knowledge_graph_entity_ids") or [])
            + [_entity_id(item) for item in list(proof_kg.get("entities") or []) if not _is_substantive_kg_entity(item)]
        )
        combined_generic_relationship_ids = _dedupe_string_sequence(
            list(prior_generic_views.get("knowledge_graph_relationship_ids") or [])
            + [_relationship_id(item) for item in list(proof_kg.get("relationships") or []) if not _is_substantive_kg_relationship(item)]
        )
        metadata["substantive_views"] = {
            "temporal_formulas": combined_substantive_temporal,
            "dcec_formulas": combined_substantive_dcec,
            "frame_ids": combined_substantive_frame_ids,
            "knowledge_graph_entity_ids": combined_substantive_entity_ids,
            "knowledge_graph_relationship_ids": combined_substantive_relationship_ids,
        }
        metadata["generic_views"] = {
            "temporal_formulas": combined_generic_temporal,
            "dcec_formulas": combined_generic_dcec,
            "knowledge_graph_entity_ids": combined_generic_entity_ids,
            "knowledge_graph_relationship_ids": combined_generic_relationship_ids,
        }
        summary = proof_assistant.setdefault("summary", {})
        summary["router_enriched_proof_count"] = int(
            (((proof_assistant.get("proof_store") or {}).get("summary") or {}).get("proof_count") or 0)
        )
        summary["temporal_formula_count"] = len(list((temporal.get("formulas") or [])))
        summary["substantive_temporal_formula_count"] = len(list(combined_substantive_temporal))
        summary["dcec_formula_count"] = len(list((dcec.get("formulas") or [])))
        summary["substantive_dcec_formula_count"] = len(list(combined_substantive_dcec))
        summary["frame_count"] = len(frames)
        summary["substantive_frame_count"] = len(list(combined_substantive_frame_ids))
        summary["proof_knowledge_graph_entity_count"] = len(list((proof_kg.get("entities") or [])))
        summary["proof_knowledge_graph_relationship_count"] = len(list((proof_kg.get("relationships") or [])))
        summary["substantive_proof_knowledge_graph_entity_count"] = len(list(combined_substantive_entity_ids))
        summary["substantive_proof_knowledge_graph_relationship_count"] = len(list(combined_substantive_relationship_ids))
        extractors = proof_assistant.setdefault("extractors", {})
        extractors.setdefault("deontic_temporal_first_order_logic", {})["formula_count"] = len(list((temporal.get("formulas") or [])))
        extractors.setdefault("deontic_temporal_first_order_logic", {})["substantive_formula_count"] = len(list(combined_substantive_temporal))
        extractors.setdefault("deontic_cognitive_event_calculus", {})["formula_count"] = len(list((dcec.get("formulas") or [])))
        extractors.setdefault("deontic_cognitive_event_calculus", {})["substantive_formula_count"] = len(list(combined_substantive_dcec))
        extractors.setdefault("frame_logic", {})["frame_count"] = len(frames)
        extractors.setdefault("frame_logic", {})["substantive_frame_count"] = len(list(combined_substantive_frame_ids))
        extractors.setdefault("knowledge_graph", {})["entity_count"] = len(list((proof_kg.get("entities") or [])))
        extractors.setdefault("knowledge_graph", {})["relationship_count"] = len(list((proof_kg.get("relationships") or [])))
        extractors.setdefault("knowledge_graph", {})["substantive_entity_count"] = len(list(combined_substantive_entity_ids))
        extractors.setdefault("knowledge_graph", {})["substantive_relationship_count"] = len(list(combined_substantive_relationship_ids))

    def _build_bm25_index(self, dataset_id: str, documents: Sequence[DocketDocument]) -> Dict[str, Any]:
        index_documents = [
            {
                "id": document.document_id,
                "text": document.text or document.title,
                "metadata": {
                    "docket_id": document.docket_id,
                    "title": document.title,
                    "date_filed": document.date_filed,
                    "document_number": document.document_number,
                },
            }
            for document in documents
            if (document.text or document.title).strip()
        ]
        bm25_index = build_bm25_index(index_documents)
        bm25_index["index_id"] = f"{dataset_id}_bm25"
        bm25_index.setdefault("stats", {})["document_count"] = int(bm25_index.get("document_count") or 0)
        return bm25_index

    def _build_vector_index(self, dataset_id: str, documents: Sequence[DocketDocument]) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        prepared_documents = [document for document in documents if (document.text or document.title).strip()]
        vectors, vector_metadata = embed_texts_with_router_or_local_chunked(
            [document.text or document.title for document in prepared_documents],
            fallback_dimension=self.vector_dimension,
            provider=self.embeddings_provider,
            model_name=self.embeddings_model_name,
            device=self.embeddings_device,
            batch_size=self.embeddings_batch_size,
            parallel_batches=self.embeddings_parallel_batches,
            chunking_strategy=self.embeddings_chunking_strategy,
            chunk_size=self.embeddings_chunk_size,
            chunk_overlap=self.embeddings_chunk_overlap,
        )
        for document, vector in zip(prepared_documents, vectors):
            items.append(
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "date_filed": document.date_filed,
                    "document_number": document.document_number,
                    "vector": vector,
                    "norm": self._vector_norm(vector),
                }
            )
        chunk_counts = vector_metadata.get("chunk_counts")
        if isinstance(chunk_counts, list) and chunk_counts:
            total_vector_count = int(sum(int(count or 0) for count in chunk_counts))
        else:
            total_vector_count = len(items)
        return {
            "index_id": f"{dataset_id}_vector",
            "dimension": len(items[0]["vector"]) if items else self.vector_dimension,
            "metric": "cosine",
            "backend": str(vector_metadata.get("backend") or "local_hashed_term_projection"),
            "provider": str(vector_metadata.get("provider") or ""),
            "model_name": str(vector_metadata.get("model_name") or ""),
            "device": str(vector_metadata.get("device") or ""),
            "batch_size": vector_metadata.get("batch_size"),
            "parallel_batches": vector_metadata.get("parallel_batches"),
            "chunking_strategy": str(vector_metadata.get("chunking_strategy") or ""),
            "chunk_size": vector_metadata.get("chunk_size"),
            "chunk_overlap": vector_metadata.get("chunk_overlap"),
            "chunk_counts": vector_metadata.get("chunk_counts"),
            "vector_count": total_vector_count,
            "document_count": len(items),
            "items": items,
        }

    def _embed_text(self, text: str) -> List[float]:
        return hashed_term_projection(text, dimension=self.vector_dimension)

    def _vector_norm(self, vector: Iterable[float]) -> float:
        return math.sqrt(sum(float(value) * float(value) for value in vector))


def search_docket_dataset_bm25(
    dataset: DocketDatasetObject | Dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search the in-memory BM25-style artifact for a docket dataset."""

    dataset_payload = dataset.to_dict() if isinstance(dataset, DocketDatasetObject) else dict(dataset)
    bm25_index = dict(dataset_payload.get("bm25_index") or {})
    documents = list(bm25_index.get("documents") or [])
    results = bm25_search_documents(query, documents, top_k=top_k)
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "result_count": len(results),
        "source": "local_bm25",
    }


def search_docket_dataset_vector(
    dataset: DocketDatasetObject | Dict[str, Any],
    query: str,
    *,
    top_k: int = 10,
    vector_dimension: int = 32,
) -> Dict[str, Any]:
    """Search the lightweight in-memory vector index for a docket dataset."""

    dataset_payload = dataset.to_dict() if isinstance(dataset, DocketDatasetObject) else dict(dataset)
    vector_index = dict(dataset_payload.get("vector_index") or {})
    items = list(vector_index.get("items") or [])
    builder = DocketDatasetBuilder(vector_dimension=vector_dimension)
    query_vector = embed_query_for_backend(
        query,
        backend=str(vector_index.get("backend") or "local_hashed_term_projection"),
        dimension=int(vector_index.get("dimension") or builder.vector_dimension),
        provider=str(vector_index.get("provider") or "") or None,
        model_name=str(vector_index.get("model_name") or "") or None,
        device=str(vector_index.get("device") or "") or None,
    )
    scored: List[Dict[str, Any]] = []
    for item in items:
        vector = list(item.get("vector") or [])
        score = vector_dot(query_vector, vector)
        scored.append(
            {
                "document_id": item.get("document_id"),
                "title": item.get("title"),
                "date_filed": item.get("date_filed"),
                "document_number": item.get("document_number"),
                "score": score,
                "backend": "local_hashed_term_projection",
            }
        )
    scored.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    results = scored[:top_k]
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "result_count": len(results),
    }


def build_docket_deontic_artifacts(
    *,
    dataset_id: str,
    docket_id: str,
    plaintiff_docket: Sequence[Dict[str, Any]],
    defendant_docket: Sequence[Dict[str, Any]],
    authorities: Sequence[Dict[str, Any]],
    explicit_statements: Optional[Sequence[Dict[str, Any]]] = None,
) -> tuple[DeonticGraph, Dict[str, Any]]:
    """Build a deontic graph and trigger state for docket party obligations."""

    inferred_statements: List[Dict[str, Any]] = list(explicit_statements or [])
    trigger_entries: List[Dict[str, Any]] = []
    authority_refs = [
        {
            "id": f"authority_{_safe_identifier(item.get('id') or item.get('title') or item.get('text') or index)}",
            "label": str(item.get("title") or item.get("label") or item.get("text") or f"Authority {index}"),
            "attributes": {"authority_type": item.get("authority_type"), "source_text": item.get("text")},
        }
        for index, item in enumerate(authorities, start=1)
        if isinstance(item, dict)
    ]

    for party, docket_items in (("plaintiff", plaintiff_docket), ("defendant", defendant_docket)):
        for index, item in enumerate(docket_items, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("description") or item.get("title") or "").strip()
            title = str(item.get("title") or item.get("label") or text or f"{party.title()} docket item {index}").strip()
            matched_keywords = _deontic_trigger_keywords(text or title)
            modality = _infer_docket_modality(text or title)
            action = _infer_docket_action(text or title)
            needs_analysis = bool(matched_keywords or authority_refs)
            trigger_id = f"{dataset_id}:trigger:{party}:{_safe_identifier(item.get('id') or title or index)}"
            trigger_entries.append(
                {
                    "trigger_id": trigger_id,
                    "party": party,
                    "source_type": "docket_item",
                    "source_id": str(item.get("id") or trigger_id),
                    "title": title,
                    "matched_keywords": matched_keywords,
                    "needs_analysis": needs_analysis,
                    "modality": modality,
                    "action": action,
                    "authority_count": len(authority_refs),
                    "last_updated": _utc_now_isoformat(),
                }
            )
            if needs_analysis:
                inferred_statements.append(
                    {
                        "id": f"{dataset_id}:statement:{party}:{_safe_identifier(item.get('id') or title or index)}",
                        "entity": party.title(),
                        "modality": modality,
                        "action": action,
                        "document_source": title,
                        "context": text or title,
                        "conditions": [f"Filed on docket {docket_id}"],
                        "confidence": 0.76 if matched_keywords else 0.62,
                        "authorities": list(authority_refs),
                        "attributes": {
                            "party": party,
                            "trigger_id": trigger_id,
                            "source_type": "docket_item",
                            "source_id": str(item.get("id") or trigger_id),
                        },
                    }
                )

    for index, authority in enumerate(authorities, start=1):
        if not isinstance(authority, dict):
            continue
        title = str(authority.get("title") or authority.get("label") or authority.get("text") or f"Authority {index}").strip()
        authority_text = str(authority.get("text") or title).strip()
        matched_keywords = _deontic_trigger_keywords(authority_text)
        modality = _infer_docket_modality(authority_text)
        action = _infer_docket_action(authority_text)
        trigger_id = f"{dataset_id}:trigger:authority:{_safe_identifier(authority.get('id') or title or index)}"
        target_parties = _infer_authority_parties(authority_text)
        trigger_entries.append(
            {
                "trigger_id": trigger_id,
                "party": "all",
                "source_type": "authority",
                "source_id": str(authority.get("id") or title or index),
                "title": title,
                "matched_keywords": matched_keywords,
                "needs_analysis": True,
                "modality": modality,
                "action": action,
                "authority_count": 1,
                "target_parties": list(target_parties),
                "last_updated": _utc_now_isoformat(),
            }
        )
        for party in target_parties:
            inferred_statements.append(
                {
                    "id": f"{dataset_id}:statement:authority:{party}:{_safe_identifier(authority.get('id') or title or index)}",
                    "entity": party.title(),
                    "modality": modality,
                    "action": action,
                    "document_source": title,
                    "context": authority_text,
                    "conditions": [f"Authority listed on docket {docket_id}"],
                    "confidence": 0.83 if matched_keywords else 0.67,
                    "authorities": [
                        {
                            "id": f"authority_{_safe_identifier(authority.get('id') or title or index)}",
                            "label": title,
                            "attributes": {
                                "authority_type": authority.get("authority_type"),
                                "source_text": authority_text,
                            },
                        }
                    ],
                    "attributes": {
                        "party": party,
                        "trigger_id": trigger_id,
                        "source_type": "authority",
                        "source_id": str(authority.get("id") or title or index),
                    },
                }
            )

    graph = DeonticGraphBuilder().build_from_statements(inferred_statements)
    party_analysis = _build_party_deontic_analysis(graph, trigger_entries)
    trigger_summary = {
        "entry_count": len(trigger_entries),
        "pending_analysis_count": sum(1 for item in trigger_entries if item.get("needs_analysis")),
        "parties_requiring_analysis": sorted(
            _parties_requiring_analysis(trigger_entries)
        ),
        "authority_trigger_count": sum(1 for item in trigger_entries if item.get("source_type") == "authority"),
        "analyzed_party_count": len(party_analysis),
        "rule_count_by_party": {
            party: int(analysis.get("rule_count") or 0)
            for party, analysis in sorted(party_analysis.items())
        },
    }
    return graph, {
        "summary": trigger_summary,
        "entries": trigger_entries,
        "party_analysis": party_analysis,
    }


def _deontic_trigger_keywords(text: str) -> List[str]:
    lowered = str(text or "").lower()
    keywords = []
    for token in (
        "must",
        "shall",
        "ordered",
        "deadline",
        "required",
        "obligation",
        "prohibited",
        "may",
        "response",
        "answer",
        "discovery",
        "motion",
        "notice",
    ):
        if token in lowered:
            keywords.append(token)
    return keywords


def _infer_docket_modality(text: str) -> str:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("shall not", "must not", "prohibited", "forbidden")):
        return "prohibition"
    if any(token in lowered for token in ("may", "permitted", "allowed")):
        return "permission"
    return "obligation"


def _infer_docket_action(text: str) -> str:
    lowered = str(text or "").strip()
    if not lowered:
        return "analyze docket obligation"
    for token, action in (
        ("answer", "file an answer or response"),
        ("response", "serve a response"),
        ("discovery", "comply with discovery obligations"),
        ("motion", "respond to motion practice"),
        ("notice", "review and comply with notice requirements"),
        ("deadline", "meet the docket deadline"),
        ("order", "comply with the court order"),
    ):
        if token in lowered.lower():
            return action
    return f"analyze obligations arising from {lowered[:80]}"


def _infer_authority_parties(text: str) -> List[str]:
    lowered = str(text or "").lower()
    parties: List[str] = []
    if "plaintiff" in lowered:
        parties.append("plaintiff")
    if "defendant" in lowered:
        parties.append("defendant")
    if parties:
        return parties
    if any(token in lowered for token in ("parties", "party", "all parties", "either party", "both parties")):
        return ["plaintiff", "defendant"]
    return ["plaintiff", "defendant"]


def _parties_requiring_analysis(trigger_entries: Sequence[Dict[str, Any]]) -> List[str]:
    parties: set[str] = set()
    for item in trigger_entries:
        if not item.get("needs_analysis"):
            continue
        party = str(item.get("party") or "").strip().lower()
        if party in {"plaintiff", "defendant"}:
            parties.add(party)
        for target_party in list(item.get("target_parties") or []):
            normalized_target = str(target_party or "").strip().lower()
            if normalized_target in {"plaintiff", "defendant"}:
                parties.add(normalized_target)
    return sorted(parties)


def _build_party_deontic_analysis(graph: DeonticGraph, trigger_entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    assessments = {item.rule_id: item for item in graph.assess_rules()}
    conflicts = graph.detect_conflicts(only_active=False)
    trigger_map = {str(item.get("trigger_id") or ""): item for item in trigger_entries if item.get("trigger_id")}
    analysis_by_party: Dict[str, Dict[str, Any]] = {}

    for rule in graph.rules.values():
        party = _infer_rule_party(graph, rule)
        if not party:
            continue
        analysis = analysis_by_party.setdefault(
            party,
            {
                "party": party,
                "rule_count": 0,
                "active_rule_count": 0,
                "modalities": {},
                "governed_actions": [],
                "pending_rule_ids": [],
                "trigger_ids": [],
                "trigger_titles": [],
                "authority_ids": [],
                "authority_labels": [],
                "source_gap_rule_ids": [],
                "conflicts": [],
            },
        )
        analysis["rule_count"] += 1
        if rule.active:
            analysis["active_rule_count"] += 1
        modality = rule.modality.value
        analysis["modalities"][modality] = int(analysis["modalities"].get(modality) or 0) + 1

        target = graph.get_node(rule.target_id)
        target_label = target.label if target else rule.predicate
        if target_label and target_label not in analysis["governed_actions"]:
            analysis["governed_actions"].append(target_label)

        assessment = assessments.get(rule.id)
        if assessment and assessment.missing_sources:
            analysis["pending_rule_ids"].append(rule.id)
            analysis["source_gap_rule_ids"].append(rule.id)

        trigger_id = str((rule.attributes or {}).get("trigger_id") or "")
        if trigger_id:
            if trigger_id not in analysis["trigger_ids"]:
                analysis["trigger_ids"].append(trigger_id)
            trigger_entry = trigger_map.get(trigger_id) or {}
            trigger_title = str(trigger_entry.get("title") or "")
            if trigger_title and trigger_title not in analysis["trigger_titles"]:
                analysis["trigger_titles"].append(trigger_title)

        for authority_id in rule.authority_ids:
            if authority_id not in analysis["authority_ids"]:
                analysis["authority_ids"].append(authority_id)
            authority_node = graph.get_node(authority_id)
            authority_label = authority_node.label if authority_node else authority_id
            if authority_label and authority_label not in analysis["authority_labels"]:
                analysis["authority_labels"].append(authority_label)

    for conflict in conflicts:
        left_rule = graph.rules.get(conflict.rule_id)
        right_rule = graph.rules.get(conflict.conflicting_rule_id)
        parties = {
            _infer_rule_party(graph, rule)
            for rule in (left_rule, right_rule)
            if rule is not None
        }
        for party in sorted(value for value in parties if value):
            analysis = analysis_by_party.setdefault(
                party,
                {
                    "party": party,
                    "rule_count": 0,
                    "active_rule_count": 0,
                    "modalities": {},
                    "governed_actions": [],
                    "pending_rule_ids": [],
                    "trigger_ids": [],
                    "trigger_titles": [],
                    "authority_ids": [],
                    "authority_labels": [],
                    "source_gap_rule_ids": [],
                    "conflicts": [],
                },
            )
            analysis["conflicts"].append(conflict.to_dict())

    for party, analysis in analysis_by_party.items():
        analysis["pending_rule_count"] = len(analysis["pending_rule_ids"])
        analysis["source_gap_count"] = len(analysis["source_gap_rule_ids"])
        analysis["conflict_count"] = len(analysis["conflicts"])
        analysis["last_updated"] = _utc_now_isoformat()
        analysis["obligations"] = _governed_actions_for_modality(graph, party, "obligation")
        analysis["prohibitions"] = _governed_actions_for_modality(graph, party, "prohibition")
        analysis["permissions"] = _governed_actions_for_modality(graph, party, "permission")
        analysis["entitlements"] = _governed_actions_for_modality(graph, party, "entitlement")
    return analysis_by_party


def _infer_rule_party(graph: DeonticGraph, rule: Any) -> str:
    attributes = dict(getattr(rule, "attributes", {}) or {})
    explicit_party = str(attributes.get("party") or "").strip().lower()
    if explicit_party in {"plaintiff", "defendant"}:
        return explicit_party
    for source_id in list(getattr(rule, "source_ids", []) or []):
        node = graph.get_node(source_id)
        label = str(node.label if node else "").strip().lower()
        if label in {"plaintiff", "defendant"}:
            return label
    return ""


def _governed_actions_for_modality(graph: DeonticGraph, party: str, modality: str) -> List[str]:
    actions: List[str] = []
    for rule in graph.rules.values():
        if rule.modality.value != modality:
            continue
        if _infer_rule_party(graph, rule) != party:
            continue
        target = graph.get_node(rule.target_id)
        label = target.label if target else rule.predicate
        if label and label not in actions:
            actions.append(label)
    return actions


def summarize_docket_dataset(dataset: DocketDatasetObject | Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact manifest-style summary for a docket dataset."""

    dataset_dict = dataset.to_dict() if isinstance(dataset, DocketDatasetObject) else dict(dataset)
    dataset_object = dataset if isinstance(dataset, DocketDatasetObject) else DocketDatasetObject.from_dict(dataset_dict)
    metadata = dict(dataset_object.metadata or {})
    eu_audit = dict(metadata.get("eu_citation_audit") or {})
    if not eu_audit:
        eu_audit = dict((metadata.get("citation_source_audit") or {}).get("eu_citation_audit") or {})
    document_dates = [document.date_filed for document in dataset_object.documents if document.date_filed]
    document_numbers = [document.document_number for document in dataset_object.documents if document.document_number]
    latest_routing = dict(
        (dataset_object.metadata or {}).get("latest_proof_packet_routing_explanation")
        or (((dataset_object.proof_assistant or {}).get("metadata") or {}).get("latest_proof_packet_routing_explanation") or {})
        or (dict(dataset_dict.get("attached_proof_assistant_packet") or {}).get("routing_explanation") or {})
    )
    return {
        **dataset_object.summary(),
        "date_range": {
            "min": min(document_dates) if document_dates else "",
            "max": max(document_dates) if document_dates else "",
        },
        "document_numbers_present": len(document_numbers),
        "documents_with_text": sum(1 for document in dataset_object.documents if document.text.strip()),
        "documents_with_source_url": sum(1 for document in dataset_object.documents if document.source_url.strip()),
        "plaintiff_docket_count": len(dataset_object.plaintiff_docket),
        "defendant_docket_count": len(dataset_object.defendant_docket),
        "authority_count": len(dataset_object.authorities),
        "deontic_rule_count": len(list((dataset_object.deontic_graph or {}).get("rules") or [])),
        "deontic_trigger_count": len(list((dataset_object.deontic_triggers or {}).get("entries") or [])),
        "proof_assistant_work_item_count": len(list((dataset_object.proof_assistant or {}).get("agenda") or [])),
        "proof_assistant_formula_count": len(
            list(((dataset_object.proof_assistant or {}).get("temporal_fol") or {}).get("formulas") or [])
        ),
        "proof_tactician_plan_count": len(list(((dataset_object.proof_assistant or {}).get("tactician") or {}).get("plans") or [])),
        "parties_requiring_deontic_analysis": list(
            (((dataset_object.deontic_triggers or {}).get("summary") or {}).get("parties_requiring_analysis") or [])
        ),
        "eu_citation_count": int(eu_audit.get("citation_count") or 0),
        "eu_unique_citation_count": int(eu_audit.get("unique_citation_count") or 0),
        "eu_documents_with_citations": int(eu_audit.get("documents_with_citations") or 0),
        "has_latest_proof_packet_routing_explanation": bool(latest_routing),
        "latest_proof_packet_routing_reason": str(latest_routing.get("routing_reason") or ""),
    }


__all__ = [
    "DocketDatasetBuilder",
    "DocketDatasetObject",
    "DocketDocument",
    "build_docket_deontic_artifacts",
    "collect_docket_dataset_citation_recovery_candidates",
    "collect_packaged_docket_citation_recovery_candidates",
    "execute_docket_dataset_missing_authority_follow_up",
    "execute_packaged_docket_missing_authority_follow_up",
    "plan_docket_dataset_missing_authority_follow_up",
    "plan_packaged_docket_missing_authority_follow_up",
    "recover_docket_dataset_missing_authorities",
    "recover_packaged_docket_missing_authorities",
    "build_docket_proof_assistant",
    "search_docket_dataset_bm25",
    "search_docket_dataset_vector",
    "summarize_docket_dataset",
]
