#!/usr/bin/env python3
"""Freeze and check the pinned justicedao/ipfs_uscode baseline audit (USCIR-001).

Default operation is offline and network-free. The fixture inventory encodes the
live Hugging Face evidence recorded for revision
``75cfc5982dc3a6808614cd4eb9b4238f8f9308b8`` so that counts, schemas, row
groups, identity anomalies, legacy joins, citations, sizes, and Dataset Viewer
validity are machine-checkable without contacting the Hub.

Validation gate (no network)::

    python scripts/ops/legal_data/audit_uscode_hf_baseline.py --fixture-only --check

The frozen report path is ``docs/reports/uscode_sparse_graphrag_baseline.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "USCIR-001"
GOAL_ID = "USCIR-G010"
PROGRAM_ID = "uscode-sparse-graphrag-v1"
PRODUCER = "audit_uscode_hf_baseline.py"
REPORT_SCHEMA = "ipfs_datasets_py/uscode-sparse-graphrag-baseline@1"
CODE_VERSION = "1"

DATASET_REPO_ID = "justicedao/ipfs_uscode"
PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
BASELINE_DATE = "2026-08-09"

DEFAULT_REPORT_RELPATH = Path("docs/reports/uscode_sparse_graphrag_baseline.json")

# Pinned inventory from the live Hub audit at PINNED_REVISION.
CORPUS_ROW_COUNT = 60_077
CANONICAL_CID_COUNT = 60_068
RECOVERY_ROW_COUNT = 9
VECTOR_ROW_COUNT = 185_563
BM25_DOCUMENT_COUNT = 60_068
KG_ENTITY_COUNT = 180_257
KG_RELATIONSHIP_COUNT = 120_136
TITLE_COUNT = 53
REPOSITORY_FILE_COUNT = 556
REPOSITORY_SIZE_BYTES = 1_094_219_366  # ~1.019 GiB

# Title coverage: U.S. Code Titles 1–52 and 54 (Title 53 is reserved/unused).
TITLE_NUMBERS: tuple[int, ...] = tuple(range(1, 53)) + (54,)

USC_CITATION_OCCURRENCES = 105_055
PUBLIC_LAW_OCCURRENCES = 234_393

BM25_K1 = 1.5
BM25_B = 0.75
EMBEDDING_DIMENSION = 384
EMBEDDING_CHUNKS_MIN = 1
EMBEDDING_CHUNKS_MAX = 454

# Approximate artifact sizes recorded at the pinned revision (bytes).
ARTIFACT_SIZES_BYTES: Mapping[str, int] = {
    "uscode_parquet/laws.parquet": 392_482_816,  # ~374.3 MiB
    "uscode_parquet/cid_index.parquet": 6_396_314,  # ~6.1 MiB
    "uscode_parquet/laws_bm25.parquet": 209_295_770,  # ~199.6 MiB
    "uscode_parquet/laws_embeddings.parquet": 147_534_643,  # ~140.7 MiB
    "uscode_parquet/laws_knowledge_graph_entities.parquet": 10_171_187,  # ~9.7 MiB
    "uscode_parquet/laws_knowledge_graph_relationships.parquet": 11_324_621,  # ~10.8 MiB
}


class BaselineAuditError(RuntimeError):
    """Raised when the baseline audit cannot complete fail-closed."""


def default_report_path(repo_root: Path | str | None = None) -> Path:
    """Return the repository-relative frozen baseline report path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def expected_title_numbers() -> list[int]:
    """Return the 53 title numbers covered by the pinned corpus."""
    titles = list(TITLE_NUMBERS)
    if len(titles) != TITLE_COUNT:
        raise BaselineAuditError(
            f"title coverage invariant broken: expected {TITLE_COUNT}, got {len(titles)}"
        )
    return titles


def _artifact(
    *,
    path: str,
    row_count: int,
    size_bytes: int,
    row_groups: int,
    media_type: str,
    schema_notes: Sequence[str],
    blocking_issues: Sequence[str],
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "path": path,
        "row_count": int(row_count),
        "size_bytes": int(size_bytes),
        "row_groups": int(row_groups),
        "media_type": media_type,
        "schema_notes": list(schema_notes),
        "blocking_issues": list(blocking_issues),
        "identity": dict(identity),
    }


def build_fixture_baseline_report() -> dict[str, Any]:
    """Build the frozen offline baseline report for the pinned Hub revision.

    The report is the durable evidence contract for USCIR-001. It does not
    contact the network; values are the sealed live-audit inventory.
    """
    titles = expected_title_numbers()
    recovery = CORPUS_ROW_COUNT - CANONICAL_CID_COUNT
    if recovery != RECOVERY_ROW_COUNT:
        raise BaselineAuditError(
            "corpus/canonical/recovery invariant broken: "
            f"{CORPUS_ROW_COUNT} - {CANONICAL_CID_COUNT} != {RECOVERY_ROW_COUNT}"
        )

    artifacts = [
        _artifact(
            path="uscode_parquet/laws.parquet",
            row_count=CORPUS_ROW_COUNT,
            size_bytes=ARTIFACT_SIZES_BYTES["uscode_parquet/laws.parquet"],
            row_groups=1,
            media_type="application/vnd.apache.parquet",
            schema_notes=[
                "legacy monolith corpus table",
                "mixes canonical rows with heterogeneous recovery JSON rows",
                "primary key candidate ipfs_cid present only on canonical rows",
            ],
            blocking_issues=[
                f"{CANONICAL_CID_COUNT} canonical rows plus {RECOVERY_ROW_COUNT} recovery rows without CIDs",
                "single row group exceeds the 4,096-row physical shard bound",
            ],
            identity={
                "durable_key": "ipfs_cid",
                "canonical_rows_with_cid": CANONICAL_CID_COUNT,
                "recovery_rows_without_cid": RECOVERY_ROW_COUNT,
                "positional_identity_used": False,
            },
        ),
        _artifact(
            path="uscode_parquet/cid_index.parquet",
            row_count=CANONICAL_CID_COUNT,
            size_bytes=ARTIFACT_SIZES_BYTES["uscode_parquet/cid_index.parquet"],
            row_groups=1,
            media_type="application/vnd.apache.parquet",
            schema_notes=[
                "CID lookup/index table for canonical corpus rows",
            ],
            blocking_issues=[
                "no release/control-plane contract",
            ],
            identity={
                "durable_key": "ipfs_cid",
                "row_count_matches_canonical": True,
            },
        ),
        _artifact(
            path="uscode_parquet/laws_bm25.parquet",
            row_count=BM25_DOCUMENT_COUNT,
            size_bytes=ARTIFACT_SIZES_BYTES["uscode_parquet/laws_bm25.parquet"],
            row_groups=1,
            media_type="application/vnd.apache.parquet",
            schema_notes=[
                "per-document term-frequency arrays",
                f"parameters k1={BM25_K1}, b={BM25_B}",
                "no tokenizer identity, title/body field separation, or term-range routing",
            ],
            blocking_issues=[
                "document term arrays, not a sorted inverted index",
                "single row group exceeds the 4,096-row physical shard bound",
            ],
            identity={
                "join_key": "ipfs_cid",
                "join_kind": "canonical_cid",
                "row_count_matches_canonical": True,
            },
        ),
        _artifact(
            path="uscode_parquet/laws_embeddings.parquet",
            row_count=VECTOR_ROW_COUNT,
            size_bytes=ARTIFACT_SIZES_BYTES["uscode_parquet/laws_embeddings.parquet"],
            row_groups=1,
            media_type="application/vnd.apache.parquet",
            schema_notes=[
                f"{EMBEDDING_DIMENSION}-dimensional vectors",
                f"{EMBEDDING_CHUNKS_MIN}–{EMBEDDING_CHUNKS_MAX} chunks per document",
                "model and revision not recorded",
                "normalization policy absent",
            ],
            blocking_issues=[
                "positional row-N identity rather than content-addressed join",
                "unknown embedding model/revision",
                "single row group exceeds the 4,096-row physical shard bound",
            ],
            identity={
                "join_key": "positional_row_index",
                "join_kind": "legacy_positional",
                "durable_cid_join": False,
                "trusted_for_migration": False,
            },
        ),
        _artifact(
            path="uscode_parquet/laws_knowledge_graph_entities.parquet",
            row_count=KG_ENTITY_COUNT,
            size_bytes=ARTIFACT_SIZES_BYTES[
                "uscode_parquet/laws_knowledge_graph_entities.parquet"
            ],
            row_groups=1,
            media_type="application/vnd.apache.parquet",
            schema_notes=[
                "entity types limited to title/document/section structure",
                "entity_type_counts: document=60068, legal_document=60068, section=60068, usc_title=53",
            ],
            blocking_issues=[
                "only title/document/section structure; citation graph evidence unused",
            ],
            identity={
                "ontology": "generic-legal-document-kg-v1",
            },
        ),
        _artifact(
            path="uscode_parquet/laws_knowledge_graph_relationships.parquet",
            row_count=KG_RELATIONSHIP_COUNT,
            size_bytes=ARTIFACT_SIZES_BYTES[
                "uscode_parquet/laws_knowledge_graph_relationships.parquet"
            ],
            row_groups=1,
            media_type="application/vnd.apache.parquet",
            schema_notes=[
                "relationship types limited to IN_TITLE and HAS_SECTION",
                "relationship_type_counts: HAS_SECTION=60068, IN_TITLE=60068",
            ],
            blocking_issues=[
                "citation, amendment, transfer, and provenance edges absent",
            ],
            identity={
                "ontology": "generic-legal-document-kg-v1",
            },
        ),
    ]

    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": "1",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "code_version": CODE_VERSION,
        "baseline_date": BASELINE_DATE,
        "dataset": {
            "repo_id": DATASET_REPO_ID,
            "revision": PINNED_REVISION,
            "revision_pinned": True,
            "unpinned_tokens_forbidden": ["main", "master", "latest", "HEAD"],
            "file_count": REPOSITORY_FILE_COUNT,
            "size_bytes": REPOSITORY_SIZE_BYTES,
            "size_gib_approx": 1.019,
            "has_readme": False,
            "has_dataset_card_configurations": False,
        },
        "counts": {
            "corpus_rows": CORPUS_ROW_COUNT,
            "canonical_cids": CANONICAL_CID_COUNT,
            "recovery_rows": RECOVERY_ROW_COUNT,
            "vectors": VECTOR_ROW_COUNT,
            "bm25_documents": BM25_DOCUMENT_COUNT,
            "kg_entities": KG_ENTITY_COUNT,
            "kg_relationships": KG_RELATIONSHIP_COUNT,
            "titles": TITLE_COUNT,
            "repository_files": REPOSITORY_FILE_COUNT,
        },
        "titles": {
            "count": TITLE_COUNT,
            "numbers": titles,
            "span_note": "Titles 1 through 52 and 54 (Title 53 reserved/unused)",
            "date_modified_year_on_canonical_rows": 2024,
            "date_modified_is_legal_currentness_claim": False,
        },
        "artifacts": artifacts,
        "schemas": {
            "corpus": {
                "path": "uscode_parquet/laws.parquet",
                "row_count": CORPUS_ROW_COUNT,
                "canonical_cid_field": "ipfs_cid",
                "heterogeneous_recovery_rows_present": True,
            },
            "cid_index": {
                "path": "uscode_parquet/cid_index.parquet",
                "row_count": CANONICAL_CID_COUNT,
            },
            "bm25": {
                "path": "uscode_parquet/laws_bm25.parquet",
                "row_count": BM25_DOCUMENT_COUNT,
                "k1": BM25_K1,
                "b": BM25_B,
                "layout": "per_document_term_arrays",
                "sorted_inverted_index": False,
                "tokenizer_identity": None,
                "term_range_routing": False,
            },
            "vectors": {
                "path": "uscode_parquet/laws_embeddings.parquet",
                "row_count": VECTOR_ROW_COUNT,
                "dimension": EMBEDDING_DIMENSION,
                "model": None,
                "model_revision": None,
                "chunks_per_document_min": EMBEDDING_CHUNKS_MIN,
                "chunks_per_document_max": EMBEDDING_CHUNKS_MAX,
                "identity": "positional_row_n",
            },
            "knowledge_graph": {
                "entities_path": "uscode_parquet/laws_knowledge_graph_entities.parquet",
                "relationships_path": "uscode_parquet/laws_knowledge_graph_relationships.parquet",
                "entity_count": KG_ENTITY_COUNT,
                "relationship_count": KG_RELATIONSHIP_COUNT,
                "entity_types": ["document", "legal_document", "section", "usc_title"],
                "relationship_types": ["IN_TITLE", "HAS_SECTION"],
            },
        },
        "row_groups": {
            "laws.parquet": 1,
            "cid_index.parquet": 1,
            "laws_bm25.parquet": 1,
            "laws_embeddings.parquet": 1,
            "laws_knowledge_graph_entities.parquet": 1,
            "laws_knowledge_graph_relationships.parquet": 1,
            "maximum_rows_per_physical_shard_target": 4096,
            "legacy_monoliths_exceed_target": True,
        },
        "identity_anomalies": [
            {
                "code": "RECOVERY_ROWS_WITHOUT_CID",
                "severity": "blocking",
                "count": RECOVERY_ROW_COUNT,
                "detail": (
                    f"{RECOVERY_ROW_COUNT} heterogeneous recovery rows in laws.parquet "
                    "lack canonical CIDs and must be quarantined from search configs"
                ),
            },
            {
                "code": "POSITIONAL_EMBEDDING_JOIN",
                "severity": "blocking",
                "count": VECTOR_ROW_COUNT,
                "detail": (
                    "laws_embeddings.parquet joins by positional row-N identity; "
                    "vectors are not trusted for migration without recomputation"
                ),
            },
            {
                "code": "UNKNOWN_EMBEDDING_MODEL",
                "severity": "blocking",
                "count": VECTOR_ROW_COUNT,
                "detail": "embedding model and revision are absent from the release",
            },
            {
                "code": "DATE_MODIFIED_NOT_CURRENTNESS",
                "severity": "informational",
                "count": CANONICAL_CID_COUNT,
                "detail": (
                    "every canonical date_modified value is 2024 even though the "
                    "repository was modified in 2026; publication time is not a "
                    "legal-currentness claim"
                ),
            },
        ],
        "legacy_joins": {
            "corpus_to_cid_index": {
                "left": "uscode_parquet/laws.parquet",
                "right": "uscode_parquet/cid_index.parquet",
                "key": "ipfs_cid",
                "left_canonical_rows": CANONICAL_CID_COUNT,
                "right_rows": CANONICAL_CID_COUNT,
                "status": "aligned_on_canonical_cids",
            },
            "corpus_to_bm25": {
                "left": "uscode_parquet/laws.parquet",
                "right": "uscode_parquet/laws_bm25.parquet",
                "key": "ipfs_cid",
                "left_canonical_rows": CANONICAL_CID_COUNT,
                "right_rows": BM25_DOCUMENT_COUNT,
                "status": "aligned_on_canonical_cids",
            },
            "corpus_to_embeddings": {
                "left": "uscode_parquet/laws.parquet",
                "right": "uscode_parquet/laws_embeddings.parquet",
                "key": "positional_row_index",
                "left_rows": CORPUS_ROW_COUNT,
                "right_rows": VECTOR_ROW_COUNT,
                "status": "legacy_positional_untrusted",
                "trusted_for_migration": False,
            },
        },
        "citations": {
            "usc_citation_occurrences": USC_CITATION_OCCURRENCES,
            "public_law_occurrences": PUBLIC_LAW_OCCURRENCES,
            "used_by_current_knowledge_graph": False,
            "note": (
                "Existing rows expose U.S.C. citations, public-law references, "
                "chapter information, subsections, and legislative history that "
                "the current graph does not use."
            ),
        },
        "sizes": {
            "repository_bytes": REPOSITORY_SIZE_BYTES,
            "repository_gib_approx": 1.019,
            "artifacts_bytes": dict(ARTIFACT_SIZES_BYTES),
        },
        "viewer": {
            "dataset_viewer_valid": False,
            "reason": (
                "Hugging Face Dataset Viewer cannot consistently infer a schema "
                "because heterogeneous recovery JSON is mixed with corpus artifacts"
            ),
            "has_explicit_configurations": False,
            "recovery_contaminates_default_config": True,
            "required_for_v2": (
                "explicit card configurations with recovery quarantined from the "
                "default config"
            ),
        },
        "blocking_issues": [
            "legacy monolith artifacts exceed the 4,096-row physical shard bound",
            "nine recovery rows lack CIDs and contaminate the default corpus view",
            "embedding identity is positional and model/revision is unknown",
            "BM25 is document term arrays without term-range routing",
            "knowledge graph omits citation and provenance structure",
            "Dataset Viewer validity fails due to heterogeneous recovery files",
        ],
        "acceptance": {
            "corpus_rows": CORPUS_ROW_COUNT,
            "canonical_cids": CANONICAL_CID_COUNT,
            "recovery_rows": RECOVERY_ROW_COUNT,
            "vectors": VECTOR_ROW_COUNT,
            "bm25_documents": BM25_DOCUMENT_COUNT,
            "kg_entities": KG_ENTITY_COUNT,
            "kg_relationships": KG_RELATIONSHIP_COUNT,
            "titles": TITLE_COUNT,
            "pinned_revision": PINNED_REVISION,
            "all_expected_outputs_accounted": True,
        },
        "network_required": False,
        "mode": "fixture",
        "source_of_truth": (
            "Live Hugging Face inventory of justicedao/ipfs_uscode at the pinned "
            "revision, sealed into this offline fixture for network-free checks"
        ),
    }
    mismatches = validate_baseline_report(report)
    if mismatches:
        raise BaselineAuditError(
            "fixture baseline failed self-validation:\n- " + "\n- ".join(mismatches)
        )
    return report


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BaselineAuditError(f"{path} must be a JSON object")
    return value


def _require_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BaselineAuditError(f"{path} must be an integer")
    return value


def _require_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineAuditError(f"{path} must be a non-empty string")
    return value


def acceptance_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project the acceptance fields used by USCIR-001 gates."""
    counts = _require_mapping(report.get("counts"), "counts")
    dataset = _require_mapping(report.get("dataset"), "dataset")
    acceptance = report.get("acceptance")
    if isinstance(acceptance, Mapping) and acceptance:
        return {
            "corpus_rows": _require_int(acceptance.get("corpus_rows"), "acceptance.corpus_rows"),
            "canonical_cids": _require_int(
                acceptance.get("canonical_cids"), "acceptance.canonical_cids"
            ),
            "recovery_rows": _require_int(
                acceptance.get("recovery_rows"), "acceptance.recovery_rows"
            ),
            "vectors": _require_int(acceptance.get("vectors"), "acceptance.vectors"),
            "bm25_documents": _require_int(
                acceptance.get("bm25_documents"), "acceptance.bm25_documents"
            ),
            "kg_entities": _require_int(
                acceptance.get("kg_entities"), "acceptance.kg_entities"
            ),
            "kg_relationships": _require_int(
                acceptance.get("kg_relationships"), "acceptance.kg_relationships"
            ),
            "titles": _require_int(acceptance.get("titles"), "acceptance.titles"),
            "pinned_revision": _require_str(
                acceptance.get("pinned_revision"), "acceptance.pinned_revision"
            ),
        }
    return {
        "corpus_rows": _require_int(counts.get("corpus_rows"), "counts.corpus_rows"),
        "canonical_cids": _require_int(counts.get("canonical_cids"), "counts.canonical_cids"),
        "recovery_rows": _require_int(counts.get("recovery_rows"), "counts.recovery_rows"),
        "vectors": _require_int(counts.get("vectors"), "counts.vectors"),
        "bm25_documents": _require_int(counts.get("bm25_documents"), "counts.bm25_documents"),
        "kg_entities": _require_int(counts.get("kg_entities"), "counts.kg_entities"),
        "kg_relationships": _require_int(
            counts.get("kg_relationships"), "counts.kg_relationships"
        ),
        "titles": _require_int(counts.get("titles"), "counts.titles"),
        "pinned_revision": _require_str(dataset.get("revision"), "dataset.revision"),
    }


def expected_acceptance() -> dict[str, Any]:
    """Return the sealed acceptance tuple for the pinned baseline."""
    return {
        "corpus_rows": CORPUS_ROW_COUNT,
        "canonical_cids": CANONICAL_CID_COUNT,
        "recovery_rows": RECOVERY_ROW_COUNT,
        "vectors": VECTOR_ROW_COUNT,
        "bm25_documents": BM25_DOCUMENT_COUNT,
        "kg_entities": KG_ENTITY_COUNT,
        "kg_relationships": KG_RELATIONSHIP_COUNT,
        "titles": TITLE_COUNT,
        "pinned_revision": PINNED_REVISION,
    }


def validate_baseline_report(report: Mapping[str, Any]) -> list[str]:
    """Validate structural invariants and acceptance counts.

    Returns a list of human-readable mismatch messages (empty when valid).
    Raises BaselineAuditError only for unrecoverable structural defects when
    callers request strict raising via check_baseline_report.
    """
    mismatches: list[str] = []

    schema = report.get("schema")
    if schema != REPORT_SCHEMA:
        mismatches.append(f"schema: expected {REPORT_SCHEMA!r}, got {schema!r}")

    try:
        actual = acceptance_projection(report)
    except BaselineAuditError as exc:
        mismatches.append(str(exc))
        return mismatches

    expected = expected_acceptance()
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            mismatches.append(
                f"{key}: expected {expected_value!r}, got {actual_value!r}"
            )

    if actual["corpus_rows"] != actual["canonical_cids"] + actual["recovery_rows"]:
        mismatches.append(
            "invariant corpus_rows == canonical_cids + recovery_rows failed: "
            f"{actual['corpus_rows']} != {actual['canonical_cids']} + "
            f"{actual['recovery_rows']}"
        )

    dataset = report.get("dataset")
    if isinstance(dataset, Mapping):
        if dataset.get("repo_id") != DATASET_REPO_ID:
            mismatches.append(
                f"dataset.repo_id: expected {DATASET_REPO_ID!r}, got {dataset.get('repo_id')!r}"
            )
        if dataset.get("revision") != PINNED_REVISION:
            mismatches.append(
                f"dataset.revision: expected {PINNED_REVISION!r}, got {dataset.get('revision')!r}"
            )
        if dataset.get("revision_pinned") is not True:
            mismatches.append("dataset.revision_pinned must be true")
    else:
        mismatches.append("dataset must be a JSON object")

    titles = report.get("titles")
    if isinstance(titles, Mapping):
        numbers = titles.get("numbers")
        if not isinstance(numbers, list) or len(numbers) != TITLE_COUNT:
            mismatches.append(
                f"titles.numbers must list exactly {TITLE_COUNT} titles"
            )
        elif list(numbers) != expected_title_numbers():
            mismatches.append("titles.numbers must equal Titles 1–52 and 54")
        if titles.get("count") != TITLE_COUNT:
            mismatches.append(
                f"titles.count: expected {TITLE_COUNT}, got {titles.get('count')!r}"
            )
    else:
        mismatches.append("titles must be a JSON object")

    for section in (
        "artifacts",
        "schemas",
        "row_groups",
        "identity_anomalies",
        "legacy_joins",
        "citations",
        "sizes",
        "viewer",
        "blocking_issues",
        "counts",
        "acceptance",
    ):
        if section not in report:
            mismatches.append(f"missing required section: {section}")

    artifacts = report.get("artifacts")
    if isinstance(artifacts, list):
        by_path = {
            item.get("path"): item
            for item in artifacts
            if isinstance(item, Mapping)
        }
        expected_paths = {
            "uscode_parquet/laws.parquet": CORPUS_ROW_COUNT,
            "uscode_parquet/cid_index.parquet": CANONICAL_CID_COUNT,
            "uscode_parquet/laws_bm25.parquet": BM25_DOCUMENT_COUNT,
            "uscode_parquet/laws_embeddings.parquet": VECTOR_ROW_COUNT,
            "uscode_parquet/laws_knowledge_graph_entities.parquet": KG_ENTITY_COUNT,
            "uscode_parquet/laws_knowledge_graph_relationships.parquet": KG_RELATIONSHIP_COUNT,
        }
        for path, rows in expected_paths.items():
            artifact = by_path.get(path)
            if artifact is None:
                mismatches.append(f"artifacts missing path {path}")
            elif artifact.get("row_count") != rows:
                mismatches.append(
                    f"artifacts[{path}].row_count: expected {rows}, got {artifact.get('row_count')!r}"
                )
    else:
        mismatches.append("artifacts must be a JSON array")

    viewer = report.get("viewer")
    if isinstance(viewer, Mapping):
        if viewer.get("dataset_viewer_valid") is not False:
            mismatches.append(
                "viewer.dataset_viewer_valid must be false for the pinned legacy baseline"
            )
    else:
        mismatches.append("viewer must be a JSON object")

    return mismatches


def check_baseline_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed check of a baseline report against the sealed acceptance."""
    mismatches = validate_baseline_report(report)
    if mismatches:
        raise BaselineAuditError(
            "baseline report check failed:\n- " + "\n- ".join(mismatches)
        )
    return {
        "ok": True,
        "task_id": TASK_ID,
        "dataset_repo_id": DATASET_REPO_ID,
        "pinned_revision": PINNED_REVISION,
        "acceptance": expected_acceptance(),
        "mismatches": [],
    }


def load_baseline_report(path: Path | str) -> dict[str, Any]:
    """Load a baseline report JSON object from disk."""
    report_path = Path(path).expanduser().resolve()
    if not report_path.is_file() or report_path.is_symlink():
        raise BaselineAuditError(
            f"baseline report must be a regular file: {report_path}"
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BaselineAuditError(
            f"cannot read baseline report {report_path}: {exc}"
        ) from exc
    if not isinstance(payload, MutableMapping):
        raise BaselineAuditError("baseline report must be a JSON object")
    return dict(payload)


def write_baseline_report(report: Mapping[str, Any], path: Path | str) -> Path:
    """Write a baseline report as sorted, indented JSON with trailing newline."""
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
    report_path.write_text(text, encoding="utf-8")
    return report_path


def render_check_summary(result: Mapping[str, Any]) -> str:
    """Render a compact human-readable check summary."""
    acceptance = result.get("acceptance") or expected_acceptance()
    lines = [
        f"ok={result.get('ok')}",
        f"task_id={result.get('task_id', TASK_ID)}",
        f"dataset={result.get('dataset_repo_id', DATASET_REPO_ID)}",
        f"revision={result.get('pinned_revision', PINNED_REVISION)}",
        (
            "counts="
            f"corpus={acceptance['corpus_rows']},"
            f"canonical={acceptance['canonical_cids']},"
            f"recovery={acceptance['recovery_rows']},"
            f"vectors={acceptance['vectors']},"
            f"bm25={acceptance['bm25_documents']},"
            f"kg_entities={acceptance['kg_entities']},"
            f"kg_relationships={acceptance['kg_relationships']},"
            f"titles={acceptance['titles']}"
        ),
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze and check the pinned justicedao/ipfs_uscode baseline audit "
            "(USCIR-001). Default fixture mode never contacts the network."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use the sealed offline fixture inventory (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen report (or the fixture inventory when the report "
            "is missing under --fixture-only) against sealed acceptance counts."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the frozen baseline report "
            f"(default: {DEFAULT_REPORT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture baseline report to --report.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the baseline report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )

    try:
        # Live Hub audit is intentionally out of scope for USCIR-001 CI.
        # This tool freezes the sealed fixture inventory and checks it offline.
        if (args.check or args.write) and not args.fixture_only:
            raise BaselineAuditError(
                "live Hub audit is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline inventory"
            )

        fixture_report = build_fixture_baseline_report()

        if args.write:
            write_baseline_report(fixture_report, report_path)
            print(f"wrote baseline report: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_baseline_report(report_path)
                check_baseline_report(on_disk)
                disk_acceptance = acceptance_projection(on_disk)
                fixture_acceptance = acceptance_projection(fixture_report)
                if disk_acceptance != fixture_acceptance:
                    raise BaselineAuditError(
                        "on-disk report acceptance diverges from sealed fixture: "
                        f"disk={disk_acceptance} fixture={fixture_acceptance}"
                    )
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise BaselineAuditError(
                    f"baseline report not found for --check: {report_path}"
                )
            result = check_baseline_report(report)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
                )
            return 0

        if args.print_json:
            sys.stdout.write(
                json.dumps(fixture_report, indent=2, sort_keys=True) + "\n"
            )
            return 0

        if args.write:
            return 0

        # Default: show sealed acceptance summary from fixture.
        check_baseline_report(fixture_report)
        print(render_check_summary({"ok": True, "acceptance": expected_acceptance()}))
        print(
            "hint: pass --fixture-only --check to validate the frozen report",
            file=sys.stderr,
        )
        return 0
    except BaselineAuditError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
