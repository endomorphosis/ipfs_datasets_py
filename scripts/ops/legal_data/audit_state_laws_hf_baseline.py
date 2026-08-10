#!/usr/bin/env python3
"""Freeze and check the pinned justicedao/ipfs_state_laws baseline audit (LCR-001).

Default operation is offline and network-free. The fixture inventory encodes the
live Hugging Face evidence recorded for revision
``42f0546acc7c6cd55627eaf51fb820d5613b9021`` so that the IA-only canonical
Viewer config, stale 51-jurisdiction embeddings, per-state row total,
truncation examples, zero CID overlap, missing summaries, and exact pin are
machine-checkable without contacting the Hub.

Validation gate (no network)::

    python scripts/ops/legal_data/audit_state_laws_hf_baseline.py --fixture-only --check

The frozen report path is ``docs/reports/legal_corpora_reindex/baseline.json``.
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

TASK_ID = "LCR-001"
GOAL_ID = "LCR-G010"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_state_laws_hf_baseline.py"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-baseline@1"
CODE_VERSION = "1"

DATASET_REPO_ID = "justicedao/ipfs_state_laws"
PINNED_REVISION = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
BASELINE_DATE = "2026-08-10"
LAST_MODIFIED_DATE = "2026-05-31"

DEFAULT_REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/baseline.json")

# Pinned inventory from the live Hub audit at PINNED_REVISION (2026-08-10).
REPOSITORY_FILE_COUNT = 2_116
JURISDICTION_COUNT = 51
STATE_PARQUET_FILENAME_COUNT = 51

VIEWER_CANONICAL_ROW_COUNT = 47_204
VIEWER_CANONICAL_LABEL = "IA"
VIEWER_EMBEDDING_ROW_COUNT = 17_338
VIEWER_EMBEDDING_JURISDICTION_COUNT = 51
VIEWER_EMBEDDING_ROWS_PER_JURISDICTION_MIN = 1
VIEWER_EMBEDDING_ROWS_PER_JURISDICTION_MAX = 104

PER_STATE_CANONICAL_TOTAL_ROWS = 212_103
README_CLAIMED_CANONICAL_ROWS = 20_514

STATE_SUMMARY_COUNT = 49
MISSING_SUMMARIES: tuple[str, ...] = ("CA", "DC")

# Obvious remote per-jurisdiction truncations sealed from the live audit.
TRUNCATION_EXAMPLES: Mapping[str, int] = {
    "GA": 2,
    "HI": 4,
    "IN": 4,
    "MS": 1,
    "WA": 1,
    "WV": 1,
}

# Repo-tracked completed-state registry marks truncated scrapes as success.
REGISTRY_JURISDICTION_COUNT = 47
REGISTRY_TRUNCATION_EXAMPLES: Mapping[str, int] = {
    "NJ": 1,
    "GA": 2,
    "LA": 4,
    "CO": 5,
    "MA": 14,
}

CID_OVERLAP_COUNT = 0

# Exact 51-jurisdiction set: 50 states + DC (sealed constant for this freeze).
JURISDICTION_CODES: tuple[str, ...] = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
)

CODE_HAZARDS: tuple[Mapping[str, str], ...] = (
    {
        "path": "scripts/ops/legal_data/refresh_state_laws_corpus.py",
        "hazard": (
            "defines `all` as 50 states with DC opt-in; merges by content CID "
            "before logical identity; rebuilds combined Parquet from the "
            "requested subset; permits upload using requested-scope is_complete"
        ),
    },
    {
        "path": "scripts/ops/legal_data/check_state_law_coverage.py",
        "hazard": "defaults to a one-row coverage threshold",
    },
    {
        "path": "scripts/ops/legal_data/report_state_law_corpus_gaps.py",
        "hazard": "omits DC from gap reporting",
    },
    {
        "path": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
        "hazard": (
            "treats a nonzero, error-free requested subset as full coverage"
        ),
    },
)


class BaselineAuditError(RuntimeError):
    """Raised when the baseline audit cannot complete fail-closed."""


def default_report_path(repo_root: Path | str | None = None) -> Path:
    """Return the repository-relative frozen baseline report path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def expected_jurisdiction_codes() -> list[str]:
    """Return the exact 51-jurisdiction set (50 states + DC)."""
    codes = list(JURISDICTION_CODES)
    if len(codes) != JURISDICTION_COUNT:
        raise BaselineAuditError(
            f"jurisdiction set invariant broken: expected {JURISDICTION_COUNT}, "
            f"got {len(codes)}"
        )
    if "DC" not in codes:
        raise BaselineAuditError("jurisdiction set must include DC")
    if len(set(codes)) != len(codes):
        raise BaselineAuditError("jurisdiction set contains duplicates")
    return codes


def expected_truncation_examples() -> dict[str, int]:
    """Return sealed remote per-jurisdiction truncation examples."""
    return dict(TRUNCATION_EXAMPLES)


def expected_missing_summaries() -> list[str]:
    """Return jurisdictions whose state summaries are absent on the Hub."""
    missing = list(MISSING_SUMMARIES)
    if STATE_SUMMARY_COUNT + len(missing) != JURISDICTION_COUNT:
        raise BaselineAuditError(
            "summary coverage invariant broken: "
            f"{STATE_SUMMARY_COUNT} + {len(missing)} != {JURISDICTION_COUNT}"
        )
    return missing


def build_fixture_baseline_report() -> dict[str, Any]:
    """Build the frozen offline baseline report for the pinned Hub revision.

    The report is the durable evidence contract for LCR-001. It does not
    contact the network; values are the sealed live-audit inventory.
    """
    jurisdictions = expected_jurisdiction_codes()
    missing_summaries = expected_missing_summaries()
    truncation_examples = expected_truncation_examples()

    if CID_OVERLAP_COUNT != 0:
        raise BaselineAuditError(
            f"CID overlap invariant broken: expected 0, got {CID_OVERLAP_COUNT}"
        )

    state_parquet_files = [f"STATE-{code}.parquet" for code in jurisdictions]

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
            "last_modified": LAST_MODIFIED_DATE,
            "has_readme": True,
            "readme_claimed_canonical_rows": README_CLAIMED_CANONICAL_ROWS,
        },
        "counts": {
            "repository_files": REPOSITORY_FILE_COUNT,
            "jurisdictions": JURISDICTION_COUNT,
            "state_parquet_filenames": STATE_PARQUET_FILENAME_COUNT,
            "viewer_canonical_rows": VIEWER_CANONICAL_ROW_COUNT,
            "viewer_embedding_rows": VIEWER_EMBEDDING_ROW_COUNT,
            "viewer_embedding_jurisdictions": VIEWER_EMBEDDING_JURISDICTION_COUNT,
            "per_state_canonical_total_rows": PER_STATE_CANONICAL_TOTAL_ROWS,
            "readme_claimed_canonical_rows": README_CLAIMED_CANONICAL_ROWS,
            "state_summaries_present": STATE_SUMMARY_COUNT,
            "state_summaries_missing": len(missing_summaries),
            "registry_jurisdictions": REGISTRY_JURISDICTION_COUNT,
            "cid_overlap_canonical_vs_embeddings": CID_OVERLAP_COUNT,
        },
        "jurisdictions": {
            "count": JURISDICTION_COUNT,
            "codes": jurisdictions,
            "includes_dc": True,
            "span_note": "Exact 50 U.S. states plus the District of Columbia",
        },
        "viewer": {
            "canonical_config": {
                "row_count": VIEWER_CANONICAL_ROW_COUNT,
                "jurisdiction_labels": [VIEWER_CANONICAL_LABEL],
                "ia_only": True,
                "all_rows_labeled_ia": True,
                "note": (
                    "Hugging Face Viewer canonical config has "
                    f"{VIEWER_CANONICAL_ROW_COUNT} rows, all labeled "
                    f"{VIEWER_CANONICAL_LABEL}"
                ),
            },
            "embedding_config": {
                "row_count": VIEWER_EMBEDDING_ROW_COUNT,
                "jurisdiction_count": VIEWER_EMBEDDING_JURISDICTION_COUNT,
                "rows_per_jurisdiction_min": VIEWER_EMBEDDING_ROWS_PER_JURISDICTION_MIN,
                "rows_per_jurisdiction_max": VIEWER_EMBEDDING_ROWS_PER_JURISDICTION_MAX,
                "stale_sample": True,
                "note": (
                    "Viewer embedding config has "
                    f"{VIEWER_EMBEDDING_ROW_COUNT} rows over "
                    f"{VIEWER_EMBEDDING_JURISDICTION_COUNT} jurisdictions; "
                    "most jurisdictions have only "
                    f"{VIEWER_EMBEDDING_ROWS_PER_JURISDICTION_MIN}–"
                    f"{VIEWER_EMBEDDING_ROWS_PER_JURISDICTION_MAX} rows and "
                    "represent an older sample"
                ),
            },
            "dataset_viewer_valid": False,
            "reason": (
                "canonical config is IA-only and conflicts with per-state "
                "Parquet totals, README claims, and embedding sample"
            ),
        },
        "cid_overlap": {
            "canonical_vs_embeddings": CID_OVERLAP_COUNT,
            "zero_overlap": True,
            "detail": (
                "Viewer embedding config has zero CID overlap with the "
                "canonical config"
            ),
        },
        "per_state_files": {
            "filename_pattern": "STATE-XX.parquet",
            "filename_count": STATE_PARQUET_FILENAME_COUNT,
            "filenames": state_parquet_files,
            "includes_dc": True,
            "total_rows": PER_STATE_CANONICAL_TOTAL_ROWS,
            "truncation_examples": truncation_examples,
            "logical_identifier_duplication": True,
            "derived_index_drift": True,
            "note": (
                f"The {STATE_PARQUET_FILENAME_COUNT} remote per-jurisdiction "
                f"canonical files total {PER_STATE_CANONICAL_TOTAL_ROWS} rows "
                "but include obvious truncations and identity/index drift"
            ),
        },
        "summaries": {
            "present_count": STATE_SUMMARY_COUNT,
            "missing": missing_summaries,
            "missing_count": len(missing_summaries),
            "note": (
                f"only {STATE_SUMMARY_COUNT} state summaries; "
                f"{' and '.join(missing_summaries)} summaries are absent"
            ),
        },
        "manifest": {
            "path": "manifest.json",
            "contains_absolute_local_paths": True,
            "contains_old_sampled_counts": True,
            "trusted_for_migration": False,
        },
        "completed_state_registry": {
            "jurisdiction_count": REGISTRY_JURISDICTION_COUNT,
            "marks_truncated_as_success": True,
            "truncation_examples": dict(REGISTRY_TRUNCATION_EXAMPLES),
            "note": (
                f"repo-tracked completed-state registry has only "
                f"{REGISTRY_JURISDICTION_COUNT} jurisdictions and marks "
                "obviously truncated results as success"
            ),
        },
        "local_salvage": {
            "recoverable_prior_three_shard_run": True,
            "role": "comparison_and_salvage_evidence_only",
            "admitted_without_new_gates": False,
            "note": (
                "a recoverable prior three-shard run under the local "
                "legal-scraper workspace reports much larger 51-jurisdiction "
                "outputs; it is comparison/salvage evidence only until the "
                "new provenance and frontier gates validate it"
            ),
        },
        "code_hazards": [dict(item) for item in CODE_HAZARDS],
        "identity_anomalies": [
            {
                "code": "IA_ONLY_CANONICAL_VIEWER",
                "severity": "blocking",
                "count": VIEWER_CANONICAL_ROW_COUNT,
                "detail": (
                    f"Viewer canonical config is entirely labeled "
                    f"{VIEWER_CANONICAL_LABEL} ({VIEWER_CANONICAL_ROW_COUNT} rows)"
                ),
            },
            {
                "code": "STALE_51_STATE_EMBEDDINGS",
                "severity": "blocking",
                "count": VIEWER_EMBEDDING_ROW_COUNT,
                "detail": (
                    f"Viewer embedding config has {VIEWER_EMBEDDING_ROW_COUNT} "
                    f"rows over {VIEWER_EMBEDDING_JURISDICTION_COUNT} "
                    "jurisdictions with sparse per-jurisdiction coverage and "
                    "represents an older sample"
                ),
            },
            {
                "code": "ZERO_CID_OVERLAP",
                "severity": "blocking",
                "count": CID_OVERLAP_COUNT,
                "detail": (
                    "embedding config has zero CID overlap with the canonical "
                    "config; vectors cannot join the corpus by content address"
                ),
            },
            {
                "code": "PER_STATE_TRUNCATION",
                "severity": "blocking",
                "count": len(truncation_examples),
                "detail": (
                    "remote per-jurisdiction files include obvious truncations: "
                    + ", ".join(
                        f"{code}={rows}"
                        for code, rows in sorted(truncation_examples.items())
                    )
                ),
            },
            {
                "code": "MISSING_STATE_SUMMARIES",
                "severity": "blocking",
                "count": len(missing_summaries),
                "detail": (
                    "state summaries absent for: "
                    + ", ".join(missing_summaries)
                ),
            },
            {
                "code": "README_ROW_COUNT_CONFLICT",
                "severity": "blocking",
                "count": README_CLAIMED_CANONICAL_ROWS,
                "detail": (
                    f"README claims {README_CLAIMED_CANONICAL_ROWS} canonical "
                    f"rows, which conflicts with Viewer "
                    f"({VIEWER_CANONICAL_ROW_COUNT}) and per-state total "
                    f"({PER_STATE_CANONICAL_TOTAL_ROWS})"
                ),
            },
            {
                "code": "REGISTRY_FALSE_SUCCESS",
                "severity": "blocking",
                "count": REGISTRY_JURISDICTION_COUNT,
                "detail": (
                    "completed-state registry marks truncated scrapes as "
                    "success and covers only "
                    f"{REGISTRY_JURISDICTION_COUNT} jurisdictions"
                ),
            },
            {
                "code": "MANIFEST_LOCAL_PATHS",
                "severity": "blocking",
                "count": 1,
                "detail": (
                    "manifest.json contains absolute local paths and old "
                    "sampled counts"
                ),
            },
        ],
        "blocking_issues": [
            "Viewer canonical config is IA-only and not a 51-jurisdiction corpus",
            "Viewer embeddings are a stale sparse sample with zero CID overlap",
            (
                f"per-state Parquet total is {PER_STATE_CANONICAL_TOTAL_ROWS} "
                "with obvious truncations"
            ),
            f"state summaries missing for {', '.join(missing_summaries)}",
            (
                f"README claims {README_CLAIMED_CANONICAL_ROWS} rows, conflicting "
                "with Viewer and per-state totals"
            ),
            "manifest.json embeds absolute local paths and old sampled counts",
            (
                f"completed-state registry covers {REGISTRY_JURISDICTION_COUNT} "
                "jurisdictions and promotes truncated success flags"
            ),
            "refresh/coverage/scraper paths treat filename presence as completion",
        ],
        "acceptance": {
            "ia_only_canonical": True,
            "viewer_canonical_rows": VIEWER_CANONICAL_ROW_COUNT,
            "viewer_canonical_label": VIEWER_CANONICAL_LABEL,
            "stale_51_state_embeddings": True,
            "viewer_embedding_rows": VIEWER_EMBEDDING_ROW_COUNT,
            "viewer_embedding_jurisdictions": VIEWER_EMBEDDING_JURISDICTION_COUNT,
            "per_state_total_rows": PER_STATE_CANONICAL_TOTAL_ROWS,
            "truncation_examples": truncation_examples,
            "zero_cid_overlap": True,
            "cid_overlap_count": CID_OVERLAP_COUNT,
            "missing_summaries": missing_summaries,
            "state_summaries_present": STATE_SUMMARY_COUNT,
            "pinned_revision": PINNED_REVISION,
            "repository_files": REPOSITORY_FILE_COUNT,
            "jurisdictions": JURISDICTION_COUNT,
            "all_expected_outputs_accounted": True,
        },
        "network_required": False,
        "mode": "fixture",
        "source_of_truth": (
            "Live Hugging Face inventory of justicedao/ipfs_state_laws at the "
            "pinned revision, sealed into this offline fixture for "
            "network-free checks"
        ),
        "unsuitable_as_source_of_truth": True,
        "evidence_role": (
            "Existing remote artifacts are evidence inputs only. They may seed "
            "differential audits, but no prior row or success flag is admitted "
            "without the new provenance and completeness gates."
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


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise BaselineAuditError(f"{path} must be a boolean")
    return value


def _require_str_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise BaselineAuditError(f"{path} must be a non-empty-string array")
    return list(value)


def _require_int_mapping(value: Any, path: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise BaselineAuditError(f"{path} must be a JSON object")
    out: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise BaselineAuditError(f"{path} keys must be non-empty strings")
        if isinstance(item, bool) or not isinstance(item, int):
            raise BaselineAuditError(f"{path}.{key} must be an integer")
        out[key] = item
    return out


def acceptance_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project the acceptance fields used by LCR-001 gates."""
    acceptance = report.get("acceptance")
    if isinstance(acceptance, Mapping) and acceptance:
        return {
            "ia_only_canonical": _require_bool(
                acceptance.get("ia_only_canonical"), "acceptance.ia_only_canonical"
            ),
            "viewer_canonical_rows": _require_int(
                acceptance.get("viewer_canonical_rows"),
                "acceptance.viewer_canonical_rows",
            ),
            "viewer_canonical_label": _require_str(
                acceptance.get("viewer_canonical_label"),
                "acceptance.viewer_canonical_label",
            ),
            "stale_51_state_embeddings": _require_bool(
                acceptance.get("stale_51_state_embeddings"),
                "acceptance.stale_51_state_embeddings",
            ),
            "viewer_embedding_rows": _require_int(
                acceptance.get("viewer_embedding_rows"),
                "acceptance.viewer_embedding_rows",
            ),
            "viewer_embedding_jurisdictions": _require_int(
                acceptance.get("viewer_embedding_jurisdictions"),
                "acceptance.viewer_embedding_jurisdictions",
            ),
            "per_state_total_rows": _require_int(
                acceptance.get("per_state_total_rows"),
                "acceptance.per_state_total_rows",
            ),
            "truncation_examples": _require_int_mapping(
                acceptance.get("truncation_examples"),
                "acceptance.truncation_examples",
            ),
            "zero_cid_overlap": _require_bool(
                acceptance.get("zero_cid_overlap"), "acceptance.zero_cid_overlap"
            ),
            "cid_overlap_count": _require_int(
                acceptance.get("cid_overlap_count"), "acceptance.cid_overlap_count"
            ),
            "missing_summaries": _require_str_list(
                acceptance.get("missing_summaries"), "acceptance.missing_summaries"
            ),
            "state_summaries_present": _require_int(
                acceptance.get("state_summaries_present"),
                "acceptance.state_summaries_present",
            ),
            "pinned_revision": _require_str(
                acceptance.get("pinned_revision"), "acceptance.pinned_revision"
            ),
            "repository_files": _require_int(
                acceptance.get("repository_files"), "acceptance.repository_files"
            ),
            "jurisdictions": _require_int(
                acceptance.get("jurisdictions"), "acceptance.jurisdictions"
            ),
        }

    counts = _require_mapping(report.get("counts"), "counts")
    dataset = _require_mapping(report.get("dataset"), "dataset")
    viewer = _require_mapping(report.get("viewer"), "viewer")
    canonical = _require_mapping(viewer.get("canonical_config"), "viewer.canonical_config")
    embeddings = _require_mapping(
        viewer.get("embedding_config"), "viewer.embedding_config"
    )
    per_state = _require_mapping(report.get("per_state_files"), "per_state_files")
    summaries = _require_mapping(report.get("summaries"), "summaries")
    cid_overlap = _require_mapping(report.get("cid_overlap"), "cid_overlap")
    return {
        "ia_only_canonical": _require_bool(
            canonical.get("ia_only"), "viewer.canonical_config.ia_only"
        ),
        "viewer_canonical_rows": _require_int(
            counts.get("viewer_canonical_rows"), "counts.viewer_canonical_rows"
        ),
        "viewer_canonical_label": VIEWER_CANONICAL_LABEL,
        "stale_51_state_embeddings": _require_bool(
            embeddings.get("stale_sample"), "viewer.embedding_config.stale_sample"
        ),
        "viewer_embedding_rows": _require_int(
            counts.get("viewer_embedding_rows"), "counts.viewer_embedding_rows"
        ),
        "viewer_embedding_jurisdictions": _require_int(
            counts.get("viewer_embedding_jurisdictions"),
            "counts.viewer_embedding_jurisdictions",
        ),
        "per_state_total_rows": _require_int(
            per_state.get("total_rows"), "per_state_files.total_rows"
        ),
        "truncation_examples": _require_int_mapping(
            per_state.get("truncation_examples"),
            "per_state_files.truncation_examples",
        ),
        "zero_cid_overlap": _require_bool(
            cid_overlap.get("zero_overlap"), "cid_overlap.zero_overlap"
        ),
        "cid_overlap_count": _require_int(
            cid_overlap.get("canonical_vs_embeddings"),
            "cid_overlap.canonical_vs_embeddings",
        ),
        "missing_summaries": _require_str_list(
            summaries.get("missing"), "summaries.missing"
        ),
        "state_summaries_present": _require_int(
            summaries.get("present_count"), "summaries.present_count"
        ),
        "pinned_revision": _require_str(dataset.get("revision"), "dataset.revision"),
        "repository_files": _require_int(
            counts.get("repository_files"), "counts.repository_files"
        ),
        "jurisdictions": _require_int(counts.get("jurisdictions"), "counts.jurisdictions"),
    }


def expected_acceptance() -> dict[str, Any]:
    """Return the sealed acceptance tuple for the pinned baseline."""
    return {
        "ia_only_canonical": True,
        "viewer_canonical_rows": VIEWER_CANONICAL_ROW_COUNT,
        "viewer_canonical_label": VIEWER_CANONICAL_LABEL,
        "stale_51_state_embeddings": True,
        "viewer_embedding_rows": VIEWER_EMBEDDING_ROW_COUNT,
        "viewer_embedding_jurisdictions": VIEWER_EMBEDDING_JURISDICTION_COUNT,
        "per_state_total_rows": PER_STATE_CANONICAL_TOTAL_ROWS,
        "truncation_examples": expected_truncation_examples(),
        "zero_cid_overlap": True,
        "cid_overlap_count": CID_OVERLAP_COUNT,
        "missing_summaries": expected_missing_summaries(),
        "state_summaries_present": STATE_SUMMARY_COUNT,
        "pinned_revision": PINNED_REVISION,
        "repository_files": REPOSITORY_FILE_COUNT,
        "jurisdictions": JURISDICTION_COUNT,
    }


def validate_baseline_report(report: Mapping[str, Any]) -> list[str]:
    """Validate structural invariants and acceptance counts.

    Returns a list of human-readable mismatch messages (empty when valid).
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

    if actual["cid_overlap_count"] != 0 or actual["zero_cid_overlap"] is not True:
        mismatches.append(
            "zero CID overlap invariant failed: "
            f"cid_overlap_count={actual['cid_overlap_count']!r}, "
            f"zero_cid_overlap={actual['zero_cid_overlap']!r}"
        )

    if actual["ia_only_canonical"] is not True:
        mismatches.append("ia_only_canonical must be true")

    if actual["stale_51_state_embeddings"] is not True:
        mismatches.append("stale_51_state_embeddings must be true")

    if actual["viewer_canonical_label"] != VIEWER_CANONICAL_LABEL:
        mismatches.append(
            f"viewer_canonical_label must be {VIEWER_CANONICAL_LABEL!r}"
        )

    if set(actual["missing_summaries"]) != set(MISSING_SUMMARIES):
        mismatches.append(
            f"missing_summaries must equal {list(MISSING_SUMMARIES)!r}"
        )

    if actual["truncation_examples"] != expected_truncation_examples():
        mismatches.append(
            "truncation_examples must equal the sealed remote truncation map"
        )

    if (
        actual["state_summaries_present"] + len(actual["missing_summaries"])
        != JURISDICTION_COUNT
    ):
        mismatches.append(
            "summary coverage invariant failed: "
            f"{actual['state_summaries_present']} present + "
            f"{len(actual['missing_summaries'])} missing != "
            f"{JURISDICTION_COUNT}"
        )

    dataset = report.get("dataset")
    if isinstance(dataset, Mapping):
        if dataset.get("repo_id") != DATASET_REPO_ID:
            mismatches.append(
                f"dataset.repo_id: expected {DATASET_REPO_ID!r}, "
                f"got {dataset.get('repo_id')!r}"
            )
        if dataset.get("revision") != PINNED_REVISION:
            mismatches.append(
                f"dataset.revision: expected {PINNED_REVISION!r}, "
                f"got {dataset.get('revision')!r}"
            )
        if dataset.get("revision_pinned") is not True:
            mismatches.append("dataset.revision_pinned must be true")
    else:
        mismatches.append("dataset must be a JSON object")

    jurisdictions = report.get("jurisdictions")
    if isinstance(jurisdictions, Mapping):
        codes = jurisdictions.get("codes")
        if not isinstance(codes, list) or len(codes) != JURISDICTION_COUNT:
            mismatches.append(
                f"jurisdictions.codes must list exactly {JURISDICTION_COUNT} codes"
            )
        elif list(codes) != expected_jurisdiction_codes():
            mismatches.append(
                "jurisdictions.codes must equal the sealed 50-state-plus-DC set"
            )
        if jurisdictions.get("count") != JURISDICTION_COUNT:
            mismatches.append(
                f"jurisdictions.count: expected {JURISDICTION_COUNT}, "
                f"got {jurisdictions.get('count')!r}"
            )
        if jurisdictions.get("includes_dc") is not True:
            mismatches.append("jurisdictions.includes_dc must be true")
    else:
        mismatches.append("jurisdictions must be a JSON object")

    for section in (
        "counts",
        "jurisdictions",
        "viewer",
        "cid_overlap",
        "per_state_files",
        "summaries",
        "manifest",
        "completed_state_registry",
        "local_salvage",
        "code_hazards",
        "identity_anomalies",
        "blocking_issues",
        "acceptance",
    ):
        if section not in report:
            mismatches.append(f"missing required section: {section}")

    viewer = report.get("viewer")
    if isinstance(viewer, Mapping):
        canonical = viewer.get("canonical_config")
        if isinstance(canonical, Mapping):
            if canonical.get("ia_only") is not True:
                mismatches.append("viewer.canonical_config.ia_only must be true")
            if canonical.get("row_count") != VIEWER_CANONICAL_ROW_COUNT:
                mismatches.append(
                    "viewer.canonical_config.row_count: expected "
                    f"{VIEWER_CANONICAL_ROW_COUNT}, got {canonical.get('row_count')!r}"
                )
        else:
            mismatches.append("viewer.canonical_config must be a JSON object")
        embeddings = viewer.get("embedding_config")
        if isinstance(embeddings, Mapping):
            if embeddings.get("stale_sample") is not True:
                mismatches.append(
                    "viewer.embedding_config.stale_sample must be true"
                )
            if embeddings.get("row_count") != VIEWER_EMBEDDING_ROW_COUNT:
                mismatches.append(
                    "viewer.embedding_config.row_count: expected "
                    f"{VIEWER_EMBEDDING_ROW_COUNT}, got {embeddings.get('row_count')!r}"
                )
            if embeddings.get("jurisdiction_count") != VIEWER_EMBEDDING_JURISDICTION_COUNT:
                mismatches.append(
                    "viewer.embedding_config.jurisdiction_count: expected "
                    f"{VIEWER_EMBEDDING_JURISDICTION_COUNT}, "
                    f"got {embeddings.get('jurisdiction_count')!r}"
                )
        else:
            mismatches.append("viewer.embedding_config must be a JSON object")
    else:
        mismatches.append("viewer must be a JSON object")

    cid_overlap = report.get("cid_overlap")
    if isinstance(cid_overlap, Mapping):
        if cid_overlap.get("canonical_vs_embeddings") != 0:
            mismatches.append(
                "cid_overlap.canonical_vs_embeddings must be 0"
            )
        if cid_overlap.get("zero_overlap") is not True:
            mismatches.append("cid_overlap.zero_overlap must be true")
    else:
        mismatches.append("cid_overlap must be a JSON object")

    per_state = report.get("per_state_files")
    if isinstance(per_state, Mapping):
        if per_state.get("total_rows") != PER_STATE_CANONICAL_TOTAL_ROWS:
            mismatches.append(
                "per_state_files.total_rows: expected "
                f"{PER_STATE_CANONICAL_TOTAL_ROWS}, "
                f"got {per_state.get('total_rows')!r}"
            )
        if per_state.get("filename_count") != STATE_PARQUET_FILENAME_COUNT:
            mismatches.append(
                "per_state_files.filename_count: expected "
                f"{STATE_PARQUET_FILENAME_COUNT}, "
                f"got {per_state.get('filename_count')!r}"
            )
        trunc = per_state.get("truncation_examples")
        if not isinstance(trunc, Mapping) or dict(trunc) != expected_truncation_examples():
            mismatches.append(
                "per_state_files.truncation_examples must match sealed map"
            )
    else:
        mismatches.append("per_state_files must be a JSON object")

    summaries = report.get("summaries")
    if isinstance(summaries, Mapping):
        if summaries.get("present_count") != STATE_SUMMARY_COUNT:
            mismatches.append(
                "summaries.present_count: expected "
                f"{STATE_SUMMARY_COUNT}, got {summaries.get('present_count')!r}"
            )
        missing = summaries.get("missing")
        if not isinstance(missing, list) or list(missing) != list(MISSING_SUMMARIES):
            mismatches.append(
                f"summaries.missing must equal {list(MISSING_SUMMARIES)!r}"
            )
    else:
        mismatches.append("summaries must be a JSON object")

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
    trunc = acceptance.get("truncation_examples") or {}
    trunc_text = ",".join(
        f"{code}={rows}" for code, rows in sorted(trunc.items())
    )
    missing = acceptance.get("missing_summaries") or []
    lines = [
        f"ok={result.get('ok')}",
        f"task_id={result.get('task_id', TASK_ID)}",
        f"dataset={result.get('dataset_repo_id', DATASET_REPO_ID)}",
        f"revision={result.get('pinned_revision', PINNED_REVISION)}",
        (
            "counts="
            f"viewer_canonical={acceptance['viewer_canonical_rows']},"
            f"viewer_embeddings={acceptance['viewer_embedding_rows']},"
            f"per_state_total={acceptance['per_state_total_rows']},"
            f"cid_overlap={acceptance['cid_overlap_count']},"
            f"summaries={acceptance['state_summaries_present']},"
            f"jurisdictions={acceptance['jurisdictions']},"
            f"files={acceptance['repository_files']}"
        ),
        f"ia_only_canonical={acceptance['ia_only_canonical']}",
        f"stale_51_state_embeddings={acceptance['stale_51_state_embeddings']}",
        f"zero_cid_overlap={acceptance['zero_cid_overlap']}",
        f"truncation_examples={trunc_text}",
        f"missing_summaries={','.join(missing)}",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze and check the pinned justicedao/ipfs_state_laws baseline "
            "audit (LCR-001). Default fixture mode never contacts the network."
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
            "Validate the frozen report (or the fixture inventory when the "
            "report is missing under --fixture-only) against sealed acceptance."
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
        # Live Hub audit is intentionally out of scope for LCR-001 CI.
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
