#!/usr/bin/env python3
"""Freeze and check the pinned justicedao/ipfs_federal_register baseline (LCR-048).

Default operation is offline and network-free. The fixture inventory encodes the
live Hugging Face evidence recorded for revision
``720668ae016cc400916dda884c9005e03618edfa`` so that the 993703 advertised versus
993708 materialized count mismatch, 1994-01-01 through 2026-03-02 range, missing
full text/card, legacy layout, and exact pin are machine-checkable without
contacting the Hub.

Validation gate (no network)::

    python scripts/ops/legal_data/audit_federal_register_hf_baseline.py --fixture-only --check

The frozen report path is ``docs/reports/legal_corpora_reindex/federal_baseline.json``.
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

TASK_ID = "LCR-048"
GOAL_ID = "LCR-G100"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_federal_register_hf_baseline.py"
REPORT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-federal-baseline@1"
CODE_VERSION = "1"

DATASET_REPO_ID = "justicedao/ipfs_federal_register"
PINNED_REVISION = "720668ae016cc400916dda884c9005e03618edfa"
BASELINE_DATE = "2026-08-10"
LAST_MODIFIED_DATE = "2026-04-18"

DEFAULT_REPORT_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_baseline.json")

# Pinned inventory from the live Hub audit at PINNED_REVISION (2026-08-10).
REPOSITORY_FILE_COUNT = 555

ADVERTISED_DOCUMENT_COUNT = 993_703
MATERIALIZED_ROW_COUNT = 993_708
RECOVERY_PLACEHOLDER_ROW_COUNT = 5
CANONICAL_DOCUMENT_ROW_COUNT = ADVERTISED_DOCUMENT_COUNT

DATE_RANGE_START = "1994-01-01"
DATE_RANGE_END = "2026-03-02"
DATE_RANGE_COUNT = 255
INCLUDE_FULL_TEXT = False

EMPTY_TEXT_ROW_COUNT = 358_455
ABSTRACT_CAP_CHARACTERS = 500
EMPTY_SOURCE_URL_ALL_ROWS = True

POST_ENDPOINT_DELTA_DOCUMENTS_MIN = 11_784
POST_ENDPOINT_DELTA_START = "2026-03-03"
PLANNING_CUTOFF_DATE = "2026-08-10"

# Legacy root-level layout present on the pinned revision.
LEGACY_LAYOUT_ARTIFACTS: tuple[str, ...] = (
    "metadata.json",
    "manifest.json",
    "federal_register.jsonld",
    "federal_register.parquet",
    "federal_register_raw/",
    "federal_register_gte_small.faiss",
    "federal_register_gte_small_metadata.parquet",
)

CODE_HAZARDS: tuple[Mapping[str, str], ...] = (
    {
        "path": "generic inventory configuration",
        "hazard": (
            "leaves publish_embeddings_files empty and aliases new FAISS "
            "output onto legacy filenames"
        ),
    },
    {
        "path": "generic quality gate",
        "hazard": (
            "quality gate is state-law-specific and does not fail publication "
            "on a degraded Federal Register audit"
        ),
    },
    {
        "path": "existing upload path",
        "hazard": (
            "can publish individual artifacts in separate commits, which "
            "cannot prove that corpus, sparse index, dense index, graph, "
            "manifest, and card belong to one immutable candidate"
        ),
    },
    {
        "path": "JSON-LD/Parquet conversion",
        "hazard": (
            "mismatched url and sourceUrl fields leave every Parquet "
            "source_url empty"
        ),
    },
)


class BaselineAuditError(RuntimeError):
    """Raised when the baseline audit cannot complete fail-closed."""


def default_report_path(repo_root: Path | str | None = None) -> Path:
    """Return the repository-relative frozen baseline report path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def expected_count_mismatch() -> dict[str, int]:
    """Return the sealed advertised-versus-materialized count mismatch."""
    delta = MATERIALIZED_ROW_COUNT - ADVERTISED_DOCUMENT_COUNT
    if delta != RECOVERY_PLACEHOLDER_ROW_COUNT:
        raise BaselineAuditError(
            "count mismatch invariant broken: "
            f"{MATERIALIZED_ROW_COUNT} - {ADVERTISED_DOCUMENT_COUNT} "
            f"!= {RECOVERY_PLACEHOLDER_ROW_COUNT}"
        )
    return {
        "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
        "materialized_rows": MATERIALIZED_ROW_COUNT,
        "delta": delta,
        "recovery_placeholders": RECOVERY_PLACEHOLDER_ROW_COUNT,
    }


def expected_date_range() -> dict[str, Any]:
    """Return the sealed metadata date range and partition count."""
    return {
        "start": DATE_RANGE_START,
        "end": DATE_RANGE_END,
        "date_range_count": DATE_RANGE_COUNT,
        "inclusive": True,
    }


def build_fixture_baseline_report() -> dict[str, Any]:
    """Build the frozen offline baseline report for the pinned Hub revision.

    The report is the durable evidence contract for LCR-048. It does not
    contact the network; values are the sealed live-audit inventory.
    """
    count_mismatch = expected_count_mismatch()
    date_range = expected_date_range()

    if INCLUDE_FULL_TEXT is not False:
        raise BaselineAuditError("include_full_text invariant broken: must be false")

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
            "has_readme": False,
            "has_dataset_card": False,
            "dataset_card_declares_release_contract": False,
        },
        "counts": {
            "repository_files": REPOSITORY_FILE_COUNT,
            "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
            "materialized_rows": MATERIALIZED_ROW_COUNT,
            "canonical_document_rows": CANONICAL_DOCUMENT_ROW_COUNT,
            "recovery_placeholder_rows": RECOVERY_PLACEHOLDER_ROW_COUNT,
            "count_mismatch_delta": count_mismatch["delta"],
            "date_ranges": DATE_RANGE_COUNT,
            "empty_text_rows": EMPTY_TEXT_ROW_COUNT,
            "post_endpoint_delta_documents_min": POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
        },
        "metadata": {
            "path": "metadata.json",
            "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
            "include_full_text": INCLUDE_FULL_TEXT,
            "date_range": date_range,
            "note": (
                f"metadata.json claims {ADVERTISED_DOCUMENT_COUNT} deduplicated "
                f"documents observed from {DATE_RANGE_START} through "
                f"{DATE_RANGE_END} across {DATE_RANGE_COUNT} date ranges, with "
                "include_full_text=false"
            ),
        },
        "date_range": date_range,
        "count_mismatch": {
            "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
            "materialized_rows": MATERIALIZED_ROW_COUNT,
            "delta": count_mismatch["delta"],
            "recovery_placeholders": RECOVERY_PLACEHOLDER_ROW_COUNT,
            "mismatch_present": True,
            "detail": (
                f"metadata.json advertises {ADVERTISED_DOCUMENT_COUNT} documents "
                f"but the local canonical Parquet materializes "
                f"{MATERIALIZED_ROW_COUNT} rows "
                f"({count_mismatch['delta']} recovery placeholders)"
            ),
        },
        "full_text": {
            "include_full_text": INCLUDE_FULL_TEXT,
            "missing_full_text_contract": True,
            "empty_text_rows": EMPTY_TEXT_ROW_COUNT,
            "abstract_cap_characters": ABSTRACT_CAP_CHARACTERS,
            "most_remaining_text_is_abstract_only": True,
            "note": (
                f"{EMPTY_TEXT_ROW_COUNT} baseline rows have empty text and most "
                f"remaining text is only an abstract capped near "
                f"{ABSTRACT_CAP_CHARACTERS} characters; metadata declares "
                "include_full_text=false"
            ),
        },
        "dataset_card": {
            "present": False,
            "declares_coherent_release_contract": False,
            "missing": True,
            "note": (
                "no dataset card declaring a coherent release contract is "
                "present on the pinned revision"
            ),
        },
        "legacy_layout": {
            "present": True,
            "descriptor_complete_v2": False,
            "root_level_jsonld": True,
            "one_row_group_parquet": True,
            "raw_json_shards": True,
            "gte_small_faiss_metadata": True,
            "artifacts": list(LEGACY_LAYOUT_ARTIFACTS),
            "note": (
                "legacy root-level JSON-LD, one-row-group Parquet, raw-JSON "
                "shards, and GTE-small FAISS/metadata artifacts rather than a "
                "descriptor-complete v2 layout"
            ),
        },
        "source_urls": {
            "all_parquet_source_url_empty": EMPTY_SOURCE_URL_ALL_ROWS,
            "cause": "JSON-LD/Parquet conversion mismatched url and sourceUrl",
            "trusted_for_migration": False,
        },
        "recovery": {
            "placeholder_rows": RECOVERY_PLACEHOLDER_ROW_COUNT,
            "must_quarantine": True,
            "note": (
                f"the {RECOVERY_PLACEHOLDER_ROW_COUNT} extra local rows are "
                "recovery placeholders rather than Federal Register documents "
                "and must be quarantined"
            ),
        },
        "post_endpoint_delta": {
            "legacy_endpoint": DATE_RANGE_END,
            "delta_start_inclusive": POST_ENDPOINT_DELTA_START,
            "planning_cutoff": PLANNING_CUTOFF_DATE,
            "official_api_documents_min": POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
            "note": (
                f"the official API already exposes at least "
                f"{POST_ENDPOINT_DELTA_DOCUMENTS_MIN} documents from "
                f"{POST_ENDPOINT_DELTA_START} through the planning cutoff on "
                f"{PLANNING_CUTOFF_DATE}"
            ),
        },
        "viewer": {
            "dataset_viewer_valid": False,
            "has_explicit_configurations": False,
            "reason": (
                "legacy layout mixes JSON-LD, one-row-group Parquet, raw JSON "
                "shards, and FAISS metadata without a card-declared contract"
            ),
        },
        "code_hazards": [dict(item) for item in CODE_HAZARDS],
        "identity_anomalies": [
            {
                "code": "ADVERTISED_VS_MATERIALIZED_COUNT_MISMATCH",
                "severity": "blocking",
                "count": count_mismatch["delta"],
                "detail": (
                    f"advertised {ADVERTISED_DOCUMENT_COUNT} vs materialized "
                    f"{MATERIALIZED_ROW_COUNT} "
                    f"(delta={count_mismatch['delta']} recovery placeholders)"
                ),
            },
            {
                "code": "MISSING_FULL_TEXT_CONTRACT",
                "severity": "blocking",
                "count": EMPTY_TEXT_ROW_COUNT,
                "detail": (
                    f"include_full_text=false; {EMPTY_TEXT_ROW_COUNT} empty-text "
                    f"rows; remaining text mostly abstract-capped near "
                    f"{ABSTRACT_CAP_CHARACTERS} characters"
                ),
            },
            {
                "code": "MISSING_DATASET_CARD",
                "severity": "blocking",
                "count": 1,
                "detail": (
                    "no dataset card declaring a coherent release contract"
                ),
            },
            {
                "code": "LEGACY_LAYOUT",
                "severity": "blocking",
                "count": REPOSITORY_FILE_COUNT,
                "detail": (
                    "legacy root-level JSON-LD/Parquet/raw-JSON/FAISS layout "
                    f"across {REPOSITORY_FILE_COUNT} files; not descriptor-complete v2"
                ),
            },
            {
                "code": "EMPTY_SOURCE_URLS",
                "severity": "blocking",
                "count": MATERIALIZED_ROW_COUNT,
                "detail": (
                    "every Parquet source_url is empty due to url/sourceUrl "
                    "field mismatch in JSON-LD conversion"
                ),
            },
            {
                "code": "RECOVERY_PLACEHOLDER_ROWS",
                "severity": "blocking",
                "count": RECOVERY_PLACEHOLDER_ROW_COUNT,
                "detail": (
                    f"{RECOVERY_PLACEHOLDER_ROW_COUNT} recovery placeholders "
                    "must be quarantined from publication counts"
                ),
            },
            {
                "code": "POST_ENDPOINT_GAP",
                "severity": "blocking",
                "count": POST_ENDPOINT_DELTA_DOCUMENTS_MIN,
                "detail": (
                    f"at least {POST_ENDPOINT_DELTA_DOCUMENTS_MIN} official "
                    f"documents after the legacy {DATE_RANGE_END} endpoint "
                    f"through {PLANNING_CUTOFF_DATE}"
                ),
            },
        ],
        "blocking_issues": [
            (
                f"advertised {ADVERTISED_DOCUMENT_COUNT} documents vs "
                f"materialized {MATERIALIZED_ROW_COUNT} rows"
            ),
            (
                f"metadata date range is {DATE_RANGE_START} through "
                f"{DATE_RANGE_END} across {DATE_RANGE_COUNT} partitions"
            ),
            "include_full_text=false with empty/abstract-only text at scale",
            "no dataset card declaring a coherent release contract",
            "legacy layout rather than descriptor-complete v2",
            "every Parquet source_url is empty",
            (
                f"{RECOVERY_PLACEHOLDER_ROW_COUNT} recovery placeholders must "
                "be quarantined"
            ),
            (
                f"at least {POST_ENDPOINT_DELTA_DOCUMENTS_MIN} documents after "
                f"the {DATE_RANGE_END} endpoint are missing"
            ),
            "publication path can split artifacts across commits",
        ],
        "acceptance": {
            "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
            "materialized_rows": MATERIALIZED_ROW_COUNT,
            "count_mismatch_delta": count_mismatch["delta"],
            "count_mismatch_present": True,
            "date_range_start": DATE_RANGE_START,
            "date_range_end": DATE_RANGE_END,
            "date_range_count": DATE_RANGE_COUNT,
            "include_full_text": INCLUDE_FULL_TEXT,
            "missing_full_text": True,
            "missing_dataset_card": True,
            "legacy_layout": True,
            "pinned_revision": PINNED_REVISION,
            "repository_files": REPOSITORY_FILE_COUNT,
            "empty_text_rows": EMPTY_TEXT_ROW_COUNT,
            "recovery_placeholder_rows": RECOVERY_PLACEHOLDER_ROW_COUNT,
            "all_expected_outputs_accounted": True,
        },
        "network_required": False,
        "mode": "fixture",
        "source_of_truth": (
            "Live Hugging Face inventory of justicedao/ipfs_federal_register "
            "at the pinned revision, sealed into this offline fixture for "
            "network-free checks"
        ),
        "unsuitable_as_source_of_truth": True,
        "evidence_role": (
            "Existing remote artifacts are evidence inputs only. They may seed "
            "differential audits and the post-2026-03-02 delta, but no prior "
            "row or advertised count is admitted without the new official "
            "inventory, full-text disposition, and completeness gates."
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


def acceptance_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project the acceptance fields used by LCR-048 gates."""
    acceptance = report.get("acceptance")
    if isinstance(acceptance, Mapping) and acceptance:
        return {
            "advertised_documents": _require_int(
                acceptance.get("advertised_documents"),
                "acceptance.advertised_documents",
            ),
            "materialized_rows": _require_int(
                acceptance.get("materialized_rows"),
                "acceptance.materialized_rows",
            ),
            "count_mismatch_delta": _require_int(
                acceptance.get("count_mismatch_delta"),
                "acceptance.count_mismatch_delta",
            ),
            "count_mismatch_present": _require_bool(
                acceptance.get("count_mismatch_present"),
                "acceptance.count_mismatch_present",
            ),
            "date_range_start": _require_str(
                acceptance.get("date_range_start"),
                "acceptance.date_range_start",
            ),
            "date_range_end": _require_str(
                acceptance.get("date_range_end"),
                "acceptance.date_range_end",
            ),
            "date_range_count": _require_int(
                acceptance.get("date_range_count"),
                "acceptance.date_range_count",
            ),
            "include_full_text": _require_bool(
                acceptance.get("include_full_text"),
                "acceptance.include_full_text",
            ),
            "missing_full_text": _require_bool(
                acceptance.get("missing_full_text"),
                "acceptance.missing_full_text",
            ),
            "missing_dataset_card": _require_bool(
                acceptance.get("missing_dataset_card"),
                "acceptance.missing_dataset_card",
            ),
            "legacy_layout": _require_bool(
                acceptance.get("legacy_layout"),
                "acceptance.legacy_layout",
            ),
            "pinned_revision": _require_str(
                acceptance.get("pinned_revision"),
                "acceptance.pinned_revision",
            ),
            "repository_files": _require_int(
                acceptance.get("repository_files"),
                "acceptance.repository_files",
            ),
            "empty_text_rows": _require_int(
                acceptance.get("empty_text_rows"),
                "acceptance.empty_text_rows",
            ),
            "recovery_placeholder_rows": _require_int(
                acceptance.get("recovery_placeholder_rows"),
                "acceptance.recovery_placeholder_rows",
            ),
        }

    counts = _require_mapping(report.get("counts"), "counts")
    dataset = _require_mapping(report.get("dataset"), "dataset")
    full_text = _require_mapping(report.get("full_text"), "full_text")
    card = _require_mapping(report.get("dataset_card"), "dataset_card")
    layout = _require_mapping(report.get("legacy_layout"), "legacy_layout")
    date_range = _require_mapping(report.get("date_range"), "date_range")
    mismatch = _require_mapping(report.get("count_mismatch"), "count_mismatch")
    return {
        "advertised_documents": _require_int(
            counts.get("advertised_documents"), "counts.advertised_documents"
        ),
        "materialized_rows": _require_int(
            counts.get("materialized_rows"), "counts.materialized_rows"
        ),
        "count_mismatch_delta": _require_int(
            mismatch.get("delta"), "count_mismatch.delta"
        ),
        "count_mismatch_present": _require_bool(
            mismatch.get("mismatch_present"), "count_mismatch.mismatch_present"
        ),
        "date_range_start": _require_str(date_range.get("start"), "date_range.start"),
        "date_range_end": _require_str(date_range.get("end"), "date_range.end"),
        "date_range_count": _require_int(
            date_range.get("date_range_count"), "date_range.date_range_count"
        ),
        "include_full_text": _require_bool(
            full_text.get("include_full_text"), "full_text.include_full_text"
        ),
        "missing_full_text": _require_bool(
            full_text.get("missing_full_text_contract"),
            "full_text.missing_full_text_contract",
        ),
        "missing_dataset_card": _require_bool(
            card.get("missing"), "dataset_card.missing"
        ),
        "legacy_layout": _require_bool(layout.get("present"), "legacy_layout.present"),
        "pinned_revision": _require_str(dataset.get("revision"), "dataset.revision"),
        "repository_files": _require_int(
            counts.get("repository_files"), "counts.repository_files"
        ),
        "empty_text_rows": _require_int(
            counts.get("empty_text_rows"), "counts.empty_text_rows"
        ),
        "recovery_placeholder_rows": _require_int(
            counts.get("recovery_placeholder_rows"),
            "counts.recovery_placeholder_rows",
        ),
    }


def expected_acceptance() -> dict[str, Any]:
    """Return the sealed acceptance tuple for the pinned baseline."""
    return {
        "advertised_documents": ADVERTISED_DOCUMENT_COUNT,
        "materialized_rows": MATERIALIZED_ROW_COUNT,
        "count_mismatch_delta": RECOVERY_PLACEHOLDER_ROW_COUNT,
        "count_mismatch_present": True,
        "date_range_start": DATE_RANGE_START,
        "date_range_end": DATE_RANGE_END,
        "date_range_count": DATE_RANGE_COUNT,
        "include_full_text": INCLUDE_FULL_TEXT,
        "missing_full_text": True,
        "missing_dataset_card": True,
        "legacy_layout": True,
        "pinned_revision": PINNED_REVISION,
        "repository_files": REPOSITORY_FILE_COUNT,
        "empty_text_rows": EMPTY_TEXT_ROW_COUNT,
        "recovery_placeholder_rows": RECOVERY_PLACEHOLDER_ROW_COUNT,
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

    if (
        actual["materialized_rows"] - actual["advertised_documents"]
        != actual["count_mismatch_delta"]
    ):
        mismatches.append(
            "invariant materialized_rows - advertised_documents == "
            "count_mismatch_delta failed: "
            f"{actual['materialized_rows']} - {actual['advertised_documents']} "
            f"!= {actual['count_mismatch_delta']}"
        )

    if actual["count_mismatch_delta"] != actual["recovery_placeholder_rows"]:
        mismatches.append(
            "invariant count_mismatch_delta == recovery_placeholder_rows failed: "
            f"{actual['count_mismatch_delta']} != "
            f"{actual['recovery_placeholder_rows']}"
        )

    if actual["count_mismatch_present"] is not True:
        mismatches.append("count_mismatch_present must be true")

    if actual["include_full_text"] is not False:
        mismatches.append("include_full_text must be false")

    if actual["missing_full_text"] is not True:
        mismatches.append("missing_full_text must be true")

    if actual["missing_dataset_card"] is not True:
        mismatches.append("missing_dataset_card must be true")

    if actual["legacy_layout"] is not True:
        mismatches.append("legacy_layout must be true")

    if actual["date_range_start"] != DATE_RANGE_START:
        mismatches.append(
            f"date_range_start must be {DATE_RANGE_START!r}"
        )

    if actual["date_range_end"] != DATE_RANGE_END:
        mismatches.append(f"date_range_end must be {DATE_RANGE_END!r}")

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
        if dataset.get("has_dataset_card") is not False:
            mismatches.append("dataset.has_dataset_card must be false")
    else:
        mismatches.append("dataset must be a JSON object")

    for section in (
        "counts",
        "metadata",
        "date_range",
        "count_mismatch",
        "full_text",
        "dataset_card",
        "legacy_layout",
        "source_urls",
        "recovery",
        "post_endpoint_delta",
        "viewer",
        "code_hazards",
        "identity_anomalies",
        "blocking_issues",
        "acceptance",
    ):
        if section not in report:
            mismatches.append(f"missing required section: {section}")

    mismatch = report.get("count_mismatch")
    if isinstance(mismatch, Mapping):
        if mismatch.get("advertised_documents") != ADVERTISED_DOCUMENT_COUNT:
            mismatches.append(
                "count_mismatch.advertised_documents: expected "
                f"{ADVERTISED_DOCUMENT_COUNT}, "
                f"got {mismatch.get('advertised_documents')!r}"
            )
        if mismatch.get("materialized_rows") != MATERIALIZED_ROW_COUNT:
            mismatches.append(
                "count_mismatch.materialized_rows: expected "
                f"{MATERIALIZED_ROW_COUNT}, "
                f"got {mismatch.get('materialized_rows')!r}"
            )
        if mismatch.get("mismatch_present") is not True:
            mismatches.append("count_mismatch.mismatch_present must be true")
    else:
        mismatches.append("count_mismatch must be a JSON object")

    full_text = report.get("full_text")
    if isinstance(full_text, Mapping):
        if full_text.get("include_full_text") is not False:
            mismatches.append("full_text.include_full_text must be false")
        if full_text.get("missing_full_text_contract") is not True:
            mismatches.append(
                "full_text.missing_full_text_contract must be true"
            )
        if full_text.get("empty_text_rows") != EMPTY_TEXT_ROW_COUNT:
            mismatches.append(
                "full_text.empty_text_rows: expected "
                f"{EMPTY_TEXT_ROW_COUNT}, got {full_text.get('empty_text_rows')!r}"
            )
    else:
        mismatches.append("full_text must be a JSON object")

    card = report.get("dataset_card")
    if isinstance(card, Mapping):
        if card.get("present") is not False:
            mismatches.append("dataset_card.present must be false")
        if card.get("missing") is not True:
            mismatches.append("dataset_card.missing must be true")
    else:
        mismatches.append("dataset_card must be a JSON object")

    layout = report.get("legacy_layout")
    if isinstance(layout, Mapping):
        if layout.get("present") is not True:
            mismatches.append("legacy_layout.present must be true")
        if layout.get("descriptor_complete_v2") is not False:
            mismatches.append(
                "legacy_layout.descriptor_complete_v2 must be false"
            )
        artifacts = layout.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            mismatches.append("legacy_layout.artifacts must be a non-empty array")
        else:
            for expected_artifact in LEGACY_LAYOUT_ARTIFACTS:
                if expected_artifact not in artifacts:
                    mismatches.append(
                        f"legacy_layout.artifacts missing {expected_artifact!r}"
                    )
    else:
        mismatches.append("legacy_layout must be a JSON object")

    date_range = report.get("date_range")
    if isinstance(date_range, Mapping):
        if date_range.get("start") != DATE_RANGE_START:
            mismatches.append(
                f"date_range.start: expected {DATE_RANGE_START!r}, "
                f"got {date_range.get('start')!r}"
            )
        if date_range.get("end") != DATE_RANGE_END:
            mismatches.append(
                f"date_range.end: expected {DATE_RANGE_END!r}, "
                f"got {date_range.get('end')!r}"
            )
        if date_range.get("date_range_count") != DATE_RANGE_COUNT:
            mismatches.append(
                "date_range.date_range_count: expected "
                f"{DATE_RANGE_COUNT}, got {date_range.get('date_range_count')!r}"
            )
    else:
        mismatches.append("date_range must be a JSON object")

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
            f"advertised={acceptance['advertised_documents']},"
            f"materialized={acceptance['materialized_rows']},"
            f"delta={acceptance['count_mismatch_delta']},"
            f"empty_text={acceptance['empty_text_rows']},"
            f"date_ranges={acceptance['date_range_count']},"
            f"files={acceptance['repository_files']}"
        ),
        (
            f"date_range={acceptance['date_range_start']}.."
            f"{acceptance['date_range_end']}"
        ),
        f"include_full_text={acceptance['include_full_text']}",
        f"missing_full_text={acceptance['missing_full_text']}",
        f"missing_dataset_card={acceptance['missing_dataset_card']}",
        f"legacy_layout={acceptance['legacy_layout']}",
        f"count_mismatch_present={acceptance['count_mismatch_present']}",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze and check the pinned justicedao/ipfs_federal_register "
            "baseline audit (LCR-048). Default fixture mode never contacts "
            "the network."
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
        # Live Hub audit is intentionally out of scope for LCR-048 CI.
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
