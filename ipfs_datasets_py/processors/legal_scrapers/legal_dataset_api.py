"""MCP/CLI-friendly APIs for legal dataset scraping.

Core scraping implementations live in the individual scraper modules. This file
provides parameter-driven helper functions so thin wrappers (MCP tools, CLI
commands, SDK calls) can share the same orchestration, defaults, and error
shapes.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, Iterable, List

import anyio

try:
    from .canonical_legal_corpora import get_canonical_legal_corpus
except ImportError:  # pragma: no cover - file-based test imports
    import importlib.util

    _CANONICAL_MODULE_PATH = Path(__file__).with_name("canonical_legal_corpora.py")
    _CANONICAL_SPEC = importlib.util.spec_from_file_location(
        "canonical_legal_corpora",
        _CANONICAL_MODULE_PATH,
    )
    if _CANONICAL_SPEC is None or _CANONICAL_SPEC.loader is None:
        raise
    _CANONICAL_MODULE = importlib.util.module_from_spec(_CANONICAL_SPEC)
    sys.modules.setdefault("canonical_legal_corpora", _CANONICAL_MODULE)
    _CANONICAL_SPEC.loader.exec_module(_CANONICAL_MODULE)
    get_canonical_legal_corpus = _CANONICAL_MODULE.get_canonical_legal_corpus

logger = logging.getLogger(__name__)


DEFAULT_CAP_HF_DATASET_ID = get_canonical_legal_corpus("caselaw_access_project").hf_dataset_id
DEFAULT_CAP_HF_PARQUET_FILE = get_canonical_legal_corpus("caselaw_access_project").combined_parquet_path()
DEFAULT_CAP_CHUNK_HF_PARQUET_FILE = get_canonical_legal_corpus("caselaw_access_project").combined_embeddings_path()

DEFAULT_USCODE_HF_DATASET_ID = get_canonical_legal_corpus("us_code").hf_dataset_id
DEFAULT_USCODE_HF_PARQUET_PREFIX = get_canonical_legal_corpus("us_code").parquet_dir_name
DEFAULT_STATE_LAWS_HF_DATASET_ID = get_canonical_legal_corpus("state_laws").hf_dataset_id
DEFAULT_STATE_ADMIN_RULES_HF_DATASET_ID = get_canonical_legal_corpus("state_admin_rules").hf_dataset_id
DEFAULT_COURT_RULES_HF_DATASET_ID = get_canonical_legal_corpus("state_court_rules").hf_dataset_id
DEFAULT_FEDERAL_REGISTER_HF_DATASET_ID = get_canonical_legal_corpus("federal_register").hf_dataset_id
DEFAULT_NETHERLANDS_LAWS_HF_DATASET_ID = get_canonical_legal_corpus("netherlands_laws").hf_dataset_id


def _normalize_state_code(value: Any, *, default: str = "OR") -> str:
    """Normalize state input to a two-letter uppercase code."""
    state = str(value or default).strip().upper()
    if len(state) != 2 or not state.isalpha():
        raise ValueError("state must be a two-letter code (e.g., OR, CA, NY)")
    return state


def _parse_iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def _extract_temporal_case(result_row: Dict[str, Any]) -> Dict[str, Any]:
    case = result_row.get("case")
    return case if isinstance(case, dict) else result_row


def _result_matches_as_of(case: Dict[str, Any], as_of_date: str) -> bool:
    target = _parse_iso_date(as_of_date)
    if not target:
        return True

    version_start = _parse_iso_date(case.get("version_start_date") or case.get("effective_date"))
    version_end = _parse_iso_date(case.get("version_end_date"))

    if version_start and target < version_start:
        return False
    if version_end and target > version_end:
        return False
    return bool(version_start) or bool(case.get("is_current"))


def _result_matches_effective_date(case: Dict[str, Any], effective_date: str) -> bool:
    target = _parse_iso_date(effective_date)
    if not target:
        return True
    return _parse_iso_date(case.get("version_start_date") or case.get("effective_date")) == target


def _apply_netherlands_temporal_filters(
    results: List[Dict[str, Any]],
    *,
    prefer_current_versions: bool,
    include_historical_versions: bool,
    as_of_date: str,
    effective_date: str,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in results:
        case = _extract_temporal_case(row)
        is_current = bool(case.get("is_current"))
        if not include_historical_versions and not is_current:
            continue
        if effective_date and not _result_matches_effective_date(case, effective_date):
            continue
        if as_of_date and not _result_matches_as_of(case, as_of_date):
            continue
        filtered.append(row)

    if prefer_current_versions:
        filtered.sort(
            key=lambda item: (
                0 if bool(_extract_temporal_case(item).get("is_current")) else 1,
                -float(item.get("score", 0.0)),
            )
        )
    return filtered


def _parse_netherlands_citation_query(value: Any) -> Dict[str, Any]:
    query = str(value or "").strip()
    if not query:
        return {}

    lowered = query.lower()
    identifier_match = re.search(r"\b(BWBR[0-9A-Z]+)\b", query, re.IGNORECASE)
    article_numbers: List[str] = []

    range_match = re.search(
        r"\bartik(?:el|elen)\s+([0-9]+)\s*(?:-|t/m|tot)\s*([0-9]+)\b",
        lowered,
        re.IGNORECASE,
    )
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start <= end and (end - start) <= 20:
            article_numbers.extend(str(number) for number in range(start, end + 1))

    if not article_numbers:
        articles_match = re.search(
            r"\bartik(?:el|elen)\s+([0-9a-z:.\s,enetm/-]+)$",
            lowered,
            re.IGNORECASE,
        )
        if articles_match:
            for token in re.findall(r"\b([0-9]+(?:[.:][0-9]+)*(?:[a-z])?)\b", articles_match.group(1), re.IGNORECASE):
                normalized_token = token.strip()
                if normalized_token and normalized_token not in article_numbers:
                    article_numbers.append(normalized_token)

    hierarchy_segments: List[str] = []
    for kind in ("boek", "titel", "hoofdstuk", "afdeling", "paragraaf"):
        for match in re.finditer(rf"\b{kind}\s+[0-9a-zivxlcdm.\-]+\b", lowered, re.IGNORECASE):
            hierarchy_segments.append(match.group(0).strip())

    law_reference = query
    for pattern in [
        r"\bBWBR[0-9A-Z]+\b",
        r"\bartik(?:el|elen)\s+[0-9]+(?:[.:][0-9]+)*(?:[a-z])?(?:\s*(?:-|t/m|tot|,|en)\s*[0-9]+(?:[.:][0-9]+)*(?:[a-z])?)*\b",
        r"\b(?:boek|titel|hoofdstuk|afdeling|paragraaf)\s+[0-9a-zivxlcdm.\-]+\b",
    ]:
        law_reference = re.sub(pattern, " ", law_reference, flags=re.IGNORECASE)
    law_reference = re.sub(r"\s+", " ", law_reference).strip(" ,;:-")

    parsed = {
        "raw_query": query,
        "law_identifier": identifier_match.group(1).upper() if identifier_match else "",
        "law_reference": law_reference.strip(),
        "article_number": article_numbers[0] if article_numbers else "",
        "article_numbers": article_numbers,
        "hierarchy_segments": hierarchy_segments,
    }
    if not parsed["law_identifier"] and not parsed["law_reference"] and not parsed["article_number"]:
        return {}
    return parsed


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _clean_answer_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _extract_netherlands_article_references(text: Any) -> List[str]:
    normalized = _normalize_match_text(text)
    if not normalized:
        return []

    references: List[str] = []
    range_match = re.search(
        r"\bartik(?:el|elen)\s+([0-9]+)\s*(?:-|t/m|tot)\s*([0-9]+)\b",
        normalized,
        re.IGNORECASE,
    )
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start <= end and (end - start) <= 20:
            references.extend(str(number) for number in range(start, end + 1))

    for match in re.finditer(
        r"\bartik(?:el|elen)\s+([0-9a-z:.\s,enetm/-]+)",
        normalized,
        re.IGNORECASE,
    ):
        for token in re.findall(r"\b([0-9]+(?:[.:][0-9]+)*(?:[a-z])?)\b", match.group(1), re.IGNORECASE):
            if token not in references:
                references.append(token)
    return references


def _article_sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    match = re.match(r"^([0-9]+)", text)
    if match:
        return (int(match.group(1)), text)
    return (10**9, text)


def _score_netherlands_citation_match(
    case: Dict[str, Any],
    parsed_citation: Dict[str, Any],
    *,
    prefer_current_versions: bool,
) -> int:
    score = 0
    query_identifier = str(parsed_citation.get("law_identifier") or "")
    query_reference = _normalize_match_text(parsed_citation.get("law_reference") or "")
    query_article = _normalize_match_text(parsed_citation.get("article_number") or "")
    query_articles = {
        _normalize_match_text(article)
        for article in (parsed_citation.get("article_numbers") or [])
        if _normalize_match_text(article)
    }

    case_identifier = str(case.get("law_identifier") or case.get("identifier") or "").upper()
    case_article = _normalize_match_text(case.get("article_number") or "")

    alias_candidates = [
        _normalize_match_text(case.get("canonical_title")),
        _normalize_match_text(case.get("title")),
        _normalize_match_text(case.get("citation")),
        _normalize_match_text(case.get("document_citation")),
    ]
    alias_candidates.extend(_normalize_match_text(item) for item in (case.get("aliases") or []))

    if query_identifier:
        if query_identifier == case_identifier:
            score += 10
        else:
            return 0

    if query_reference:
        if any(query_reference == candidate for candidate in alias_candidates if candidate):
            score += 8
        elif any(query_reference in candidate for candidate in alias_candidates if candidate):
            score += 5
        elif not query_identifier:
            return 0

    if query_articles or query_article:
        if (query_articles and case_article in query_articles) or (query_article and query_article == case_article):
            score += 10
        else:
            return 0

    hierarchy_labels = [_normalize_match_text(item) for item in (case.get("hierarchy_labels") or [])]
    for segment in parsed_citation.get("hierarchy_segments") or []:
        if _normalize_match_text(segment) in hierarchy_labels:
            score += 2

    if prefer_current_versions and bool(case.get("is_current")):
        score += 1
    return score


def _determine_netherlands_match_reason(case: Dict[str, Any], parsed_citation: Dict[str, Any]) -> str:
    query_identifier = str(parsed_citation.get("law_identifier") or "").upper()
    query_reference = _normalize_match_text(parsed_citation.get("law_reference") or "")
    case_identifier = str(case.get("law_identifier") or case.get("identifier") or "").upper()
    aliases = [_normalize_match_text(item) for item in (case.get("aliases") or [])]
    titles = [
        _normalize_match_text(case.get("canonical_title")),
        _normalize_match_text(case.get("title")),
    ]

    if query_identifier and query_identifier == case_identifier:
        return "identifier_article_match"
    if query_reference and query_reference in aliases:
        return "alias_article_match"
    if query_reference and query_reference in titles:
        return "title_article_match"
    if query_reference:
        return "citation_article_match"
    return "vector_match"


def _format_netherlands_article_answer(
    case: Dict[str, Any],
    *,
    match_reason: str,
    retrieval_reason: str,
) -> Dict[str, Any]:
    return {
        "canonical_citation": str(case.get("citation") or case.get("document_citation") or ""),
        "law_identifier": str(case.get("law_identifier") or case.get("identifier") or ""),
        "law_version_identifier": str(case.get("law_version_identifier") or case.get("version_specific_identifier") or ""),
        "canonical_title": str(case.get("canonical_title") or case.get("title") or ""),
        "aliases": list(case.get("aliases") or []),
        "article_number": str(case.get("article_number") or ""),
        "hierarchy_path": list(case.get("hierarchy_path") or []),
        "hierarchy_labels": list(case.get("hierarchy_labels") or []),
        "effective_date": str(case.get("effective_date") or ""),
        "version_start_date": str(case.get("version_start_date") or case.get("effective_date") or ""),
        "version_end_date": str(case.get("version_end_date") or ""),
        "source_url": str(case.get("source_url") or case.get("versioned_law_url") or case.get("canonical_law_url") or ""),
        "information_url": str(case.get("information_url") or ""),
        "article_text": _clean_answer_text(case.get("text") or ""),
        "referenced_articles": _extract_netherlands_article_references(case.get("text") or ""),
        "previous_article": None,
        "next_article": None,
        "sibling_articles": [],
        "match_reason": match_reason,
        "retrieval_reason": retrieval_reason,
    }


def _compact_netherlands_context_article(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "canonical_citation": str(case.get("citation") or case.get("document_citation") or ""),
        "law_identifier": str(case.get("law_identifier") or case.get("identifier") or ""),
        "law_version_identifier": str(case.get("law_version_identifier") or case.get("version_specific_identifier") or ""),
        "article_number": str(case.get("article_number") or ""),
        "hierarchy_labels": list(case.get("hierarchy_labels") or []),
        "source_url": str(case.get("source_url") or case.get("versioned_law_url") or case.get("canonical_law_url") or ""),
    }


def _same_netherlands_hierarchy_scope(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_path = list(left.get("hierarchy_path") or [])
    right_path = list(right.get("hierarchy_path") or [])
    if not left_path or not right_path:
        return False
    left_scope = [item.get("label") for item in left_path[:-1]]
    right_scope = [item.get("label") for item in right_path[:-1]]
    return left_scope == right_scope


def _enrich_netherlands_answers_with_context(
    answers: List[Dict[str, Any]],
    *,
    results: List[Dict[str, Any]],
    context_mode: str,
) -> List[Dict[str, Any]]:
    normalized_mode = str(context_mode or "exact").strip().lower()
    if normalized_mode not in {"exact", "neighbors", "hierarchy"}:
        normalized_mode = "exact"

    cases = [_extract_temporal_case(row) for row in results]
    by_version: Dict[str, List[Dict[str, Any]]] = {}
    for case in cases:
        version_id = str(case.get("law_version_identifier") or case.get("version_specific_identifier") or "")
        by_version.setdefault(version_id, []).append(case)

    for version_id, version_cases in by_version.items():
        version_cases.sort(key=lambda case: _article_sort_key(case.get("article_number")))
        by_version[version_id] = version_cases

    for answer in answers:
        version_cases = by_version.get(str(answer.get("law_version_identifier") or ""), [])
        current_index = next(
            (
                index
                for index, case in enumerate(version_cases)
                if str(case.get("article_number") or "") == str(answer.get("article_number") or "")
            ),
            -1,
        )
        if current_index < 0:
            continue

        current_case = version_cases[current_index]
        if normalized_mode in {"neighbors", "hierarchy"}:
            if current_index > 0:
                answer["previous_article"] = _compact_netherlands_context_article(version_cases[current_index - 1])
            if current_index + 1 < len(version_cases):
                answer["next_article"] = _compact_netherlands_context_article(version_cases[current_index + 1])

        if normalized_mode == "hierarchy":
            siblings = [
                _compact_netherlands_context_article(case)
                for case in version_cases
                if case is not current_case and _same_netherlands_hierarchy_scope(current_case, case)
            ]
            answer["sibling_articles"] = siblings

    return answers


def _assemble_netherlands_answers(
    results: List[Dict[str, Any]],
    *,
    citation_query: str,
    prefer_current_versions: bool,
    context_mode: str,
    context_results: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    parsed = _parse_netherlands_citation_query(citation_query)
    answers: List[Dict[str, Any]] = []

    if parsed:
        for row in results:
            case = _extract_temporal_case(row)
            score = _score_netherlands_citation_match(
                case,
                parsed,
                prefer_current_versions=prefer_current_versions,
            )
            if score <= 0:
                continue
            answers.append(
                _format_netherlands_article_answer(
                    case,
                    match_reason=_determine_netherlands_match_reason(case, parsed),
                    retrieval_reason="citation_grounded_retrieval",
                )
            )

        if parsed.get("article_numbers"):
            desired_order = {
                str(article): index
                for index, article in enumerate(parsed.get("article_numbers") or [])
            }
            answers.sort(
                key=lambda item: (
                    desired_order.get(str(item.get("article_number") or ""), 999),
                    0 if item.get("version_end_date") == "" else 1,
                    item.get("canonical_citation") or "",
                )
            )
        if answers:
            return _enrich_netherlands_answers_with_context(
                answers,
                results=list(context_results or results),
                context_mode=context_mode,
            )

    for row in results[:3]:
        case = _extract_temporal_case(row)
        answers.append(
            _format_netherlands_article_answer(
                case,
                match_reason="vector_match",
                retrieval_reason="vector_search_fallback",
            )
        )
    return _enrich_netherlands_answers_with_context(
        answers,
        results=list(context_results or results),
        context_mode=context_mode,
    )


def _apply_netherlands_citation_query(
    results: List[Dict[str, Any]],
    *,
    citation_query: str,
    prefer_current_versions: bool,
) -> List[Dict[str, Any]]:
    parsed = _parse_netherlands_citation_query(citation_query)
    if not parsed:
        return results

    scored: List[tuple[int, Dict[str, Any]]] = []
    for row in results:
        case = _extract_temporal_case(row)
        score = _score_netherlands_citation_match(
            case,
            parsed,
            prefer_current_versions=prefer_current_versions,
        )
        scored.append((score, row))

    matches = [(score, row) for score, row in scored if score > 0]
    if not matches:
        return results

    matches.sort(key=lambda item: (-item[0], -float(item[1].get("score", 0.0))))
    return [row for _, row in matches]


def _get_repo_root() -> Path:
    """Resolve repository root from this module path."""
    return Path(__file__).resolve().parents[3]


def _venv_python(venv_dir: str = ".venv") -> Path:
    """Return interpreter path for the target virtual environment."""
    root = _get_repo_root()
    return root / venv_dir / "bin" / "python"


def _ensure_venv(
    *,
    venv_dir: str = ".venv",
    packages: Iterable[str],
    upgrade_pip: bool = True,
) -> Dict[str, Any]:
    """Create/update a project venv and install required packages."""
    root = _get_repo_root()
    python_path = _venv_python(venv_dir)
    venv_path = root / venv_dir

    created = False
    if not python_path.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
        created = True

    if upgrade_pip:
        subprocess.run(
            [str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )

    pkg_list = [p for p in packages if p]
    if pkg_list:
        subprocess.run(
            [str(python_path), "-m", "pip", "install", *pkg_list],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )

    return {
        "venv_path": str(venv_path),
        "python_path": str(python_path),
        "created": created,
        "installed_packages": pkg_list,
    }


def _run_cap_vector_operation_in_venv(
    *,
    operation: str,
    payload: Dict[str, Any],
    venv_dir: str = ".venv",
) -> Dict[str, Any]:
    """Run CAP vector operations in the project venv and return parsed JSON."""
    root = _get_repo_root()
    python_path = _venv_python(venv_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["CAP_VECTOR_PAYLOAD"] = json.dumps(payload)
    env["CAP_VECTOR_MODULE_PATH"] = str(
        root
        / "ipfs_datasets_py"
        / "processors"
        / "legal_scrapers"
        / "caselaw_access_program"
        / "vector_search_integration.py"
    )

    script = r'''
from ipfs_datasets_py.utils import anyio_compat as asyncio
import importlib.util
import json
import os
import sys
import time

module_path = os.environ["CAP_VECTOR_MODULE_PATH"]
spec = importlib.util.spec_from_file_location("cap_vector_search_integration", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Failed to load CAP module spec from {module_path}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
create_caselaw_access_vector_search = module.create_caselaw_access_vector_search
CAPVectorSearchConfig = module.CAPVectorSearchConfig


async def _main() -> None:
    payload = json.loads(os.environ.get("CAP_VECTOR_PAYLOAD", "{}"))
    dataset_id = payload.get("hf_dataset_id")
    cache_dir = payload.get("hf_cache_dir")
    if dataset_id or cache_dir:
        cap = create_caselaw_access_vector_search(
            CAPVectorSearchConfig(
                dataset_id=dataset_id or CAPVectorSearchConfig().dataset_id,
                cache_dir=cache_dir,
            )
        )
    else:
        cap = create_caselaw_access_vector_search()
    op = payload.get("operation")

    if op == "ingest":
        result = await cap.ingest_embeddings(
            collection_name=payload["collection_name"],
            store_type=payload.get("store_type", "faiss"),
            parquet_file=payload.get("parquet_file"),
            model_hint=payload.get("model_hint"),
            max_rows=int(payload.get("max_rows", 10000)),
            batch_size=int(payload.get("batch_size", 512)),
            distance_metric=payload.get("distance_metric", "cosine"),
        )
        print(json.dumps({
            "status": "success",
            "operation": op,
            "result": {
                "collection_name": result.collection_name,
                "store_type": result.store_type,
                "source_file": result.source_file,
                "ingested_count": result.ingested_count,
                "vector_dimension": result.vector_dimension,
            },
        }))
        return

    if op == "search":
        results = await cap.search_by_vector(
            collection_name=payload["collection_name"],
            query_vector=payload["query_vector"],
            store_type=payload.get("store_type", "faiss"),
            top_k=int(payload.get("top_k", 10)),
            filter_dict=payload.get("filter_dict"),
        )
        output = []
        for r in results:
            output.append(
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
            )
        print(json.dumps({"status": "success", "operation": op, "results": output}))
        return

    if op == "search_cases":
        from huggingface_hub import hf_hub_url, list_repo_files
        import duckdb

        def _resolve_hf_parquet_files(
            *,
            dataset_id: str,
            explicit_file: str | None = None,
            explicit_files: list[str] | None = None,
            parquet_prefix: str | None = None,
            preferred_names: list[str] | None = None,
            max_files: int = 0,
            exclude_name_tokens: list[str] | None = None,
        ) -> list[str]:
            if explicit_file:
                return [explicit_file]

            explicit_files = [str(f).strip() for f in (explicit_files or []) if str(f).strip()]
            if explicit_files:
                return explicit_files[:max_files] if max_files > 0 else explicit_files

            repo_files = list_repo_files(repo_id=dataset_id, repo_type="dataset")
            parquet_files = [f for f in repo_files if f.endswith(".parquet")]

            if parquet_prefix:
                normalized = parquet_prefix.strip("/")
                parquet_files = [
                    f
                    for f in parquet_files
                    if f == normalized or f.startswith(f"{normalized}/")
                ]

            if exclude_name_tokens:
                lowered_tokens = [str(tok).lower() for tok in exclude_name_tokens if str(tok).strip()]
                parquet_files = [
                    f
                    for f in parquet_files
                    if not any(tok in f.lower() for tok in lowered_tokens)
                ]

            if preferred_names:
                preferred = {name.lower() for name in preferred_names if name}
                preferred_matches = []
                for candidate in sorted(parquet_files):
                    lowered = candidate.lower()
                    if any(pref in lowered for pref in preferred):
                        preferred_matches.append(candidate)
                if preferred_matches:
                    return preferred_matches[:max_files] if max_files > 0 else preferred_matches

            if parquet_files:
                return [sorted(parquet_files)[0]]

            raise ValueError(
                f"No parquet file found in dataset '{dataset_id}'"
                + (f" under prefix '{parquet_prefix}'" if parquet_prefix else "")
            )

        results = await cap.search_by_vector(
            collection_name=payload["collection_name"],
            query_vector=payload["query_vector"],
            store_type=payload.get("store_type", "faiss"),
            top_k=int(payload.get("top_k", 10)),
            filter_dict=payload.get("filter_dict"),
        )

        cid_field = payload.get("cid_metadata_field", "cid")
        cid_column = payload.get("cid_column", "cid")
        text_candidates = payload.get("text_field_candidates") or ["head_matter", "text"]
        snippet_chars = int(payload.get("snippet_chars", 320))
        chunk_lookup_enabled = bool(payload.get("chunk_lookup_enabled", True))

        cid_order = []
        for hit in results:
            metadata = hit.metadata or {}
            cid = metadata.get(cid_field) or hit.chunk_id
            cid_str = str(cid).strip() if cid is not None else ""
            if cid_str and cid_str not in cid_order:
                cid_order.append(cid_str)

        case_rows = {}
        case_source = None
        chunk_source = None
        chunk_lookup_error = None
        chunk_rows_by_chunk_cid = {}
        chunk_rows_by_source_cid = {}
        if cid_order:
            dataset_ids_raw = payload.get("hf_dataset_ids")
            if isinstance(dataset_ids_raw, list):
                dataset_ids = [str(value).strip() for value in dataset_ids_raw if str(value).strip()]
            elif dataset_ids_raw is not None:
                dataset_ids = [str(dataset_ids_raw).strip()] if str(dataset_ids_raw).strip() else []
            else:
                dataset_ids = [
                    str(payload.get("hf_dataset_id", "justicedao/ipfs_caselaw_access_project")).strip()
                ]
            if not dataset_ids:
                dataset_ids = ["justicedao/ipfs_caselaw_access_project"]

            local_parquet = payload.get("local_case_parquet_file")
            con = duckdb.connect()

            def _execute_with_retries(query_text, params=None, retries=4):
                last_exc = None
                for attempt in range(retries):
                    try:
                        if params is None:
                            return con.execute(query_text)
                        return con.execute(query_text, params)
                    except Exception as exc:
                        last_exc = exc
                        message = str(exc)
                        if "HTTP 429" in message and attempt < retries - 1:
                            # Simple exponential backoff for transient HF rate limits.
                            time.sleep(1.5 * (2 ** attempt))
                            continue
                        raise
                if last_exc is not None:
                    raise last_exc

            last_exc = None
            case_sources: list[str] = []
            for dataset_index, dataset_id in enumerate(dataset_ids):
                parquet_files = _resolve_hf_parquet_files(
                    dataset_id=dataset_id,
                    explicit_file=payload.get("hf_parquet_file"),
                    explicit_files=payload.get("hf_parquet_files"),
                    parquet_prefix=payload.get("hf_parquet_prefix"),
                    preferred_names=payload.get("preferred_case_parquet_names"),
                    max_files=int(payload.get("max_case_parquet_files", 0)),
                    exclude_name_tokens=["embedding", "_cid_index", "_vector_index"],
                )

                for parquet_file in parquet_files:
                    hf_url = hf_hub_url(repo_id=dataset_id, repo_type="dataset", filename=parquet_file)
                    sources = [("hf", hf_url, f"{dataset_id}:{parquet_file}")]
                    if dataset_index == 0 and local_parquet and os.path.exists(local_parquet):
                        sources.append(("local", local_parquet, local_parquet))

                    for source_name, source_ref, source_label in sources:
                        try:
                            schema_rows = _execute_with_retries(
                                f"DESCRIBE SELECT * FROM read_parquet('{source_ref}')"
                            ).fetchall()
                            schema_cols = {row[0] for row in schema_rows}

                            selected_text_field = None
                            for candidate in text_candidates:
                                if candidate in schema_cols:
                                    selected_text_field = candidate
                                    break

                            optional_fields = [
                                "name",
                                "court",
                                "decision_date",
                                "jurisdiction",
                                "docket_number",
                                "citations",
                            ]
                            present_optionals = [f for f in optional_fields if f in schema_cols]

                            select_parts = [f"{cid_column} AS cid"]
                            for field in present_optionals:
                                select_parts.append(field)
                            if selected_text_field:
                                select_parts.append(
                                    f"substr({selected_text_field}, 1, {snippet_chars}) AS snippet"
                                )

                            missing_cids = [cid for cid in cid_order if cid not in case_rows]
                            if not missing_cids:
                                if source_name == "hf":
                                    case_sources.append(source_label)
                                else:
                                    case_sources.append(source_name)
                                break

                            placeholders = ", ".join(["?"] * len(missing_cids))
                            query = (
                                f"SELECT {', '.join(select_parts)} "
                                f"FROM read_parquet('{source_ref}') "
                                f"WHERE {cid_column} IN ({placeholders})"
                            )
                            rows = _execute_with_retries(query, missing_cids).fetchall()
                            col_names = [p.split(" AS ")[-1] for p in select_parts]
                            for row in rows:
                                row_obj = dict(zip(col_names, row))
                                cid_key = str(row_obj.get("cid"))
                                if cid_key not in case_rows:
                                    case_rows[cid_key] = row_obj

                            if source_name == "hf":
                                case_sources.append(source_label)
                            else:
                                case_sources.append(source_name)
                            break
                        except Exception as exc:
                            last_exc = exc
                            continue

                    if len(case_rows) >= len(cid_order):
                        break

                if len(case_rows) >= len(cid_order):
                    break

            if case_sources:
                case_source = sorted(set(case_sources))

            if not case_rows and last_exc is not None:
                raise last_exc

            if chunk_lookup_enabled:
                chunk_dataset_id = payload.get("chunk_hf_dataset_id", dataset_ids[0])
                chunk_parquet_file = payload.get("chunk_hf_parquet_file")
                if not chunk_parquet_file:
                    try:
                        chunk_parquet_file = _resolve_hf_parquet_files(
                            dataset_id=chunk_dataset_id,
                            explicit_file=None,
                            explicit_files=None,
                            parquet_prefix=payload.get("chunk_hf_parquet_prefix"),
                            preferred_names=payload.get("preferred_chunk_parquet_names"),
                            max_files=1,
                        )[0]
                    except Exception:
                        chunk_parquet_file = None

                local_chunk_parquet = payload.get("local_chunk_parquet_file")
                chunk_snippet_chars = int(payload.get("chunk_snippet_chars", 1000))

                chunk_sources = []
                if local_chunk_parquet and os.path.exists(local_chunk_parquet):
                    chunk_sources.append(("local", local_chunk_parquet))
                if chunk_parquet_file:
                    chunk_hf_url = hf_hub_url(
                        repo_id=chunk_dataset_id,
                        repo_type="dataset",
                        filename=chunk_parquet_file,
                    )
                    chunk_sources.append(("hf", chunk_hf_url))

                if not chunk_sources:
                    chunk_lookup_error = "No chunk parquet source available"
                    chunk_lookup_enabled = False

                last_chunk_exc = None
                for source_name, source_ref in chunk_sources:
                    try:
                        chunk_schema_rows = _execute_with_retries(
                            f"DESCRIBE SELECT * FROM read_parquet('{source_ref}')"
                        ).fetchall()
                        chunk_schema_cols = {row[0] for row in chunk_schema_rows}

                        where_clauses = []
                        if "items" in chunk_schema_cols:
                            where_clauses.append("items.cid")
                        if "source_file_cid" in chunk_schema_cols:
                            where_clauses.append("source_file_cid")

                        if not where_clauses:
                            continue

                        placeholders = ", ".join(["?"] * len(cid_order))
                        where_sql = " OR ".join(
                            [f"{field} IN ({placeholders})" for field in where_clauses]
                        )
                        query = (
                            "SELECT "
                            "source_file_cid, "
                            "source_filename, "
                            "items.cid AS chunk_cid, "
                            f"substr(items.content, 1, {chunk_snippet_chars}) AS chunk_snippet "
                            f"FROM read_parquet('{source_ref}') "
                            f"WHERE {where_sql}"
                        )

                        params = []
                        for _ in where_clauses:
                            params.extend(cid_order)

                        rows = _execute_with_retries(query, params).fetchall()
                        for row in rows:
                            source_file_cid, source_filename, chunk_cid, chunk_snippet = row
                            source_file_cid_str = (
                                str(source_file_cid).strip() if source_file_cid is not None else ""
                            )
                            chunk_cid_str = str(chunk_cid).strip() if chunk_cid is not None else ""
                            chunk_obj = {
                                "chunk_cid": chunk_cid_str,
                                "source_file_cid": source_file_cid_str,
                                "source_filename": source_filename,
                                "snippet": chunk_snippet,
                            }
                            if chunk_cid_str and chunk_cid_str not in chunk_rows_by_chunk_cid:
                                chunk_rows_by_chunk_cid[chunk_cid_str] = chunk_obj
                            if (
                                source_file_cid_str
                                and source_file_cid_str not in chunk_rows_by_source_cid
                            ):
                                chunk_rows_by_source_cid[source_file_cid_str] = chunk_obj

                        chunk_source = source_name
                        break
                    except Exception as exc:
                        last_chunk_exc = exc
                        continue
                if chunk_source is None and last_chunk_exc is not None:
                    chunk_lookup_error = str(last_chunk_exc)

        output = []
        for hit in results:
            metadata = hit.metadata or {}
            cid = metadata.get(cid_field) or hit.chunk_id
            cid_str = str(cid).strip() if cid is not None else ""
            hit_chunk_id = str(hit.chunk_id).strip() if hit.chunk_id is not None else ""
            file_chunk = None
            for candidate in (hit_chunk_id, cid_str):
                if candidate and candidate in chunk_rows_by_chunk_cid:
                    file_chunk = chunk_rows_by_chunk_cid[candidate]
                    break
            if file_chunk is None:
                for candidate in (cid_str, hit_chunk_id):
                    if candidate and candidate in chunk_rows_by_source_cid:
                        file_chunk = chunk_rows_by_source_cid[candidate]
                        break
            output.append(
                {
                    "chunk_id": hit.chunk_id,
                    "content": hit.content,
                    "score": hit.score,
                    "metadata": metadata,
                    "cid": cid_str,
                    "case": case_rows.get(cid_str),
                    "file_chunk": file_chunk,
                }
            )

        print(
            json.dumps(
                {
                    "status": "success",
                    "operation": op,
                    "results": output,
                    "case_source": case_source,
                    "chunk_source": chunk_source,
                    "chunk_lookup_error": chunk_lookup_error,
                }
            )
        )
        return

    if op == "list_files":
        result = cap.describe_dataset_files(model_hint=payload.get("model_hint"))
        print(json.dumps({"status": "success", "operation": op, "result": result}))
        return

    if op == "centroid_search":
        plan = await cap.search_with_centroid_routing(
            target_collection_name=payload["target_collection_name"],
            centroid_collection_name=payload["centroid_collection_name"],
            query_vector=payload["query_vector"],
            store_type=payload.get("store_type", "faiss"),
            centroid_top_k=int(payload.get("centroid_top_k", 5)),
            per_cluster_top_k=int(payload.get("per_cluster_top_k", 20)),
            final_top_k=int(payload.get("final_top_k", 10)),
            cluster_metadata_field=payload.get("cluster_metadata_field", "cluster_id"),
            cluster_cids_parquet_file=payload.get("cluster_cids_parquet_file"),
            cid_metadata_field=payload.get("cid_metadata_field", "cid"),
            cid_list_field=payload.get("cid_list_field", "cids"),
            cluster_id_field_in_cid_map=payload.get("cluster_id_field_in_cid_map", "cluster_id"),
            cid_candidate_multiplier=int(payload.get("cid_candidate_multiplier", 20)),
            base_filter_dict=payload.get("base_filter_dict"),
        )
        print(
            json.dumps(
                {
                    "status": "success",
                    "operation": op,
                    "plan": {
                        "centroid_collection_name": plan.centroid_collection_name,
                        "target_collection_name": plan.target_collection_name,
                        "selected_cluster_ids": plan.selected_cluster_ids,
                        "centroid_candidates": [
                            {
                                "chunk_id": r.chunk_id,
                                "score": r.score,
                                "metadata": r.metadata,
                                "content": r.content,
                            }
                            for r in plan.centroid_candidates
                        ],
                        "retrieved_results": [
                            {
                                "chunk_id": r.chunk_id,
                                "content": r.content,
                                "score": r.score,
                                "metadata": r.metadata,
                            }
                            for r in plan.retrieved_results
                        ],
                    },
                }
            )
        )
        return

    if op == "ingest_bundle":
        target = await cap.ingest_embeddings(
            collection_name=payload["target_collection_name"],
            store_type=payload.get("store_type", "faiss"),
            parquet_file=payload.get("target_parquet_file"),
            model_hint=payload.get("target_model_hint"),
            max_rows=int(payload.get("target_max_rows", 10000)),
            batch_size=int(payload.get("batch_size", 512)),
            distance_metric=payload.get("distance_metric", "cosine"),
        )

        centroid = await cap.ingest_embeddings(
            collection_name=payload["centroid_collection_name"],
            store_type=payload.get("store_type", "faiss"),
            parquet_file=payload.get("centroid_parquet_file"),
            model_hint=payload.get("centroid_model_hint") or payload.get("target_model_hint"),
            max_rows=int(payload.get("centroid_max_rows", 0)),
            batch_size=int(payload.get("batch_size", 512)),
            distance_metric=payload.get("distance_metric", "cosine"),
        )

        print(
            json.dumps(
                {
                    "status": "success",
                    "operation": op,
                    "result": {
                        "target": {
                            "collection_name": target.collection_name,
                            "store_type": target.store_type,
                            "source_file": target.source_file,
                            "ingested_count": target.ingested_count,
                            "vector_dimension": target.vector_dimension,
                        },
                        "centroid": {
                            "collection_name": centroid.collection_name,
                            "store_type": centroid.store_type,
                            "source_file": centroid.source_file,
                            "ingested_count": centroid.ingested_count,
                            "vector_dimension": centroid.vector_dimension,
                        },
                    },
                }
            )
        )
        return

    raise ValueError(f"Unsupported CAP vector operation: {op}")


asyncio.run(_main())
'''

    completed = subprocess.run(
        [str(python_path), "-c", script],
        cwd=str(root),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        return {
            "status": "error",
            "operation": operation,
            "error": "CAP vector subprocess failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    stdout = completed.stdout.strip()
    if not stdout:
        return {"status": "error", "error": "No output from CAP vector operation"}

    # Some imports in this repository emit warnings to stdout. Parse the last JSON line.
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    return {
        "status": "error",
        "error": "Could not parse JSON output from CAP vector operation",
        "raw_stdout": stdout,
    }


def _search_federal_register_hf_index_sync(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Search HF-hosted Federal Register FAISS + metadata directly by query text."""
    import faiss
    import numpy as np
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download
    from sentence_transformers import SentenceTransformer

    dataset_id = str(payload.get("hf_dataset_id") or DEFAULT_FEDERAL_REGISTER_HF_DATASET_ID)
    index_file = str(payload.get("hf_index_file") or "federal_register_gte_small.faiss")
    metadata_file = str(
        payload.get("hf_metadata_file") or "federal_register_gte_small_metadata.parquet"
    )
    model_name = str(payload.get("model_name") or "thenlper/gte-small")
    query_text = str(payload.get("query_text") or "").strip()
    if not query_text:
        raise ValueError("query_text is required")

    top_k = int(payload.get("top_k", 10))
    snippet_chars = int(payload.get("snippet_chars", 320))
    cache_dir = payload.get("hf_cache_dir")

    local_index = hf_hub_download(
        repo_id=dataset_id,
        repo_type="dataset",
        filename=index_file,
        cache_dir=cache_dir,
    )
    local_meta = hf_hub_download(
        repo_id=dataset_id,
        repo_type="dataset",
        filename=metadata_file,
        cache_dir=cache_dir,
    )

    index = faiss.read_index(local_index)
    model = SentenceTransformer(model_name)
    query_vec = model.encode(
        [query_text],
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    distances, neighbors = index.search(query_vec, top_k)
    vector_ids = [int(v) for v in neighbors[0].tolist() if int(v) >= 0]

    metadata_table = pq.read_table(
        local_meta,
        columns=[
            "vector_id",
            "cid",
            "identifier",
            "name",
            "agency",
            "legislation_type",
            "date_published",
            "semantic_text",
        ],
    )
    metadata_rows = metadata_table.to_pylist()
    metadata_by_vid = {
        int(row.get("vector_id")): row
        for row in metadata_rows
        if row.get("vector_id") is not None
    }

    hits: List[Dict[str, Any]] = []
    for rank, vid in enumerate(vector_ids, start=1):
        row = metadata_by_vid.get(vid, {})
        semantic_text = str(row.get("semantic_text") or "")
        hits.append(
            {
                "rank": rank,
                "vector_id": vid,
                "score": float(distances[0][rank - 1]),
                "cid": str(row.get("cid") or ""),
                "identifier": str(row.get("identifier") or ""),
                "name": str(row.get("name") or ""),
                "agency": str(row.get("agency") or ""),
                "legislation_type": str(row.get("legislation_type") or ""),
                "date_published": str(row.get("date_published") or ""),
                "snippet": semantic_text[:snippet_chars],
            }
        )

    return {
        "status": "success",
        "operation": "search_federal_register_hf_index",
        "dataset_id": dataset_id,
        "index_file": index_file,
        "metadata_file": metadata_file,
        "model_name": model_name,
        "query_text": query_text,
        "top_k": top_k,
        "count": len(hits),
        "hits": hits,
    }


async def scrape_recap_archive_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .recap_archive_scraper import scrape_recap_archive

        return await scrape_recap_archive(
            courts=parameters.get("courts"),
            document_types=parameters.get("document_types"),
            filed_after=parameters.get("filed_after"),
            filed_before=parameters.get("filed_before"),
            case_name_pattern=parameters.get("case_name_pattern"),
            output_format="json",
            include_text=parameters.get("include_text", True),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 1.0),
            max_documents=parameters.get("max_documents"),
            job_id=parameters.get("job_id"),
            resume=parameters.get("resume", False),
        )

    except Exception as e:
        logger.error("RECAP Archive scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def search_recap_documents_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .recap_archive_scraper import search_recap_documents

        return await search_recap_documents(
            query=parameters.get("query"),
            court=parameters.get("court"),
            case_name=parameters.get("case_name"),
            filed_after=parameters.get("filed_after"),
            filed_before=parameters.get("filed_before"),
            document_type=parameters.get("document_type"),
            limit=parameters.get("limit", 100),
        )

    except Exception as e:
        logger.error("RECAP Archive search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "documents": [],
            "count": 0,
        }


async def scrape_state_laws_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .state_laws_scraper import scrape_state_laws

        result = await scrape_state_laws(
            states=parameters.get("states"),
            legal_areas=parameters.get("legal_areas"),
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 2.0),
            max_statutes=parameters.get("max_statutes"),
            output_dir=parameters.get("output_dir"),
            write_jsonld=parameters.get("write_jsonld", True),
            strict_full_text=parameters.get("strict_full_text", False),
            min_full_text_chars=parameters.get("min_full_text_chars", 300),
            hydrate_statute_text=parameters.get("hydrate_statute_text", True),
            parallel_workers=parameters.get("parallel_workers", 6),
            per_state_retry_attempts=parameters.get("per_state_retry_attempts", 1),
            retry_zero_statute_states=parameters.get("retry_zero_statute_states", True),
        )

        # For forward compatibility with resumable orchestration, include job_id when provided.
        job_id = parameters.get("job_id")
        if job_id:
            result["job_id"] = job_id

        return result

    except Exception as e:
        logger.error("State laws scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def scrape_state_admin_rules_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .state_admin_rules_scraper import scrape_state_admin_rules

        result = await scrape_state_admin_rules(
            states=parameters.get("states"),
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 2.0),
            max_rules=parameters.get("max_rules"),
            max_base_statutes=parameters.get("max_base_statutes"),
            output_dir=parameters.get("output_dir"),
            write_jsonld=parameters.get("write_jsonld", True),
            strict_full_text=parameters.get("strict_full_text", False),
            min_full_text_chars=parameters.get("min_full_text_chars", 300),
            hydrate_rule_text=parameters.get("hydrate_rule_text", True),
            parallel_workers=parameters.get("parallel_workers", 6),
            per_state_retry_attempts=parameters.get("per_state_retry_attempts", 1),
            retry_zero_rule_states=parameters.get("retry_zero_rule_states", True),
            per_state_timeout_seconds=parameters.get("per_state_timeout_seconds", 86400.0),
            include_dc=parameters.get("include_dc", False),
            agentic_fallback_enabled=parameters.get("agentic_fallback_enabled", True),
            agentic_max_candidates_per_state=parameters.get("agentic_max_candidates_per_state", 1000),
            agentic_max_fetch_per_state=parameters.get("agentic_max_fetch_per_state", 1000),
            agentic_max_results_per_domain=parameters.get("agentic_max_results_per_domain", 1000),
            agentic_max_hops=parameters.get("agentic_max_hops", 4),
            agentic_max_pages=parameters.get("agentic_max_pages", 1000),
            agentic_fetch_concurrency=parameters.get("agentic_fetch_concurrency", 6),
            write_agentic_kg_corpus=parameters.get("write_agentic_kg_corpus", True),
            require_substantive_rule_text=parameters.get("require_substantive_rule_text", True),
        )

        job_id = parameters.get("job_id")
        if job_id:
            result["job_id"] = job_id

        return result

    except Exception as e:
        logger.error("State administrative-rules scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def list_scraping_jobs_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .scraping_state import list_scraping_jobs

        jobs = await anyio.to_thread.run_sync(list_scraping_jobs)

        status_filter = parameters.get("status_filter", "all")
        job_type = parameters.get("job_type", "all")

        filtered_jobs = jobs
        if status_filter != "all":
            filtered_jobs = [j for j in filtered_jobs if j.get("status") == status_filter]

        if job_type != "all":
            filtered_jobs = [
                j for j in filtered_jobs if str(j.get("job_id", "")).startswith(job_type)
            ]

        return {
            "status": "success",
            "jobs": filtered_jobs,
            "total_count": len(filtered_jobs),
            "filters": {"status": status_filter, "job_type": job_type},
        }

    except Exception as e:
        logger.error("Failed to list scraping jobs: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "jobs": [],
        }


async def scrape_us_code_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .federal_scrapers.us_code_scraper import scrape_us_code

        titles = parameters.get("titles")
        if titles is None and parameters.get("title"):
            titles = [str(parameters.get("title"))]

        return await scrape_us_code(
            titles=titles,
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 1.0),
            max_sections=parameters.get("max_sections"),
            year=parameters.get("year"),
            cache_dir=parameters.get("cache_dir"),
            force_download=parameters.get("force_download", False),
            output_dir=parameters.get("output_dir"),
            keep_zip_cache=parameters.get("keep_zip_cache", False),
        )

    except Exception as e:
        logger.error("US Code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def scrape_federal_laws_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .federal_scrapers.federal_law_scraper import scrape_federal_laws

        return await scrape_federal_laws(
            rulesets=parameters.get("rulesets"),
            include_local_rules=parameters.get("include_local_rules", True),
            output_format=parameters.get("output_format", "json"),
            output_dir=parameters.get("output_dir"),
            rate_limit_delay=parameters.get("rate_limit_delay", 0.4),
            max_rules_per_ruleset=parameters.get("max_rules_per_ruleset"),
            custom_sources=parameters.get("custom_sources"),
        )

    except Exception as e:
        logger.error("Federal laws scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def scrape_netherlands_laws_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .netherlands_laws_scraper import scrape_netherlands_laws

        return await scrape_netherlands_laws(
            document_urls=parameters.get("document_urls"),
            seed_urls=parameters.get("seed_urls"),
            output_format=parameters.get("output_format", "json"),
            output_dir=parameters.get("output_dir"),
            rate_limit_delay=parameters.get("rate_limit_delay", 0.4),
            max_documents=parameters.get("max_documents"),
            include_metadata=parameters.get("include_metadata", True),
            custom_sources=parameters.get("custom_sources"),
            max_seed_pages=parameters.get("max_seed_pages", 25),
            crawl_depth=parameters.get("crawl_depth", 2),
            use_default_seeds=parameters.get("use_default_seeds", False),
            skip_existing=parameters.get("skip_existing", False),
            resume=parameters.get("resume", False),
        )

    except Exception as e:
        logger.error("Netherlands laws scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def scrape_municipal_codes_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .municipal_codes_api import initialize_municipal_codes_job

        return initialize_municipal_codes_job(parameters, tool_version=tool_version)

    except Exception as e:
        logger.error("Municipal code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def setup_legal_tools_venv_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Create/update project venv and install legal vector dependencies."""
    try:
        venv_dir = parameters.get("venv_dir", ".venv")
        packages: List[str] = parameters.get(
            "packages",
            [
                "datasets",
                "huggingface_hub",
                "pyarrow",
                "numpy",
                "faiss-cpu",
                "anyio",
            ],
        )
        setup_info = await anyio.to_thread.run_sync(
            lambda: _ensure_venv(
                venv_dir=venv_dir,
                packages=packages,
                upgrade_pip=bool(parameters.get("upgrade_pip", True)),
            )
        )
        return {
            "status": "success",
            "tool_version": tool_version,
            "venv": setup_info,
        }
    except Exception as e:
        logger.error("Legal tools venv setup failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "tool_version": tool_version,
        }


async def ingest_caselaw_access_vectors_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Ingest CAP embeddings into configured vector store.

    By default this operation bootstraps and executes in ``.venv``.
    """
    try:
        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "ingest",
            "collection_name": parameters["collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "parquet_file": parameters.get("parquet_file"),
            "hf_dataset_id": parameters.get("hf_dataset_id"),
            "hf_cache_dir": parameters.get("hf_cache_dir"),
            "model_hint": parameters.get("model_hint"),
            "max_rows": int(parameters.get("max_rows", 10000)),
            "batch_size": int(parameters.get("batch_size", 512)),
            "distance_metric": parameters.get("distance_metric", "cosine"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="ingest",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP vector ingestion failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "ingest",
            "tool_version": tool_version,
        }


async def search_caselaw_access_vectors_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search CAP vectors by precomputed query vector using the project venv."""
    try:
        if "query_vector" not in parameters:
            return {
                "status": "error",
                "error": "query_vector is required",
                "operation": "search",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "search",
            "collection_name": parameters["collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "hf_dataset_id": parameters.get("hf_dataset_id"),
            "hf_cache_dir": parameters.get("hf_cache_dir"),
            "query_vector": parameters["query_vector"],
            "top_k": int(parameters.get("top_k", 10)),
            "filter_dict": parameters.get("filter_dict"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="search",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP vector search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "search",
            "tool_version": tool_version,
        }


async def search_caselaw_access_cases_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search CAP vectors and enrich matches with caselaw fields by CID from HF parquet."""
    try:
        if "query_vector" not in parameters:
            return {
                "status": "error",
                "error": "query_vector is required",
                "operation": "search_cases",
                "tool_version": tool_version,
            }
        if not parameters.get("collection_name"):
            return {
                "status": "error",
                "error": "collection_name is required",
                "operation": "search_cases",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        [
                            "datasets",
                            "huggingface_hub",
                            "pyarrow",
                            "numpy",
                            "faiss-cpu",
                            "duckdb",
                            "anyio",
                        ],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "search_cases",
            "collection_name": parameters["collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "query_vector": parameters["query_vector"],
            "top_k": int(parameters.get("top_k", 10)),
            "filter_dict": parameters.get("filter_dict"),
            "hf_dataset_id": parameters.get("hf_dataset_id", DEFAULT_CAP_HF_DATASET_ID),
            "hf_dataset_ids": parameters.get("hf_dataset_ids"),
            "hf_parquet_file": parameters.get("hf_parquet_file", DEFAULT_CAP_HF_PARQUET_FILE),
            "hf_parquet_prefix": parameters.get("hf_parquet_prefix"),
            "cid_metadata_field": parameters.get("cid_metadata_field", "cid"),
            "cid_column": parameters.get("cid_column", "cid"),
            "text_field_candidates": parameters.get("text_field_candidates", ["head_matter", "text"]),
            "snippet_chars": int(parameters.get("snippet_chars", 320)),
            "local_case_parquet_file": parameters.get("local_case_parquet_file"),
            "chunk_lookup_enabled": bool(parameters.get("chunk_lookup_enabled", True)),
            "chunk_hf_dataset_id": parameters.get(
                "chunk_hf_dataset_id",
                parameters.get("hf_dataset_id", DEFAULT_CAP_HF_DATASET_ID),
            ),
            "chunk_hf_parquet_file": parameters.get(
                "chunk_hf_parquet_file",
                DEFAULT_CAP_CHUNK_HF_PARQUET_FILE,
            ),
            "chunk_hf_parquet_prefix": parameters.get("chunk_hf_parquet_prefix"),
            "local_chunk_parquet_file": parameters.get("local_chunk_parquet_file"),
            "chunk_snippet_chars": int(parameters.get("chunk_snippet_chars", 1000)),
            "preferred_case_parquet_names": parameters.get("preferred_case_parquet_names"),
            "hf_parquet_files": parameters.get("hf_parquet_files"),
            "max_case_parquet_files": int(parameters.get("max_case_parquet_files", 0)),
            "preferred_chunk_parquet_names": parameters.get("preferred_chunk_parquet_names"),
            "prefer_current_versions": parameters.get("prefer_current_versions"),
            "include_historical_versions": parameters.get("include_historical_versions"),
            "as_of_date": parameters.get("as_of_date"),
            "effective_date": parameters.get("effective_date"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="search_cases",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP caselaw-enriched vector search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "search_cases",
            "tool_version": tool_version,
        }


async def search_us_code_corpus_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search US Code corpus vectors and enrich matches with section metadata/snippets."""
    uscode_params = dict(parameters)

    uscode_params.setdefault("hf_dataset_id", DEFAULT_USCODE_HF_DATASET_ID)
    uscode_params.setdefault("hf_parquet_prefix", DEFAULT_USCODE_HF_PARQUET_PREFIX)
    uscode_params.setdefault("hf_parquet_file", None)
    uscode_params.setdefault("cid_metadata_field", "cid")
    uscode_params.setdefault("cid_column", "cid")
    uscode_params.setdefault(
        "text_field_candidates",
        ["text", "section_text", "content", "heading", "title"],
    )
    uscode_params.setdefault("chunk_lookup_enabled", False)
    uscode_params.setdefault("chunk_hf_parquet_file", None)
    uscode_params.setdefault("chunk_hf_parquet_prefix", None)
    uscode_params.setdefault("preferred_case_parquet_names", ["uscode", "sections", "title"])

    return await search_caselaw_access_cases_from_parameters(
        uscode_params,
        tool_version=tool_version,
    )


async def search_state_law_corpus_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search a state-law corpus vectors with optional statute metadata enrichment.

    Defaults are oriented to the canonical multi-state CID-keyed corpora. By default this includes both:
    - `justicedao/ipfs_state_laws` (legislative + judicial sources)
    - `justicedao/ipfs_state_admin_rules` (executive admin rules)
    """
    state_params = dict(parameters)
    state_laws_corpus = get_canonical_legal_corpus("state_laws")
    state_admin_corpus = get_canonical_legal_corpus("state_admin_rules")
    try:
        state_code = _normalize_state_code(state_params.get("state", "OR"))
    except ValueError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "operation": "search_cases",
            "tool_version": tool_version,
        }

    state_params.setdefault("hf_dataset_id", state_laws_corpus.hf_dataset_id)
    state_params.setdefault(
        "hf_dataset_ids",
        [state_laws_corpus.hf_dataset_id, state_admin_corpus.hf_dataset_id],
    )
    state_params.setdefault("hf_parquet_prefix", None)
    state_params.setdefault("hf_parquet_file", None)
    state_params.setdefault("cid_metadata_field", state_laws_corpus.cid_field)
    state_params.setdefault("cid_column", state_laws_corpus.cid_field)
    state_params.setdefault(
        "text_field_candidates",
        ["text", "content", "section_text", "body", "title", "heading", "semantic_text", "jsonld"],
    )
    state_params.setdefault("chunk_lookup_enabled", False)
    state_params.setdefault("chunk_hf_parquet_file", None)
    state_params.setdefault("chunk_hf_parquet_prefix", None)
    enrich_with_cases = bool(state_params.get("enrich_with_cases", False))

    if enrich_with_cases:
        state_params.setdefault(
            "preferred_case_parquet_names",
            list(
                dict.fromkeys(
                    [
                        state_laws_corpus.state_parquet_filename(state_code),
                        state_admin_corpus.state_parquet_filename(state_code),
                        state_laws_corpus.combined_parquet_filename,
                        state_admin_corpus.combined_parquet_filename,
                        "oregon_laws_by_cid.parquet",
                        "oregon_administrative_rules.parquet",
                        "oregon_laws_cid_index.parquet",
                        "oregon_administrative_rules_key_cid_index.parquet",
                        state_code.lower(),
                    ]
                )
            ),
        )
        state_params.setdefault("max_case_parquet_files", 4)
        result = await search_caselaw_access_cases_from_parameters(
            state_params,
            tool_version=tool_version,
        )
    else:
        result = await search_caselaw_access_vectors_from_parameters(
            state_params,
            tool_version=tool_version,
        )

    if isinstance(result, dict):
        result.setdefault("state", state_code)
    return result


async def search_federal_register_corpus_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search Federal Register vector corpus and enrich matches with metadata/snippets.

    Defaults target the published Federal Register dataset:
    `justicedao/ipfs_federal_register`.
    """
    fr_params = dict(parameters)
    federal_register_corpus = get_canonical_legal_corpus("federal_register")

    fr_params.setdefault("hf_dataset_id", federal_register_corpus.hf_dataset_id)
    fr_params.setdefault("hf_parquet_file", federal_register_corpus.combined_parquet_filename)
    fr_params.setdefault("hf_parquet_prefix", None)
    fr_params.setdefault("cid_metadata_field", federal_register_corpus.cid_field)
    fr_params.setdefault("cid_column", federal_register_corpus.cid_field)
    fr_params.setdefault(
        "text_field_candidates",
        [
            "title",
            "name",
            "text",
            "agency_name",
            "document_type",
            "publication_date",
            "description",
            "summary",
            "abstract",
            "agency",
            "legislation_type",
            "raw_json",
            "jsonld",
        ],
    )
    fr_params.setdefault("chunk_lookup_enabled", False)
    fr_params.setdefault("chunk_hf_parquet_file", None)
    fr_params.setdefault("chunk_hf_parquet_prefix", None)
    fr_params.setdefault(
        "preferred_case_parquet_names",
        [
            federal_register_corpus.combined_parquet_filename,
            "federal_register.parquet",
            "federal_register",
            "laws",
        ],
    )

    return await search_caselaw_access_cases_from_parameters(
        fr_params,
        tool_version=tool_version,
    )


async def search_netherlands_law_corpus_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search Netherlands law corpus vectors and enrich matches with law metadata/snippets."""
    nl_params = dict(parameters)
    netherlands_corpus = get_canonical_legal_corpus("netherlands_laws")

    nl_params.setdefault("hf_dataset_id", netherlands_corpus.hf_dataset_id)
    nl_params.setdefault("hf_parquet_file", netherlands_corpus.combined_parquet_filename)
    nl_params.setdefault("hf_parquet_prefix", None)
    nl_params.setdefault("cid_metadata_field", netherlands_corpus.cid_field)
    nl_params.setdefault("cid_column", netherlands_corpus.cid_field)
    nl_params.setdefault(
        "text_field_candidates",
        [
            "citation",
            "document_citation",
            "canonical_title",
            "title",
            "aliases",
            "hierarchy_path_text",
            "hierarchy_labels",
            "text",
            "document_type",
            "citations",
            "headings",
            "jsonld",
        ],
    )
    nl_params.setdefault("chunk_lookup_enabled", False)
    nl_params.setdefault("chunk_hf_parquet_file", None)
    nl_params.setdefault("chunk_hf_parquet_prefix", None)
    nl_params.setdefault("prefer_current_versions", True)
    nl_params.setdefault("include_historical_versions", True)
    nl_params.setdefault("citation_query", str(nl_params.get("query_text") or ""))
    nl_params.setdefault("context_mode", "exact")
    nl_params.setdefault(
        "preferred_case_parquet_names",
        [
            netherlands_corpus.combined_parquet_filename,
            "netherlands_laws.parquet",
            "nl_laws.parquet",
            "wetten_overheid.parquet",
        ],
    )

    result = await search_caselaw_access_cases_from_parameters(
        nl_params,
        tool_version=tool_version,
    )
    if isinstance(result, dict):
        if isinstance(result.get("results"), list):
            temporally_filtered_results = _apply_netherlands_temporal_filters(
                list(result.get("results") or []),
                prefer_current_versions=bool(nl_params.get("prefer_current_versions", True)),
                include_historical_versions=bool(nl_params.get("include_historical_versions", True)),
                as_of_date=str(nl_params.get("as_of_date") or ""),
                effective_date=str(nl_params.get("effective_date") or ""),
            )
            result["results"] = _apply_netherlands_citation_query(
                list(temporally_filtered_results),
                citation_query=str(nl_params.get("citation_query") or ""),
                prefer_current_versions=bool(nl_params.get("prefer_current_versions", True)),
            )
            result["answers"] = _assemble_netherlands_answers(
                list(result.get("results") or []),
                citation_query=str(nl_params.get("citation_query") or ""),
                prefer_current_versions=bool(nl_params.get("prefer_current_versions", True)),
                context_mode=str(nl_params.get("context_mode") or "exact"),
                context_results=list(temporally_filtered_results),
            )
        result.setdefault(
            "temporal_parameters",
            {
                "prefer_current_versions": bool(nl_params.get("prefer_current_versions", True)),
                "include_historical_versions": bool(nl_params.get("include_historical_versions", True)),
                "as_of_date": str(nl_params.get("as_of_date") or ""),
                "effective_date": str(nl_params.get("effective_date") or ""),
            },
        )
        result.setdefault("citation_query", str(nl_params.get("citation_query") or ""))
        result.setdefault("context_mode", str(nl_params.get("context_mode") or "exact"))
        result.setdefault("jurisdiction", "NL")
    return result


async def search_court_rules_corpus_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search court-rules corpus vectors with federal/state jurisdiction filtering.

    Defaults target: `justicedao/ipfs_court_rules`.
    Supported jurisdiction values:
    - `federal`: federal court rules
    - `state`: state court rules (optionally narrowed by `state`)
    - `both`: search both federal + state court rules
    """
    court_params = dict(parameters)
    state_court_corpus = get_canonical_legal_corpus("state_court_rules")

    jurisdiction = str(court_params.get("jurisdiction", "both")).strip().lower()
    if jurisdiction not in {"federal", "state", "both"}:
        return {
            "status": "error",
            "error": "jurisdiction must be one of: federal, state, both",
            "operation": "search_cases",
            "tool_version": tool_version,
        }

    state_code = None
    if jurisdiction == "state":
        try:
            state_code = _normalize_state_code(court_params.get("state", "OR"))
        except ValueError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "operation": "search_cases",
                "tool_version": tool_version,
            }

    court_params.setdefault("hf_dataset_id", state_court_corpus.hf_dataset_id)
    court_params.setdefault("hf_dataset_ids", [state_court_corpus.hf_dataset_id])

    if "hf_parquet_prefix" not in court_params:
        court_params["hf_parquet_prefix"] = None

    court_params.setdefault("hf_parquet_file", None)
    if jurisdiction == "state":
        court_params.setdefault("cid_metadata_field", state_court_corpus.cid_field)
        court_params.setdefault("cid_column", state_court_corpus.cid_field)
    else:
        court_params.setdefault("cid_metadata_field", "cid")
        court_params.setdefault("cid_column", "cid")
    court_params.setdefault(
        "text_field_candidates",
        ["text", "content", "section_text", "body", "title", "heading", "semantic_text", "jsonld"],
    )
    court_params.setdefault("chunk_lookup_enabled", False)
    court_params.setdefault("chunk_hf_parquet_file", None)
    court_params.setdefault("chunk_hf_parquet_prefix", None)

    if "preferred_case_parquet_names" not in court_params:
        common_terms = ["court_rules", "rules_of_civil_procedure", "rules_of_criminal_procedure"]
        if jurisdiction == "federal":
            preferred = [
                "FEDERAL-RULES.parquet",
                "federal_rules",
                "federal_court_rules",
                "local_court_rules",
                "federal",
                *common_terms,
            ]
        elif jurisdiction == "state":
            preferred = [
                state_court_corpus.state_parquet_filename(state_code or ""),
                state_court_corpus.combined_parquet_filename,
                "state_court_rules",
                "state_rules",
                "local_court_rules",
                "state",
                state_code.lower() if state_code else "",
                *common_terms,
            ]
        else:
            preferred = [
                state_court_corpus.combined_parquet_filename,
                "federal_rules",
                "state_court_rules",
                "state_rules",
                "local_court_rules",
                "federal",
                "state",
                *common_terms,
            ]
        court_params["preferred_case_parquet_names"] = [term for term in preferred if term]

    court_params.setdefault("max_case_parquet_files", 24)
    enrich_with_cases = bool(court_params.get("enrich_with_cases", jurisdiction == "state"))

    if enrich_with_cases:
        result = await search_caselaw_access_cases_from_parameters(
            court_params,
            tool_version=tool_version,
        )
    else:
        result = await search_caselaw_access_vectors_from_parameters(
            court_params,
            tool_version=tool_version,
        )

    if isinstance(result, dict):
        result.setdefault("jurisdiction", jurisdiction)
        if state_code is not None:
            result.setdefault("state", state_code)
    return result


async def recover_missing_legal_citation_source_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search, archive, and optionally publish candidate sources for an unresolved legal citation."""
    from .legal_source_recovery import recover_missing_legal_citation_source

    citation_text = str(parameters.get("citation_text") or "").strip()
    normalized_citation = str(parameters.get("normalized_citation") or citation_text).strip()
    if not citation_text:
        return {
            "status": "error",
            "error": "citation_text is required",
            "operation": "recover_missing_legal_citation_source",
            "tool_version": tool_version,
        }

    corpus_key = str(parameters.get("corpus_key") or "").strip() or None
    state_code_raw = str(parameters.get("state_code") or parameters.get("state") or "").strip()
    state_code = None
    if state_code_raw:
        try:
            state_code = _normalize_state_code(state_code_raw)
        except ValueError as exc:
            return {
                "status": "error",
                "error": str(exc),
                "operation": "recover_missing_legal_citation_source",
                "tool_version": tool_version,
            }

    metadata = dict(parameters.get("metadata") or {})
    candidate_corpora = [
        str(item).strip()
        for item in list(parameters.get("candidate_corpora") or metadata.get("candidate_corpora") or [])
        if str(item).strip()
    ]
    if candidate_corpora:
        metadata["candidate_corpora"] = candidate_corpora

    result = await recover_missing_legal_citation_source(
        citation_text=citation_text,
        normalized_citation=normalized_citation or None,
        corpus_key=corpus_key,
        state_code=state_code,
        metadata=metadata,
        max_candidates=int(parameters.get("max_candidates", 8)),
        archive_top_k=int(parameters.get("archive_top_k", 3)),
        publish_to_hf=bool(parameters.get("publish_to_hf", False)),
        hf_token=str(parameters.get("hf_token") or "") or None,
    )
    result["status"] = str(result.get("status") or "tracked")
    result["operation"] = "recover_missing_legal_citation_source"
    result["tool_version"] = tool_version
    return result


async def promote_recovery_manifest_to_canonical_bundle_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from .legal_source_recovery_promotion import promote_recovery_manifest_to_canonical_bundle

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "promote_recovery_manifest_to_canonical_bundle",
            "tool_version": tool_version,
        }

    output_dir = str(parameters.get("output_dir") or "").strip() or None
    result = await anyio.to_thread.run_sync(
        lambda: promote_recovery_manifest_to_canonical_bundle(
            manifest_path,
            output_dir=output_dir,
            write_parquet=bool(parameters.get("write_parquet", True)),
        )
    )
    result["status"] = str(result.get("status") or "success")
    result["operation"] = "promote_recovery_manifest_to_canonical_bundle"
    result["tool_version"] = tool_version
    return result


async def preview_recovery_manifest_release_plan_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from .legal_source_recovery_promotion import build_recovery_manifest_release_plan

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "preview_recovery_manifest_release_plan",
            "tool_version": tool_version,
        }

    output_dir = str(parameters.get("output_dir") or "").strip() or None
    workspace_root = str(parameters.get("workspace_root") or "").strip() or None
    python_bin = str(parameters.get("python_bin") or "python3").strip() or "python3"
    result = await anyio.to_thread.run_sync(
        lambda: build_recovery_manifest_release_plan(
            manifest_path,
            output_dir=output_dir,
            workspace_root=workspace_root,
            python_bin=python_bin,
        )
    )
    result["operation"] = "preview_recovery_manifest_release_plan"
    result["tool_version"] = tool_version
    return result


async def merge_recovery_manifest_into_canonical_dataset_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from .legal_source_recovery_promotion import merge_recovery_manifest_into_canonical_dataset

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "merge_recovery_manifest_into_canonical_dataset",
            "tool_version": tool_version,
        }

    output_dir = str(parameters.get("output_dir") or "").strip() or None
    target_local_parquet_path = str(parameters.get("target_local_parquet_path") or "").strip() or None
    hf_cache_dir = str(parameters.get("hf_cache_dir") or "").strip() or None
    result = await anyio.to_thread.run_sync(
        lambda: merge_recovery_manifest_into_canonical_dataset(
            manifest_path,
            output_dir=output_dir,
            target_local_parquet_path=target_local_parquet_path,
            write_promotion_parquet=bool(parameters.get("write_promotion_parquet", True)),
            hydrate_from_hf=bool(parameters.get("hydrate_from_hf", False)),
            hf_token=str(parameters.get("hf_token") or "") or None,
            hf_revision=str(parameters.get("hf_revision") or "") or None,
            hf_cache_dir=hf_cache_dir,
            force_hf_download=bool(parameters.get("force_hf_download", False)),
            publish_merged_to_hf=bool(parameters.get("publish_merged_to_hf", False)),
            hf_commit_message=str(parameters.get("hf_commit_message") or "") or None,
        )
    )
    result["status"] = str(result.get("status") or "success")
    result["operation"] = "merge_recovery_manifest_into_canonical_dataset"
    result["tool_version"] = tool_version
    return result


async def collect_packaged_docket_citation_recovery_candidates_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from ipfs_datasets_py.processors.legal_data.docket_dataset import (
        collect_packaged_docket_citation_recovery_candidates,
    )

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "collect_packaged_docket_citation_recovery_candidates",
            "tool_version": tool_version,
        }

    result = await anyio.to_thread.run_sync(
        lambda: collect_packaged_docket_citation_recovery_candidates(manifest_path)
    )
    result["status"] = "success"
    result["operation"] = "collect_packaged_docket_citation_recovery_candidates"
    result["tool_version"] = tool_version
    return result


async def recover_packaged_docket_missing_authorities_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from ipfs_datasets_py.processors.legal_data.docket_dataset import (
        recover_packaged_docket_missing_authorities,
    )

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "recover_packaged_docket_missing_authorities",
            "tool_version": tool_version,
        }

    result = await recover_packaged_docket_missing_authorities(
        manifest_path,
        publish_to_hf=bool(parameters.get("publish_to_hf", False)),
        hf_token=str(parameters.get("hf_token") or "") or None,
        max_candidates=int(parameters.get("max_candidates", 8)),
        archive_top_k=int(parameters.get("archive_top_k", 3)),
    )
    result["status"] = "success"
    result["operation"] = "recover_packaged_docket_missing_authorities"
    result["tool_version"] = tool_version
    return result


async def plan_packaged_docket_missing_authority_follow_up_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from ipfs_datasets_py.processors.legal_data.docket_dataset import (
        plan_packaged_docket_missing_authority_follow_up,
    )

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "plan_packaged_docket_missing_authority_follow_up",
            "tool_version": tool_version,
        }

    result = await plan_packaged_docket_missing_authority_follow_up(
        manifest_path,
        publish_to_hf=bool(parameters.get("publish_to_hf", False)),
        hf_token=str(parameters.get("hf_token") or "") or None,
        max_candidates=int(parameters.get("max_candidates", 8)),
        archive_top_k=int(parameters.get("archive_top_k", 3)),
    )
    result["status"] = "success"
    result["operation"] = "plan_packaged_docket_missing_authority_follow_up"
    result["tool_version"] = tool_version
    return result


async def execute_packaged_docket_missing_authority_follow_up_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    from ipfs_datasets_py.processors.legal_data.docket_dataset import (
        execute_packaged_docket_missing_authority_follow_up,
    )

    manifest_path = str(parameters.get("manifest_path") or "").strip()
    if not manifest_path:
        return {
            "status": "error",
            "error": "manifest_path is required",
            "operation": "execute_packaged_docket_missing_authority_follow_up",
            "tool_version": tool_version,
        }

    result = await execute_packaged_docket_missing_authority_follow_up(
        manifest_path,
        publish_to_hf=bool(parameters.get("publish_to_hf", False)),
        hf_token=str(parameters.get("hf_token") or "") or None,
        max_candidates=int(parameters.get("max_candidates", 8)),
        archive_top_k=int(parameters.get("archive_top_k", 3)),
        execute_publish=bool(parameters.get("execute_publish", False)),
    )
    result["status"] = str(result.get("status") or "success")
    result["operation"] = "execute_packaged_docket_missing_authority_follow_up"
    result["tool_version"] = tool_version
    return result


async def search_federal_register_hf_index_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search Federal Register directly from HF-hosted FAISS and metadata files."""
    try:
        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        [
                            "huggingface_hub",
                            "sentence-transformers",
                            "pyarrow",
                            "numpy",
                            "faiss-cpu",
                            "anyio",
                        ],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        payload = {
            "hf_dataset_id": parameters.get("hf_dataset_id", DEFAULT_FEDERAL_REGISTER_HF_DATASET_ID),
            "hf_index_file": parameters.get("hf_index_file", "federal_register_gte_small.faiss"),
            "hf_metadata_file": parameters.get(
                "hf_metadata_file",
                "federal_register_gte_small_metadata.parquet",
            ),
            "model_name": parameters.get("model_name", "thenlper/gte-small"),
            "query_text": parameters.get("query_text"),
            "top_k": int(parameters.get("top_k", 10)),
            "snippet_chars": int(parameters.get("snippet_chars", 320)),
            "hf_cache_dir": parameters.get("hf_cache_dir"),
        }

        result = await anyio.to_thread.run_sync(
            lambda: _search_federal_register_hf_index_sync(payload)
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("Federal Register HF index search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "search_federal_register_hf_index",
            "tool_version": tool_version,
        }


async def list_caselaw_access_vector_files_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """List CAP dataset files/models via the project venv."""
    try:
        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "list_files",
            "hf_dataset_id": parameters.get("hf_dataset_id"),
            "hf_cache_dir": parameters.get("hf_cache_dir"),
            "model_hint": parameters.get("model_hint"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="list_files",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP vector file listing failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "list_files",
            "tool_version": tool_version,
        }


async def search_caselaw_access_vectors_with_centroids_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Run centroid-first retrieval over CAP vectors using the project venv."""
    try:
        if "query_vector" not in parameters:
            return {
                "status": "error",
                "error": "query_vector is required",
                "operation": "centroid_search",
                "tool_version": tool_version,
            }

        missing_required = [
            key
            for key in ("target_collection_name", "centroid_collection_name")
            if not parameters.get(key)
        ]
        if missing_required:
            return {
                "status": "error",
                "error": f"Missing required parameters: {', '.join(missing_required)}",
                "operation": "centroid_search",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "centroid_search",
            "target_collection_name": parameters["target_collection_name"],
            "centroid_collection_name": parameters["centroid_collection_name"],
            "hf_dataset_id": parameters.get("hf_dataset_id"),
            "hf_cache_dir": parameters.get("hf_cache_dir"),
            "query_vector": parameters["query_vector"],
            "store_type": parameters.get("store_type", "faiss"),
            "centroid_top_k": int(parameters.get("centroid_top_k", 5)),
            "per_cluster_top_k": int(parameters.get("per_cluster_top_k", 20)),
            "final_top_k": int(parameters.get("final_top_k", 10)),
            "cluster_metadata_field": parameters.get("cluster_metadata_field", "cluster_id"),
            "cluster_cids_parquet_file": parameters.get("cluster_cids_parquet_file"),
            "cid_metadata_field": parameters.get("cid_metadata_field", "cid"),
            "cid_list_field": parameters.get("cid_list_field", "cids"),
            "cluster_id_field_in_cid_map": parameters.get("cluster_id_field_in_cid_map", "cluster_id"),
            "cid_candidate_multiplier": int(parameters.get("cid_candidate_multiplier", 20)),
            "base_filter_dict": parameters.get("base_filter_dict"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="centroid_search",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP centroid-first vector search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "centroid_search",
            "tool_version": tool_version,
        }


async def ingest_caselaw_access_vector_bundle_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Ingest both target vectors and centroid vectors in one call."""
    try:
        missing_required = [
            key
            for key in ("target_collection_name", "centroid_collection_name")
            if not parameters.get(key)
        ]
        if missing_required:
            return {
                "status": "error",
                "error": f"Missing required parameters: {', '.join(missing_required)}",
                "operation": "ingest_bundle",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "ingest_bundle",
            "target_collection_name": parameters["target_collection_name"],
            "centroid_collection_name": parameters["centroid_collection_name"],
            "hf_dataset_id": parameters.get("hf_dataset_id"),
            "hf_cache_dir": parameters.get("hf_cache_dir"),
            "store_type": parameters.get("store_type", "faiss"),
            "target_parquet_file": parameters.get("target_parquet_file"),
            "target_model_hint": parameters.get("target_model_hint"),
            "target_max_rows": int(parameters.get("target_max_rows", 10000)),
            "centroid_parquet_file": parameters.get("centroid_parquet_file"),
            "centroid_model_hint": parameters.get("centroid_model_hint"),
            "centroid_max_rows": int(parameters.get("centroid_max_rows", 0)),
            "batch_size": int(parameters.get("batch_size", 512)),
            "distance_metric": parameters.get("distance_metric", "cosine"),
        }

        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="ingest_bundle",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP bundle ingestion failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "ingest_bundle",
            "tool_version": tool_version,
        }
