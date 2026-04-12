"""Inventory JusticeDAO Hugging Face datasets and derive query strategies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
import asyncio
import hashlib
import re
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import requests

from .citation_extraction import Citation, CitationExtractor
from .bluebook_citation_linker import BluebookCitationResolver, citation_link_to_dict
from .canonical_legal_corpora import (
    build_missing_eu_corpus_proposals,
    infer_canonical_legal_corpus_for_dataset_id,
    infer_proposed_eu_corpus_for_dataset_id,
    list_canonical_legal_corpora_by_country,
)
from .eu_legal_citation_bridge import get_eu_jurisdiction_profiles
from .eu_legal_citation_bridge import extract_eu_legal_citations
from .legal_source_recovery_promotion import (
    build_recovery_manifest_promotion_row,
    build_recovery_manifest_release_plan,
)
from .legal_source_recovery import recover_missing_legal_citation_source
from ..legal_data.document_structure import build_document_knowledge_graph, parse_legal_document
from ..retrieval import (
    bm25_search_documents,
    build_bm25_index,
    embed_query_for_backend,
    embed_texts_with_router_or_local,
    vector_dot,
)
from ...utils.cid_utils import canonical_json_bytes, cid_for_obj


DATASET_SERVER_BASE_URL = "https://datasets-server.huggingface.co"


@dataclass(frozen=True)
class DatasetConfigProfile:
    config: str
    split: str
    features: List[str] = field(default_factory=list)
    sample_row: Dict[str, Any] = field(default_factory=dict)
    query_modes: List[str] = field(default_factory=list)
    recommended_fields: List[str] = field(default_factory=list)
    query_templates: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass(frozen=True)
class DatasetProfile:
    dataset_id: str
    canonical_corpus_key: Optional[str] = None
    proposed_corpus_key: Optional[str] = None
    legal_branch: Optional[str] = None
    country_codes: List[str] = field(default_factory=list)
    parquet_files: List[str] = field(default_factory=list)
    top_level_paths: List[str] = field(default_factory=list)
    configs: List[DatasetConfigProfile] = field(default_factory=list)
    error: Optional[str] = None


@dataclass(frozen=True)
class BluebookQueryStrategy:
    dataset_id: str
    support_level: str
    query_path: str
    canonical_corpus_key: Optional[str] = None
    proposed_corpus_key: Optional[str] = None
    legal_branch: Optional[str] = None
    country_codes: List[str] = field(default_factory=list)
    citation_lookup_fields: List[str] = field(default_factory=list)
    text_fields: List[str] = field(default_factory=list)
    join_fields: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


LegalCitationQueryStrategy = BluebookQueryStrategy


@dataclass(frozen=True)
class CitationQueryPlan:
    citation_text: str
    citation_type: str
    normalized_citation: str
    candidate_datasets: List[BluebookQueryStrategy] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class BluebookDatasetQueryPlan:
    input_text: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    query_plans: List[CitationQueryPlan] = field(default_factory=list)
    dataset_notes: List[str] = field(default_factory=list)


LegalCitationDatasetQueryPlan = BluebookDatasetQueryPlan


@dataclass(frozen=True)
class CanonicalCorpusQueryResult:
    corpus_key: str
    dataset_id: str
    mode: str
    query_text: str
    state_code: Optional[str] = None
    parquet_file: Optional[str] = None
    embeddings_file: Optional[str] = None
    citation_links: List[Dict[str, Any]] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)
    legal_branch: Optional[str] = None
    country_codes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CanonicalCorpusIndexBuildResult:
    corpus_key: str
    dataset_id: str
    canonical_parquet_path: str
    embeddings_parquet_path: str
    faiss_index_path: Optional[str] = None
    faiss_metadata_path: Optional[str] = None
    row_count: int = 0
    vector_dimension: int = 0
    backend: str = ""
    provider: str = ""
    model_name: str = ""
    join_field: str = ""
    state_code: Optional[str] = None


@dataclass(frozen=True)
class CanonicalCorpusIndexPublishResult:
    corpus_key: str
    dataset_id: str
    uploaded_files: List[Dict[str, Any]] = field(default_factory=list)
    upload_count: int = 0
    commit_message: str = ""


@dataclass(frozen=True)
class CanonicalCorpusArtifactBuildResult:
    corpus_key: str
    dataset_id: str
    canonical_parquet_path: str
    updated_canonical_parquet_path: str
    row_count: int = 0
    join_field: str = ""
    state_code: Optional[str] = None
    missing_join_values_filled: int = 0
    cid_index_path: Optional[str] = None
    bm25_documents_path: Optional[str] = None
    knowledge_graph_entities_path: Optional[str] = None
    knowledge_graph_relationships_path: Optional[str] = None
    knowledge_graph_summary_path: Optional[str] = None
    corpus_quality_summary: Optional[Dict[str, Any]] = None
    recovery_recommendation: Optional[Dict[str, Any]] = None
    recovery_manifest_draft: Optional[Dict[str, Any]] = None
    recovery_execution: Optional[Dict[str, Any]] = None
    llm_knowledge_graph_summary: Optional[Dict[str, Any]] = None
    semantic_index: Optional[Dict[str, Any]] = None
    publish_result: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class JusticeDAOLibraryRebuildResult:
    artifact_results: List[CanonicalCorpusArtifactBuildResult] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.artifact_results)

    @property
    def failure_count(self) -> int:
        return len(self.errors)


@dataclass(frozen=True)
class JusticeDAORebuildTarget:
    corpus_key: str
    dataset_id: str
    parquet_path: str
    state_code: Optional[str] = None


@dataclass(frozen=True)
class JusticeDAORebuildRecommendation:
    country_code: str
    label: str
    status: str
    reason: str
    canonical_corpus_keys: List[str] = field(default_factory=list)
    existing_dataset_ids: List[str] = field(default_factory=list)
    proposed_corpus_key: Optional[str] = None
    proposed_dataset_id: Optional[str] = None


@dataclass(frozen=True)
class JusticeDAORebuildPlan:
    targets: List[JusticeDAORebuildTarget] = field(default_factory=list)
    batches: List[List[JusticeDAORebuildTarget]] = field(default_factory=list)
    recommendations: List[JusticeDAORebuildRecommendation] = field(default_factory=list)


@dataclass(frozen=True)
class CitationDatasetMatch:
    dataset_id: str
    source_ref: str
    strategy: BluebookQueryStrategy
    result_count: int
    rows: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CitationExecutionPlanResult:
    citation_text: str
    citation_type: str
    normalized_citation: str
    matches: List[CitationDatasetMatch] = field(default_factory=list)
    attempted_datasets: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class BluebookDatasetExecutionResult:
    input_text: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    execution_results: List[CitationExecutionPlanResult] = field(default_factory=list)


LegalCitationDatasetExecutionResult = BluebookDatasetExecutionResult


def _feature_names(features_payload: Sequence[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for item in features_payload:
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _top_level_paths(files: Iterable[str]) -> List[str]:
    values: List[str] = []
    for file_path in files:
        normalized = str(file_path or "").strip()
        if not normalized:
            continue
        token = normalized.split("/", 1)[0]
        if token and token not in values:
            values.append(token)
    return sorted(values)


def _classify_query_modes(features: Sequence[str], config: str) -> List[str]:
    feature_set = set(features)
    config_lower = str(config or "").lower()
    modes: List[str] = []

    if "embedding" in feature_set:
        modes.append("semantic_vector")
    if "semantic_text" in feature_set and "embedding" not in feature_set:
        modes.append("semantic_text")
    if {"title_number", "section_number"}.issubset(feature_set):
        modes.append("section_lookup")
    if {"state_code", "section_number"}.issubset(feature_set):
        modes.append("state_section_lookup")
    if {"identifier", "source_id"}.intersection(feature_set):
        modes.append("identifier_lookup")
    if {"citations", "reporter", "volume"}.issubset(feature_set):
        modes.append("citation_lookup")
    if {"law_identifier", "article_identifier"}.issubset(feature_set):
        modes.append("article_lookup")
    if "jsonld" in feature_set:
        modes.append("jsonld_lookup")
    if config_lower.endswith("embeddings") and "semantic_vector" not in modes:
        modes.append("semantic_vector")
    if not modes:
        modes.append("metadata_lookup")

    ordered: List[str] = []
    for mode in modes:
        if mode not in ordered:
            ordered.append(mode)
    return ordered


def _recommended_fields(features: Sequence[str], query_modes: Sequence[str]) -> List[str]:
    feature_set = set(features)
    recommendations: List[str] = []

    def _add(value: str) -> None:
        if value not in recommendations:
            recommendations.append(value)

    if "section_lookup" in query_modes:
        if {"title_number", "section_number"}.issubset(feature_set):
            _add("title_number + section_number")
    if "state_section_lookup" in query_modes:
        if {"state_code", "official_cite"}.issubset(feature_set):
            _add("state_code + official_cite")
        if {"state_code", "section_number"}.issubset(feature_set):
            _add("state_code + section_number")
        if {"state_code", "identifier"}.issubset(feature_set):
            _add("state_code + identifier")
    if "citation_lookup" in query_modes:
        if "citations" in feature_set:
            _add("citations")
        if {"volume", "reporter", "first_page"}.issubset(feature_set):
            _add("volume + reporter + first_page")
    if "identifier_lookup" in query_modes:
        if "identifier" in feature_set:
            _add("identifier")
        if "source_id" in feature_set:
            _add("source_id")
    if "article_lookup" in query_modes:
        if {"law_identifier", "article_number"}.issubset(feature_set):
            _add("law_identifier + article_number")
        if "citation" in feature_set:
            _add("citation")
    if "semantic_vector" in query_modes and "semantic_text" in feature_set:
        _add("semantic_text")
    if "jsonld_lookup" in query_modes:
        _add("jsonld")
    if "metadata_lookup" in query_modes:
        for field in ("name", "title", "source_url", "law_identifier"):
            if field in feature_set:
                _add(field)

    return recommendations


def _query_templates(features: Sequence[str], query_modes: Sequence[str]) -> List[str]:
    feature_set = set(features)
    templates: List[str] = []

    def _add(value: str) -> None:
        if value not in templates:
            templates.append(value)

    if "section_lookup" in query_modes and {"title_number", "section_number"}.issubset(feature_set):
        _add("SELECT * WHERE title_number = ? AND section_number = ?")

    if "state_section_lookup" in query_modes:
        if {"state_code", "official_cite"}.issubset(feature_set):
            _add("SELECT * WHERE state_code = ? AND official_cite = ?")
        if {"state_code", "section_number"}.issubset(feature_set):
            _add("SELECT * WHERE state_code = ? AND section_number = ?")
        if {"state_code", "identifier"}.issubset(feature_set):
            _add("SELECT * WHERE state_code = ? AND identifier = ?")

    if "identifier_lookup" in query_modes:
        if "identifier" in feature_set:
            _add("SELECT * WHERE identifier = ?")
        if "source_id" in feature_set:
            _add("SELECT * WHERE source_id = ?")
            if "text" in feature_set and "official_cite" not in feature_set:
                _add("SELECT * WHERE source_id LIKE ? OR text LIKE ?")

    if "citation_lookup" in query_modes:
        if "citations" in feature_set:
            _add("SELECT * WHERE citations = ?")
        if {"volume", "reporter", "first_page"}.issubset(feature_set):
            _add("SELECT * WHERE volume = ? AND reporter = ? AND first_page = ?")

    if "article_lookup" in query_modes:
        if {"law_identifier", "article_number"}.issubset(feature_set):
            _add("SELECT * WHERE law_identifier = ? AND article_number = ?")
        elif {"law_identifier", "article_identifier"}.issubset(feature_set):
            _add("SELECT * WHERE law_identifier = ? AND article_identifier = ?")
        if "citation" in feature_set:
            _add("SELECT * WHERE citation = ?")

    if "jsonld_lookup" in query_modes and "jsonld" in feature_set:
        _add("SELECT * WHERE jsonld CONTAINS identifier/source slug")

    if "semantic_vector" in query_modes:
        if "embedding" in feature_set:
            _add("VECTOR SEARCH embedding USING semantic_text or citation seed")
        elif "semantic_text" in feature_set:
            _add("FULLTEXT/semantic search over semantic_text")

    if "metadata_lookup" in query_modes:
        metadata_fields = [field for field in ("name", "title", "source_url", "law_identifier") if field in feature_set]
        if metadata_fields:
            _add(f"SELECT * WHERE {' OR '.join(f'{field} = ?' for field in metadata_fields)}")

    return templates


def _notes_for_config(features: Sequence[str], query_modes: Sequence[str]) -> List[str]:
    feature_set = set(features)
    notes: List[str] = []
    if "semantic_vector" in query_modes:
        notes.append("Embedding rows are for semantic retrieval, not direct authority lookup.")
    if "jsonld" in feature_set:
        notes.append("JSON-LD often contains richer identifiers than the top-level columns.")
    if feature_set <= {"ipfs_cid", "title_number", "section_number"}:
        notes.append("This config is a compact CID index; dereference the CID for rich text.")
    if {"source_id", "identifier", "text"}.issubset(feature_set) and "official_cite" not in feature_set:
        notes.append("Exact matching may require parsing section slugs from source_id or text.")
    return notes


def _dataset_server_json(session: requests.Session, url: str) -> Dict[str, Any]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected payload type from {url}: {type(payload).__name__}")
    return payload


def _canonical_metadata_for_dataset(dataset_id: str) -> Dict[str, Any]:
    normalized = str(dataset_id or "").strip()
    try:
        corpus = infer_canonical_legal_corpus_for_dataset_id(normalized)
        return {
            "canonical_corpus_key": corpus.key,
            "proposed_corpus_key": None,
            "legal_branch": corpus.normalized_branch(),
            "country_codes": list(corpus.country_codes),
        }
    except KeyError:
        pass
    try:
        proposed = infer_proposed_eu_corpus_for_dataset_id(normalized)
        return {
            "canonical_corpus_key": None,
            "proposed_corpus_key": proposed.key,
            "legal_branch": proposed.normalized_branch(),
            "country_codes": list(proposed.country_codes),
        }
    except KeyError:
        return {}


def _profile_legal_branch(profile: DatasetProfile) -> str:
    branch = str(profile.legal_branch or "").strip().lower()
    if branch:
        return branch
    return str(_canonical_metadata_for_dataset(profile.dataset_id).get("legal_branch") or "").strip().lower()


def _profile_country_codes(profile: DatasetProfile) -> List[str]:
    values = [str(item).strip().upper() for item in list(profile.country_codes or []) if str(item).strip()]
    if values:
        return values
    return [str(item).strip().upper() for item in list(_canonical_metadata_for_dataset(profile.dataset_id).get("country_codes") or []) if str(item).strip()]


def inspect_justicedao_datasets(
    *,
    author: str = "justicedao",
    dataset_prefix: str = "ipfs_",
    legal_branch: Optional[str] = None,
    country_code: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> List[DatasetProfile]:
    from huggingface_hub import list_datasets, list_repo_files

    active_session = session or requests.Session()
    dataset_infos = [
        item
        for item in list_datasets(author=author, full=True)
        if str(getattr(item, "id", "")).startswith(f"{author}/{dataset_prefix}")
    ]

    profiles: List[DatasetProfile] = []
    for dataset_info in sorted(dataset_infos, key=lambda item: str(item.id)):
        dataset_id = str(dataset_info.id)
        try:
            repo_files = list_repo_files(repo_id=dataset_id, repo_type="dataset")
            parquet_files = sorted([path for path in repo_files if path.endswith(".parquet")])
            splits_payload = _dataset_server_json(
                active_session,
                f"{DATASET_SERVER_BASE_URL}/splits?dataset={dataset_id}",
            )
            configs: List[DatasetConfigProfile] = []
            for split_info in splits_payload.get("splits", []):
                config = str(split_info.get("config") or "").strip()
                split = str(split_info.get("split") or "train").strip() or "train"
                try:
                    first_rows_payload = _dataset_server_json(
                        active_session,
                        f"{DATASET_SERVER_BASE_URL}/first-rows?dataset={dataset_id}&config={config}&split={split}",
                    )
                    features = _feature_names(first_rows_payload.get("features", []))
                    rows = first_rows_payload.get("rows", [])
                    sample_row = dict(rows[0].get("row") or {}) if rows else {}
                    query_modes = _classify_query_modes(features, config)
                    configs.append(
                        DatasetConfigProfile(
                            config=config,
                            split=split,
                            features=features,
                            sample_row=sample_row,
                            query_modes=query_modes,
                            recommended_fields=_recommended_fields(features, query_modes),
                            query_templates=_query_templates(features, query_modes),
                            notes=_notes_for_config(features, query_modes),
                        )
                    )
                except Exception as exc:
                    configs.append(
                        DatasetConfigProfile(
                            config=config,
                            split=split,
                            error=str(exc),
                        )
                    )
            profiles.append(
                DatasetProfile(
                    dataset_id=dataset_id,
                    **_canonical_metadata_for_dataset(dataset_id),
                    parquet_files=parquet_files,
                    top_level_paths=_top_level_paths(repo_files),
                    configs=configs,
                )
            )
        except Exception as exc:
            profiles.append(DatasetProfile(dataset_id=dataset_id, error=str(exc), **_canonical_metadata_for_dataset(dataset_id)))
    return filter_dataset_profiles(
        profiles,
        legal_branch=legal_branch,
        country_code=country_code,
    )


def filter_dataset_profiles(
    profiles: Sequence[DatasetProfile],
    *,
    legal_branch: Optional[str] = None,
    country_code: Optional[str] = None,
) -> List[DatasetProfile]:
    normalized_branch = str(legal_branch or "").strip().lower()
    normalized_country = str(country_code or "").strip().upper()
    filtered: List[DatasetProfile] = []
    for profile in profiles:
        branch = _profile_legal_branch(profile)
        countries = _profile_country_codes(profile)
        if normalized_branch and branch != normalized_branch:
            continue
        if normalized_country and normalized_country not in countries:
            continue
        filtered.append(profile)
    return filtered


def summarize_dataset_profiles_by_branch(profiles: Sequence[DatasetProfile]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for profile in profiles:
        branch = _profile_legal_branch(profile) or "unclassified"
        bucket = summary.setdefault(
            branch,
            {"dataset_count": 0, "dataset_ids": [], "country_codes": []},
        )
        bucket["dataset_count"] += 1
        bucket["dataset_ids"].append(profile.dataset_id)
        for code in _profile_country_codes(profile):
            if code not in bucket["country_codes"]:
                bucket["country_codes"].append(code)
    for bucket in summary.values():
        bucket["dataset_ids"] = sorted(bucket["dataset_ids"])
        bucket["country_codes"] = sorted(bucket["country_codes"])
    return dict(sorted(summary.items()))


def summarize_dataset_profiles_by_country(profiles: Sequence[DatasetProfile]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for profile in profiles:
        countries = _profile_country_codes(profile) or ["UNSPECIFIED"]
        branch = _profile_legal_branch(profile) or "unclassified"
        for country_code in countries:
            bucket = summary.setdefault(
                str(country_code).upper(),
                {"dataset_count": 0, "dataset_ids": [], "legal_branches": []},
            )
            bucket["dataset_count"] += 1
            bucket["dataset_ids"].append(profile.dataset_id)
            if branch not in bucket["legal_branches"]:
                bucket["legal_branches"].append(branch)
    for bucket in summary.values():
        bucket["dataset_ids"] = sorted(bucket["dataset_ids"])
        bucket["legal_branches"] = sorted(bucket["legal_branches"])
    return dict(sorted(summary.items()))


def _default_expected_country_codes_by_branch() -> Dict[str, List[str]]:
    eu_codes = sorted(code for code in get_eu_jurisdiction_profiles() if str(code).upper() != "EU")
    return {
        "eu": eu_codes,
        "us": ["US"],
    }


def summarize_dataset_profile_coverage_by_branch(
    profiles: Sequence[DatasetProfile],
    *,
    expected_country_codes_by_branch: Optional[Mapping[str, Sequence[str]]] = None,
) -> Dict[str, Dict[str, Any]]:
    branch_summary = summarize_dataset_profiles_by_branch(profiles)
    observed_countries_by_branch: Dict[str, set[str]] = {}
    for profile in profiles:
        branch = _profile_legal_branch(profile) or "unclassified"
        observed_countries_by_branch.setdefault(branch, set()).update(_profile_country_codes(profile))

    expected_map = expected_country_codes_by_branch or _default_expected_country_codes_by_branch()
    coverage: Dict[str, Dict[str, Any]] = {}
    for branch, payload in branch_summary.items():
        covered_country_codes = sorted(observed_countries_by_branch.get(branch, set()))
        expected_country_codes = sorted(
            {
                str(country_code).strip().upper()
                for country_code in list(expected_map.get(branch, []))
                if str(country_code).strip()
            }
        )
        coverage[branch] = {
            "dataset_count": payload["dataset_count"],
            "dataset_ids": list(payload["dataset_ids"]),
            "covered_country_codes": covered_country_codes,
            "expected_country_codes": expected_country_codes,
            "missing_country_codes": [
                country_code for country_code in expected_country_codes if country_code not in covered_country_codes
            ],
        }
    for branch, expected_country_codes in expected_map.items():
        normalized_branch = str(branch).strip().lower()
        if normalized_branch in coverage:
            continue
        normalized_expected = sorted(
            {
                str(country_code).strip().upper()
                for country_code in list(expected_country_codes or [])
                if str(country_code).strip()
            }
        )
        coverage[normalized_branch] = {
            "dataset_count": 0,
            "dataset_ids": [],
            "covered_country_codes": [],
            "expected_country_codes": normalized_expected,
            "missing_country_codes": list(normalized_expected),
        }
    return dict(sorted(coverage.items()))


def build_eu_country_corpus_onboarding_plan(
    profiles: Sequence[DatasetProfile],
    *,
    expected_country_codes: Optional[Sequence[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    country_summary = summarize_dataset_profiles_by_country(profiles)
    eu_profiles = get_eu_jurisdiction_profiles()
    proposed_corpora = build_missing_eu_corpus_proposals(
        expected_country_codes=[str(code) for code in list(expected_country_codes or [])] or None,
    )
    supported_codes = sorted(
        str(code).strip().upper()
        for code in list(expected_country_codes or eu_profiles.keys())
        if str(code).strip() and str(code).strip().upper() != "EU"
    )
    plan: Dict[str, Dict[str, Any]] = {}
    for country_code in supported_codes:
        profile = dict(eu_profiles.get(country_code) or {})
        label = str(profile.get("label") or country_code)
        canonical_corpora = list_canonical_legal_corpora_by_country(country_code)
        existing_dataset_ids = [
            dataset_id
            for dataset_id in list(country_summary.get(country_code, {}).get("dataset_ids") or [])
            if dataset_id
        ]
        canonical_keys = [corpus.key for corpus in canonical_corpora if corpus.normalized_branch() == "eu"]
        canonical_dataset_ids = {
            str(corpus.hf_dataset_id)
            for corpus in canonical_corpora
            if corpus.normalized_branch() == "eu"
        }
        has_observed_primary_dataset = any(dataset_id in canonical_dataset_ids for dataset_id in existing_dataset_ids)
        proposed_corpus = proposed_corpora.get(country_code)
        plan[country_code] = {
            "label": label,
            "languages": list(profile.get("languages") or []),
            "identifier_schemes": list(profile.get("identifier_schemes") or []),
            "canonical_corpus_keys": canonical_keys,
            "existing_dataset_count": len(existing_dataset_ids),
            "existing_dataset_ids": sorted(existing_dataset_ids),
            "status": (
                "covered"
                if canonical_keys and has_observed_primary_dataset
                else "registered"
                if canonical_keys
                else "in_progress"
                if existing_dataset_ids
                else "missing_dataset"
            ),
            "proposed_corpus_key": None if proposed_corpus is None else proposed_corpus.key,
            "proposed_dataset_id": None if proposed_corpus is None else proposed_corpus.hf_dataset_id,
            "proposed_local_root_name": None if proposed_corpus is None else proposed_corpus.local_root_name,
        }
    return plan


def dataset_profiles_to_dict(profiles: Sequence[DatasetProfile]) -> List[Dict[str, Any]]:
    return [asdict(profile) for profile in profiles]


def render_dataset_profiles_markdown(profiles: Sequence[DatasetProfile]) -> str:
    lines: List[str] = ["# JusticeDAO Dataset Query Map", ""]
    branch_summary = summarize_dataset_profiles_by_branch(profiles)
    if branch_summary:
        lines.append("## Branch Summary")
        lines.append("")
        for branch, payload in branch_summary.items():
            lines.append(
                f"- {str(branch).upper()}: {payload['dataset_count']} datasets"
                f" ({', '.join(payload['country_codes']) if payload['country_codes'] else 'no country codes'})"
            )
        lines.append("")
    country_summary = summarize_dataset_profiles_by_country(profiles)
    if country_summary:
        lines.append("## Country Summary")
        lines.append("")
        for country_code, payload in country_summary.items():
            lines.append(
                f"- {country_code}: {payload['dataset_count']} datasets"
                f" ({', '.join(str(item).upper() for item in payload['legal_branches']) if payload['legal_branches'] else 'no branches'})"
            )
        lines.append("")
    coverage_summary = summarize_dataset_profile_coverage_by_branch(profiles)
    if coverage_summary:
        lines.append("## Coverage Summary")
        lines.append("")
        for branch, payload in coverage_summary.items():
            coverage_bits: List[str] = []
            covered = ", ".join(payload["covered_country_codes"]) if payload["covered_country_codes"] else "none"
            coverage_bits.append(f"covered {covered}")
            if payload["missing_country_codes"]:
                coverage_bits.append(f"missing {', '.join(payload['missing_country_codes'])}")
            lines.append(f"- {str(branch).upper()}: {'; '.join(coverage_bits)}")
        lines.append("")
    eu_onboarding = build_eu_country_corpus_onboarding_plan(profiles)
    if eu_onboarding:
        lines.append("## EU Country Onboarding")
        lines.append("")
        for country_code, payload in eu_onboarding.items():
            schemes = ", ".join(payload["identifier_schemes"]) if payload["identifier_schemes"] else "n/a"
            if payload["status"] == "covered":
                lines.append(
                    f"- {country_code}: covered by {', '.join(payload['existing_dataset_ids'])}"
                    f" ({schemes})"
                )
            elif payload["status"] == "registered":
                lines.append(
                    f"- {country_code}: canonical registry includes {', '.join(payload['canonical_corpus_keys'])};"
                    f" awaiting observed datasets ({schemes})"
                )
            elif payload["status"] == "in_progress":
                lines.append(
                    f"- {country_code}: observed {', '.join(payload['existing_dataset_ids'])};"
                    f" awaiting canonical registration as {payload['proposed_corpus_key']} ({schemes})"
                )
            else:
                lines.append(
                    f"- {country_code}: missing dataset; propose {payload['proposed_corpus_key']}"
                    f" -> {payload['proposed_dataset_id']} ({schemes})"
                )
        lines.append("")
    for profile in profiles:
        lines.append(f"## {profile.dataset_id}")
        lines.append("")
        if profile.error:
            lines.append(f"Error: {profile.error}")
            lines.append("")
            continue
        metadata = _canonical_metadata_for_dataset(profile.dataset_id)
        canonical_corpus_key = str(profile.canonical_corpus_key or metadata.get("canonical_corpus_key") or "").strip()
        proposed_corpus_key = str(profile.proposed_corpus_key or metadata.get("proposed_corpus_key") or "").strip()
        if canonical_corpus_key:
            lines.append(f"Canonical corpus: {canonical_corpus_key}")
        elif proposed_corpus_key:
            lines.append(f"Proposed corpus: {proposed_corpus_key}")
        if profile.legal_branch:
            lines.append(f"Legal branch: {str(profile.legal_branch).upper()}")
        if profile.country_codes:
            lines.append(f"Countries: {', '.join(profile.country_codes)}")
        lines.append(f"Top-level paths: {', '.join(profile.top_level_paths) if profile.top_level_paths else 'n/a'}")
        lines.append(f"Parquet files: {len(profile.parquet_files)}")
        lines.append("")
        for config in profile.configs:
            lines.append(f"### {config.config} / {config.split}")
            lines.append("")
            if config.error:
                lines.append(f"Error: {config.error}")
                lines.append("")
                continue
            lines.append(f"Query modes: {', '.join(config.query_modes) if config.query_modes else 'n/a'}")
            lines.append(
                f"Recommended fields: {', '.join(config.recommended_fields) if config.recommended_fields else 'n/a'}"
            )
            lines.append(
                f"Query templates: {' | '.join(config.query_templates) if config.query_templates else 'n/a'}"
            )
            lines.append(f"Features: {', '.join(config.features[:20])}")
            if config.notes:
                lines.append(f"Notes: {' '.join(config.notes)}")
            if config.sample_row:
                sample_keys = ", ".join(sorted(config.sample_row.keys())[:12])
                lines.append(f"Sample row keys: {sample_keys}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _strategy(
    dataset_id: str,
    support_level: str,
    query_path: str,
    *,
    citation_lookup_fields: Optional[Sequence[str]] = None,
    text_fields: Optional[Sequence[str]] = None,
    join_fields: Optional[Sequence[str]] = None,
    notes: Optional[Sequence[str]] = None,
) -> BluebookQueryStrategy:
    metadata = _canonical_metadata_for_dataset(dataset_id)
    return BluebookQueryStrategy(
        dataset_id=dataset_id,
        support_level=support_level,
        query_path=query_path,
        canonical_corpus_key=metadata.get("canonical_corpus_key"),
        proposed_corpus_key=metadata.get("proposed_corpus_key"),
        legal_branch=metadata.get("legal_branch"),
        country_codes=list(metadata.get("country_codes") or []),
        citation_lookup_fields=[str(item) for item in list(citation_lookup_fields or []) if str(item).strip()],
        text_fields=[str(item) for item in list(text_fields or []) if str(item).strip()],
        join_fields=[str(item) for item in list(join_fields or []) if str(item).strip()],
        notes=[str(item) for item in list(notes or []) if str(item).strip()],
    )


def _dataset_profile_map(profiles: Sequence[DatasetProfile]) -> Dict[str, DatasetProfile]:
    return {str(profile.dataset_id): profile for profile in profiles}


def _has_any_path(profile: Optional[DatasetProfile], tokens: Sequence[str]) -> bool:
    if profile is None:
        return False
    haystack = [str(item) for item in list(profile.parquet_files) + list(profile.top_level_paths)]
    lowered = [item.lower() for item in haystack]
    return any(any(token.lower() in item for item in lowered) for token in tokens)


def derive_justicedao_bluebook_strategies(
    profiles: Sequence[DatasetProfile],
) -> Dict[str, BluebookQueryStrategy]:
    profile_map = _dataset_profile_map(profiles)
    strategies: Dict[str, BluebookQueryStrategy] = {}

    if "justicedao/american_municipal_law" in profile_map:
        profile = profile_map["justicedao/american_municipal_law"]
        notes = [
            "Use *_citation.parquet first because it already stores Bluebook-friendly rows.",
            "Join citation rows back to *_html.parquet or *_embeddings.parquet with cid.",
        ]
        if _has_any_path(profile, ["_citation.parquet"]):
            strategies[profile.dataset_id] = _strategy(
                profile.dataset_id,
                "direct",
                "precomputed_citation_table_then_cid_join",
                citation_lookup_fields=[
                    "bluebook_citation",
                    "title",
                    "chapter",
                    "public_law_num",
                    "bluebook_state_code",
                    "place_name",
                ],
                text_fields=["html_title", "html"],
                join_fields=["cid"],
                notes=notes,
            )

    if "justicedao/ipfs_state_laws" in profile_map:
        strategies["justicedao/ipfs_state_laws"] = _strategy(
            "justicedao/ipfs_state_laws",
            "direct",
            "bluebook_extract_then_identifier_or_state_section_lookup",
            citation_lookup_fields=["identifier", "source_id", "name", "state_code"],
            text_fields=["text", "jsonld"],
            join_fields=["ipfs_cid"],
            notes=[
                "Best fit for Bluebook state-statute citations like Or. Rev. Stat. § 90.155.",
                "When exact citation text misses, fall back to state_code plus parsed section number.",
            ],
        )

    if "justicedao/ipfs_state_admin_rules" in profile_map:
        strategies["justicedao/ipfs_state_admin_rules"] = _strategy(
            "justicedao/ipfs_state_admin_rules",
            "direct",
            "bluebook_extract_then_identifier_or_state_section_lookup",
            citation_lookup_fields=["identifier", "source_id", "name", "state_code"],
            text_fields=["text", "jsonld"],
            join_fields=["ipfs_cid"],
            notes=[
                "Best fit for Bluebook state administrative citations and OAR-style rule numbers.",
                "Rule history and implemented statutes often appear inside text/jsonld and can be second-pass extracted.",
            ],
        )

    if "justicedao/ipfs_court_rules" in profile_map:
        strategies["justicedao/ipfs_court_rules"] = _strategy(
            "justicedao/ipfs_court_rules",
            "direct",
            "bluebook_extract_then_identifier_or_state_section_lookup",
            citation_lookup_fields=["identifier", "source_id", "name", "state_code"],
            text_fields=["text", "jsonld"],
            join_fields=["ipfs_cid"],
            notes=[
                "Use for Bluebook citations to court rules and procedural rules.",
                "Some rows are metadata-heavy, so jsonld is often the richer fallback when text is sparse.",
            ],
        )

    if "justicedao/ipfs_uscode" in profile_map:
        strategies["justicedao/ipfs_uscode"] = _strategy(
            "justicedao/ipfs_uscode",
            "cid_join",
            "usc_title_section_to_cid_then_dereference_laws_parquet",
            citation_lookup_fields=["title_number", "section_number", "ipfs_cid"],
            join_fields=["ipfs_cid", "cid"],
            notes=[
                "The dataset server exposes a compact CID index for title_number + section_number.",
                "Use the extracted U.S.C. citation to find the CID, then dereference the rich laws parquet for full text.",
            ],
        )

    if "justicedao/ipfs_federal_register" in profile_map:
        strategies["justicedao/ipfs_federal_register"] = _strategy(
            "justicedao/ipfs_federal_register",
            "direct",
            "federal_register_volume_page_or_identifier_lookup",
            citation_lookup_fields=["identifier", "source_id", "name", "cid"],
            text_fields=["jsonld"],
            join_fields=["cid"],
            notes=[
                "Use extracted FR citations to query identifier or source_id first.",
                "If the local parquet includes text-bearing rows, keep identifier lookup as stage 1 and text extraction as stage 2.",
            ],
        )

    for dataset_id in ("justicedao/caselaw_access_project", "justicedao/ipfs_caselaw_access_project"):
        if dataset_id in profile_map:
            strategies[dataset_id] = _strategy(
                dataset_id,
                "direct",
                "case_reporter_lookup",
                citation_lookup_fields=["citation", "reporter", "volume", "page", "name", "id"],
                join_fields=["cid", "id"],
                notes=[
                    "Use extracted reporter citations such as 347 U.S. 483.",
                    "Volume + reporter + page should be the primary exact-match key.",
                ],
            )

    if "justicedao/ipfs_netherlands_laws" in profile_map:
        strategies["justicedao/ipfs_netherlands_laws"] = _strategy(
            "justicedao/ipfs_netherlands_laws",
            "metadata_only",
            "non_bluebook_identifier_or_citation_lookup",
            citation_lookup_fields=["citation", "identifier", "law_identifier", "official_identifier"],
            text_fields=["title", "text", "metadata"],
            join_fields=["cid", "content_address"],
            notes=[
                "This corpus is queryable, but not with the current Bluebook extractor alone.",
                "Use it after extending citation extraction to Dutch official citation formats, or after external identifier normalization.",
            ],
        )

    if "justicedao/ipfs_france_laws" in profile_map:
        strategies["justicedao/ipfs_france_laws"] = _strategy(
            "justicedao/ipfs_france_laws",
            "metadata_only",
            "non_bluebook_identifier_or_citation_lookup",
            citation_lookup_fields=["citation", "identifier", "law_identifier", "official_identifier"],
            text_fields=["title", "text", "metadata"],
            join_fields=["cid", "content_address", "source_cid"],
            notes=[
                "This corpus is queryable, but not with the current Bluebook extractor alone.",
                "Use it after extending citation extraction to French official citation formats, or after external identifier normalization.",
            ],
        )

    if "justicedao/ipfs_france_laws_bm25_index" in profile_map:
        strategies["justicedao/ipfs_france_laws_bm25_index"] = _strategy(
            "justicedao/ipfs_france_laws_bm25_index",
            "sidecar",
            "secondary_sparse_retrieval_after_primary_citation_match",
            citation_lookup_fields=["citation", "law_identifier", "article_identifier", "source_cid"],
            text_fields=["title", "text_preview"],
            join_fields=["source_cid", "law_cid", "cid"],
            notes=[
                "Use only after a primary citation or identifier match to expand supporting context.",
            ],
        )

    if "justicedao/ipfs_france_laws_knowledge_graph" in profile_map:
        strategies["justicedao/ipfs_france_laws_knowledge_graph"] = _strategy(
            "justicedao/ipfs_france_laws_knowledge_graph",
            "sidecar",
            "secondary_graph_expansion_after_primary_citation_match",
            citation_lookup_fields=["law_identifier", "article_identifier", "jsonld_id", "label"],
            join_fields=["source_cid", "node_cid", "cid"],
            notes=[
                "Use only after a primary law/article match to walk related entities and references.",
            ],
        )

    if "justicedao/ipfs_spain_laws" in profile_map:
        strategies["justicedao/ipfs_spain_laws"] = _strategy(
            "justicedao/ipfs_spain_laws",
            "metadata_only",
            "non_bluebook_identifier_or_citation_lookup",
            citation_lookup_fields=["citation", "identifier", "law_identifier", "official_identifier"],
            text_fields=["title", "text", "metadata"],
            join_fields=["cid", "content_address", "source_cid"],
            notes=[
                "This corpus is queryable, but not with the current Bluebook extractor alone.",
                "Use it after extending citation extraction to Spanish official citation formats, or after external identifier normalization.",
            ],
        )

    if "justicedao/ipfs_spain_laws_bm25_index" in profile_map:
        strategies["justicedao/ipfs_spain_laws_bm25_index"] = _strategy(
            "justicedao/ipfs_spain_laws_bm25_index",
            "sidecar",
            "secondary_sparse_retrieval_after_primary_citation_match",
            citation_lookup_fields=["citation", "law_identifier", "article_identifier", "source_cid"],
            text_fields=["title", "text_preview"],
            join_fields=["source_cid", "law_cid", "cid"],
            notes=[
                "Use only after a primary citation or identifier match to expand supporting context.",
            ],
        )

    if "justicedao/ipfs_spain_laws_knowledge_graph" in profile_map:
        strategies["justicedao/ipfs_spain_laws_knowledge_graph"] = _strategy(
            "justicedao/ipfs_spain_laws_knowledge_graph",
            "sidecar",
            "secondary_graph_expansion_after_primary_citation_match",
            citation_lookup_fields=["law_identifier", "article_identifier", "jsonld_id", "label"],
            join_fields=["source_cid", "node_cid", "cid"],
            notes=[
                "Use only after a primary law/article match to walk related entities and references.",
            ],
        )

    if "justicedao/ipfs_germany_laws" in profile_map:
        strategies["justicedao/ipfs_germany_laws"] = _strategy(
            "justicedao/ipfs_germany_laws",
            "metadata_only",
            "non_bluebook_identifier_or_citation_lookup",
            citation_lookup_fields=["citation", "identifier", "law_identifier", "official_identifier"],
            text_fields=["title", "text", "metadata"],
            join_fields=["cid", "content_address", "source_cid"],
            notes=[
                "This corpus is queryable, but not with the current Bluebook extractor alone.",
                "Use it after extending citation extraction to German official citation formats, or after external identifier normalization.",
            ],
        )

    if "justicedao/ipfs_germany_laws_bm25_index" in profile_map:
        strategies["justicedao/ipfs_germany_laws_bm25_index"] = _strategy(
            "justicedao/ipfs_germany_laws_bm25_index",
            "sidecar",
            "secondary_sparse_retrieval_after_primary_citation_match",
            citation_lookup_fields=["citation", "law_identifier", "article_identifier", "source_cid"],
            text_fields=["title", "text_preview"],
            join_fields=["source_cid", "law_cid", "cid"],
            notes=[
                "Use only after a primary citation or identifier match to expand supporting context.",
            ],
        )

    if "justicedao/ipfs_germany_laws_knowledge_graph" in profile_map:
        strategies["justicedao/ipfs_germany_laws_knowledge_graph"] = _strategy(
            "justicedao/ipfs_germany_laws_knowledge_graph",
            "sidecar",
            "secondary_graph_expansion_after_primary_citation_match",
            citation_lookup_fields=["law_identifier", "article_identifier", "jsonld_id", "label"],
            join_fields=["source_cid", "node_cid", "cid"],
            notes=[
                "Use only after a primary law/article match to walk related entities and references.",
            ],
        )

    if "justicedao/ipfs_netherlands_laws_bm25_index" in profile_map:
        strategies["justicedao/ipfs_netherlands_laws_bm25_index"] = _strategy(
            "justicedao/ipfs_netherlands_laws_bm25_index",
            "sidecar",
            "secondary_sparse_retrieval_after_primary_citation_match",
            citation_lookup_fields=["citation", "law_identifier", "article_identifier", "source_cid"],
            text_fields=["title", "text_preview"],
            join_fields=["source_cid", "law_cid", "cid"],
            notes=[
                "Use only after a primary citation or identifier match to expand supporting context.",
            ],
        )

    if "justicedao/ipfs_netherlands_laws_knowledge_graph" in profile_map:
        strategies["justicedao/ipfs_netherlands_laws_knowledge_graph"] = _strategy(
            "justicedao/ipfs_netherlands_laws_knowledge_graph",
            "sidecar",
            "secondary_graph_expansion_after_primary_citation_match",
            citation_lookup_fields=["law_identifier", "article_identifier", "jsonld_id", "label"],
            join_fields=["source_cid", "node_cid", "cid"],
            notes=[
                "Use only after a primary law/article match to walk related entities and references.",
            ],
        )

    return strategies


def derive_justicedao_legal_citation_strategies(
    profiles: Sequence[DatasetProfile],
) -> Dict[str, BluebookQueryStrategy]:
    return derive_justicedao_bluebook_strategies(profiles)


def _strategy_rank_for_citation(citation: Citation, strategy: BluebookQueryStrategy) -> int:
    if citation.type == "state_statute":
        if strategy.dataset_id.endswith("ipfs_state_laws"):
            return 100
        if strategy.dataset_id.endswith("ipfs_state_admin_rules"):
            return 90
        if strategy.dataset_id.endswith("ipfs_court_rules"):
            return 85
        if strategy.dataset_id.endswith("american_municipal_law"):
            return 60
    if citation.type == "usc" and strategy.dataset_id.endswith("ipfs_uscode"):
        return 100
    if citation.type == "federal_register" and strategy.dataset_id.endswith("ipfs_federal_register"):
        return 100
    if citation.type == "case" and "caselaw_access_project" in strategy.dataset_id:
        return 100
    if citation.type == "public_law" and strategy.dataset_id.endswith("ipfs_uscode"):
        return 80
    return 0


def _strategy_rank_for_eu_citation(citation: Any, strategy: BluebookQueryStrategy) -> int:
    member_state = str(getattr(citation, "member_state", "") or "").strip().upper()
    if not member_state or member_state not in {str(code).strip().upper() for code in strategy.country_codes}:
        return 0
    if strategy.support_level == "metadata_only":
        return 100
    if strategy.support_level == "sidecar":
        return 70
    return 10


def build_justicedao_bluebook_query_plan(
    text: str,
    *,
    profiles: Optional[Sequence[DatasetProfile]] = None,
    extractor: Optional[CitationExtractor] = None,
) -> BluebookDatasetQueryPlan:
    active_extractor = extractor or CitationExtractor()
    citations = active_extractor.extract_citations(text)
    eu_citations = extract_eu_legal_citations(text)
    active_profiles = list(profiles or inspect_justicedao_datasets(dataset_prefix=""))
    strategies = derive_justicedao_bluebook_strategies(active_profiles)

    plans: List[CitationQueryPlan] = []
    for citation in citations:
        ranked = sorted(
            strategies.values(),
            key=lambda item: (-_strategy_rank_for_citation(citation, item), item.dataset_id),
        )
        candidates = [item for item in ranked if _strategy_rank_for_citation(citation, item) > 0]
        notes: List[str] = []
        if citation.type == "state_statute":
            notes.append("Parse state abbreviation and section number first, then try state_laws before rules datasets.")
        elif citation.type == "usc":
            notes.append("Convert the Bluebook citation to title_number + section_number before querying the CID index.")
        elif citation.type == "federal_register":
            notes.append("Prefer exact identifier or volume/page lookup before semantic retrieval.")
        elif citation.type == "case":
            notes.append("Prefer exact volume + reporter + page matching.")
        elif citation.type == "public_law":
            notes.append("Resolve Pub. L. references through uscode/federal_register metadata before text search.")
        plans.append(
            CitationQueryPlan(
                citation_text=citation.text,
                citation_type=citation.type,
                normalized_citation=_normalize_citation_text(citation),
                candidate_datasets=candidates,
                notes=notes,
            )
        )

    for citation in eu_citations:
        ranked = sorted(
            strategies.values(),
            key=lambda item: (-_strategy_rank_for_eu_citation(citation, item), item.dataset_id),
        )
        candidates = [item for item in ranked if _strategy_rank_for_eu_citation(citation, item) > 0]
        if not candidates:
            continue
        notes = [
            "Use the extracted EU/member-state identifier as the primary lookup key before falling back to lexical search.",
        ]
        if str(getattr(citation, "member_state", "") or "").strip().upper():
            notes.append(
                f"Prefer the canonical {str(getattr(citation, 'member_state', '')).strip().upper()} member-state corpus before sidecars."
            )
        plans.append(
            CitationQueryPlan(
                citation_text=_eu_query_text(citation),
                citation_type=f"eu_{str(getattr(citation, 'scheme', 'identifier')).strip().lower()}",
                normalized_citation=str(getattr(citation, "normalized_text", "") or "").strip(),
                candidate_datasets=candidates,
                notes=notes,
            )
        )

    dataset_notes = [
        "Canonical corpora are partitioned into legal branches, currently US and EU, so dataset maintenance can expand country-by-country without mixing jurisdiction assumptions.",
        "JusticeDAO state-law, admin-rule, and court-rule corpora share a near-identical schema, so one legal citation adapter can handle all three.",
        "american_municipal_law is best queried through its *_citation.parquet files, then joined to *_html.parquet by cid.",
        "ipfs_uscode is exposed as a CID index in the datasets server and should be treated as a two-step citation -> cid -> rich text lookup.",
        "Netherlands laws is maintained as an EU-country corpus, with BM25 and knowledge-graph sidecars layered on top of the primary laws dataset.",
        "EU member-state citations extracted by the EU bridge can now seed canonical corpus query plans for Netherlands, France, Germany, and Spain.",
    ]
    return BluebookDatasetQueryPlan(
        input_text=str(text or ""),
        citations=[
            *[
                {
                    "text": citation.text,
                    "type": citation.type,
                    "jurisdiction": citation.jurisdiction,
                    "title": citation.title,
                    "section": citation.section,
                    "volume": citation.volume,
                    "reporter": citation.reporter,
                    "page": citation.page,
                }
                for citation in citations
            ],
            *[
                {
                    "text": _eu_query_text(citation),
                    "type": f"eu_{str(getattr(citation, 'scheme', 'identifier')).strip().lower()}",
                    "jurisdiction": getattr(citation, "jurisdiction", None),
                    "member_state": getattr(citation, "member_state", None),
                    "scheme": getattr(citation, "scheme", None),
                    "canonical_uri": getattr(citation, "canonical_uri", None),
                }
                for citation in eu_citations
            ],
        ],
        query_plans=plans,
        dataset_notes=dataset_notes,
    )


def bluebook_dataset_query_plan_to_dict(plan: BluebookDatasetQueryPlan) -> Dict[str, Any]:
    return {
        "input_text": plan.input_text,
        "citations": [dict(item) for item in plan.citations],
        "query_plans": [
            {
                "citation_text": item.citation_text,
                "citation_type": item.citation_type,
                "normalized_citation": item.normalized_citation,
                "candidate_datasets": [
                    {
                        "dataset_id": strategy.dataset_id,
                        "support_level": strategy.support_level,
                        "query_path": strategy.query_path,
                        "citation_lookup_fields": list(strategy.citation_lookup_fields),
                        "proposed_corpus_key": strategy.proposed_corpus_key,
                        "text_fields": list(strategy.text_fields),
                        "join_fields": list(strategy.join_fields),
                        "notes": list(strategy.notes),
                    }
                    for strategy in item.candidate_datasets
                ],
                "notes": list(item.notes),
            }
            for item in plan.query_plans
        ],
        "dataset_notes": list(plan.dataset_notes),
    }


def legal_citation_dataset_query_plan_to_dict(plan: BluebookDatasetQueryPlan) -> Dict[str, Any]:
    return bluebook_dataset_query_plan_to_dict(plan)


def render_bluebook_dataset_query_plan_markdown(plan: BluebookDatasetQueryPlan) -> str:
    lines: List[str] = ["# JusticeDAO Legal Citation Query Plan", ""]
    if not plan.citations:
        lines.append("No supported legal citations were extracted from the supplied text.")
        lines.append("")
    for item in plan.query_plans:
        lines.append(f"## {item.citation_text}")
        lines.append("")
        lines.append(f"Citation type: {item.citation_type}")
        lines.append(f"Normalized: {item.normalized_citation}")
        if item.notes:
            lines.append(f"Notes: {' '.join(item.notes)}")
        lines.append("")
        for strategy in item.candidate_datasets:
            lines.append(f"### {strategy.dataset_id}")
            lines.append("")
            lines.append(f"Support level: {strategy.support_level}")
            lines.append(f"Query path: {strategy.query_path}")
            if strategy.citation_lookup_fields:
                lines.append(f"Citation lookup fields: {', '.join(strategy.citation_lookup_fields)}")
            if strategy.text_fields:
                lines.append(f"Text fields: {', '.join(strategy.text_fields)}")
            if strategy.join_fields:
                lines.append(f"Join fields: {', '.join(strategy.join_fields)}")
            if strategy.notes:
                lines.append(f"Notes: {' '.join(strategy.notes)}")
            lines.append("")
    if plan.dataset_notes:
        lines.append("## Dataset Notes")
        lines.append("")
        for note in plan.dataset_notes:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_justicedao_legal_citation_query_plan(
    text: str,
    *,
    profiles: Optional[Sequence[DatasetProfile]] = None,
    extractor: Optional[CitationExtractor] = None,
) -> BluebookDatasetQueryPlan:
    return build_justicedao_bluebook_query_plan(
        text,
        profiles=profiles,
        extractor=extractor,
    )


def render_justicedao_legal_citation_query_plan_markdown(plan: BluebookDatasetQueryPlan) -> str:
    return render_bluebook_dataset_query_plan_markdown(plan)


def _normalize_citation_text(citation: Citation) -> str:
    if citation.type == "usc" and citation.title and citation.section:
        return f"{citation.title} U.S.C. § {citation.section}"
    if citation.type == "federal_register" and citation.volume and citation.page:
        return f"{citation.volume} FR {citation.page}"
    if citation.type == "case" and citation.volume and citation.reporter and citation.page:
        return f"{citation.volume} {citation.reporter} {citation.page}"
    return str(citation.text or "").strip()


_CANONICAL_QUERY_DATASETS: Dict[str, Dict[str, Any]] = {
    "us_code": {
        "dataset_id": "justicedao/ipfs_uscode",
        "parquet_files": ["uscode_parquet/laws.parquet"],
        "embedding_files": ["uscode_parquet/laws_embeddings.parquet"],
        "publish_cid_index_files": ["uscode_parquet/cid_index.parquet"],
        "publish_bm25_files": ["uscode_parquet/laws_bm25.parquet"],
        "publish_kg_entities_files": ["uscode_parquet/laws_knowledge_graph_entities.parquet"],
        "publish_kg_relationships_files": ["uscode_parquet/laws_knowledge_graph_relationships.parquet"],
        "publish_kg_summary_files": ["uscode_parquet/laws_knowledge_graph_summary.json"],
        "publish_embeddings_files": ["uscode_parquet/laws_embeddings.parquet"],
        "publish_faiss_index_files": ["uscode_parquet/laws.faiss"],
        "publish_faiss_metadata_files": ["uscode_parquet/laws_faiss_metadata.parquet"],
        "join_field": "ipfs_cid",
        "title_fields": ["law_name", "title_name", "identifier", "source_id"],
        "text_fields": ["text", "law_name", "title_name", "raw_json"],
    },
    "federal_register": {
        "dataset_id": "justicedao/ipfs_federal_register",
        "parquet_files": ["federal_register.parquet"],
        "embedding_files": [],
        "faiss_index_files": ["federal_register_gte_small.faiss"],
        "faiss_metadata_files": ["federal_register_gte_small_metadata.parquet"],
        "publish_cid_index_files": ["federal_register_cid_index.parquet"],
        "publish_bm25_files": ["federal_register_bm25.parquet"],
        "publish_kg_entities_files": ["federal_register_knowledge_graph_entities.parquet"],
        "publish_kg_relationships_files": ["federal_register_knowledge_graph_relationships.parquet"],
        "publish_kg_summary_files": ["federal_register_knowledge_graph_summary.json"],
        "publish_embeddings_files": [],
        "publish_faiss_index_files": ["federal_register_gte_small.faiss"],
        "publish_faiss_metadata_files": ["federal_register_gte_small_metadata.parquet"],
        "join_field": "cid",
        "title_fields": ["name", "identifier", "source_id"],
        "text_fields": ["name", "agency", "jsonld", "source_url"],
    },
    "state_laws": {
        "dataset_id": "justicedao/ipfs_state_laws",
        "parquet_templates": ["state_laws_parquet_cid/STATE-{state}.parquet"],
        "parquet_fallback_patterns": [r"state_laws_parquet_cid/.+\.parquet$"],
        "embedding_templates": ["state_laws_parquet_cid/STATE-{state}_embeddings.parquet"],
        "embedding_fallback_patterns": [r"state_laws_parquet_cid/.+_embeddings\.parquet$"],
        "publish_cid_index_templates": ["state_laws_parquet_cid/STATE-{state}_cid_index.parquet"],
        "publish_bm25_templates": ["state_laws_parquet_cid/STATE-{state}_bm25.parquet"],
        "publish_kg_entities_templates": ["state_laws_parquet_cid/STATE-{state}_knowledge_graph_entities.parquet"],
        "publish_kg_relationships_templates": ["state_laws_parquet_cid/STATE-{state}_knowledge_graph_relationships.parquet"],
        "publish_kg_summary_templates": ["state_laws_parquet_cid/STATE-{state}_knowledge_graph_summary.json"],
        "publish_embeddings_templates": ["state_laws_parquet_cid/STATE-{state}_embeddings.parquet"],
        "publish_faiss_index_templates": ["state_laws_parquet_cid/STATE-{state}.faiss"],
        "publish_faiss_metadata_templates": ["state_laws_parquet_cid/STATE-{state}_faiss_metadata.parquet"],
        "join_field": "ipfs_cid",
        "title_fields": ["name", "identifier", "source_id", "official_cite"],
        "text_fields": ["text", "jsonld", "name", "identifier", "source_id"],
    },
    "state_admin_rules": {
        "dataset_id": "justicedao/ipfs_state_admin_rules",
        "parquet_templates": ["state_admin_rules_parquet_cid/STATE-{state}.parquet"],
        "parquet_fallback_patterns": [r".*administrative_rules.*\.parquet$"],
        "embedding_templates": ["state_admin_rules_parquet_cid/STATE-{state}_embeddings.parquet"],
        "embedding_fallback_patterns": [r".*administrative_rules.*embeddings.*\.parquet$"],
        "publish_cid_index_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_cid_index.parquet"],
        "publish_bm25_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_bm25.parquet"],
        "publish_kg_entities_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_knowledge_graph_entities.parquet"],
        "publish_kg_relationships_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_knowledge_graph_relationships.parquet"],
        "publish_kg_summary_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_knowledge_graph_summary.json"],
        "publish_embeddings_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_embeddings.parquet"],
        "publish_faiss_index_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}.faiss"],
        "publish_faiss_metadata_templates": ["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/STATE-{state}_faiss_metadata.parquet"],
        "join_field": "ipfs_cid",
        "title_fields": ["section_name", "short_title", "official_cite", "statute_id"],
        "text_fields": ["full_text", "summary", "official_cite", "statute_id", "metadata"],
    },
    "state_court_rules": {
        "dataset_id": "justicedao/ipfs_court_rules",
        "parquet_templates": [
            "state_court_rules_parquet_cid/STATE-{state}.parquet",
            "FEDERAL-RULES.parquet",
        ],
        "parquet_fallback_patterns": [r"state_court_rules_parquet_cid/.+\.parquet$", r"FEDERAL-RULES\.parquet$"],
        "embedding_templates": ["state_court_rules_parquet_cid/STATE-{state}_embeddings.parquet"],
        "embedding_fallback_patterns": [r"state_court_rules_parquet_cid/.+_embeddings\.parquet$"],
        "publish_cid_index_templates": ["state_court_rules_parquet_cid/STATE-{state}_cid_index.parquet"],
        "publish_bm25_templates": ["state_court_rules_parquet_cid/STATE-{state}_bm25.parquet"],
        "publish_kg_entities_templates": ["state_court_rules_parquet_cid/STATE-{state}_knowledge_graph_entities.parquet"],
        "publish_kg_relationships_templates": ["state_court_rules_parquet_cid/STATE-{state}_knowledge_graph_relationships.parquet"],
        "publish_kg_summary_templates": ["state_court_rules_parquet_cid/STATE-{state}_knowledge_graph_summary.json"],
        "publish_embeddings_templates": ["state_court_rules_parquet_cid/STATE-{state}_embeddings.parquet"],
        "publish_faiss_index_templates": ["state_court_rules_parquet_cid/STATE-{state}.faiss"],
        "publish_faiss_metadata_templates": ["state_court_rules_parquet_cid/STATE-{state}_faiss_metadata.parquet"],
        "join_field": "ipfs_cid",
        "title_fields": ["name", "identifier", "source_id", "ruleNumber", "@id"],
        "text_fields": ["text", "jsonld", "name", "@id", "ruleNumber"],
    },
    "netherlands_laws": {
        "dataset_id": "justicedao/ipfs_netherlands_laws",
        "parquet_files": ["parquet/laws/train-00000-of-00001.parquet", "parquet/articles/train-00000-of-00001.parquet"],
        "embedding_files": [],
        "publish_cid_index_files": ["artifacts/cid_index.parquet"],
        "publish_bm25_files": ["artifacts/bm25_documents.parquet"],
        "publish_kg_entities_files": ["artifacts/knowledge_graph_entities.parquet"],
        "publish_kg_relationships_files": ["artifacts/knowledge_graph_relationships.parquet"],
        "publish_kg_summary_files": ["artifacts/knowledge_graph_summary.json"],
        "publish_embeddings_files": ["netherlands_laws_embeddings.parquet"],
        "publish_faiss_index_files": ["artifacts/faiss.index"],
        "publish_faiss_metadata_files": ["artifacts/faiss_metadata.parquet"],
        "join_field": "source_cid",
        "title_fields": ["title", "identifier", "law_identifier", "official_identifier", "citation"],
        "text_fields": ["text", "title", "summary", "citation", "law_identifier", "article_identifier"],
    },
    "france_laws": {
        "dataset_id": "justicedao/ipfs_france_laws",
        "parquet_files": ["parquet/laws/train-00000-of-00001.parquet", "parquet/articles/train-00000-of-00001.parquet"],
        "embedding_files": [],
        "publish_cid_index_files": ["artifacts/cid_index.parquet"],
        "publish_bm25_files": ["artifacts/bm25_documents.parquet"],
        "publish_kg_entities_files": ["artifacts/knowledge_graph_entities.parquet"],
        "publish_kg_relationships_files": ["artifacts/knowledge_graph_relationships.parquet"],
        "publish_kg_summary_files": ["artifacts/knowledge_graph_summary.json"],
        "publish_embeddings_files": ["france_laws_embeddings.parquet"],
        "publish_faiss_index_files": ["artifacts/faiss.index"],
        "publish_faiss_metadata_files": ["artifacts/faiss_metadata.parquet"],
        "join_field": "source_cid",
        "title_fields": ["title", "identifier", "law_identifier", "official_identifier", "citation"],
        "text_fields": ["text", "title", "summary", "citation", "law_identifier", "article_identifier"],
    },
    "spain_laws": {
        "dataset_id": "justicedao/ipfs_spain_laws",
        "parquet_files": ["parquet/laws/train-00000-of-00001.parquet", "parquet/articles/train-00000-of-00001.parquet"],
        "embedding_files": [],
        "publish_cid_index_files": ["artifacts/cid_index.parquet"],
        "publish_bm25_files": ["artifacts/bm25_documents.parquet"],
        "publish_kg_entities_files": ["artifacts/knowledge_graph_entities.parquet"],
        "publish_kg_relationships_files": ["artifacts/knowledge_graph_relationships.parquet"],
        "publish_kg_summary_files": ["artifacts/knowledge_graph_summary.json"],
        "publish_embeddings_files": ["spain_laws_embeddings.parquet"],
        "publish_faiss_index_files": ["artifacts/faiss.index"],
        "publish_faiss_metadata_files": ["artifacts/faiss_metadata.parquet"],
        "join_field": "source_cid",
        "title_fields": ["title", "identifier", "law_identifier", "official_identifier", "citation"],
        "text_fields": ["text", "title", "summary", "citation", "law_identifier", "article_identifier"],
    },
    "germany_laws": {
        "dataset_id": "justicedao/ipfs_germany_laws",
        "parquet_files": ["parquet/laws/train-00000-of-00001.parquet", "parquet/articles/train-00000-of-00001.parquet"],
        "embedding_files": [],
        "publish_cid_index_files": ["artifacts/cid_index.parquet"],
        "publish_bm25_files": ["artifacts/bm25_documents.parquet"],
        "publish_kg_entities_files": ["artifacts/knowledge_graph_entities.parquet"],
        "publish_kg_relationships_files": ["artifacts/knowledge_graph_relationships.parquet"],
        "publish_kg_summary_files": ["artifacts/knowledge_graph_summary.json"],
        "publish_embeddings_files": ["germany_laws_embeddings.parquet"],
        "publish_faiss_index_files": ["artifacts/faiss.index"],
        "publish_faiss_metadata_files": ["artifacts/faiss_metadata.parquet"],
        "join_field": "source_cid",
        "title_fields": ["title", "identifier", "law_identifier", "official_identifier", "citation"],
        "text_fields": ["text", "title", "summary", "citation", "law_identifier", "article_identifier"],
    },
}


def canonical_corpus_query_result_to_dict(result: CanonicalCorpusQueryResult) -> Dict[str, Any]:
    return asdict(result)


def canonical_corpus_index_build_result_to_dict(result: CanonicalCorpusIndexBuildResult) -> Dict[str, Any]:
    return asdict(result)


def canonical_corpus_index_publish_result_to_dict(result: CanonicalCorpusIndexPublishResult) -> Dict[str, Any]:
    return asdict(result)


def _normalize_state_code(state_code: Optional[str]) -> Optional[str]:
    value = str(state_code or "").strip().upper()
    return value or None


def _list_repo_files_cached(repo_id: str) -> List[str]:
    from huggingface_hub import list_repo_files

    return list(list_repo_files(repo_id=repo_id, repo_type="dataset"))


def _select_repo_file(
    repo_files: Sequence[str],
    *,
    preferred_paths: Sequence[str],
    fallback_patterns: Sequence[str],
    state_code: Optional[str],
) -> Optional[str]:
    normalized_state = _normalize_state_code(state_code)
    available = [str(item) for item in repo_files]

    for template in preferred_paths:
        candidate = template.format(state=normalized_state) if normalized_state else template
        if candidate in available:
            return candidate

    for pattern in fallback_patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        matches = [path for path in available if compiled.search(path)]
        if normalized_state:
            state_matches = [path for path in matches if f"STATE-{normalized_state}" in path.upper()]
            if state_matches:
                return sorted(state_matches)[0]
        if matches:
            return sorted(matches)[0]
    return None


def _matching_inventory_profiles_for_corpus(
    profiles: Sequence[DatasetProfile],
    *,
    corpus_key: str,
    dataset_id: str,
) -> List[DatasetProfile]:
    matches: List[DatasetProfile] = []
    for profile in profiles:
        if str(profile.dataset_id) == str(dataset_id):
            matches.append(profile)
            continue
        if str(profile.canonical_corpus_key or "").strip().lower() == str(corpus_key).strip().lower():
            matches.append(profile)
    return matches


def _inventory_query_modes(profile: DatasetProfile) -> set[str]:
    modes: set[str] = set()
    for config in list(profile.configs or []):
        for mode in list(config.query_modes or []):
            text = str(mode or "").strip().lower()
            if text:
                modes.add(text)
    return modes


def _inventory_score_repo_file(
    path: str,
    *,
    kind: str,
    corpus_key: str,
    state_code: Optional[str],
    profile: DatasetProfile,
) -> int:
    candidate = str(path or "").strip()
    if not candidate:
        return -10_000

    lowered = candidate.lower()
    filename = lowered.rsplit("/", 1)[-1]
    normalized_kind = str(kind or "parquet").strip().lower()
    score = 0
    query_modes = _inventory_query_modes(profile)

    if state_code and f"state-{str(state_code).strip().lower()}" in lowered:
        score += 120

    if normalized_kind == "parquet":
        if not lowered.endswith(".parquet"):
            return -10_000
        if any(token in filename for token in ("_embeddings.parquet", "_metadata.parquet", "_bm25.parquet")):
            score -= 200
        if any(token in lowered for token in ("knowledge_graph", "cid_index", "vector_index")):
            score -= 120
        if corpus_key == "us_code" and "laws" in filename:
            score += 80
        if corpus_key == "federal_register" and "federal_register" in filename:
            score += 80
        if corpus_key.startswith("state_") and filename.startswith("state-"):
            score += 90
        if corpus_key in {"netherlands_laws", "france_laws", "spain_laws", "germany_laws"} and "/laws/" in lowered:
            score += 80
        if corpus_key in {"netherlands_laws", "france_laws", "spain_laws", "germany_laws"} and "/articles/" in lowered:
            score += 40
        if any(mode in query_modes for mode in ("identifier_lookup", "section_lookup", "state_section_lookup", "citation_lookup")):
            score += 25
        return score

    if normalized_kind == "embeddings":
        if not lowered.endswith(".parquet"):
            return -10_000
        if "embedding" in lowered or "semantic" in lowered or "vector" in lowered:
            score += 140
        else:
            score -= 80
        if "semantic_vector" in query_modes:
            score += 40
        return score

    if normalized_kind == "faiss_index":
        if lowered.endswith(".faiss"):
            score += 180
        elif lowered.endswith(".index"):
            score += 120
        else:
            return -10_000
        return score

    if normalized_kind == "faiss_metadata":
        if not lowered.endswith(".parquet"):
            return -10_000
        if "metadata" in lowered:
            score += 160
        if "faiss" in lowered or "gte_small" in lowered or "vector" in lowered:
            score += 40
        return score

    return -10_000


def _inventory_select_repo_file(
    repo_files: Sequence[str],
    *,
    corpus_key: str,
    dataset_id: str,
    state_code: Optional[str],
    kind: str,
) -> Optional[str]:
    try:
        profiles = inspect_justicedao_datasets(dataset_prefix="")
    except Exception:
        return None

    available = {str(item) for item in repo_files}
    best_candidate: Optional[str] = None
    best_score = -10_000
    for profile in _matching_inventory_profiles_for_corpus(
        profiles,
        corpus_key=corpus_key,
        dataset_id=dataset_id,
    ):
        for candidate in list(profile.parquet_files or []):
            candidate_text = str(candidate)
            if candidate_text not in available:
                continue
            score = _inventory_score_repo_file(
                candidate_text,
                kind=kind,
                corpus_key=corpus_key,
                state_code=state_code,
                profile=profile,
            )
            if score > best_score:
                best_candidate = candidate_text
                best_score = score
    return best_candidate if best_score > 0 else None


def _resolve_remote_repo_file(
    repo_files: Sequence[str],
    *,
    corpus_key: str,
    dataset_id: str,
    state_code: Optional[str],
    preferred_paths: Sequence[str],
    fallback_patterns: Sequence[str],
    kind: str,
) -> Optional[str]:
    selected = _select_repo_file(
        repo_files,
        preferred_paths=preferred_paths,
        fallback_patterns=fallback_patterns,
        state_code=state_code,
    )
    if selected:
        return selected
    return _inventory_select_repo_file(
        repo_files,
        corpus_key=corpus_key,
        dataset_id=dataset_id,
        state_code=state_code,
        kind=kind,
    )


def _download_hf_dataset_file(repo_id: str, filename: str) -> str:
    from huggingface_hub import hf_hub_download

    return str(hf_hub_download(repo_id=repo_id, repo_type="dataset", filename=filename))


def _first_remote_publish_path(
    config: Mapping[str, Any],
    *,
    key_files: str,
    key_templates: str,
    state_code: Optional[str],
) -> Optional[str]:
    normalized_state = _normalize_state_code(state_code)
    for value in list(config.get(key_files) or []):
        text = str(value).strip()
        if text:
            return text
    for value in list(config.get(key_templates) or []):
        text = str(value).strip()
        if not text:
            continue
        return text.format(state=normalized_state) if normalized_state else text
    return None


def _schema_for_parquet(path: str) -> List[str]:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    return list(parquet.schema_arrow.names)


def _first_available(fields: Sequence[str], schema: Sequence[str]) -> List[str]:
    schema_set = set(schema)
    return [field for field in fields if field in schema_set]


def _coerce_embedding_vector(value: Any) -> List[float]:
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, tuple):
        return [float(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return [float(item) for item in value.tolist()]
        except Exception:
            pass
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [float(item) for item in parsed]
    except Exception:
        pass
    if text.startswith("[") and text.endswith("]"):
        body = text[1:-1].strip()
        if body:
            return [float(item.strip()) for item in body.split(",") if item.strip()]
    return []


def _fit_vector_dimension(vector: Sequence[float], dimension: int) -> List[float]:
    values = [float(item) for item in vector]
    if dimension <= 0:
        return []
    if len(values) == dimension:
        return values
    if len(values) > dimension:
        return values[:dimension]
    return values + ([0.0] * (dimension - len(values)))


def _row_title(row: Mapping[str, Any], title_fields: Sequence[str]) -> str:
    for field in title_fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _row_text(row: Mapping[str, Any], text_fields: Sequence[str]) -> str:
    values: List[str] = []
    for field in text_fields:
        value = str(row.get(field) or "").strip()
        if value and value not in values:
            values.append(value)
    return "\n".join(values)


def _default_embeddings_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_embeddings.parquet"))
    return str(path) + "_embeddings.parquet"


def _default_faiss_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    return str(path.with_suffix(".faiss"))


def _default_faiss_metadata_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_faiss_metadata.parquet"))
    return str(path) + "_faiss_metadata.parquet"


def _default_cid_index_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_cid_index.parquet"))
    return str(path) + "_cid_index.parquet"


def _default_bm25_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_bm25.parquet"))
    return str(path) + "_bm25.parquet"


def _default_kg_entities_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_knowledge_graph_entities.parquet"))
    return str(path) + "_knowledge_graph_entities.parquet"


def _default_kg_relationships_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_knowledge_graph_relationships.parquet"))
    return str(path) + "_knowledge_graph_relationships.parquet"


def _default_kg_summary_output_path(canonical_parquet_path: str) -> str:
    path = Path(canonical_parquet_path)
    if path.suffix.lower() == ".parquet":
        return str(path.with_name(f"{path.stem}_knowledge_graph_summary.json"))
    return str(path) + "_knowledge_graph_summary.json"


def _is_hf_cache_snapshot_path(path: str) -> bool:
    normalized = str(path or "")
    return "/.cache/huggingface/hub/datasets--" in normalized and "/snapshots/" in normalized


def _safe_artifact_base_dir(corpus_key: str, dataset_id: str, canonical_parquet_path: str) -> Path:
    canonical_path = Path(canonical_parquet_path).expanduser()
    if not _is_hf_cache_snapshot_path(str(canonical_path)):
        return canonical_path.parent
    repo_slug = str(dataset_id or corpus_key).replace("/", "__")
    target_root = Path.home() / ".ipfs_datasets" / "justicedao_rebuilds" / repo_slug / str(corpus_key)
    target_root.mkdir(parents=True, exist_ok=True)
    return target_root


def _artifact_output_path(base_dir: Path, canonical_parquet_path: str, suffix: str) -> str:
    canonical_path = Path(canonical_parquet_path)
    stem = canonical_path.stem
    if suffix.startswith("."):
        filename = f"{stem}{suffix}"
    else:
        filename = f"{stem}_{suffix}"
    return str((base_dir / filename).resolve())


def _content_addressed_row_identifier(row: Mapping[str, Any], *, join_field: str) -> str:
    payload = {
        str(key): value
        for key, value in dict(row).items()
        if str(key) not in {join_field, "cid", "ipfs_cid", "source_cid"}
    }
    try:
        return cid_for_obj(payload)
    except Exception:
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return f"sha256:{digest}"


def _ensure_join_field_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    join_field: str,
) -> tuple[List[Dict[str, Any]], int]:
    normalized: List[Dict[str, Any]] = []
    filled = 0
    for row in rows:
        row_dict = dict(row)
        join_value = str(row_dict.get(join_field) or "").strip()
        if not join_value:
            row_dict[join_field] = _content_addressed_row_identifier(row_dict, join_field=join_field)
            filled += 1
        normalized.append(row_dict)
    return normalized, filled


def _build_cid_index_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    join_field: str,
    config: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    candidate_fields: List[str] = []
    for key in ("state_code", "country_code", "identifier", "source_id", "official_cite", "citation", "name", "title_number", "section_number", "law_identifier", "article_identifier"):
        if key not in candidate_fields:
            candidate_fields.append(key)
    for key in list(config.get("title_fields") or []) + list(config.get("text_fields") or []):
        text = str(key).strip()
        if text and text not in candidate_fields:
            candidate_fields.append(text)

    out: List[Dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        entry: Dict[str, Any] = {join_field: row_dict.get(join_field)}
        for field in candidate_fields:
            if field in row_dict and row_dict.get(field) not in (None, ""):
                entry[field] = row_dict.get(field)
        out.append(entry)
    return out


def _build_bm25_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    join_field: str,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        title = _row_title(row_dict, title_fields)
        text = _row_text(row_dict, text_fields)
        if not (title or text):
            continue
        documents.append(
            {
                "id": str(row_dict.get(join_field) or ""),
                "document_id": str(row_dict.get(join_field) or ""),
                "title": title,
                "text": text,
                "metadata": row_dict,
            }
        )
    return list(build_bm25_index(documents).get("documents") or [])


def _build_generic_knowledge_graph_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    corpus_key: str,
    join_field: str,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    relationships: List[Dict[str, Any]] = []
    entity_ids: set[str] = set()
    relationship_ids: set[str] = set()

    def _add_entity(entity: Dict[str, Any]) -> None:
        entity_id = str(entity.get("id") or "").strip()
        if not entity_id or entity_id in entity_ids:
            return
        properties = entity.get("properties")
        if isinstance(properties, dict):
            entity["properties_json"] = json.dumps(properties, sort_keys=True, ensure_ascii=False)
        elif properties is not None:
            entity["properties_json"] = str(properties)
        entity.pop("properties", None)
        entity_ids.add(entity_id)
        entities.append(entity)

    def _add_relationship(rel: Dict[str, Any]) -> None:
        rel_id = str(rel.get("id") or "").strip()
        if not rel_id or rel_id in relationship_ids:
            return
        properties = rel.get("properties")
        if isinstance(properties, dict):
            rel["properties_json"] = json.dumps(properties, sort_keys=True, ensure_ascii=False)
        elif properties is not None:
            rel["properties_json"] = str(properties)
        rel.pop("properties", None)
        relationship_ids.add(rel_id)
        relationships.append(rel)

    for row in rows:
        row_dict = dict(row)
        join_value = str(row_dict.get(join_field) or "").strip()
        if not join_value:
            continue
        title = _row_title(row_dict, title_fields) or join_value
        text = _row_text(row_dict, text_fields)
        document_entity = {
            "id": join_value,
            "type": "legal_document",
            "label": title,
            "properties": {
                "corpus_key": corpus_key,
                "join_field": join_field,
                "state_code": row_dict.get("state_code"),
                "identifier": row_dict.get("identifier") or row_dict.get("source_id"),
            },
        }
        _add_entity(document_entity)

        if text.strip():
            parsed = parse_legal_document(text)
            graph = build_document_knowledge_graph(parsed, graph_id=join_value)
            for node in list(graph.get("nodes") or []):
                _add_entity(
                    {
                        "id": str(node.get("id") or ""),
                        "type": str(node.get("type") or "node"),
                        "label": str(node.get("label") or node.get("id") or ""),
                        "properties": dict(node.get("properties") or {}),
                    }
                )
            for edge in list(graph.get("edges") or []):
                rel_id = f"{edge.get('source')}->{edge.get('type')}->{edge.get('target')}"
                _add_relationship(
                    {
                        "id": rel_id,
                        "source": str(edge.get("source") or ""),
                        "target": str(edge.get("target") or ""),
                        "type": str(edge.get("type") or "RELATED_TO"),
                        "properties": {},
                    }
                )

        identifier = str(row_dict.get("identifier") or row_dict.get("source_id") or "").strip()
        if identifier:
            identifier_id = f"{join_value}:identifier"
            _add_entity(
                {
                    "id": identifier_id,
                    "type": "identifier",
                    "label": identifier,
                    "properties": {},
                }
            )
            _add_relationship(
                {
                    "id": f"{join_value}:identified_by",
                    "source": join_value,
                    "target": identifier_id,
                    "type": "IDENTIFIED_BY",
                    "properties": {},
                }
            )

        citation = str(row_dict.get("official_cite") or row_dict.get("citation") or "").strip()
        if citation:
            citation_id = f"{join_value}:citation"
            _add_entity(
                {
                    "id": citation_id,
                    "type": "citation",
                    "label": citation,
                    "properties": {},
                }
            )
            _add_relationship(
                {
                    "id": f"{join_value}:has_citation",
                    "source": join_value,
                    "target": citation_id,
                    "type": "HAS_CITATION",
                    "properties": {},
                }
            )

        state_code = str(row_dict.get("state_code") or "").strip().upper()
        if state_code:
            state_id = f"jurisdiction:{state_code}"
            _add_entity(
                {
                    "id": state_id,
                    "type": "jurisdiction",
                    "label": state_code,
                    "properties": {"state_code": state_code},
                }
            )
            _add_relationship(
                {
                    "id": f"{join_value}:in_jurisdiction",
                    "source": join_value,
                    "target": state_id,
                    "type": "IN_JURISDICTION",
                    "properties": {},
                }
            )

        title_number = str(row_dict.get("title_number") or "").strip()
        if title_number:
            title_id = f"usc:title:{title_number}"
            _add_entity(
                {
                    "id": title_id,
                    "type": "usc_title",
                    "label": f"Title {title_number}",
                    "properties": {"title_number": title_number},
                }
            )
            _add_relationship(
                {
                    "id": f"{join_value}:in_title",
                    "source": join_value,
                    "target": title_id,
                    "type": "IN_TITLE",
                    "properties": {},
                }
            )

        section_number = str(row_dict.get("section_number") or "").strip()
        if section_number:
            section_id = f"{join_value}:section:{section_number}"
            _add_entity(
                {
                    "id": section_id,
                    "type": "section",
                    "label": section_number,
                    "properties": {"section_number": section_number},
                }
            )
            _add_relationship(
                {
                    "id": f"{join_value}:has_section",
                    "source": join_value,
                    "target": section_id,
                    "type": "HAS_SECTION",
                    "properties": {},
                }
            )

    summary = {
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "document_count": len([entity for entity in entities if entity.get("type") == "legal_document"]),
    }
    return entities, relationships, summary


_LEGAL_SIGNAL_PATTERNS = (
    "shall",
    "must",
    "means",
    "includes",
    "prohibited",
    "required",
    "penalty",
    "court",
    "jurisdiction",
    "section",
    "subsection",
    "chapter",
    "rule",
    "statute",
)

_LLM_TITLE_PENALTY_PATTERNS = (
    "glossary",
    "constitution",
    "introduced",
    "index",
    "table of contents",
    "preface",
)

_STATE_LAWS_TITLE_PENALTY_PATTERNS = (
    "house",
    "senate",
    "bills in committee",
    "interactive district map",
    "current members",
    "by session",
    "alphabetical",
    "statistics",
    "journals",
    "finance committees",
    "legislative branch",
    "public opinion",
    "announcement mailing list",
    "tour information",
    "rentals needed",
)

_STATE_LAWS_TEXT_PENALTY_PATTERNS = (
    "home senate house bills & laws",
    "this page is no longer used",
    "34th legislature",
    "33rd legislature",
    "member information",
    "current members",
    "past members",
    "district",
    "party:",
    "city:",
    "committee",
    "calendar",
    "live now",
    "public opinion messaging system",
)


def _audit_canonical_corpus_quality(
    rows: Sequence[Mapping[str, Any]],
    *,
    corpus_key: str,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
) -> Dict[str, Any]:
    normalized_corpus = str(corpus_key or "").strip().lower()
    total_rows = len(list(rows or []))
    if total_rows <= 0:
        return {
            "corpus_key": normalized_corpus,
            "row_count": 0,
            "status": "empty",
            "issues": ["no_rows"],
        }

    navigation_like_count = 0
    identified_row_count = 0
    section_like_identifier_count = 0
    samples: List[Dict[str, Any]] = []

    for row in rows:
        row_dict = dict(row)
        title = _row_title(row_dict, title_fields)
        text = _row_text(row_dict, text_fields)
        identifier = str(row_dict.get("identifier") or "").strip()
        source_id = str(row_dict.get("source_id") or "").strip()
        lowered_title = title.lower()
        lowered_text = text.lower()
        title_penalties = sum(1 for token in _STATE_LAWS_TITLE_PENALTY_PATTERNS if token in lowered_title)
        text_penalties = sum(1 for token in _STATE_LAWS_TEXT_PENALTY_PATTERNS if token in lowered_text)
        is_navigation_like = (title_penalties + text_penalties) > 0
        if is_navigation_like:
            navigation_like_count += 1
            if len(samples) < 5:
                samples.append(
                    {
                        "title": title,
                        "identifier": identifier,
                        "source_id": source_id,
                        "classification": "navigation_like",
                    }
                )
        if identifier:
            identified_row_count += 1
        if identifier and ("§" in identifier or re.search(r"\b\d+(\.\d+)+\b", identifier)):
            section_like_identifier_count += 1

    issues: List[str] = []
    navigation_ratio = float(navigation_like_count) / float(total_rows)
    identified_ratio = float(identified_row_count) / float(total_rows)
    section_like_ratio = float(section_like_identifier_count) / float(total_rows)
    if normalized_corpus == "state_laws":
        if navigation_ratio >= 0.30:
            issues.append("navigation_like_content_dominates")
        if identified_ratio < 0.20:
            issues.append("few_rows_have_identifiers")
        if section_like_ratio < 0.10:
            issues.append("few_rows_look_like_statute_sections")

    status = "healthy" if not issues else "degraded"
    return {
        "corpus_key": normalized_corpus,
        "row_count": total_rows,
        "status": status,
        "issues": issues,
        "navigation_like_row_count": navigation_like_count,
        "navigation_like_ratio": navigation_ratio,
        "identified_row_count": identified_row_count,
        "identified_row_ratio": identified_ratio,
        "section_like_identifier_count": section_like_identifier_count,
        "section_like_identifier_ratio": section_like_ratio,
        "sample_rows": samples,
    }


def _build_corpus_quality_recovery_recommendation(
    *,
    corpus_key: str,
    dataset_id: str,
    state_code: Optional[str],
    quality_summary: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    issues = [str(item) for item in list(quality_summary.get("issues") or []) if str(item).strip()]
    if not issues:
        return None
    normalized_corpus = str(corpus_key or "").strip().lower()
    normalized_state = _normalize_state_code(state_code)
    query_parts: List[str] = []
    if normalized_corpus == "state_laws":
        state_hint = f" {normalized_state}" if normalized_state else ""
        query_parts.append(f"{state_hint.strip()} statutes site:.gov OR site:.us".strip())
        query_parts.append("official code")
        query_parts.append("legislature")
    else:
        query_parts.append(str(normalized_corpus or dataset_id))

    return {
        "recommended_action": "recover_source_rows",
        "corpus_key": normalized_corpus,
        "dataset_id": dataset_id,
        "state_code": normalized_state,
        "reason": f"Corpus quality degraded: {', '.join(issues)}",
        "recovery_query": " ".join(part for part in query_parts if part).strip(),
        "publish_target": {
            "dataset_id": dataset_id,
            "state_code": normalized_state,
        },
        "sample_problem_rows": list(quality_summary.get("sample_rows") or [])[:5],
    }


def _write_corpus_quality_recovery_manifest_draft(
    *,
    recommendation: Mapping[str, Any],
    artifact_base_dir: Path,
) -> Optional[Dict[str, Any]]:
    if not recommendation:
        return None
    corpus_key = str(recommendation.get("corpus_key") or "").strip().lower()
    dataset_id = str(recommendation.get("dataset_id") or "").strip()
    state_code = _normalize_state_code(recommendation.get("state_code"))
    query = str(recommendation.get("recovery_query") or "").strip()
    if not (corpus_key and dataset_id and query):
        return None

    if corpus_key == "state_laws" and state_code:
        citation_text = f"{state_code} official statutes"
    else:
        citation_text = f"{corpus_key} recovery"

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    manifest_dir = (artifact_base_dir / "source_recovery" / f"{stamp}_{corpus_key}_{(state_code or 'corpus').lower()}").resolve()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "recovery_manifest.json"
    payload = {
        "citation_text": citation_text,
        "normalized_citation": citation_text,
        "corpus_key": corpus_key,
        "hf_dataset_id": dataset_id,
        "state_code": state_code,
        "search_query": query,
        "generated_at": datetime.utcnow().isoformat(),
        "candidates": [],
        "archived_sources": [],
        "draft_source": "canonical_corpus_quality_recovery",
        "reason": str(recommendation.get("reason") or ""),
        "sample_problem_rows": list(recommendation.get("sample_problem_rows") or []),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    promotion_preview = None
    release_plan_preview = None
    try:
        promotion_preview = build_recovery_manifest_promotion_row(str(manifest_path))
    except Exception:
        promotion_preview = None
    try:
        release_plan_preview = build_recovery_manifest_release_plan(str(manifest_path))
    except Exception:
        release_plan_preview = None

    return {
        "manifest_path": str(manifest_path),
        "manifest_directory": str(manifest_dir),
        "promotion_preview": promotion_preview,
        "release_plan_preview": release_plan_preview,
    }


def _execute_corpus_quality_recovery(
    *,
    recommendation: Mapping[str, Any],
    hf_token: Optional[str],
    max_candidates: int,
    archive_top_k: int,
    publish_to_hf: bool,
) -> Optional[Dict[str, Any]]:
    if not recommendation:
        return None
    citation_text = (
        f"{str(recommendation.get('state_code') or '').strip()} official statutes".strip()
        if str(recommendation.get("corpus_key") or "").strip().lower() == "state_laws"
        else str(recommendation.get("corpus_key") or "corpus recovery")
    )
    if not citation_text.strip():
        return None
    return asyncio.run(
        recover_missing_legal_citation_source(
            citation_text=citation_text,
            normalized_citation=citation_text,
            corpus_key=str(recommendation.get("corpus_key") or "") or None,
            state_code=str(recommendation.get("state_code") or "") or None,
            metadata={
                "candidate_corpora": [str(recommendation.get("corpus_key") or "")],
            },
            max_candidates=max(1, int(max_candidates or 8)),
            archive_top_k=max(0, int(archive_top_k or 3)),
            publish_to_hf=bool(publish_to_hf),
            hf_token=hf_token,
        )
    )


def _score_row_for_llm_knowledge_graph(
    row: Mapping[str, Any],
    *,
    corpus_key: Optional[str] = None,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
) -> float:
    title = _row_title(row, title_fields)
    text = _row_text(row, text_fields)
    combined = f"{title}\n{text}".strip()
    if not combined:
        return -1.0

    lowered = combined.lower()
    lowered_title = str(title or "").strip().lower()
    signal_hits = sum(1 for token in _LEGAL_SIGNAL_PATTERNS if token in lowered)
    title_penalty_hits = sum(1 for token in _LLM_TITLE_PENALTY_PATTERNS if token in lowered_title)
    line_count = combined.count("\n") + 1
    text_length = len(text)
    title_length = len(title)
    score = float(text_length) + (signal_hits * 250.0) + (line_count * 25.0) + (title_length * 0.1) - (title_penalty_hits * 5000.0)

    normalized_corpus = str(corpus_key or "").strip().lower()
    if normalized_corpus == "state_laws":
        state_title_penalties = sum(1 for token in _STATE_LAWS_TITLE_PENALTY_PATTERNS if token in lowered_title)
        state_text_penalties = sum(1 for token in _STATE_LAWS_TEXT_PENALTY_PATTERNS if token in lowered)
        identifier = str(row.get("identifier") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        if identifier:
            score += 4000.0
        else:
            score -= 2500.0
        if "section-" in source_id.lower():
            score -= 1500.0
        score -= state_title_penalties * 8000.0
        score -= state_text_penalties * 4000.0
    return score


def _select_rows_for_llm_knowledge_graph(
    rows: Sequence[Mapping[str, Any]],
    *,
    corpus_key: Optional[str] = None,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
    max_rows: int,
) -> List[Dict[str, Any]]:
    items = [dict(row) for row in list(rows or [])]
    row_limit = max(0, int(max_rows or 0))
    if row_limit <= 0 or row_limit >= len(items):
        return items

    ranked = sorted(
        items,
        key=lambda row: _score_row_for_llm_knowledge_graph(
            row,
            corpus_key=corpus_key,
            title_fields=title_fields,
            text_fields=text_fields,
        ),
        reverse=True,
    )
    return ranked[:row_limit]


def _merge_router_knowledge_graph_rows(
    *,
    rows: Sequence[Mapping[str, Any]],
    corpus_key: str,
    dataset_id: str,
    join_field: str,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
    base_entities: Sequence[Mapping[str, Any]],
    base_relationships: Sequence[Mapping[str, Any]],
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    max_rows: int = 0,
    max_chars: int = 700,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    from ..legal_data.rich_docket_enrichment import analyze_document_with_routers

    entities = [dict(item) for item in list(base_entities or [])]
    relationships = [dict(item) for item in list(base_relationships or [])]
    entity_ids = {str(item.get("id") or "").strip() for item in entities if str(item.get("id") or "").strip()}
    relationship_ids = {str(item.get("id") or "").strip() for item in relationships if str(item.get("id") or "").strip()}

    llm_document_count = 0
    llm_entity_count = 0
    llm_relationship_count = 0
    llm_skipped_count = 0
    missing_document_id_count = 0
    missing_text_count = 0
    no_analysis_count = 0
    providers_used: List[str] = []
    models_used: List[str] = []
    sampled_rows: List[Dict[str, Any]] = []
    failed_samples: List[Dict[str, Any]] = []

    row_limit = max(0, int(max_rows or 0))
    candidate_rows = _select_rows_for_llm_knowledge_graph(
        rows,
        corpus_key=corpus_key,
        title_fields=title_fields,
        text_fields=text_fields,
        max_rows=row_limit,
    )

    def _normalize_entity(entity: Mapping[str, Any], *, document_id: str) -> Dict[str, Any]:
        raw_id = str(entity.get("id") or "").strip()
        entity_id = raw_id or f"{document_id}:router_entity:{hashlib.sha256(canonical_json_bytes(entity)).hexdigest()[:16]}"
        return {
            "id": entity_id,
            "type": str(entity.get("type") or "router_entity"),
            "label": str(entity.get("label") or entity_id),
            "properties_json": json.dumps(
                {
                    "backend": "llm_router",
                    "document_id": document_id,
                    "source_entity_id": raw_id or None,
                    **{
                        str(key): value
                        for key, value in dict(entity).items()
                        if str(key) not in {"id", "type", "label"}
                    },
                },
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
        }

    def _normalize_relationship(rel: Mapping[str, Any], *, document_id: str) -> Optional[Dict[str, Any]]:
        source = str(rel.get("source") or "").strip()
        target = str(rel.get("target") or "").strip()
        rel_type = str(rel.get("type") or "RELATED_TO").strip() or "RELATED_TO"
        if not (source and target):
            return None
        rel_id = str(rel.get("id") or "").strip() or f"{document_id}:router_rel:{source}:{rel_type}:{target}"
        return {
            "id": rel_id,
            "source": source,
            "target": target,
            "type": rel_type,
            "properties_json": json.dumps(
                {
                    "backend": "llm_router",
                    "document_id": document_id,
                    **{
                        str(key): value
                        for key, value in dict(rel).items()
                        if str(key) not in {"id", "source", "target", "type"}
                    },
                },
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
        }

    for row in candidate_rows:
        row_dict = dict(row)
        document_id = str(row_dict.get(join_field) or "").strip()
        title = _row_title(row_dict, title_fields) or document_id
        sampled_rows.append(
            {
                "document_id": document_id,
                "title": title,
                "score": _score_row_for_llm_knowledge_graph(
                    row_dict,
                    corpus_key=corpus_key,
                    title_fields=title_fields,
                    text_fields=text_fields,
                ),
            }
        )
        if not document_id:
            llm_skipped_count += 1
            missing_document_id_count += 1
            continue
        text = _row_text(row_dict, text_fields).strip()
        if not text:
            llm_skipped_count += 1
            missing_text_count += 1
            failed_samples.append(
                {
                    "document_id": document_id,
                    "title": title,
                    "status": "missing_text",
                }
            )
            continue
        analysis_result = analyze_document_with_routers(
            docket_id=f"{corpus_key}:{dataset_id}",
            case_name=dataset_id,
            court=corpus_key,
            document_id=document_id,
            title=title,
            text=text[: max(192, int(max_chars or 700))],
            source_url=str(row_dict.get("source_url") or ""),
            provider=provider,
            model_name=model_name,
            return_diagnostics=True,
        )
        if isinstance(analysis_result, tuple) and len(analysis_result) == 2:
            analysis, diagnostics = analysis_result
        else:
            analysis = analysis_result
            diagnostics = {}
        if analysis is None:
            llm_skipped_count += 1
            no_analysis_count += 1
            failed_samples.append(
                {
                    "document_id": document_id,
                    "title": title,
                    "status": str(diagnostics.get("status") or "no_analysis"),
                    "provider_name": diagnostics.get("provider_name"),
                    "model_name": diagnostics.get("model_name"),
                    "raw_response_preview": diagnostics.get("raw_response_preview"),
                    "error": diagnostics.get("error"),
                }
            )
            continue
        llm_document_count += 1
        provenance = dict(analysis.provenance or {})
        provider_name = str(provenance.get("provider") or "").strip()
        routed_model = str(provenance.get("model_name") or "").strip()
        if provider_name and provider_name not in providers_used:
            providers_used.append(provider_name)
        if routed_model and routed_model not in models_used:
            models_used.append(routed_model)

        for entity in list(analysis.entities or []):
            normalized = _normalize_entity(entity, document_id=document_id)
            entity_id = str(normalized.get("id") or "")
            if entity_id in entity_ids:
                continue
            entity_ids.add(entity_id)
            entities.append(normalized)
            llm_entity_count += 1

        for rel in list(analysis.relationships or []):
            normalized_rel = _normalize_relationship(rel, document_id=document_id)
            if normalized_rel is None:
                continue
            rel_id = str(normalized_rel.get("id") or "")
            if rel_id in relationship_ids:
                continue
            relationship_ids.add(rel_id)
            relationships.append(normalized_rel)
            llm_relationship_count += 1

    return entities, relationships, {
        "enabled": True,
        "analyzed_document_count": llm_document_count,
        "skipped_document_count": llm_skipped_count,
        "entity_count": llm_entity_count,
        "relationship_count": llm_relationship_count,
        "missing_document_id_count": missing_document_id_count,
        "missing_text_count": missing_text_count,
        "no_analysis_count": no_analysis_count,
        "providers": providers_used,
        "model_names": models_used,
        "max_rows": row_limit,
        "max_chars": max(192, int(max_chars or 700)),
        "sampled_rows": sampled_rows,
        "failed_samples": failed_samples[:10],
    }


def _normalize_value_for_parquet(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return str(value)


def _normalize_rows_for_parquet(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalized_rows.append(
            {
                str(key): _normalize_value_for_parquet(value)
                for key, value in dict(row).items()
            }
        )
    return normalized_rows


def _canonical_only_overrides(
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]],
) -> Dict[str, Sequence[str] | str]:
    filtered: Dict[str, Sequence[str] | str] = {}
    for key, value in dict(parquet_file_overrides or {}).items():
        items = [str(value)] if isinstance(value, str) else [str(item) for item in value]
        canonical_items = [
            item
            for item in items
            if not item.endswith("_embeddings.parquet")
            and not item.endswith("_metadata.parquet")
            and not item.endswith(".faiss")
        ]
        if canonical_items:
            filtered[str(key)] = canonical_items if len(canonical_items) > 1 else canonical_items[0]
    return filtered


def _is_canonical_parquet_candidate(path: str) -> bool:
    text = str(path or "").strip()
    if not text.endswith(".parquet"):
        return False
    lowered = text.lower()
    if lowered.endswith("_embeddings.parquet"):
        return False
    if lowered.endswith("_metadata.parquet"):
        return False
    if lowered.endswith("_cid_index.parquet"):
        return False
    if "cid_index.parquet" in lowered:
        return False
    return True


def _build_semantic_text_for_row(
    row: Mapping[str, Any],
    *,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
) -> str:
    title = _row_title(row, title_fields)
    text = _row_text(row, text_fields)
    if title and text:
        return f"{title}\n{text}"
    return title or text


def _lexical_query_rows(
    parquet_path: str,
    *,
    query_text: str,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
    state_code: Optional[str],
    top_k: int,
    candidate_limit: int = 250,
) -> List[Dict[str, Any]]:
    schema = _schema_for_parquet(parquet_path)
    searchable_fields = _first_available(list(title_fields) + list(text_fields), schema)
    if not searchable_fields:
        return []

    lowered_query = str(query_text or "").strip().lower()
    if not lowered_query:
        return []

    rows: List[Dict[str, Any]] = []
    try:
        import duckdb

        con = duckdb.connect()
        try:
            text_clause = "(" + " OR ".join(
                f"lower(CAST({field} AS VARCHAR)) LIKE ?" for field in searchable_fields
            ) + ")"
            where_parts = [text_clause]
            params: List[Any] = [f"%{lowered_query}%"] * len(searchable_fields)
            if state_code and "state_code" in schema:
                where_parts.insert(0, "upper(CAST(state_code AS VARCHAR)) = ?")
                params.insert(0, state_code)
            escaped_parquet_path = parquet_path.replace("'", "''")
            sql = (
                f"SELECT * FROM read_parquet('{escaped_parquet_path}') "
                f"WHERE {' AND '.join(where_parts)} "
                f"LIMIT {int(candidate_limit)}"
            )
            cursor = con.execute(sql, params)
            rows = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
        finally:
            con.close()
    except Exception:
        candidate_rows = _load_rows_from_source(parquet_path)
        lowered_terms = [term for term in re.split(r"\s+", lowered_query) if term]
        for row in candidate_rows:
            if state_code and str(row.get("state_code") or "").strip().upper() != str(state_code).strip().upper():
                continue
            haystack = "\n".join(
                str(row.get(field) or "").lower()
                for field in searchable_fields
                if str(row.get(field) or "").strip()
            )
            if not haystack:
                continue
            if lowered_query in haystack or any(term in haystack for term in lowered_terms):
                rows.append(dict(row))
            if len(rows) >= int(candidate_limit):
                break

    docs = [
        {
            "id": str(index),
            "title": _row_title(row, title_fields),
            "text": _row_text(row, text_fields),
            "metadata": dict(row),
        }
        for index, row in enumerate(rows, start=1)
    ]
    ranked = bm25_search_documents(query_text, docs, top_k=top_k)
    results: List[Dict[str, Any]] = []
    for item in ranked:
        metadata = dict(item.get("metadata") or {})
        results.append(
            {
                "title": item.get("title"),
                "score": float(item.get("score") or 0.0),
                "matched_terms": list(item.get("matched_terms") or []),
                "row": metadata,
            }
        )
    return results


def _semantic_query_rows(
    parquet_path: str,
    embeddings_path: str,
    *,
    query_text: str,
    join_field: str,
    title_fields: Sequence[str],
    text_fields: Sequence[str],
    state_code: Optional[str],
    top_k: int,
) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    canonical_rows = pq.read_table(parquet_path).to_pylist()
    embeddings_rows = pq.read_table(embeddings_path).to_pylist()
    if not canonical_rows or not embeddings_rows:
        return []

    index_by_join = {
        str(row.get(join_field) or ""): dict(row)
        for row in canonical_rows
        if str(row.get(join_field) or "")
    }
    sample_vector = _coerce_embedding_vector(embeddings_rows[0].get("embedding"))
    if not sample_vector:
        return []

    sample_backend = str(embeddings_rows[0].get("embedding_backend") or "").strip()
    sample_model = str(embeddings_rows[0].get("embedding_model") or "").strip()
    query_backend = sample_backend or "embeddings_router"
    normalized_model = sample_model.lower()
    if not sample_backend and (
        normalized_model.startswith("local")
        or normalized_model.endswith("-test")
        or normalized_model == "test"
    ):
        query_backend = "local_hashed_term_projection"

    query_vector = embed_query_for_backend(
        query_text,
        backend=query_backend,
        dimension=len(sample_vector),
        model_name=sample_model or None,
    )
    query_vector = _fit_vector_dimension(query_vector, len(sample_vector))
    if not query_vector:
        return []

    scored: List[Dict[str, Any]] = []
    normalized_state = _normalize_state_code(state_code)
    for row in embeddings_rows:
        if normalized_state and str(row.get("state_code") or "").strip().upper() not in {"", normalized_state}:
            continue
        join_value = str(row.get(join_field) or "")
        if not join_value:
            continue
        base_row = index_by_join.get(join_value)
        if not base_row:
            continue
        vector = _coerce_embedding_vector(row.get("embedding"))
        vector = _fit_vector_dimension(vector, len(query_vector))
        if not vector:
            continue
        score = vector_dot(query_vector, vector)
        scored.append(
            {
                "title": _row_title(base_row, title_fields),
                "score": float(score),
                "semantic_text": row.get("semantic_text"),
                "row": dict(base_row),
            }
        )
    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return scored[:top_k]


def _faiss_query_rows(
    parquet_path: str,
    faiss_index_path: str,
    faiss_metadata_path: str,
    *,
    query_text: str,
    join_field: str,
    title_fields: Sequence[str],
    state_code: Optional[str],
    top_k: int,
) -> List[Dict[str, Any]]:
    import faiss
    import numpy as np
    import pyarrow.parquet as pq

    canonical_rows = pq.read_table(parquet_path).to_pylist()
    metadata_rows = pq.read_table(faiss_metadata_path).to_pylist()
    if not canonical_rows or not metadata_rows:
        return []

    index = faiss.read_index(faiss_index_path)
    dimension = int(index.d) if hasattr(index, "d") else 0
    if dimension <= 0:
        return []

    query_vector = embed_query_for_backend(
        query_text,
        backend="embeddings_router",
        dimension=dimension,
    )
    query_vector = _fit_vector_dimension(query_vector, dimension)
    if not query_vector:
        return []

    query_array = np.asarray([query_vector], dtype="float32")
    scores, neighbors = index.search(query_array, max(1, int(top_k)))

    metadata_by_vector_id = {
        int(row.get("vector_id")): dict(row)
        for row in metadata_rows
        if row.get("vector_id") is not None
    }
    canonical_by_join = {
        str(row.get(join_field) or ""): dict(row)
        for row in canonical_rows
        if str(row.get(join_field) or "")
    }

    normalized_state = _normalize_state_code(state_code)
    results: List[Dict[str, Any]] = []
    for distance, vector_id in zip(list(scores[0]), list(neighbors[0])):
        vector_id = int(vector_id)
        if vector_id < 0:
            continue
        meta = metadata_by_vector_id.get(vector_id)
        if not meta:
            continue
        join_value = str(meta.get(join_field) or "")
        if not join_value:
            continue
        row = canonical_by_join.get(join_value)
        if not row:
            continue
        if normalized_state and str(row.get("state_code") or "").strip().upper() not in {"", normalized_state}:
            continue
        results.append(
            {
                "title": _row_title(row, title_fields),
                "score": float(distance),
                "semantic_text": meta.get("semantic_text"),
                "row": dict(row),
            }
        )
    return results[:top_k]


def build_canonical_corpus_semantic_index(
    corpus_key: str,
    *,
    canonical_parquet_path: str,
    state_code: Optional[str] = None,
    embeddings_output_path: Optional[str] = None,
    faiss_index_output_path: Optional[str] = None,
    faiss_metadata_output_path: Optional[str] = None,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    build_faiss: bool = True,
) -> CanonicalCorpusIndexBuildResult:
    import pyarrow as pa
    import pyarrow.parquet as pq

    normalized_corpus = str(corpus_key or "").strip().lower()
    if normalized_corpus not in _CANONICAL_QUERY_DATASETS:
        raise KeyError(f"Unsupported canonical legal corpus: {corpus_key}")

    config = _CANONICAL_QUERY_DATASETS[normalized_corpus]
    dataset_id = str(config["dataset_id"])
    normalized_state = _normalize_state_code(state_code)
    join_field = str(config["join_field"])
    title_fields = list(config["title_fields"])
    text_fields = list(config["text_fields"])

    rows = pq.read_table(canonical_parquet_path).to_pylist()
    filtered_rows: List[Dict[str, Any]] = []
    semantic_texts: List[str] = []
    for row in rows:
        row_dict = dict(row)
        if normalized_state and str(row_dict.get("state_code") or "").strip().upper() not in {"", normalized_state}:
            continue
        join_value = str(row_dict.get(join_field) or "").strip()
        if not join_value:
            continue
        semantic_text = _build_semantic_text_for_row(row_dict, title_fields=title_fields, text_fields=text_fields)
        if not semantic_text.strip():
            continue
        filtered_rows.append(row_dict)
        semantic_texts.append(semantic_text)

    if not filtered_rows:
        raise ValueError("No rows with join keys and semantic text were available to index")

    vectors, metadata = embed_texts_with_router_or_local(
        semantic_texts,
        fallback_dimension=384,
        provider=provider,
        model_name=model_name,
        device=device,
    )
    if not vectors:
        raise ValueError("Embedding generation returned no vectors")

    embeddings_output = embeddings_output_path or _default_embeddings_output_path(canonical_parquet_path)
    faiss_index_output = faiss_index_output_path or _default_faiss_output_path(canonical_parquet_path)
    faiss_metadata_output = faiss_metadata_output_path or _default_faiss_metadata_output_path(canonical_parquet_path)

    embedding_rows: List[Dict[str, Any]] = []
    faiss_rows: List[Dict[str, Any]] = []
    for vector_id, (row, semantic_text, vector) in enumerate(zip(filtered_rows, semantic_texts, vectors)):
        emb_row: Dict[str, Any] = {
            join_field: row.get(join_field),
            "semantic_text": semantic_text,
            "embedding_backend": metadata.get("backend") or "local_hashed_term_projection",
            "embedding_model": metadata.get("model_name") or "",
            "embedding": [float(item) for item in vector],
        }
        if "state_code" in row:
            emb_row["state_code"] = row.get("state_code")
        embedding_rows.append(emb_row)

        faiss_row: Dict[str, Any] = {
            "vector_id": vector_id,
            join_field: row.get(join_field),
            "semantic_text": semantic_text,
        }
        for field in ("identifier", "name", "source_id", "agency", "legislation_type", "date_published", "state_code"):
            if field in row:
                faiss_row[field] = row.get(field)
        faiss_rows.append(faiss_row)

    Path(embeddings_output).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(embedding_rows), embeddings_output)

    faiss_index_written: Optional[str] = None
    faiss_metadata_written: Optional[str] = None
    if build_faiss:
        try:
            import faiss
            import numpy as np

            if hasattr(faiss, "IndexFlatIP"):
                index = faiss.IndexFlatIP(len(vectors[0]))
            elif hasattr(faiss, "IndexFlatL2"):
                index = faiss.IndexFlatL2(len(vectors[0]))
            elif hasattr(faiss, "index_factory"):
                index = faiss.index_factory(len(vectors[0]), "Flat", getattr(faiss, "METRIC_INNER_PRODUCT", 0))
            else:
                raise RuntimeError("No usable faiss index constructor found")

            vector_matrix = np.asarray(vectors, dtype="float32")
            index.add(vector_matrix)
            Path(faiss_index_output).parent.mkdir(parents=True, exist_ok=True)
            Path(faiss_metadata_output).parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(index, faiss_index_output)
            pq.write_table(pa.Table.from_pylist(faiss_rows), faiss_metadata_output)
            faiss_index_written = faiss_index_output
            faiss_metadata_written = faiss_metadata_output
        except Exception:
            faiss_index_written = None
            faiss_metadata_written = None

    return CanonicalCorpusIndexBuildResult(
        corpus_key=normalized_corpus,
        dataset_id=dataset_id,
        canonical_parquet_path=str(canonical_parquet_path),
        embeddings_parquet_path=str(embeddings_output),
        faiss_index_path=faiss_index_written,
        faiss_metadata_path=faiss_metadata_written,
        row_count=len(filtered_rows),
        vector_dimension=len(vectors[0]) if vectors else 0,
        backend=str(metadata.get("backend") or ""),
        provider=str(metadata.get("provider") or ""),
        model_name=str(metadata.get("model_name") or ""),
        join_field=join_field,
        state_code=normalized_state,
    )


def publish_canonical_corpus_semantic_index(
    index_result: CanonicalCorpusIndexBuildResult | Mapping[str, Any],
    *,
    hf_token: Optional[str] = None,
    repo_id: Optional[str] = None,
    include_canonical_parquet: bool = False,
    canonical_repo_path: Optional[str] = None,
    embeddings_repo_path: Optional[str] = None,
    faiss_index_repo_path: Optional[str] = None,
    faiss_metadata_repo_path: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> CanonicalCorpusIndexPublishResult:
    from huggingface_hub import HfApi

    payload = asdict(index_result) if isinstance(index_result, CanonicalCorpusIndexBuildResult) else dict(index_result)
    corpus_key = str(payload.get("corpus_key") or "").strip().lower()
    if corpus_key not in _CANONICAL_QUERY_DATASETS:
        raise KeyError(f"Unsupported canonical legal corpus: {corpus_key}")
    config = _CANONICAL_QUERY_DATASETS[corpus_key]
    dataset_id = str(repo_id or payload.get("dataset_id") or config["dataset_id"])
    state_code = _normalize_state_code(payload.get("state_code"))

    api = HfApi(token=hf_token) if hf_token else HfApi()
    effective_commit_message = commit_message or f"Update semantic index artifacts for {corpus_key}"

    uploads: List[Dict[str, Any]] = []

    def _upload(local_path: Optional[str], repo_path: Optional[str]) -> None:
        local_value = str(local_path or "").strip()
        repo_value = str(repo_path or "").strip()
        if not local_value or not repo_value:
            return
        api.upload_file(
            path_or_fileobj=local_value,
            path_in_repo=repo_value,
            repo_id=dataset_id,
            repo_type="dataset",
            commit_message=effective_commit_message,
        )
        uploads.append(
            {
                "local_path": local_value,
                "repo_path": repo_value,
            }
        )

    if include_canonical_parquet:
        _upload(
            payload.get("canonical_parquet_path"),
            canonical_repo_path or _first_remote_publish_path(
                config,
                key_files="parquet_files",
                key_templates="parquet_templates",
                state_code=state_code,
            ),
        )

    _upload(
        payload.get("embeddings_parquet_path"),
        embeddings_repo_path or _first_remote_publish_path(
            config,
            key_files="publish_embeddings_files",
            key_templates="publish_embeddings_templates",
            state_code=state_code,
        ),
    )
    _upload(
        payload.get("faiss_index_path"),
        faiss_index_repo_path or _first_remote_publish_path(
            config,
            key_files="publish_faiss_index_files",
            key_templates="publish_faiss_index_templates",
            state_code=state_code,
        ),
    )
    _upload(
        payload.get("faiss_metadata_path"),
        faiss_metadata_repo_path or _first_remote_publish_path(
            config,
            key_files="publish_faiss_metadata_files",
            key_templates="publish_faiss_metadata_templates",
            state_code=state_code,
        ),
    )

    return CanonicalCorpusIndexPublishResult(
        corpus_key=corpus_key,
        dataset_id=dataset_id,
        uploaded_files=uploads,
        upload_count=len(uploads),
        commit_message=effective_commit_message,
    )


def canonical_corpus_artifact_build_result_to_dict(result: CanonicalCorpusArtifactBuildResult) -> Dict[str, Any]:
    return asdict(result)


def justicedao_library_rebuild_result_to_dict(result: JusticeDAOLibraryRebuildResult) -> Dict[str, Any]:
    return {
        "artifact_results": [canonical_corpus_artifact_build_result_to_dict(item) for item in result.artifact_results],
        "errors": [dict(item) for item in result.errors],
        "success_count": result.success_count,
        "failure_count": result.failure_count,
    }


def justicedao_rebuild_plan_to_dict(plan: JusticeDAORebuildPlan) -> Dict[str, Any]:
    return {
        "target_count": len(plan.targets),
        "batch_count": len(plan.batches),
        "recommendation_count": len(plan.recommendations),
        "targets": [asdict(item) for item in plan.targets],
        "batches": [[asdict(item) for item in batch] for batch in plan.batches],
        "recommendations": [asdict(item) for item in plan.recommendations],
    }


def render_justicedao_rebuild_plan_markdown(plan: JusticeDAORebuildPlan) -> str:
    lines: List[str] = ["# JusticeDAO Rebuild Plan", ""]
    lines.append(f"Targets: {len(plan.targets)}")
    lines.append(f"Batches: {len(plan.batches)}")
    lines.append(f"Recommendations: {len(plan.recommendations)}")
    lines.append("")

    if plan.targets:
        lines.append("## Rebuild Targets")
        lines.append("")
        for target in plan.targets:
            detail = f"- {target.corpus_key}: {target.dataset_id} -> {target.parquet_path}"
            if target.state_code:
                detail += f" (state={target.state_code})"
            lines.append(detail)
        lines.append("")

    if plan.batches:
        lines.append("## Batches")
        lines.append("")
        for index, batch in enumerate(plan.batches, start=1):
            labels = ", ".join(
                f"{item.corpus_key}{f'[{item.state_code}]' if item.state_code else ''}"
                for item in batch
            )
            lines.append(f"- Batch {index}: {labels}")
        lines.append("")

    if plan.recommendations:
        lines.append("## Recommendations")
        lines.append("")
        for item in plan.recommendations:
            if item.status == "registered":
                lines.append(
                    f"- {item.country_code}: canonical registry includes {', '.join(item.canonical_corpus_keys)};"
                    f" awaiting observed datasets"
                )
            elif item.status == "in_progress":
                lines.append(
                    f"- {item.country_code}: observed {', '.join(item.existing_dataset_ids)};"
                    f" awaiting canonical registration as {item.proposed_corpus_key}"
                )
            else:
                lines.append(
                    f"- {item.country_code}: missing dataset; propose {item.proposed_corpus_key}"
                    f" -> {item.proposed_dataset_id}"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _build_eu_rebuild_recommendations(
    profiles: Sequence[DatasetProfile],
) -> List[JusticeDAORebuildRecommendation]:
    recommendations: List[JusticeDAORebuildRecommendation] = []
    onboarding = build_eu_country_corpus_onboarding_plan(profiles)
    for country_code, payload in onboarding.items():
        status = str(payload.get("status") or "").strip().lower()
        if status == "covered":
            continue
        if status == "registered":
            reason = "canonical_registered_but_unobserved"
        elif status == "in_progress":
            reason = "observed_dataset_awaits_canonical_registration"
        else:
            reason = "missing_supported_country_dataset"
        recommendations.append(
            JusticeDAORebuildRecommendation(
                country_code=country_code,
                label=str(payload.get("label") or country_code),
                status=status,
                reason=reason,
                canonical_corpus_keys=[str(item) for item in list(payload.get("canonical_corpus_keys") or [])],
                existing_dataset_ids=[str(item) for item in list(payload.get("existing_dataset_ids") or [])],
                proposed_corpus_key=str(payload.get("proposed_corpus_key") or "").strip() or None,
                proposed_dataset_id=str(payload.get("proposed_dataset_id") or "").strip() or None,
            )
        )
    return recommendations


def _state_code_from_path(value: str) -> Optional[str]:
    match = re.search(r"STATE-([A-Z]{2})", str(value or "").upper())
    if match:
        return _normalize_state_code(match.group(1))
    return None


def _build_rebuild_batches(
    targets: Sequence[JusticeDAORebuildTarget],
    *,
    batch_size: int,
) -> List[List[JusticeDAORebuildTarget]]:
    items = list(targets)
    if batch_size <= 0:
        return [items] if items else []
    return [items[index:index + batch_size] for index in range(0, len(items), batch_size)]


def build_justicedao_rebuild_plan(
    *,
    profiles: Optional[Sequence[DatasetProfile]] = None,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    batch_size: int = 0,
    max_files_per_corpus: int = 0,
) -> JusticeDAORebuildPlan:
    active_profiles = list(profiles or [])
    selected_corpora = {
        str(item).strip().lower()
        for item in (corpus_keys or list(_CANONICAL_QUERY_DATASETS.keys()))
        if str(item).strip()
    }
    selected_states = {
        _normalize_state_code(item)
        for item in list(state_codes or [])
        if _normalize_state_code(item)
    }

    targets: List[JusticeDAORebuildTarget] = []
    seen: set[tuple[str, str, Optional[str]]] = set()
    profile_map = {str(profile.dataset_id): profile for profile in active_profiles}
    for corpus_key in sorted(selected_corpora):
        config = _CANONICAL_QUERY_DATASETS.get(corpus_key)
        if not config:
            continue
        dataset_id = str(config["dataset_id"])
        profile = profile_map.get(dataset_id)
        parquet_files: List[str]
        if profile is not None and profile.parquet_files:
            parquet_files = [
                str(item)
                for item in list(profile.parquet_files or [])
                if _is_canonical_parquet_candidate(str(item))
            ]
        else:
            try:
                repo_files = _list_repo_files_cached(dataset_id)
            except Exception:
                parquet_files = []
            else:
                parquet_files = [
                    str(item)
                    for item in list(repo_files or [])
                    if _is_canonical_parquet_candidate(str(item))
                ]
        if not parquet_files:
            continue
        count = 0
        candidate_states = sorted(selected_states) if selected_states else [None]
        if any("{state}" in str(template) for template in list(config.get("parquet_templates") or [])):
            for candidate_state in candidate_states:
                if candidate_state is None and selected_states:
                    continue
                parquet_path = _select_repo_file(
                    parquet_files,
                    preferred_paths=list(config.get("parquet_files") or []) + list(config.get("parquet_templates") or []),
                    fallback_patterns=list(config.get("parquet_fallback_patterns") or []),
                    state_code=candidate_state,
                )
                if not parquet_path:
                    continue
                key = (corpus_key, parquet_path, candidate_state)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    JusticeDAORebuildTarget(
                        corpus_key=corpus_key,
                        dataset_id=dataset_id,
                        parquet_path=parquet_path,
                        state_code=candidate_state,
                    )
                )
                count += 1
                if max_files_per_corpus > 0 and count >= int(max_files_per_corpus):
                    break
        else:
            parquet_path = _select_repo_file(
                parquet_files,
                preferred_paths=list(config.get("parquet_files") or []) + list(config.get("parquet_templates") or []),
                fallback_patterns=list(config.get("parquet_fallback_patterns") or []),
                state_code=None,
            )
            if parquet_path:
                key = (corpus_key, parquet_path, None)
                if key not in seen:
                    seen.add(key)
                    targets.append(
                        JusticeDAORebuildTarget(
                            corpus_key=corpus_key,
                            dataset_id=dataset_id,
                            parquet_path=parquet_path,
                            state_code=None,
                        )
                    )
    targets.sort(key=lambda item: (item.corpus_key, item.state_code or "", item.parquet_path))
    include_eu_recommendations = corpus_keys is None
    recommendations = _build_eu_rebuild_recommendations(active_profiles) if include_eu_recommendations else []
    return JusticeDAORebuildPlan(
        targets=targets,
        batches=_build_rebuild_batches(targets, batch_size=batch_size),
        recommendations=recommendations,
    )


def build_canonical_corpus_artifacts(
    corpus_key: str,
    *,
    canonical_parquet_path: str,
    state_code: Optional[str] = None,
    rewrite_canonical_parquet: bool = True,
    output_root: Optional[str] = None,
    cid_index_output_path: Optional[str] = None,
    bm25_output_path: Optional[str] = None,
    knowledge_graph_entities_output_path: Optional[str] = None,
    knowledge_graph_relationships_output_path: Optional[str] = None,
    knowledge_graph_summary_output_path: Optional[str] = None,
    embeddings_output_path: Optional[str] = None,
    faiss_index_output_path: Optional[str] = None,
    faiss_metadata_output_path: Optional[str] = None,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    enable_llm_kg_enrichment: bool = False,
    llm_provider: Optional[str] = None,
    llm_model_name: Optional[str] = None,
    llm_max_rows: int = 0,
    llm_max_chars: int = 700,
    execute_recovery_for_degraded_corpora: bool = False,
    recovery_max_candidates: int = 8,
    recovery_archive_top_k: int = 3,
    recovery_publish_to_hf: bool = False,
    build_faiss: bool = True,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    repo_id: Optional[str] = None,
    include_canonical_parquet: bool = False,
) -> CanonicalCorpusArtifactBuildResult:
    import pyarrow as pa
    import pyarrow.parquet as pq

    normalized_corpus = str(corpus_key or "").strip().lower()
    if normalized_corpus not in _CANONICAL_QUERY_DATASETS:
        raise KeyError(f"Unsupported canonical legal corpus: {corpus_key}")

    config = _CANONICAL_QUERY_DATASETS[normalized_corpus]
    dataset_id = str(repo_id or config["dataset_id"])
    normalized_state = _normalize_state_code(state_code)
    join_field = str(config["join_field"])
    title_fields = list(config["title_fields"])
    text_fields = list(config["text_fields"])
    artifact_base_dir = (
        Path(output_root).expanduser().resolve()
        if str(output_root or "").strip()
        else _safe_artifact_base_dir(normalized_corpus, dataset_id, canonical_parquet_path)
    )
    artifact_base_dir.mkdir(parents=True, exist_ok=True)

    original_rows = pq.read_table(canonical_parquet_path).to_pylist()
    filtered_rows: List[Dict[str, Any]] = []
    for row in original_rows:
        row_dict = dict(row)
        if normalized_state and str(row_dict.get("state_code") or "").strip().upper() not in {"", normalized_state}:
            continue
        filtered_rows.append(row_dict)
    if not filtered_rows:
        raise ValueError("No canonical rows were available for artifact rebuild")

    normalized_rows, filled_join_values = _ensure_join_field_rows(filtered_rows, join_field=join_field)
    effective_canonical_path = str(canonical_parquet_path)
    if _is_hf_cache_snapshot_path(effective_canonical_path):
        effective_canonical_path = str((artifact_base_dir / Path(canonical_parquet_path).name).resolve())
    if rewrite_canonical_parquet and (filled_join_values > 0 or effective_canonical_path != str(canonical_parquet_path)):
        pq.write_table(pa.Table.from_pylist(normalized_rows), effective_canonical_path)

    cid_index_path = cid_index_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, "cid_index.parquet")
    bm25_path = bm25_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, "bm25.parquet")
    kg_entities_path = knowledge_graph_entities_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, "knowledge_graph_entities.parquet")
    kg_relationships_path = (
        knowledge_graph_relationships_output_path
        or _artifact_output_path(artifact_base_dir, effective_canonical_path, "knowledge_graph_relationships.parquet")
    )
    kg_summary_path = knowledge_graph_summary_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, "knowledge_graph_summary.json")

    Path(cid_index_path).parent.mkdir(parents=True, exist_ok=True)
    Path(bm25_path).parent.mkdir(parents=True, exist_ok=True)
    Path(kg_entities_path).parent.mkdir(parents=True, exist_ok=True)
    Path(kg_relationships_path).parent.mkdir(parents=True, exist_ok=True)
    Path(kg_summary_path).parent.mkdir(parents=True, exist_ok=True)

    cid_index_rows = _build_cid_index_rows(normalized_rows, join_field=join_field, config=config)
    pq.write_table(pa.Table.from_pylist(cid_index_rows), cid_index_path)

    bm25_rows = _build_bm25_rows(normalized_rows, join_field=join_field, title_fields=title_fields, text_fields=text_fields)
    pq.write_table(pa.Table.from_pylist(bm25_rows), bm25_path)

    kg_entities, kg_relationships, kg_summary = _build_generic_knowledge_graph_rows(
        normalized_rows,
        corpus_key=normalized_corpus,
        join_field=join_field,
        title_fields=title_fields,
        text_fields=text_fields,
    )
    corpus_quality_summary = _audit_canonical_corpus_quality(
        normalized_rows,
        corpus_key=normalized_corpus,
        title_fields=title_fields,
        text_fields=text_fields,
    )
    recovery_recommendation = _build_corpus_quality_recovery_recommendation(
        corpus_key=normalized_corpus,
        dataset_id=dataset_id,
        state_code=normalized_state,
        quality_summary=corpus_quality_summary,
    )
    recovery_manifest_draft = _write_corpus_quality_recovery_manifest_draft(
        recommendation=recovery_recommendation or {},
        artifact_base_dir=artifact_base_dir,
    )
    recovery_execution: Optional[Dict[str, Any]] = None
    if execute_recovery_for_degraded_corpora and recovery_recommendation:
        try:
            recovery_execution = _execute_corpus_quality_recovery(
                recommendation=recovery_recommendation,
                hf_token=hf_token,
                max_candidates=recovery_max_candidates,
                archive_top_k=recovery_archive_top_k,
                publish_to_hf=recovery_publish_to_hf,
            )
        except Exception as exc:
            recovery_execution = {
                "status": "error",
                "error": str(exc),
                "source": "canonical_corpus_quality_recovery",
            }
    llm_kg_summary: Optional[Dict[str, Any]] = None
    if enable_llm_kg_enrichment:
        kg_entities, kg_relationships, llm_kg_summary = _merge_router_knowledge_graph_rows(
            rows=normalized_rows,
            corpus_key=normalized_corpus,
            dataset_id=dataset_id,
            join_field=join_field,
            title_fields=title_fields,
            text_fields=text_fields,
            base_entities=kg_entities,
            base_relationships=kg_relationships,
            provider=llm_provider,
            model_name=llm_model_name,
            max_rows=llm_max_rows,
            max_chars=llm_max_chars,
        )
        kg_summary = {
            **dict(kg_summary),
            "entity_count": len(kg_entities),
            "relationship_count": len(kg_relationships),
            "llm_enrichment": dict(llm_kg_summary),
        }
    kg_summary = {
        **dict(kg_summary),
        "corpus_quality": dict(corpus_quality_summary),
    }
    pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(kg_entities)), kg_entities_path)
    pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(kg_relationships)), kg_relationships_path)
    Path(kg_summary_path).write_text(json.dumps(kg_summary, indent=2, sort_keys=True), encoding="utf-8")

    semantic_index = build_canonical_corpus_semantic_index(
        normalized_corpus,
        canonical_parquet_path=effective_canonical_path,
        state_code=normalized_state,
        embeddings_output_path=embeddings_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, "embeddings.parquet"),
        faiss_index_output_path=faiss_index_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, ".faiss"),
        faiss_metadata_output_path=faiss_metadata_output_path or _artifact_output_path(artifact_base_dir, effective_canonical_path, "faiss_metadata.parquet"),
        provider=provider,
        model_name=model_name,
        device=device,
        build_faiss=build_faiss,
    )

    publish_payload: Optional[Dict[str, Any]] = None
    if publish_to_hf:
        from huggingface_hub import HfApi

        api = HfApi(token=hf_token) if hf_token else HfApi()
        extra_uploads: List[Dict[str, Any]] = []
        for artifact_name, local_path, files_key, templates_key in (
            ("cid_index", cid_index_path, "publish_cid_index_files", "publish_cid_index_templates"),
            ("bm25", bm25_path, "publish_bm25_files", "publish_bm25_templates"),
            ("kg_entities", kg_entities_path, "publish_kg_entities_files", "publish_kg_entities_templates"),
            ("kg_relationships", kg_relationships_path, "publish_kg_relationships_files", "publish_kg_relationships_templates"),
            ("kg_summary", kg_summary_path, "publish_kg_summary_files", "publish_kg_summary_templates"),
        ):
            repo_path = _first_remote_publish_path(
                config,
                key_files=files_key,
                key_templates=templates_key,
                state_code=normalized_state,
            )
            if not repo_path:
                continue
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=str(repo_path),
                repo_id=dataset_id,
                repo_type="dataset",
                commit_message=f"Rebuild retrieval artifacts for {normalized_corpus}",
            )
            extra_uploads.append(
                {
                    "artifact": artifact_name,
                    "local_path": str(local_path),
                    "repo_path": str(repo_path),
                }
            )

        semantic_publish = publish_canonical_corpus_semantic_index(
            semantic_index,
            hf_token=hf_token,
            repo_id=dataset_id,
            include_canonical_parquet=include_canonical_parquet,
            commit_message=f"Rebuild retrieval artifacts for {normalized_corpus}",
        )
        publish_payload = canonical_corpus_index_publish_result_to_dict(semantic_publish)
        publish_payload["uploaded_files"].extend(extra_uploads)
        publish_payload["upload_count"] = len(list(publish_payload.get("uploaded_files") or []))

    return CanonicalCorpusArtifactBuildResult(
        corpus_key=normalized_corpus,
        dataset_id=dataset_id,
        canonical_parquet_path=str(canonical_parquet_path),
        updated_canonical_parquet_path=effective_canonical_path,
        row_count=len(normalized_rows),
        join_field=join_field,
        state_code=normalized_state,
        missing_join_values_filled=filled_join_values,
        cid_index_path=str(cid_index_path),
        bm25_documents_path=str(bm25_path),
        knowledge_graph_entities_path=str(kg_entities_path),
        knowledge_graph_relationships_path=str(kg_relationships_path),
        knowledge_graph_summary_path=str(kg_summary_path),
        corpus_quality_summary=corpus_quality_summary,
        recovery_recommendation=recovery_recommendation,
        recovery_manifest_draft=recovery_manifest_draft,
        recovery_execution=recovery_execution,
        llm_knowledge_graph_summary=llm_kg_summary,
        semantic_index=canonical_corpus_index_build_result_to_dict(semantic_index),
        publish_result=publish_payload,
    )


def rebuild_justicedao_dataset_library(
    *,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]] = None,
    allow_hf_download: bool = True,
    build_faiss: bool = True,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    enable_llm_kg_enrichment: bool = False,
    llm_provider: Optional[str] = None,
    llm_model_name: Optional[str] = None,
    llm_max_rows: int = 0,
    llm_max_chars: int = 700,
    execute_recovery_for_degraded_corpora: bool = False,
    recovery_max_candidates: int = 8,
    recovery_archive_top_k: int = 3,
    recovery_publish_to_hf: bool = False,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    include_canonical_parquet: bool = False,
    max_files_per_corpus: int = 0,
    output_root: Optional[str] = None,
) -> JusticeDAOLibraryRebuildResult:
    selected = [
        str(item).strip().lower()
        for item in (corpus_keys or list(_CANONICAL_QUERY_DATASETS.keys()))
        if str(item).strip()
    ]
    normalized_states = [_normalize_state_code(item) for item in list(state_codes or []) if _normalize_state_code(item)]
    errors: List[Dict[str, Any]] = []
    artifact_results: List[CanonicalCorpusArtifactBuildResult] = []
    override_map = _canonical_only_overrides(parquet_file_overrides)

    for corpus_key in selected:
        config = _CANONICAL_QUERY_DATASETS.get(corpus_key)
        if not config:
            errors.append({"corpus_key": corpus_key, "error": "unsupported_corpus"})
            continue
        try:
            source_refs: List[tuple[str, Optional[str]]] = []
            override_value = override_map.get(corpus_key)
            if override_value is not None:
                override_items = [str(override_value)] if isinstance(override_value, str) else [str(item) for item in override_value]
                for path in override_items:
                    if not _is_canonical_parquet_candidate(path):
                        continue
                    match = re.search(r"STATE-([A-Z]{2})", path.upper())
                    source_refs.append((path, _normalize_state_code(match.group(1)) if match else None))
            else:
                if not allow_hf_download:
                    errors.append({"corpus_key": corpus_key, "error": "no_local_overrides_and_hf_download_disabled"})
                    continue
                repo_files = _list_repo_files_cached(str(config["dataset_id"]))
                candidate_states = normalized_states or [None]
                for candidate_state in candidate_states:
                    parquet_path = _resolve_remote_repo_file(
                        repo_files,
                        corpus_key=corpus_key,
                        dataset_id=str(config["dataset_id"]),
                        kind="parquet",
                        preferred_paths=list(config.get("parquet_files") or []) + list(config.get("parquet_templates") or []),
                        fallback_patterns=list(config.get("parquet_fallback_patterns") or []),
                        state_code=candidate_state,
                    )
                    if parquet_path:
                        source_refs.append((_download_hf_dataset_file(str(config["dataset_id"]), parquet_path), candidate_state))
            deduped_source_refs: List[tuple[str, Optional[str]]] = []
            seen_sources: set[str] = set()
            for source_ref, candidate_state in source_refs:
                if source_ref in seen_sources:
                    continue
                seen_sources.add(source_ref)
                deduped_source_refs.append((source_ref, candidate_state))
            if max_files_per_corpus > 0:
                deduped_source_refs = deduped_source_refs[: int(max_files_per_corpus)]
            for source_ref, candidate_state in deduped_source_refs:
                artifact_results.append(
                    build_canonical_corpus_artifacts(
                        corpus_key,
                        canonical_parquet_path=source_ref,
                        state_code=candidate_state,
                        output_root=output_root,
                        provider=provider,
                        model_name=model_name,
                        device=device,
                        enable_llm_kg_enrichment=enable_llm_kg_enrichment,
                        llm_provider=llm_provider,
                        llm_model_name=llm_model_name,
                        llm_max_rows=llm_max_rows,
                        llm_max_chars=llm_max_chars,
                        execute_recovery_for_degraded_corpora=execute_recovery_for_degraded_corpora,
                        recovery_max_candidates=recovery_max_candidates,
                        recovery_archive_top_k=recovery_archive_top_k,
                        recovery_publish_to_hf=recovery_publish_to_hf,
                        build_faiss=build_faiss,
                        publish_to_hf=publish_to_hf,
                        hf_token=hf_token,
                        include_canonical_parquet=include_canonical_parquet,
                    )
                )
        except Exception as exc:
            errors.append({"corpus_key": corpus_key, "error": str(exc)})

    return JusticeDAOLibraryRebuildResult(artifact_results=artifact_results, errors=errors)


def query_canonical_legal_corpus(
    corpus_key: str,
    *,
    query_text: str,
    state_code: Optional[str] = None,
    mode: str = "auto",
    top_k: int = 5,
    allow_hf_fallback: bool = True,
    resolver: Optional[BluebookCitationResolver] = None,
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]] = None,
) -> CanonicalCorpusQueryResult:
    normalized_corpus = str(corpus_key or "").strip().lower()
    if normalized_corpus not in _CANONICAL_QUERY_DATASETS:
        raise KeyError(f"Unsupported canonical legal corpus: {corpus_key}")

    config = _CANONICAL_QUERY_DATASETS[normalized_corpus]
    dataset_id = str(config["dataset_id"])
    normalized_state = _normalize_state_code(state_code)
    active_mode = str(mode or "auto").strip().lower()
    notes: List[str] = []

    resolver_parquet_overrides = _canonical_only_overrides(parquet_file_overrides)
    override_value = (parquet_file_overrides or {}).get(normalized_corpus)
    override_items = [str(override_value)] if isinstance(override_value, str) else [str(item) for item in list(override_value or [])]
    prefer_override_search = (
        active_mode == "auto"
        and any(
            item.endswith("_embeddings.parquet")
            or item.endswith("_metadata.parquet")
            or item.endswith(".faiss")
            for item in override_items
        )
    )

    extracted_links = []
    if active_mode in {"auto", "exact"} and not prefer_override_search:
        active_resolver = resolver or BluebookCitationResolver(
            allow_hf_fallback=allow_hf_fallback,
            parquet_file_overrides=resolver_parquet_overrides,
        )
        try:
            links = active_resolver.resolve_text(query_text, state_code=normalized_state)
            for link in links:
                if link.matched and link.corpus_key == normalized_corpus:
                    extracted_links.append(citation_link_to_dict(link))
        except Exception as exc:
            notes.append(f"Exact citation resolution failed: {exc}")
        if extracted_links:
            return CanonicalCorpusQueryResult(
                corpus_key=normalized_corpus,
                dataset_id=dataset_id,
                legal_branch=_canonical_metadata_for_dataset(dataset_id).get("legal_branch"),
                country_codes=list(_canonical_metadata_for_dataset(dataset_id).get("country_codes") or []),
                mode="exact",
                query_text=query_text,
                state_code=normalized_state,
                parquet_file=str(extracted_links[0].get("source_ref") or "") or None,
                embeddings_file=None,
                citation_links=extracted_links,
                results=[
                    {
                        "title": link.get("source_title"),
                        "score": float(link.get("confidence") or 1.0),
                        "source_url": link.get("source_url"),
                        "source_cid": link.get("source_cid"),
                        "row": dict(link.get("metadata", {}).get("row") or {})
                        or {
                            "source_document_id": link.get("source_document_id"),
                            "source_ref": link.get("source_ref"),
                            "normalized_citation": link.get("normalized_citation"),
                        },
                    }
                    for link in extracted_links
                ][:top_k],
                notes=["Resolved with BluebookCitationResolver before parquet search."],
            )

    parquet_path: Optional[str] = None
    embeddings_path: Optional[str] = None
    faiss_index_path: Optional[str] = None
    faiss_metadata_path: Optional[str] = None
    if override_value:
        override_items = [str(override_value)] if isinstance(override_value, str) else [str(item) for item in override_value]
        parquet_candidates = [
            item
            for item in override_items
            if not item.endswith("_embeddings.parquet")
            and not item.endswith("_metadata.parquet")
            and not item.endswith(".faiss")
        ]
        embedding_candidates = [item for item in override_items if item.endswith("_embeddings.parquet")]
        faiss_index_candidates = [item for item in override_items if item.endswith(".faiss")]
        faiss_metadata_candidates = [item for item in override_items if item.endswith("_metadata.parquet")]
        parquet_path = parquet_candidates[0] if parquet_candidates else None
        embeddings_path = embedding_candidates[0] if embedding_candidates else None
        faiss_index_path = faiss_index_candidates[0] if faiss_index_candidates else None
        faiss_metadata_path = faiss_metadata_candidates[0] if faiss_metadata_candidates else None
    else:
        try:
            repo_files = _list_repo_files_cached(dataset_id)
        except Exception as exc:
            return CanonicalCorpusQueryResult(
                corpus_key=normalized_corpus,
                dataset_id=dataset_id,
                legal_branch=_canonical_metadata_for_dataset(dataset_id).get("legal_branch"),
                country_codes=list(_canonical_metadata_for_dataset(dataset_id).get("country_codes") or []),
                mode=active_mode,
                query_text=query_text,
                state_code=normalized_state,
                citation_links=extracted_links,
                results=[],
                notes=[f"No local override was provided and HF dataset access is unavailable: {exc}"],
            )
        selected_parquet = _resolve_remote_repo_file(
            repo_files,
            corpus_key=normalized_corpus,
            dataset_id=dataset_id,
            kind="parquet",
            preferred_paths=list(config.get("parquet_files") or config.get("parquet_templates") or []),
            fallback_patterns=list(config.get("parquet_fallback_patterns") or []),
            state_code=normalized_state,
        )
        if selected_parquet:
            parquet_path = _download_hf_dataset_file(dataset_id, selected_parquet)
        selected_embeddings = _resolve_remote_repo_file(
            repo_files,
            corpus_key=normalized_corpus,
            dataset_id=dataset_id,
            kind="embeddings",
            preferred_paths=list(config.get("embedding_files") or config.get("embedding_templates") or []),
            fallback_patterns=list(config.get("embedding_fallback_patterns") or []),
            state_code=normalized_state,
        )
        if selected_embeddings:
            embeddings_path = _download_hf_dataset_file(dataset_id, selected_embeddings)
        selected_faiss_index = _resolve_remote_repo_file(
            repo_files,
            corpus_key=normalized_corpus,
            dataset_id=dataset_id,
            kind="faiss_index",
            preferred_paths=list(config.get("faiss_index_files") or []),
            fallback_patterns=list(config.get("faiss_index_patterns") or []),
            state_code=normalized_state,
        )
        if selected_faiss_index:
            faiss_index_path = _download_hf_dataset_file(dataset_id, selected_faiss_index)
        selected_faiss_metadata = _resolve_remote_repo_file(
            repo_files,
            corpus_key=normalized_corpus,
            dataset_id=dataset_id,
            kind="faiss_metadata",
            preferred_paths=list(config.get("faiss_metadata_files") or []),
            fallback_patterns=list(config.get("faiss_metadata_patterns") or []),
            state_code=normalized_state,
        )
        if selected_faiss_metadata:
            faiss_metadata_path = _download_hf_dataset_file(dataset_id, selected_faiss_metadata)

    if not parquet_path:
        return CanonicalCorpusQueryResult(
            corpus_key=normalized_corpus,
            dataset_id=dataset_id,
            legal_branch=_canonical_metadata_for_dataset(dataset_id).get("legal_branch"),
            country_codes=list(_canonical_metadata_for_dataset(dataset_id).get("country_codes") or []),
            mode=active_mode,
            query_text=query_text,
            state_code=normalized_state,
            citation_links=extracted_links,
            results=[],
            notes=["No parquet file could be resolved for this corpus."],
        )

    title_fields = list(config["title_fields"])
    text_fields = list(config["text_fields"])
    join_field = str(config["join_field"])

    if active_mode in {"auto", "exact"} and _canonical_metadata_for_dataset(dataset_id).get("legal_branch") == "eu":
        eu_citation_links, eu_exact_results = _exact_eu_query_rows(
            parquet_path,
            query_text=query_text,
            title_fields=title_fields,
            join_field=join_field,
            top_k=top_k,
        )
        if eu_exact_results:
            return CanonicalCorpusQueryResult(
                corpus_key=normalized_corpus,
                dataset_id=dataset_id,
                legal_branch=_canonical_metadata_for_dataset(dataset_id).get("legal_branch"),
                country_codes=list(_canonical_metadata_for_dataset(dataset_id).get("country_codes") or []),
                mode="exact",
                query_text=query_text,
                state_code=normalized_state,
                parquet_file=parquet_path,
                embeddings_file=None,
                citation_links=eu_citation_links,
                results=eu_exact_results,
                notes=["Resolved with EU citation bridge identifiers before semantic or lexical search."],
            )

    if active_mode in {"semantic", "auto"} and faiss_index_path and faiss_metadata_path:
        faiss_results = _faiss_query_rows(
            parquet_path,
            faiss_index_path,
            faiss_metadata_path,
            query_text=query_text,
            join_field=join_field,
            title_fields=title_fields,
            state_code=normalized_state,
            top_k=top_k,
        )
        if faiss_results:
            return CanonicalCorpusQueryResult(
                corpus_key=normalized_corpus,
                dataset_id=dataset_id,
                mode="semantic_faiss",
                query_text=query_text,
                state_code=normalized_state,
                parquet_file=parquet_path,
                embeddings_file=faiss_metadata_path,
                citation_links=extracted_links,
                results=faiss_results,
                notes=["Resolved with FAISS index sidecar and metadata parquet."],
            )
        notes.append("FAISS query path found no ranked rows; falling back to embeddings or lexical search.")

    if active_mode in {"semantic", "auto"} and embeddings_path:
        semantic_results = _semantic_query_rows(
            parquet_path,
            embeddings_path,
            query_text=query_text,
            join_field=join_field,
            title_fields=title_fields,
            text_fields=text_fields,
            state_code=normalized_state,
            top_k=top_k,
        )
        if semantic_results:
            return CanonicalCorpusQueryResult(
                corpus_key=normalized_corpus,
                dataset_id=dataset_id,
                legal_branch=_canonical_metadata_for_dataset(dataset_id).get("legal_branch"),
                country_codes=list(_canonical_metadata_for_dataset(dataset_id).get("country_codes") or []),
                mode="semantic",
                query_text=query_text,
                state_code=normalized_state,
                parquet_file=parquet_path,
                embeddings_file=embeddings_path,
                citation_links=extracted_links,
                results=semantic_results,
                notes=["Resolved with embeddings parquet and embeddings_router-compatible query embedding."],
            )
        notes.append("Semantic query path found no ranked rows; falling back to lexical search.")

    lexical_results = _lexical_query_rows(
        parquet_path,
        query_text=query_text,
        title_fields=title_fields,
        text_fields=text_fields,
        state_code=normalized_state,
        top_k=top_k,
    )
    return CanonicalCorpusQueryResult(
        corpus_key=normalized_corpus,
        dataset_id=dataset_id,
        legal_branch=_canonical_metadata_for_dataset(dataset_id).get("legal_branch"),
        country_codes=list(_canonical_metadata_for_dataset(dataset_id).get("country_codes") or []),
        mode="lexical",
        query_text=query_text,
        state_code=normalized_state,
        parquet_file=parquet_path,
        embeddings_file=embeddings_path,
        citation_links=extracted_links,
        results=lexical_results,
        notes=notes or ["Resolved with parquet lexical search."],
    )


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("§", " section ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _compact_alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _contains_ordered_tokens(container: str, query: str) -> bool:
    container_tokens = [token for token in str(container or "").split() if token]
    query_tokens = [token for token in str(query or "").split() if token]
    if not container_tokens or not query_tokens:
        return False

    query_index = 0
    for token in container_tokens:
        if token == query_tokens[query_index]:
            query_index += 1
            if query_index == len(query_tokens):
                return True
    return False


def _eu_citation_match_terms(citation: Any) -> List[str]:
    terms: List[str] = []

    def _add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in terms:
            terms.append(text)

    _add(getattr(citation, "raw_text", ""))
    _add(getattr(citation, "normalized_text", ""))
    _add(getattr(citation, "canonical_uri", ""))
    for identifier in list(getattr(citation, "identifiers", []) or []):
        _add(getattr(identifier, "value", ""))
        _add(getattr(identifier, "canonical_uri", ""))
    metadata = dict(getattr(citation, "metadata", {}) or {})
    _add(metadata.get("article"))
    _add(metadata.get("code"))
    return terms


def _row_matches_eu_citation(row: Dict[str, Any], citation: Any) -> bool:
    terms = _eu_citation_match_terms(citation)
    normalized_terms = {_normalize_text(term) for term in terms if term}
    compact_terms = {_compact_alnum(term) for term in terms if term}
    candidate_fields = [
        "citation",
        "identifier",
        "law_identifier",
        "official_identifier",
        "title",
        "source_id",
        "jsonld_id",
    ]
    for field in candidate_fields:
        value = row.get(field)
        if value in (None, ""):
            continue
        normalized_value = _normalize_text(value)
        compact_value = _compact_alnum(value)
        if normalized_value and normalized_value in normalized_terms:
            return True
        if compact_value and compact_value in compact_terms:
            return True
        if normalized_value and any(
            term and (term in normalized_value or normalized_value in term) for term in normalized_terms
        ):
            return True
        if normalized_value and any(
            term and (_contains_ordered_tokens(normalized_value, term) or _contains_ordered_tokens(term, normalized_value))
            for term in normalized_terms
        ):
            return True
        if compact_value and any(
            term and (term in compact_value or compact_value in term) for term in compact_terms
        ):
            return True
    return False


def _exact_eu_query_rows(
    parquet_path: str,
    *,
    query_text: str,
    title_fields: Sequence[str],
    join_field: str,
    top_k: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    eu_citations = extract_eu_legal_citations(query_text)
    if not eu_citations:
        return [], []

    rows = _load_rows_from_source(parquet_path)
    if not rows:
        return [], []

    citation_links: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    seen_rows: set[str] = set()
    for citation in eu_citations:
        for row in rows:
            if not _row_matches_eu_citation(row, citation):
                continue
            row_key = canonical_json_bytes(row).hex()
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            source_cid = str(row.get(join_field) or row.get("source_cid") or row.get("cid") or "")
            citation_links.append(
                {
                    "citation_text": str(getattr(citation, "raw_text", "") or getattr(citation, "normalized_text", "") or ""),
                    "citation_type": f"eu_{str(getattr(citation, 'scheme', 'identifier')).strip().lower()}",
                    "normalized_citation": str(getattr(citation, "normalized_text", "") or "").strip(),
                    "matched": True,
                    "corpus_key": None,
                    "dataset_id": None,
                    "matched_field": "eu_identifier",
                    "confidence": 1.0,
                    "source_document_id": str(row.get("law_identifier") or row.get("identifier") or ""),
                    "source_title": _row_title(row, title_fields),
                    "source_url": str(row.get("source_url") or ""),
                    "source_cid": source_cid,
                    "source_ref": parquet_path,
                    "metadata": {"row": dict(row), "canonical_uri": getattr(citation, "canonical_uri", None)},
                }
            )
            results.append(
                {
                    "title": _row_title(row, title_fields),
                    "score": 1.0,
                    "source_url": str(row.get("source_url") or ""),
                    "source_cid": source_cid,
                    "row": dict(row),
                }
            )
            if len(results) >= int(top_k):
                return citation_links, results
    return citation_links, results


def _citation_match_terms(citation: Citation) -> List[str]:
    terms: List[str] = []

    def _add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in terms:
            terms.append(text)

    _add(citation.text)
    normalized = _normalize_citation_text(citation)
    if normalized and normalized != citation.text:
        _add(normalized)
    if citation.type == "usc" and citation.title and citation.section:
        _add(f"{citation.title} USC {citation.section}")
        _add(f"{citation.title} U.S.C. {citation.section}")
    if citation.type == "federal_register" and citation.volume and citation.page:
        _add(f"{citation.volume} Fed. Reg. {citation.page}")
    if citation.type == "case" and citation.volume and citation.reporter and citation.page:
        _add(f"{citation.volume} {citation.reporter.replace('.', '').strip()} {citation.page}")
    return terms


def _candidate_parquet_files_for_strategy(
    profile: DatasetProfile,
    strategy: BluebookQueryStrategy,
) -> List[str]:
    parquet_files = [str(item) for item in profile.parquet_files if str(item).endswith(".parquet")]
    if strategy.query_path == "precomputed_citation_table_then_cid_join":
        citation_files = [item for item in parquet_files if "_citation.parquet" in item]
        html_files = [item for item in parquet_files if "_html.parquet" in item]
        return citation_files + html_files
    if strategy.dataset_id.endswith("ipfs_uscode"):
        ordered = []
        for token in ("cid_index.parquet", "laws.parquet"):
            ordered.extend([item for item in parquet_files if item.endswith(token)])
        if ordered:
            return ordered
    return parquet_files[:8]


def _load_rows_from_source(source_ref: str) -> List[Dict[str, Any]]:
    try:
        import pyarrow.parquet as pq

        return pq.read_table(source_ref).to_pylist()
    except Exception:
        pass
    try:
        import pandas as pd

        return pd.read_parquet(source_ref).to_dict("records")
    except Exception:
        return []


def _resolve_local_or_hf_sources(
    profile: DatasetProfile,
    strategy: BluebookQueryStrategy,
    *,
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]] = None,
) -> List[str]:
    override = (parquet_file_overrides or {}).get(profile.dataset_id)
    if override:
        return [str(override)] if isinstance(override, str) else [str(item) for item in override]

    candidates = _candidate_parquet_files_for_strategy(profile, strategy)
    resolved: List[str] = []
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists():
            resolved.append(str(path.resolve()))
            continue
        try:
            from huggingface_hub import hf_hub_download

            local = hf_hub_download(repo_id=profile.dataset_id, repo_type="dataset", filename=candidate)
            resolved.append(str(Path(local).resolve()))
        except Exception:
            continue
    deduped: List[str] = []
    seen: set[str] = set()
    for item in resolved:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _translate_overrides_to_canonical_keys(
    profiles_by_dataset: Mapping[str, DatasetProfile],
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]],
) -> Dict[str, Sequence[str] | str]:
    translated: Dict[str, Sequence[str] | str] = {}
    for key, value in dict(parquet_file_overrides or {}).items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if normalized_key in _CANONICAL_QUERY_DATASETS:
            translated[normalized_key] = value
            continue
        profile = profiles_by_dataset.get(normalized_key)
        canonical_key = None
        if profile is not None:
            canonical_key = profile.canonical_corpus_key
        if not canonical_key:
            try:
                canonical_key = infer_canonical_legal_corpus_for_dataset_id(normalized_key).key
            except KeyError:
                canonical_key = None
        if canonical_key and canonical_key not in translated:
            translated[canonical_key] = value
    return translated


def _notes_union(*groups: Sequence[str]) -> List[str]:
    notes: List[str] = []
    for group in groups:
        for note in group:
            text = str(note or "").strip()
            if text and text not in notes:
                notes.append(text)
    return notes

def _eu_query_text(citation: Any) -> str:
    raw_text = str(getattr(citation, "raw_text", "") or "").strip()
    if raw_text and extract_eu_legal_citations(raw_text):
        return raw_text

    metadata = dict(getattr(citation, "metadata", {}) or {})
    scheme = str(getattr(citation, "scheme", "") or "").strip().upper()
    article = str(metadata.get("article") or "").strip()
    code = str(metadata.get("code") or "").strip()
    paragraph = str(metadata.get("paragraph") or "").strip()

    if scheme == "DE_GG_ARTICLE" and article:
        if paragraph:
            return f"Art. {article} Abs. {paragraph} GG"
        return f"Art. {article} GG"
    if scheme == "FR_CC_ARTICLE" and article:
        return f"Article {article} du code civil"
    if scheme == "ES_CC_ARTICLE" and article:
        return f"Articulo {article} del Codigo Civil"
    if scheme == "NL_BW_ARTICLE" and article:
        code_text = code or "BW"
        return f"Artikel {article} {code_text}".strip()

    return str(getattr(citation, "normalized_text", "") or "").strip()


def _citation_state_code(citation: Citation) -> Optional[str]:
    return _normalize_state_code(citation.jurisdiction)


def _match_from_canonical_query(
    strategy: BluebookQueryStrategy,
    result: CanonicalCorpusQueryResult,
) -> Optional[CitationDatasetMatch]:
    if not result.results:
        return None
    rows = [dict(item.get("row") or {}) for item in result.results if dict(item.get("row") or {})]
    if not rows:
        return None
    source_ref = str(result.parquet_file or rows[0].get("source_ref") or "")
    return CitationDatasetMatch(
        dataset_id=strategy.dataset_id,
        source_ref=source_ref,
        strategy=strategy,
        result_count=len(rows),
        rows=rows,
        notes=_notes_union(strategy.notes, result.notes),
    )


def _row_matches_citation(row: Dict[str, Any], citation: Citation, strategy: BluebookQueryStrategy) -> bool:
    terms = _citation_match_terms(citation)
    normalized_terms = {_normalize_text(term) for term in terms if term}
    compact_terms = {_compact_alnum(term) for term in terms if term}

    for field in list(strategy.citation_lookup_fields) + list(strategy.text_fields):
        value = row.get(field)
        if value in (None, ""):
            continue
        normalized_value = _normalize_text(value)
        compact_value = _compact_alnum(value)
        if normalized_value and normalized_value in normalized_terms:
            return True
        if compact_value and compact_value in compact_terms:
            return True
        if normalized_value and any(term and term in normalized_value for term in normalized_terms):
            return True

    if citation.type == "usc":
        title = str(row.get("title_number") or row.get("title") or "").strip()
        section = str(row.get("section_number") or row.get("section") or "").strip()
        if title == str(citation.title or "") and section == str(citation.section or ""):
            return True
    if citation.type == "federal_register":
        identifier = str(row.get("identifier") or row.get("citation") or "").strip()
        if identifier and _normalize_text(identifier) in normalized_terms:
            return True
    if citation.type == "case":
        volume = str(row.get("volume") or "").strip()
        reporter = str(row.get("reporter") or "").strip()
        page = str(row.get("page") or row.get("first_page") or "").strip()
        if volume == str(citation.volume or "") and page == str(citation.page or "") and reporter:
            if _compact_alnum(reporter) == _compact_alnum(citation.reporter):
                return True
    return False


def execute_justicedao_bluebook_query_plan(
    plan: BluebookDatasetQueryPlan,
    *,
    profiles: Optional[Sequence[DatasetProfile]] = None,
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]] = None,
    max_rows_per_dataset: int = 5,
) -> BluebookDatasetExecutionResult:
    active_profiles = {profile.dataset_id: profile for profile in list(profiles or inspect_justicedao_datasets(dataset_prefix=""))}
    canonical_overrides = _translate_overrides_to_canonical_keys(active_profiles, parquet_file_overrides)
    extractor = CitationExtractor()
    extracted = extractor.extract_citations(plan.input_text)
    citation_map = {(citation.text, citation.type): citation for citation in extracted}

    execution_results: List[CitationExecutionPlanResult] = []
    for query_plan in plan.query_plans:
        citation = citation_map.get((query_plan.citation_text, query_plan.citation_type))
        if citation is None:
            citation = Citation(
                type=query_plan.citation_type,
                text=query_plan.citation_text,
            )
        matches: List[CitationDatasetMatch] = []
        attempted: List[str] = []
        for strategy in query_plan.candidate_datasets:
            profile = active_profiles.get(strategy.dataset_id)
            if profile is None:
                continue
            attempted.append(strategy.dataset_id)
            if strategy.canonical_corpus_key:
                result = query_canonical_legal_corpus(
                    strategy.canonical_corpus_key,
                    query_text=query_plan.citation_text,
                    state_code=_citation_state_code(citation),
                    mode="auto",
                    top_k=max_rows_per_dataset,
                    parquet_file_overrides=canonical_overrides,
                )
                match = _match_from_canonical_query(strategy, result)
                if match is not None:
                    matches.append(match)
                    break
            source_refs = _resolve_local_or_hf_sources(
                profile,
                strategy,
                parquet_file_overrides=parquet_file_overrides,
            )
            dataset_rows: List[Dict[str, Any]] = []
            chosen_source = ""
            for source_ref in source_refs:
                rows = _load_rows_from_source(source_ref)
                filtered = [row for row in rows if _row_matches_citation(row, citation, strategy)]
                if filtered:
                    dataset_rows = filtered[:max_rows_per_dataset]
                    chosen_source = source_ref
                    break
            if dataset_rows:
                matches.append(
                    CitationDatasetMatch(
                        dataset_id=strategy.dataset_id,
                        source_ref=chosen_source,
                        strategy=strategy,
                        result_count=len(dataset_rows),
                        rows=dataset_rows,
                        notes=list(strategy.notes),
                    )
                )
                break
        execution_results.append(
            CitationExecutionPlanResult(
                citation_text=query_plan.citation_text,
                citation_type=query_plan.citation_type,
                normalized_citation=query_plan.normalized_citation,
                matches=matches,
                attempted_datasets=attempted,
            )
        )
    return BluebookDatasetExecutionResult(
        input_text=plan.input_text,
        citations=list(plan.citations),
        execution_results=execution_results,
    )


def execute_justicedao_legal_citation_query_plan(
    plan: BluebookDatasetQueryPlan,
    *,
    profiles: Optional[Sequence[DatasetProfile]] = None,
    parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]] = None,
    max_rows_per_dataset: int = 5,
) -> BluebookDatasetExecutionResult:
    return execute_justicedao_bluebook_query_plan(
        plan,
        profiles=profiles,
        parquet_file_overrides=parquet_file_overrides,
        max_rows_per_dataset=max_rows_per_dataset,
    )


def bluebook_dataset_execution_result_to_dict(result: BluebookDatasetExecutionResult) -> Dict[str, Any]:
    return {
        "input_text": result.input_text,
        "citations": [dict(item) for item in result.citations],
        "execution_results": [
            {
                "citation_text": item.citation_text,
                "citation_type": item.citation_type,
                "normalized_citation": item.normalized_citation,
                "attempted_datasets": list(item.attempted_datasets),
                "matches": [
                    {
                        "dataset_id": match.dataset_id,
                        "source_ref": match.source_ref,
                        "result_count": match.result_count,
                        "rows": list(match.rows),
                        "strategy": {
                            "support_level": match.strategy.support_level,
                            "query_path": match.strategy.query_path,
                            "citation_lookup_fields": list(match.strategy.citation_lookup_fields),
                            "text_fields": list(match.strategy.text_fields),
                            "join_fields": list(match.strategy.join_fields),
                        },
                        "notes": list(match.notes),
                    }
                    for match in item.matches
                ],
            }
            for item in result.execution_results
        ],
    }


def legal_citation_dataset_execution_result_to_dict(result: BluebookDatasetExecutionResult) -> Dict[str, Any]:
    return bluebook_dataset_execution_result_to_dict(result)
