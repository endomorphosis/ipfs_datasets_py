"""Prepare and launch the semantic round-trip dynamic bundle scheduler.

The generic objective daemon creates a bundle index while deriving new tasks
from an objective heap.  The semantic round-trip board is deliberately
hand-authored, so this module provides the narrower missing projection:

``existing taskboard -> queryable bundle index -> DynamicBundleScheduler``.

It does not implement another scheduler.  Launches are delegated to
``ipfs_accelerate_py.agent_supervisor.bundle_supervisor`` so leases, conflict
checks, worktree isolation, provider admission, and recovery retain their
normal authority.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from ipfs_accelerate_py.agent_supervisor.artifact_store import (
    write_bundle_index_artifact,
)
from ipfs_accelerate_py.agent_supervisor.objective_graph import (
    materialize_task_planning_graph,
)
from ipfs_accelerate_py.agent_supervisor.resource_scheduler import (
    LEGACY_RESOURCE_CLASSES,
    PROOF_RESOURCE_CLASSES,
    ProofResourceClass,
    normalize_adaptive_stage,
    normalize_resource_class,
)
from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    PortalTask,
    parse_task_file,
    split_csv,
)


CONFIG_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.scheduler_config@1"
)
BUNDLE_INDEX_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.taskboard_bundle_index@1"
)
PROVIDER_CAPACITY_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.provider_capacity@1"
)
SRT014_DOWNSTREAM_GATE_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.srt014_downstream_gate@1"
)
SRT014_REPORT_RELATIVE_PATH = Path(
    "docs/performance_snapshots/"
    "2026-07-26_semantic_roundtrip_composition_pilot.json"
)
REPLACEMENT_REPORT_RELATIVE_PATH = Path(
    "docs/performance_snapshots/"
    "2026-07-27_semantic_roundtrip_composition_replacement.json"
)
NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "no_eligible_remediation_manifest.json"
)
CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "replacement_selection_gate.json"
)
SRT014_GATED_TASK_ID = "SRT-015"
SRT014_REMEDIATION_ROOT_TASK_ID = "SRT-021"
SRT014_REPLACEMENT_GATE_TASK_ID = "SRT-027"
REPLACEMENT_SELECTION_GATE_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip."
    "replacement_selection_gate@1"
)
CANONICAL_DESIGN_GATE_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip.canonical_design_gate@1"
)
CANONICAL_DESIGN_GATE_ARTIFACT_VALIDATION_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip."
    "canonical_design_gate_artifact_validation@1"
)
NO_ELIGIBLE_REMEDIATION_MANIFEST_INTERFACE = (
    "SRT014NoEligibleRemediationManifest@1"
)
NO_ELIGIBLE_REMEDIATION_MANIFEST_SCHEMA = (
    "ipfs-datasets.semantic-roundtrip-no-eligible-remediation.v1"
)
NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA = (
    "ipfs_datasets_py.benchmarks.semantic_roundtrip."
    "no_eligible_remediation_manifest_gate@1"
)
SRT014_SELECTION_GATE_IDS = (
    "source_copy_exclusion",
    "polarity_preservation",
    "full_coverage",
)
DEFAULT_TASK_PREFIX = "## SRT-"
DEFAULT_RUNTIME_ROOT = Path("/var/tmp/hssl-srt-dynamic-supervisor")
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "semantic_roundtrip_scheduler.json"
)
SUPPORTED_RESOURCE_CLASSES = frozenset(
    {*LEGACY_RESOURCE_CLASSES, *PROOF_RESOURCE_CLASSES}
)
TERMINAL_STATUSES = frozenset(
    {"complete", "completed", "done", "merged", "passed", "success", "succeeded"}
)
BLOCKED_STATUSES = frozenset({"blocked", "on_hold"})


class SchedulerPreparationError(ValueError):
    """Raised when scheduler inputs cannot fail closed."""


def _gate_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    receipt = dict(payload)
    receipt["gate_cid"] = cid_for_dag_json(receipt)
    receipt["gate_cid_codec"] = "dag-json"
    receipt["gate_cid_scope"] = "payload_without_gate_cid_fields"
    return receipt


def _gate_receipt_has_valid_identity(
    receipt: Mapping[str, Any],
    *,
    schema: str,
) -> bool:
    """Return whether a gate receipt is exact, typed, and CID-bound."""

    try:
        if (
            receipt.get("schema") != schema
            or receipt.get("gate_cid_codec") != "dag-json"
            or receipt.get("gate_cid_scope")
            != "payload_without_gate_cid_fields"
        ):
            return False
        gate_cid = validate_cid(
            receipt.get("gate_cid"),
            codecs=("dag-json",),
        )
        payload = {
            key: value
            for key, value in receipt.items()
            if key
            not in {"gate_cid", "gate_cid_codec", "gate_cid_scope"}
        }
        return cid_for_dag_json(payload) == gate_cid
    except (TypeError, ValueError):
        return False


def _srt014_remediation_summary(
    report: Mapping[str, Any],
    *,
    arm_order: Sequence[str],
) -> dict[str, Any]:
    """Summarize frozen failure evidence without changing its decision."""

    execution = report.get("execution")
    if not isinstance(execution, Mapping):
        raise SchedulerPreparationError("SRT-014 execution must be an object")
    records: list[Mapping[str, Any]] = []
    for partition in ("deterministic", "model_backed"):
        group = execution.get(partition)
        if not isinstance(group, Mapping):
            raise SchedulerPreparationError(
                f"SRT-014 execution.{partition} must be an object"
            )
        values = group.get("records")
        if not isinstance(values, list) or any(
            not isinstance(record, Mapping) for record in values
        ):
            raise SchedulerPreparationError(
                f"SRT-014 execution.{partition}.records must be an object array"
            )
        records.extend(values)

    arm_set = set(arm_order)
    by_arm: dict[str, list[Mapping[str, Any]]] = {
        arm_id: [] for arm_id in arm_order
    }
    for record in records:
        arm_id = record.get("arm_id", record.get("cell_id"))
        if arm_id not in arm_set:
            raise SchedulerPreparationError(
                "SRT-014 remediation record identifies an unknown arm"
            )
        by_arm[str(arm_id)].append(record)

    gate_coordinate_counts = Counter(
        {gate_id: 0 for gate_id in SRT014_SELECTION_GATE_IDS}
    )
    gate_arm_ids: dict[str, list[str]] = {
        gate_id: [] for gate_id in SRT014_SELECTION_GATE_IDS
    }
    terminal_reason_counts: Counter[str] = Counter()
    terminal_stage_counts: Counter[str] = Counter()
    arm_summaries: dict[str, dict[str, Any]] = {}
    for arm_id in arm_order:
        arm_records = by_arm[arm_id]
        if not arm_records:
            raise SchedulerPreparationError(
                f"SRT-014 remediation evidence has no records for {arm_id!r}"
            )
        failed_counts = Counter(
            {gate_id: 0 for gate_id in SRT014_SELECTION_GATE_IDS}
        )
        affected_cases: dict[str, set[str]] = {
            gate_id: set() for gate_id in SRT014_SELECTION_GATE_IDS
        }
        sample_coordinates: dict[str, list[str]] = {
            gate_id: [] for gate_id in SRT014_SELECTION_GATE_IDS
        }
        arm_terminal_reasons: Counter[str] = Counter()
        arm_terminal_stages: Counter[str] = Counter()
        terminal_failure_count = 0
        for record_index, record in enumerate(arm_records):
            gates = record.get("gates")
            if not isinstance(gates, Mapping):
                raise SchedulerPreparationError(
                    f"SRT-014 remediation gates are missing for {arm_id!r}"
                )
            case_id = str(record.get("case_id") or "")
            coordinate_key = str(
                record.get("coordinate_key")
                or (
                    f"{case_id}:{record.get('repeat_index')}:{arm_id}:"
                    f"{record_index}"
                )
            )
            for gate_id in SRT014_SELECTION_GATE_IDS:
                if gates.get(gate_id) is False:
                    failed_counts[gate_id] += 1
                    gate_coordinate_counts[gate_id] += 1
                    if case_id:
                        affected_cases[gate_id].add(case_id)
                    if len(sample_coordinates[gate_id]) < 5:
                        sample_coordinates[gate_id].append(coordinate_key)
                elif gates.get(gate_id) is not True:
                    raise SchedulerPreparationError(
                        f"SRT-014 remediation gate {gate_id!r} is not boolean"
                    )
            if record.get("status") != "failed":
                continue
            terminal_failure_count += 1
            failure = record.get("failure")
            if isinstance(failure, Mapping):
                reason = str(
                    failure.get("code")
                    or failure.get("reason_code")
                    or failure.get("reason")
                    or failure.get("type")
                    or "unspecified_terminal_failure"
                )
                stage = str(failure.get("stage") or "unspecified_stage")
            else:
                reason = "terminal_failure_without_reason"
                stage = "unspecified_stage"
            arm_terminal_reasons[reason] += 1
            arm_terminal_stages[stage] += 1
            terminal_reason_counts[reason] += 1
            terminal_stage_counts[stage] += 1

        failed_gate_ids = [
            gate_id
            for gate_id in SRT014_SELECTION_GATE_IDS
            if failed_counts[gate_id] > 0
        ]
        if not failed_gate_ids:
            raise SchedulerPreparationError(
                f"no-eligible outcome has no failed gate for {arm_id!r}"
            )
        for gate_id in failed_gate_ids:
            gate_arm_ids[gate_id].append(arm_id)
        arm_summaries[arm_id] = {
            "coordinate_count": len(arm_records),
            "failed_gate_ids": failed_gate_ids,
            "failed_coordinate_count_by_gate": {
                gate_id: failed_counts[gate_id]
                for gate_id in SRT014_SELECTION_GATE_IDS
            },
            "affected_case_ids_by_gate": {
                gate_id: sorted(affected_cases[gate_id])
                for gate_id in SRT014_SELECTION_GATE_IDS
            },
            "sample_coordinate_keys_by_gate": sample_coordinates,
            "terminal_failure_count": terminal_failure_count,
            "terminal_failure_reason_counts": dict(
                sorted(arm_terminal_reasons.items())
            ),
            "terminal_failure_stage_counts": dict(
                sorted(arm_terminal_stages.items())
            ),
        }

    gate_evidence = {
        gate_id: {
            "affected_arm_count": len(gate_arm_ids[gate_id]),
            "affected_arm_ids": gate_arm_ids[gate_id],
            "failed_coordinate_count": gate_coordinate_counts[gate_id],
        }
        for gate_id in SRT014_SELECTION_GATE_IDS
    }
    systemic_gate_ids = [
        gate_id
        for gate_id in SRT014_SELECTION_GATE_IDS
        if len(gate_arm_ids[gate_id]) == len(arm_order)
    ]
    task_inputs: list[dict[str, Any]] = [
        {
            "task_kind": "diagnose_and_repair_selection_gate",
            "gate_id": gate_id,
            **gate_evidence[gate_id],
        }
        for gate_id in SRT014_SELECTION_GATE_IDS
        if gate_coordinate_counts[gate_id] > 0
    ]
    if terminal_reason_counts:
        task_inputs.append(
            {
                "task_kind": "diagnose_and_repair_terminal_failures",
                "failure_reason_counts": dict(
                    sorted(terminal_reason_counts.items())
                ),
                "failure_stage_counts": dict(
                    sorted(terminal_stage_counts.items())
                ),
            }
        )
    task_inputs.append(
        {
            "task_kind": "execute_replacement_full_matrix",
            "protocol_action": "preserve_frozen_protocol",
            "artifact_action": "new_immutable_run_namespace_and_report",
            "requires_all_prior_remediation_receipts": True,
        }
    )
    return {
        "source_report_cid": report.get("report_cid"),
        "classification": "all_preregistered_arms_failed_selection_eligibility",
        "arm_count": len(arm_order),
        "eligible_arm_count": 0,
        "gate_evidence": gate_evidence,
        "systemic_gate_ids": systemic_gate_ids,
        "component_local_gate_ids": [
            gate_id
            for gate_id in SRT014_SELECTION_GATE_IDS
            if gate_coordinate_counts[gate_id] > 0
            and gate_id not in systemic_gate_ids
        ],
        "terminal_failure_reason_counts": dict(
            sorted(terminal_reason_counts.items())
        ),
        "terminal_failure_stage_counts": dict(
            sorted(terminal_stage_counts.items())
        ),
        "arms": arm_summaries,
        "recommended_task_inputs": task_inputs,
        "srt015_must_remain_fenced": True,
        "frozen_protocol_must_not_change": True,
    }


def evaluate_srt014_downstream_gate(
    repo_root: Path,
    *,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Return the fail-closed SRT-014 selectability receipt.

    A completed measurement is not necessarily an implementation input.  The
    report must independently validate to either one unique winner or an
    explicit exact co-winner set bounded by the 30 preregistered arms.  A
    valid ``no_eligible_composition`` result remains useful benchmark
    evidence, but it cannot authorize SRT-015.
    """

    repo_root = repo_root.resolve()
    path = (
        report_path.resolve()
        if report_path is not None
        else repo_root / SRT014_REPORT_RELATIVE_PATH
    )
    try:
        relative_path = path.relative_to(repo_root).as_posix()
    except ValueError:
        return _gate_receipt(
            {
                "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
                "status": "invalid",
                "launch_authorized": False,
                "report_path": str(path),
                "report_cid": None,
                "report_raw_cid": None,
                "selection_outcome": None,
                "selection_basis": None,
                "selectable_arm_ids": [],
                "implementation_representative_arm_id": None,
                "tie_bound": 30,
                "reason_codes": ["srt014_report_outside_repository"],
            }
        )
    if not path.is_file():
        return _gate_receipt(
            {
                "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
                "status": "pending",
                "launch_authorized": False,
                "report_path": relative_path,
                "report_cid": None,
                "report_raw_cid": None,
                "selection_outcome": None,
                "selection_basis": None,
                "selectable_arm_ids": [],
                "implementation_representative_arm_id": None,
                "tie_bound": 30,
                "reason_codes": ["srt014_report_missing"],
            }
        )

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _gate_receipt(
            {
                "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
                "status": "invalid",
                "launch_authorized": False,
                "report_path": relative_path,
                "report_cid": None,
                "report_raw_cid": None,
                "selection_outcome": None,
                "selection_basis": None,
                "selectable_arm_ids": [],
                "implementation_representative_arm_id": None,
                "tie_bound": 30,
                "reason_codes": [
                    "srt014_report_read_failed",
                    f"{type(exc).__name__}:{exc}",
                ],
            }
        )
    report: object = None
    try:
        report = json.loads(raw)
        if not isinstance(report, Mapping):
            raise SchedulerPreparationError("SRT-014 report must be an object")
        from benchmarks.bench_semantic_roundtrip_compositions import (
            validate_composition_report,
        )

        validated = validate_composition_report(
            report,
            fixture_path=(
                repo_root / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
            ),
        )
        preregistration = report.get("preregistration")
        if not isinstance(preregistration, Mapping):
            raise SchedulerPreparationError(
                "SRT-014 preregistration must be an object"
            )
        deterministic_ids = preregistration.get("deterministic_cell_ids")
        model_ids = preregistration.get("model_backed_cell_ids")
        if (
            not isinstance(deterministic_ids, list)
            or not isinstance(model_ids, list)
        ):
            raise SchedulerPreparationError(
                "SRT-014 preregistered arm IDs must be arrays"
            )
        arm_order = [*deterministic_ids, *model_ids]
        if (
            len(arm_order) != 30
            or len(set(arm_order)) != 30
            or any(not isinstance(arm_id, str) for arm_id in arm_order)
        ):
            raise SchedulerPreparationError(
                "SRT-014 tie bound requires exactly 30 unique arm IDs"
            )
        outcome = str(validated["selection_outcome"])
        if outcome == "selected":
            selectable = [str(validated["winner_arm_id"])]
            representative = selectable[0]
            selection_basis = "srt014_unique_winner"
            status = "authorized"
            authorized = True
            reasons = ["srt014_unique_full_coverage_winner"]
            remediation = None
        elif outcome == "exact_tie" and validated["bounded_tie"] is True:
            selectable = [
                str(arm_id) for arm_id in validated["co_winner_arm_ids"]
            ]
            representative = next(
                arm_id for arm_id in arm_order if arm_id in set(selectable)
            )
            selection_basis = "srt015_bounded_tie_policy"
            status = "authorized"
            authorized = True
            reasons = [
                "srt014_exact_tie_bounded_by_preregistered_30_arm_universe",
                "implementation_representative_uses_frozen_preregistered_arm_order",
            ]
            remediation = None
        elif outcome == "no_eligible_composition":
            selectable = []
            representative = None
            selection_basis = None
            status = "remediation_required"
            authorized = False
            reasons = [
                "srt014_no_eligible_composition",
                "all_preregistered_arms_failed_selection_eligibility",
            ]
            remediation = _srt014_remediation_summary(
                report,
                arm_order=arm_order,
            )
        else:
            selectable = []
            representative = None
            selection_basis = None
            status = "invalid"
            authorized = False
            reasons = ["srt014_unbounded_or_unsupported_selection"]
            remediation = None
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        return _gate_receipt(
            {
                "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
                "status": "invalid",
                "launch_authorized": False,
                "report_path": relative_path,
                "report_cid": (
                    report.get("report_cid")
                    if isinstance(report, Mapping)
                    else None
                ),
                "report_raw_cid": cid_for_bytes(raw),
                "selection_outcome": None,
                "selection_basis": None,
                "selectable_arm_ids": [],
                "implementation_representative_arm_id": None,
                "tie_bound": 30,
                "reason_codes": [
                    "srt014_report_validation_failed",
                    f"{type(exc).__name__}:{exc}",
                ],
            }
        )

    return _gate_receipt(
        {
            "schema": SRT014_DOWNSTREAM_GATE_SCHEMA,
            "status": status,
            "launch_authorized": authorized,
            "report_path": relative_path,
            "report_cid": validated["report_cid"],
            "report_raw_cid": cid_for_bytes(raw),
            "selection_outcome": outcome,
            "selection_basis": selection_basis,
            "selectable_arm_ids": selectable,
            "implementation_representative_arm_id": representative,
            "tie_bound": len(arm_order),
            "reason_codes": reasons,
            "remediation": remediation,
        }
    )


def _evaluate_no_eligible_remediation_manifest_gate(
    repo_root: Path,
    *,
    srt014_gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate SRT-021 using a trusted freshly recomputed SRT-014 gate."""

    repo_root = repo_root.resolve()
    original = dict(srt014_gate)
    path = repo_root / NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH
    base = {
        "schema": NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA,
        "report_path": str(SRT014_REPORT_RELATIVE_PATH),
        "srt014_gate_cid": original.get("gate_cid"),
        "srt014_report_cid": original.get("report_cid"),
        "srt014_report_raw_cid": original.get("report_raw_cid"),
        "manifest_path": str(
            NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH
        ),
        "manifest_cid": None,
        "manifest_raw_cid": None,
        "reason_codes": [],
    }
    if original.get("status") != "remediation_required":
        return _gate_receipt(
            {
                **base,
                "status": "not_admissible",
                "valid": False,
                "reason_codes": [
                    "remediation_manifest_requires_no_eligible_srt014"
                ],
            }
        )
    if not path.is_file():
        return _gate_receipt(
            {
                **base,
                "status": "pending",
                "valid": False,
                "reason_codes": ["no_eligible_remediation_manifest_missing"],
            }
        )
    raw: bytes | None = None
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise SchedulerPreparationError(
                "no-eligible remediation manifest must be an object"
            )
        expected_keys = {
            "interface",
            "schema_version",
            "status",
            "source",
            "remediation",
            "protocol_immutable",
            "replacement_run_required",
            "srt015_fenced",
            "manifest_cid",
        }
        if set(value) != expected_keys:
            raise SchedulerPreparationError(
                "no-eligible remediation manifest fields changed"
            )
        if (
            value.get("interface")
            != NO_ELIGIBLE_REMEDIATION_MANIFEST_INTERFACE
            or value.get("schema_version")
            != NO_ELIGIBLE_REMEDIATION_MANIFEST_SCHEMA
        ):
            raise SchedulerPreparationError(
                "no-eligible remediation manifest identity changed"
            )
        manifest_cid = value.get("manifest_cid")
        validate_cid(manifest_cid, codecs=("dag-json",))
        cid_payload = dict(value)
        del cid_payload["manifest_cid"]
        if cid_for_dag_json(cid_payload) != manifest_cid:
            raise SchedulerPreparationError(
                "no-eligible remediation manifest CID does not match payload"
            )
        if value.get("status") != "frozen_no_eligible":
            raise SchedulerPreparationError(
                "no-eligible remediation manifest status must be frozen"
            )
        source = value.get("source")
        if not isinstance(source, Mapping):
            raise SchedulerPreparationError(
                "no-eligible remediation manifest source must be an object"
            )
        expected_source = {
            "srt014_report_path": str(SRT014_REPORT_RELATIVE_PATH),
            "srt014_report_cid": original.get("report_cid"),
            "srt014_report_raw_cid": original.get("report_raw_cid"),
            "srt014_gate_cid": original.get("gate_cid"),
        }
        if dict(source) != expected_source:
            raise SchedulerPreparationError(
                "no-eligible remediation manifest source lineage changed"
            )
        validate_cid(
            source.get("srt014_report_cid"),
            codecs=("dag-json",),
        )
        validate_cid(
            source.get("srt014_report_raw_cid"),
            codecs=("raw",),
        )
        validate_cid(
            source.get("srt014_gate_cid"),
            codecs=("dag-json",),
        )
        if not isinstance(value.get("remediation"), Mapping):
            raise SchedulerPreparationError(
                "no-eligible remediation manifest remediation must be an object"
            )
        if value.get("remediation") != original.get("remediation"):
            raise SchedulerPreparationError(
                "no-eligible remediation manifest differs from gate evidence"
            )
        for field in (
            "protocol_immutable",
            "replacement_run_required",
            "srt015_fenced",
        ):
            if value.get(field) is not True:
                raise SchedulerPreparationError(
                    f"no-eligible remediation manifest {field} must be true"
                )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return _gate_receipt(
            {
                **base,
                "status": "invalid",
                "valid": False,
                "manifest_raw_cid": (
                    cid_for_bytes(raw) if raw is not None else None
                ),
                "reason_codes": [
                    "no_eligible_remediation_manifest_invalid",
                    f"{type(exc).__name__}:{exc}",
                ],
            }
        )
    return _gate_receipt(
        {
            **base,
            "status": "valid",
            "valid": True,
            "manifest_cid": manifest_cid,
            "manifest_raw_cid": cid_for_bytes(raw),
            "reason_codes": ["no_eligible_remediation_manifest_valid"],
        }
    )


def evaluate_no_eligible_remediation_manifest_gate(
    repo_root: Path,
    *,
    srt014_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind an optional cached original gate to repository evidence."""

    repo_root = repo_root.resolve()
    original = evaluate_srt014_downstream_gate(repo_root)
    if not _supplied_receipt_matches(srt014_gate, original):
        return _gate_receipt(
            {
                "schema": (
                    NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA
                ),
                "status": "invalid",
                "valid": False,
                "report_path": str(SRT014_REPORT_RELATIVE_PATH),
                "srt014_gate_cid": original.get("gate_cid"),
                "srt014_report_cid": original.get("report_cid"),
                "srt014_report_raw_cid": original.get("report_raw_cid"),
                "manifest_path": str(
                    NO_ELIGIBLE_REMEDIATION_MANIFEST_RELATIVE_PATH
                ),
                "manifest_cid": None,
                "manifest_raw_cid": None,
                "reason_codes": [
                    (
                        "supplied_srt014_receipt_"
                        "does_not_match_repo_evidence"
                    )
                ],
            }
        )
    return _evaluate_no_eligible_remediation_manifest_gate(
        repo_root,
        srt014_gate=original,
    )


def evaluate_replacement_selection_gate(
    repo_root: Path,
) -> dict[str, Any]:
    """Validate the immutable replacement report under the same protocol."""

    original_shape = evaluate_srt014_downstream_gate(
        repo_root,
        report_path=repo_root.resolve() / REPLACEMENT_REPORT_RELATIVE_PATH,
    )
    payload = {
        key: value
        for key, value in original_shape.items()
        if key not in {"gate_cid", "gate_cid_codec", "gate_cid_scope"}
    }
    payload["schema"] = REPLACEMENT_SELECTION_GATE_SCHEMA
    payload["report_role"] = "replacement_full_matrix"
    payload["reason_codes"] = [
        str(reason).replace("srt014_", "replacement_", 1)
        for reason in original_shape["reason_codes"]
    ]
    status = str(original_shape["status"])
    if status == "authorized":
        payload["selection_basis"] = (
            "replacement_unique_winner"
            if original_shape["selection_outcome"] == "selected"
            else "replacement_bounded_tie_policy"
        )
    elif status == "remediation_required":
        payload["status"] = "replacement_remediation_required"
    return _gate_receipt(payload)


def _compose_canonical_design_gate(
    *,
    srt014_gate: Mapping[str, Any],
    remediation_manifest_gate: Mapping[str, Any],
    replacement_gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Compose receipts already recomputed from one repository snapshot."""

    original = dict(srt014_gate)
    manifest = dict(remediation_manifest_gate)
    replacement = dict(replacement_gate)
    original_status = str(original.get("status") or "invalid")
    replacement_status = str(replacement.get("status") or "invalid")
    original_identity_valid = _gate_receipt_has_valid_identity(
        original,
        schema=SRT014_DOWNSTREAM_GATE_SCHEMA,
    )
    manifest_identity_valid = _gate_receipt_has_valid_identity(
        manifest,
        schema=NO_ELIGIBLE_REMEDIATION_MANIFEST_GATE_SCHEMA,
    )
    replacement_identity_valid = _gate_receipt_has_valid_identity(
        replacement,
        schema=REPLACEMENT_SELECTION_GATE_SCHEMA,
    )
    original_admissible = (
        original_identity_valid
        and original_status == "remediation_required"
    )
    if not original_admissible:
        status = (
            "original_evidence_pending"
            if original_identity_valid and original_status == "pending"
            else "original_evidence_invalid_or_not_no_eligible"
        )
        authorized = False
        reasons = [
            "canonical_design_requires_valid_original_srt014_evidence",
            *(
                str(reason)
                for reason in original.get("reason_codes") or ()
            ),
        ]
    elif not (
        manifest_identity_valid
        and manifest.get("status") == "valid"
        and manifest.get("valid") is True
    ):
        status = (
            "remediation_manifest_pending"
            if (
                manifest_identity_valid
                and manifest.get("status") == "pending"
            )
            else "remediation_manifest_invalid"
        )
        authorized = False
        reasons = [
            "canonical_design_requires_valid_remediation_manifest",
            *(
                str(reason)
                for reason in manifest.get("reason_codes") or ()
            ),
        ]
    elif (
        replacement_identity_valid
        and replacement_status == "authorized"
        and replacement.get("launch_authorized") is True
    ):
        status = "authorized"
        authorized = True
        reasons = [
            "replacement_report_independently_authorizes_selection",
            *(
                str(reason)
                for reason in replacement.get("reason_codes") or ()
            ),
        ]
    elif replacement_identity_valid and replacement_status == "pending":
        status = "replacement_pending"
        authorized = False
        reasons = ["replacement_report_missing"]
    elif (
        replacement_identity_valid
        and replacement_status == "replacement_remediation_required"
    ):
        status = "replacement_remediation_required"
        authorized = False
        reasons = ["replacement_report_has_no_eligible_composition"]
    else:
        status = "replacement_invalid"
        authorized = False
        reasons = [
            "replacement_report_invalid_or_unbounded",
            *(
                str(reason)
                for reason in replacement.get("reason_codes") or ()
            ),
        ]
    return _gate_receipt(
        {
            "schema": CANONICAL_DESIGN_GATE_SCHEMA,
            "status": status,
            "launch_authorized": authorized,
            "srt014_gate_cid": original.get("gate_cid"),
            "srt014_report_cid": original.get("report_cid"),
            "srt014_selection_outcome": original.get("selection_outcome"),
            "remediation_manifest_gate_cid": manifest.get("gate_cid"),
            "remediation_manifest_cid": manifest.get("manifest_cid"),
            "remediation_manifest_raw_cid": manifest.get("manifest_raw_cid"),
            "replacement_gate_cid": replacement.get("gate_cid"),
            "replacement_report_cid": replacement.get("report_cid"),
            "replacement_selection_outcome": replacement.get(
                "selection_outcome"
            ),
            "selection_basis": (
                replacement.get("selection_basis") if authorized else None
            ),
            "selectable_arm_ids": (
                list(replacement.get("selectable_arm_ids") or ())
                if authorized
                else []
            ),
            "implementation_representative_arm_id": (
                replacement.get("implementation_representative_arm_id")
                if authorized
                else None
            ),
            "reason_codes": list(dict.fromkeys(reasons)),
            "remediation": (
                replacement.get("remediation")
                if replacement_status == "replacement_remediation_required"
                else original.get("remediation")
                if original_status == "remediation_required"
                else None
            ),
        }
    )


def _supplied_receipt_matches(
    supplied: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> bool:
    if supplied is None:
        return True
    try:
        return dict(supplied) == dict(expected)
    except (TypeError, ValueError):
        return False


def _canonical_design_receipt_mismatch_gate(
    *,
    mismatch_kind: str,
    original: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
    replacement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a CID-bound denial without preserving untrusted selections."""

    statuses = {
        "original": "original_evidence_invalid_or_not_no_eligible",
        "remediation_manifest": "remediation_manifest_invalid",
        "replacement": "replacement_invalid",
    }
    manifest = dict(manifest or {})
    replacement = dict(replacement or {})
    return _gate_receipt(
        {
            "schema": CANONICAL_DESIGN_GATE_SCHEMA,
            "status": statuses[mismatch_kind],
            "launch_authorized": False,
            "srt014_gate_cid": original.get("gate_cid"),
            "srt014_report_cid": original.get("report_cid"),
            "srt014_selection_outcome": original.get("selection_outcome"),
            "remediation_manifest_gate_cid": manifest.get("gate_cid"),
            "remediation_manifest_cid": manifest.get("manifest_cid"),
            "remediation_manifest_raw_cid": manifest.get("manifest_raw_cid"),
            "replacement_gate_cid": replacement.get("gate_cid"),
            "replacement_report_cid": replacement.get("report_cid"),
            "replacement_selection_outcome": replacement.get(
                "selection_outcome"
            ),
            "selection_basis": None,
            "selectable_arm_ids": [],
            "implementation_representative_arm_id": None,
            "reason_codes": [
                f"supplied_{mismatch_kind}_receipt_does_not_match_repo_evidence"
            ],
            "remediation": (
                original.get("remediation")
                if original.get("status") == "remediation_required"
                else None
            ),
        }
    )


def evaluate_canonical_design_gate(
    repo_root: Path,
    *,
    srt014_gate: Mapping[str, Any] | None = None,
    remediation_manifest_gate: Mapping[str, Any] | None = None,
    replacement_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently bind every optional cached receipt to repository state."""

    repo_root = repo_root.resolve()
    original = evaluate_srt014_downstream_gate(repo_root)
    if not _supplied_receipt_matches(srt014_gate, original):
        return _canonical_design_receipt_mismatch_gate(
            mismatch_kind="original",
            original=original,
        )
    manifest = _evaluate_no_eligible_remediation_manifest_gate(
        repo_root,
        srt014_gate=original,
    )
    if not _supplied_receipt_matches(
        remediation_manifest_gate,
        manifest,
    ):
        return _canonical_design_receipt_mismatch_gate(
            mismatch_kind="remediation_manifest",
            original=original,
            manifest=manifest,
        )
    replacement = evaluate_replacement_selection_gate(repo_root)
    if not _supplied_receipt_matches(replacement_gate, replacement):
        return _canonical_design_receipt_mismatch_gate(
            mismatch_kind="replacement",
            original=original,
            manifest=manifest,
            replacement=replacement,
        )
    return _compose_canonical_design_gate(
        srt014_gate=original,
        remediation_manifest_gate=manifest,
        replacement_gate=replacement,
    )


def _evaluate_canonical_design_gate_artifact(
    repo_root: Path,
    *,
    artifact_path: Path | None = None,
    canonical_gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an artifact against a trusted freshly recomputed gate."""

    repo_root = repo_root.resolve()
    path = artifact_path or CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH
    path = path if path.is_absolute() else repo_root / path
    path = path.resolve()
    relative_path = _repo_relative(repo_root, path)
    expected = dict(canonical_gate)
    base = {
        "schema": CANONICAL_DESIGN_GATE_ARTIFACT_VALIDATION_SCHEMA,
        "artifact_path": relative_path,
        "artifact_raw_cid": None,
        "canonical_design_gate_cid": expected.get("gate_cid"),
        "reason_codes": [],
    }
    if not _gate_receipt_has_valid_identity(
        expected,
        schema=CANONICAL_DESIGN_GATE_SCHEMA,
    ):
        return _gate_receipt(
            {
                **base,
                "status": "invalid",
                "valid": False,
                "reason_codes": [
                    "recomputed_canonical_design_gate_invalid"
                ],
            }
        )
    if not path.is_file():
        return _gate_receipt(
            {
                **base,
                "status": "pending",
                "valid": False,
                "reason_codes": [
                    "canonical_design_gate_artifact_missing"
                ],
            }
        )
    raw: bytes | None = None
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
        if not isinstance(value, Mapping):
            raise SchedulerPreparationError(
                "canonical design gate artifact must be an object"
            )
        if dict(value) != expected:
            raise SchedulerPreparationError(
                "canonical design gate artifact differs from recomputed gate"
            )
    except (OSError, TypeError, ValueError) as exc:
        return _gate_receipt(
            {
                **base,
                "status": "invalid",
                "valid": False,
                "artifact_raw_cid": (
                    cid_for_bytes(raw) if raw is not None else None
                ),
                "reason_codes": [
                    "canonical_design_gate_artifact_invalid",
                    f"{type(exc).__name__}:{exc}",
                ],
            }
        )
    return _gate_receipt(
        {
            **base,
            "status": "valid",
            "valid": True,
            "artifact_raw_cid": cid_for_bytes(raw),
            "reason_codes": [
                "canonical_design_gate_artifact_matches_recomputed_gate"
            ],
        }
    )


def evaluate_canonical_design_gate_artifact(
    repo_root: Path,
    *,
    artifact_path: Path | None = None,
    canonical_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind an optional cached gate to repository evidence before validation."""

    repo_root = repo_root.resolve()
    expected = evaluate_canonical_design_gate(repo_root)
    if not _supplied_receipt_matches(canonical_gate, expected):
        path = artifact_path or CANONICAL_DESIGN_GATE_ARTIFACT_RELATIVE_PATH
        path = path if path.is_absolute() else repo_root / path
        relative_path = _repo_relative(repo_root, path.resolve())
        return _gate_receipt(
            {
                "schema": (
                    CANONICAL_DESIGN_GATE_ARTIFACT_VALIDATION_SCHEMA
                ),
                "status": "invalid",
                "valid": False,
                "artifact_path": relative_path,
                "artifact_raw_cid": None,
                "canonical_design_gate_cid": expected.get("gate_cid"),
                "reason_codes": [
                    (
                        "supplied_canonical_design_gate_receipt_"
                        "does_not_match_repo_evidence"
                    )
                ],
            }
        )
    return _evaluate_canonical_design_gate_artifact(
        repo_root,
        artifact_path=artifact_path,
        canonical_gate=expected,
    )


def _dependent_task_ids(
    tasks: Sequence[Mapping[str, Any]],
    root_task_id: str,
) -> set[str]:
    task_ids = {str(task.get("task_id") or "") for task in tasks}
    if root_task_id not in task_ids:
        return set()
    dependents = {root_task_id}
    changed = True
    while changed:
        changed = False
        for task in tasks:
            task_id = str(task.get("task_id") or "")
            dependencies = set(task.get("depends_on") or ())
            if task_id not in dependents and dependencies.intersection(
                dependents
            ):
                dependents.add(task_id)
                changed = True
    return dependents


def _apply_no_eligible_remediation_gate(
    tasks: list[dict[str, Any]],
    gate: Mapping[str, Any],
) -> None:
    """Admit remediation only for a validated no-eligible SRT-014 result."""

    remediation_ids = _dependent_task_ids(
        tasks,
        SRT014_REMEDIATION_ROOT_TASK_ID,
    )
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        if task_id not in remediation_ids:
            continue
        task["srt014_remediation_gate_cid"] = gate["gate_cid"]
        task["srt014_remediation_gate_status"] = gate["status"]
        task["srt014_remediation_gate_reason_codes"] = list(
            gate["reason_codes"]
        )
        if gate.get("status") not in {"pending", "remediation_required"}:
            task["is_schedulable"] = False
            task["preflight_blocked"] = True
            task["preflight_blocked_by"] = SRT014_REMEDIATION_ROOT_TASK_ID


def _apply_canonical_design_gate(
    tasks: list[dict[str, Any]],
    gate: Mapping[str, Any],
) -> None:
    """Fence SRT-015 and its descendants when selection is not admissible."""

    blocked = _dependent_task_ids(tasks, SRT014_GATED_TASK_ID)
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        if task_id not in blocked:
            continue
        task["canonical_design_gate_cid"] = gate["gate_cid"]
        task["canonical_design_gate_status"] = gate["status"]
        task["canonical_design_gate_reason_codes"] = list(
            gate["reason_codes"]
        )
        if gate.get("status") in {
            "original_evidence_invalid_or_not_no_eligible",
            "remediation_manifest_invalid",
            "replacement_invalid",
            "replacement_remediation_required",
        }:
            task["is_schedulable"] = False
            task["preflight_blocked"] = True
            task["preflight_blocked_by"] = SRT014_REPLACEMENT_GATE_TASK_ID


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SchedulerPreparationError(f"invalid boolean value {value!r}")


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise SchedulerPreparationError(
            f"taskboard must be inside the repository: {path}"
        ) from exc


def load_scheduler_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the committed scheduler configuration."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchedulerPreparationError("scheduler config must be a JSON object")
    if payload.get("schema") != CONFIG_SCHEMA:
        raise SchedulerPreparationError(
            f"unsupported scheduler config schema {payload.get('schema')!r}"
        )
    provider = payload.get("provider")
    if not isinstance(provider, dict):
        raise SchedulerPreparationError("scheduler config requires provider")
    if str(provider.get("provider_id") or "").strip().lower() != "leanstral-local":
        raise SchedulerPreparationError(
            "semantic round-trip provider_id must be leanstral-local"
        )
    if int(provider.get("max_concurrency") or 0) != 1:
        raise SchedulerPreparationError(
            "Leanstral provider max_concurrency must be exactly one"
        )
    return payload


def resolve_taskboard(
    repo_root: Path,
    config: Mapping[str, Any],
    taskboard_path: Path | None = None,
) -> Path:
    raw = taskboard_path or Path(str(config.get("taskboard_path") or ""))
    path = raw if raw.is_absolute() else repo_root / raw
    path = path.resolve()
    if not path.is_file():
        raise SchedulerPreparationError(f"taskboard does not exist: {path}")
    _repo_relative(repo_root, path)
    return path


def _normalized_metadata(task: PortalTask) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        _canonical_field_name(key): value
        for key, value in task.metadata.items()
    }
    list_fields = {
        "allow_concurrent_with",
        "ast_symbols",
        "changed_paths",
        "effects",
        "generated_artifacts",
        "interfaces",
        "predicted_files",
        "required_capabilities",
        "required_tools",
        "submodules",
    }
    for field in list_fields:
        if field in metadata:
            metadata[field] = split_csv(str(metadata[field]))
    for field in (
        "estimated_context_tokens",
        "estimated_tokens",
        "gpu_memory_bytes",
        "implementation_timeout_seconds",
        "memory_bytes",
        "process_slots",
        "required_context_tokens",
        "token_budget",
    ):
        if field in metadata:
            metadata[field] = _parse_int(metadata[field])
    if (
        "implementation_timeout_seconds" in metadata
        and metadata["implementation_timeout_seconds"] <= 0
    ):
        raise SchedulerPreparationError(
            "implementation_timeout_seconds must be a positive integer"
        )
    for field in ("is_schedulable", "requires_provider", "review_only"):
        if field in metadata:
            metadata[field] = _parse_bool(metadata[field])
    return metadata


def _task_resource_binding(
    task: PortalTask,
    *,
    provider_id: str,
) -> tuple[str, str, str, bool]:
    metadata = _normalized_metadata(task)
    resource_class = normalize_resource_class(metadata.get("resource_class"))
    resource_stage = normalize_adaptive_stage(
        metadata.get("resource_stage") or "analysis"
    )
    task_provider = str(
        metadata.get("provider_id")
        or metadata.get("llm_provider")
        or ""
    ).strip().lower()
    requires_provider = _parse_bool(
        metadata.get("requires_provider"),
        bool(task_provider),
    )

    if resource_class not in SUPPORTED_RESOURCE_CLASSES:
        raise SchedulerPreparationError(
            f"{task.task_id}: unsupported resource class {resource_class!r}; "
            f"choose one of {', '.join(sorted(SUPPORTED_RESOURCE_CLASSES))}"
        )
    is_model_lane = (
        resource_class == ProofResourceClass.MODEL_DRAFT.value
        or task_provider
        or requires_provider
    )
    if is_model_lane:
        if resource_class != ProofResourceClass.MODEL_DRAFT.value:
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must use "
                f"{ProofResourceClass.MODEL_DRAFT.value!r}"
            )
        if resource_stage != "inference":
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must use resource stage 'inference'"
            )
        if task_provider != provider_id:
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must bind {provider_id!r}"
            )
        if not requires_provider:
            raise SchedulerPreparationError(
                f"{task.task_id}: provider work must declare Requires provider: true"
            )
    elif resource_stage == "inference":
        raise SchedulerPreparationError(
            f"{task.task_id}: inference work must bind a provider"
        )
    return resource_class, resource_stage, task_provider, requires_provider


def validate_taskboard_for_dynamic_scheduler(
    tasks: Sequence[PortalTask],
    *,
    provider_id: str = "leanstral-local",
) -> None:
    """Fail closed on metadata that would bypass scheduler admission."""

    if not tasks:
        raise SchedulerPreparationError("taskboard contains no tasks")
    bundle_bindings: dict[str, set[tuple[str, str, str, bool]]] = defaultdict(set)
    bundle_lanes: dict[str, set[str]] = defaultdict(set)
    seen_ids: set[str] = set()
    for task in tasks:
        if task.task_id in seen_ids:
            raise SchedulerPreparationError(f"duplicate task ID {task.task_id}")
        seen_ids.add(task.task_id)
        metadata = _normalized_metadata(task)
        bundle_key = str(metadata.get("bundle") or "").strip()
        parallel_lane = str(metadata.get("parallel_lane") or "").strip()
        if not bundle_key:
            raise SchedulerPreparationError(f"{task.task_id}: Bundle is required")
        if not parallel_lane:
            raise SchedulerPreparationError(
                f"{task.task_id}: Parallel lane is required"
            )
        binding = _task_resource_binding(task, provider_id=provider_id)
        bundle_bindings[bundle_key].add(binding)
        bundle_lanes[bundle_key].add(parallel_lane)

    unknown_dependencies = {
        dependency
        for task in tasks
        for dependency in task.depends_on
        if dependency not in seen_ids
    }
    if unknown_dependencies:
        raise SchedulerPreparationError(
            "unknown task dependencies: " + ", ".join(sorted(unknown_dependencies))
        )
    for bundle_key, lanes in sorted(bundle_lanes.items()):
        if len(lanes) != 1:
            raise SchedulerPreparationError(
                f"bundle {bundle_key!r} spans multiple parallel lanes: "
                + ", ".join(sorted(lanes))
            )
        if len(bundle_bindings[bundle_key]) != 1:
            raise SchedulerPreparationError(
                f"bundle {bundle_key!r} mixes resource/provider bindings; "
                "split independently schedulable work into distinct bundles"
            )


def _task_payload(
    task: PortalTask,
    *,
    provider_id: str,
) -> dict[str, Any]:
    metadata = _normalized_metadata(task)
    resource_class, resource_stage, task_provider, requires_provider = (
        _task_resource_binding(task, provider_id=provider_id)
    )
    status = str(task.status or "todo").strip().lower()
    is_schedulable = (
        _parse_bool(metadata.get("is_schedulable"), True)
        and status not in TERMINAL_STATUSES
        and status not in BLOCKED_STATUSES
    )
    review_only = _parse_bool(metadata.get("review_only"), False)
    return {
        **metadata,
        "task_id": task.task_id,
        "title": task.title,
        "status": status,
        "completion": task.completion,
        "priority": task.priority,
        "track": task.track,
        "depends_on": list(task.depends_on),
        "dependency_task_ids": list(task.depends_on),
        "outputs": list(task.outputs),
        "validation": list(task.validation),
        "acceptance": task.acceptance,
        "source_line": task.source_line,
        "board_namespace": task.board_namespace,
        "canonical_task_key": task.canonical_task_key,
        "canonical_task_cid": task.canonical_task_cid,
        "resource_class": resource_class,
        "resource_stage": resource_stage,
        "provider_id": task_provider,
        "llm_provider": task_provider,
        "requires_provider": requires_provider,
        "is_schedulable": is_schedulable,
        "review_only": review_only,
        "execution_authority": "agent-supervisor/v1",
    }


def build_taskboard_bundle_index(
    *,
    repo_root: Path,
    taskboard_path: Path,
    bundle_index_path: Path,
    task_prefix: str = DEFAULT_TASK_PREFIX,
    provider_id: str = "leanstral-local",
) -> dict[str, Any]:
    """Write the supervisor's queryable JSON/DuckDB bundle-index artifact."""

    repo_root = repo_root.resolve()
    taskboard_path = taskboard_path.resolve()
    tasks = parse_task_file(taskboard_path, task_prefix)
    validate_taskboard_for_dynamic_scheduler(tasks, provider_id=provider_id)
    source_todo = _repo_relative(repo_root, taskboard_path)
    source_todo_raw_cid = cid_for_bytes(taskboard_path.read_bytes())
    task_payloads = [
        _task_payload(task, provider_id=provider_id)
        for task in tasks
    ]
    task_cids_by_id = {
        str(task["task_id"]): str(task["canonical_task_cid"])
        for task in task_payloads
    }
    for task in task_payloads:
        task["dependency_task_cids"] = [
            task_cids_by_id[dependency_id]
            for dependency_id in task["depends_on"]
        ]
    srt014_gate = evaluate_srt014_downstream_gate(repo_root)
    remediation_manifest_gate = (
        _evaluate_no_eligible_remediation_manifest_gate(
            repo_root,
            srt014_gate=srt014_gate,
        )
    )
    replacement_gate = evaluate_replacement_selection_gate(repo_root)
    canonical_design_gate = _compose_canonical_design_gate(
        srt014_gate=srt014_gate,
        remediation_manifest_gate=remediation_manifest_gate,
        replacement_gate=replacement_gate,
    )
    _apply_no_eligible_remediation_gate(task_payloads, srt014_gate)
    _apply_canonical_design_gate(task_payloads, canonical_design_gate)
    planning_graph = materialize_task_planning_graph(
        task_payloads,
        repo_root=repo_root,
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in task_payloads:
        grouped[str(task["bundle"])].append(task)

    bundles: dict[str, Any] = {}
    for bundle_key, members in sorted(grouped.items()):
        first = members[0]
        schedulable = [
            member
            for member in members
            if member["is_schedulable"] and not member["review_only"]
        ]
        bundles[bundle_key] = {
            "bundle_key": bundle_key,
            # Each lane receives an immutable runtime copy and an authorized
            # execution slice, so all bundles may safely reference the same
            # protected source board.
            "shard_path": source_todo,
            "parallel_lane": first["parallel_lane"],
            "conflict_policy": first.get("conflict_policy", ""),
            "bundle_strategy": "taskboard-declared",
            "execution_authority": "agent-supervisor/v1",
            "resource_class": first["resource_class"],
            "resource_stage": first["resource_stage"],
            "provider_id": first["provider_id"],
            "llm_provider": first["llm_provider"],
            "requires_provider": first["requires_provider"],
            "is_schedulable": bool(schedulable),
            "review_only": bool(members)
            and all(bool(member["review_only"]) for member in members),
            "tasks": members,
        }

    payload = {
        "schema": BUNDLE_INDEX_SCHEMA,
        "generated_at": _utc_now(),
        "source_todo": source_todo,
        "source_todo_raw_cid": source_todo_raw_cid,
        "source_todo_cid_codec": "raw",
        "task_prefix": task_prefix,
        "execution_authority": "agent-supervisor/v1",
        "srt014_downstream_gate": srt014_gate,
        "no_eligible_remediation_manifest_gate": remediation_manifest_gate,
        "replacement_selection_gate": replacement_gate,
        "canonical_design_gate": canonical_design_gate,
        "bundles": bundles,
        "task_dependency_graph": planning_graph.dependency_graph.to_dict(),
        "dependency_dag": planning_graph.dependency_graph.to_dict(),
        "task_conflict_graph": planning_graph.conflict_graph.to_dict(),
        "conflict_graph": planning_graph.conflict_graph.to_dict(),
        "task_planning_graph": planning_graph.to_dict(),
    }
    bundle_index_path.parent.mkdir(parents=True, exist_ok=True)
    write_bundle_index_artifact(bundle_index_path, payload)
    return payload


def _http_json(url: str, timeout_seconds: float) -> tuple[object, int]:
    started = time.monotonic_ns()
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        status = int(getattr(response, "status", 200))
        body = response.read()
    elapsed_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
    payload = json.loads(body.decode("utf-8"))
    if status < 200 or status >= 300:
        raise SchedulerPreparationError(f"{url} returned HTTP {status}")
    return payload, elapsed_ms


def _probe_mapping(value: object, endpoint: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchedulerPreparationError(
            f"{endpoint} returned non-object JSON"
        )
    return value


def _slot_rows(value: object) -> list[Mapping[str, Any]]:
    """Return a strict llama.cpp ``/slots`` observation.

    Current llama.cpp exposes a top-level array.  A mapping containing a
    ``slots`` array is accepted for compatible reverse proxies, but every
    slot must expose the authoritative boolean ``is_processing`` field.
    Guessing from a task identifier would incorrectly reserve idle
    prompt-cache slots.
    """

    raw_slots: object
    if isinstance(value, list):
        raw_slots = value
    elif isinstance(value, Mapping):
        raw_slots = value.get("slots")
    else:
        raw_slots = None
    if not isinstance(raw_slots, list) or not raw_slots:
        raise SchedulerPreparationError(
            "slots probe must return a nonempty slot array"
        )
    slots: list[Mapping[str, Any]] = []
    for index, raw_slot in enumerate(raw_slots):
        if not isinstance(raw_slot, Mapping):
            raise SchedulerPreparationError(
                f"slots[{index}] must be an object"
            )
        if type(raw_slot.get("is_processing")) is not bool:
            raise SchedulerPreparationError(
                f"slots[{index}].is_processing must be boolean"
            )
        slots.append(raw_slot)
    return slots


def probe_provider_capacity(
    provider_config: Mapping[str, Any],
    *,
    http_json: Callable[[str, float], tuple[object, int]] = _http_json,
) -> dict[str, Any]:
    """Probe the exact local Leanstral identity and emit fail-closed telemetry."""

    provider_id = str(provider_config.get("provider_id") or "").strip().lower()
    base_url = str(provider_config.get("base_url") or "").rstrip("/")
    expected_model = str(provider_config.get("model_id") or "").strip()
    timeout_seconds = float(provider_config.get("timeout_seconds") or 5)
    max_concurrency = int(provider_config.get("max_concurrency") or 0)
    if provider_id != "leanstral-local" or max_concurrency != 1:
        raise SchedulerPreparationError(
            "provider capacity must bind leanstral-local at max_concurrency one"
        )
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 10
    ):
        raise SchedulerPreparationError(
            "provider probe timeout_seconds must be in the bounded range (0, 10]"
        )
    errors: list[str] = []
    healthy = False
    latency_ms = 0
    model_ids: list[str] = []
    capabilities: list[str] = []
    context_window_tokens = -1
    reported_total_slots = -1
    observed_slot_count = -1
    active_requests = max_concurrency
    slot_ids: list[int] = []
    model_alias = ""
    build_info = ""
    try:
        health_value, health_latency = http_json(
            base_url + str(provider_config.get("health_path") or "/health"),
            timeout_seconds,
        )
        health = _probe_mapping(health_value, "health probe")
        latency_ms = max(latency_ms, health_latency)
        if str(health.get("status") or "").strip().lower() not in {
            "ok",
            "ready",
            "healthy",
            "up",
        }:
            errors.append("health_status_not_ready")
    except Exception as exc:  # The artifact records the exact failed preflight.
        errors.append(f"health_probe:{type(exc).__name__}:{exc}")

    try:
        models_value, model_latency = http_json(
            base_url + str(provider_config.get("models_path") or "/v1/models"),
            timeout_seconds,
        )
        models = _probe_mapping(models_value, "model probe")
        latency_ms = max(latency_ms, model_latency)
        raw_models = models.get("data") or models.get("models") or []
        for item in raw_models if isinstance(raw_models, list) else []:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "")
            if model_id:
                model_ids.append(model_id)
            for capability in item.get("capabilities") or ():
                value = str(capability).strip().lower()
                if value and value not in capabilities:
                    capabilities.append(value)
            meta = item.get("meta") if isinstance(item.get("meta"), Mapping) else {}
            context_window_tokens = max(
                context_window_tokens,
                _parse_int(
                    meta.get("n_ctx")
                    or item.get("context_window_tokens")
                    or item.get("context_length"),
                    0,
                ),
            )
        if expected_model not in model_ids:
            errors.append("configured_model_not_served")
    except Exception as exc:
        errors.append(f"model_probe:{type(exc).__name__}:{exc}")

    try:
        props_value, props_latency = http_json(
            base_url + str(provider_config.get("props_path") or "/props"),
            timeout_seconds,
        )
        props = _probe_mapping(props_value, "props probe")
        latency_ms = max(latency_ms, props_latency)
        reported_total_slots = _parse_int(props.get("total_slots"), 0)
        model_alias = str(props.get("model_alias") or "").strip()
        build_info = str(props.get("build_info") or "").strip()
        defaults = (
            props.get("default_generation_settings")
            if isinstance(props.get("default_generation_settings"), Mapping)
            else {}
        )
        props_context = _parse_int(defaults.get("n_ctx"), 0)
        if props_context:
            context_window_tokens = props_context
        if reported_total_slots != max_concurrency:
            errors.append("configured_capacity_mismatch")
        if model_alias != expected_model:
            errors.append("props_model_alias_mismatch")
        if context_window_tokens <= 0:
            errors.append("props_context_window_missing")
    except Exception as exc:
        errors.append(f"props_probe:{type(exc).__name__}:{exc}")

    try:
        slots_value, slots_latency = http_json(
            base_url + str(provider_config.get("slots_path") or "/slots"),
            timeout_seconds,
        )
        latency_ms = max(latency_ms, slots_latency)
        slots = _slot_rows(slots_value)
        observed_slot_count = len(slots)
        active_requests = sum(
            1 for slot in slots if bool(slot["is_processing"])
        )
        if observed_slot_count != max_concurrency:
            errors.append("observed_slot_count_mismatch")
        if active_requests > max_concurrency:
            errors.append("active_request_count_exceeds_capacity")
        for index, slot in enumerate(slots):
            raw_id = slot.get("id", index)
            if (
                not isinstance(raw_id, int)
                or isinstance(raw_id, bool)
                or raw_id < 0
            ):
                raise SchedulerPreparationError(
                    f"slots[{index}].id must be a nonnegative integer"
                )
            slot_ids.append(raw_id)
        if len(slot_ids) != len(set(slot_ids)):
            errors.append("duplicate_slot_ids")
    except Exception as exc:
        # Unknown occupancy must reserve the whole configured capacity even
        # though ``healthy`` also fails closed.  This prevents a downstream
        # scheduler that inspects capacity before health from admitting work.
        active_requests = max_concurrency
        observed_slot_count = -1
        slot_ids = []
        errors.append(f"slots_probe:{type(exc).__name__}:{exc}")

    healthy = not errors
    observed_at_ms = int(time.time() * 1_000)
    cid_payload = {
        "schema": PROVIDER_CAPACITY_SCHEMA,
        "generated_at": _utc_now(),
        "provider_endpoint": base_url,
        "configured_model_id": expected_model,
        "probe_errors": errors,
        "providers": {
            provider_id: {
                "provider_id": provider_id,
                "healthy": healthy,
                "max_concurrency": max_concurrency,
                "active_requests": active_requests,
                "available_concurrency": max(
                    0, max_concurrency - active_requests
                ),
                "observed_slot_count": observed_slot_count,
                "slot_ids": slot_ids,
                "latency_ms": latency_ms,
                "context_window_tokens": context_window_tokens,
                "capabilities": capabilities,
                "observed_at_ms": observed_at_ms,
                "model_ids": sorted(set(model_ids)),
                "model_alias": model_alias,
                "reported_total_slots": reported_total_slots,
                "backend_build_info": build_info,
            }
        },
    }
    return {
        **cid_payload,
        "provider_capacity_cid": cid_for_dag_json(cid_payload),
        "provider_capacity_cid_codec": "dag-json",
        "provider_capacity_cid_scope": "payload_without_cid_fields",
    }


def write_provider_capacity(
    path: Path,
    provider_config: Mapping[str, Any],
    *,
    http_json: Callable[[str, float], tuple[object, int]] = _http_json,
) -> dict[str, Any]:
    payload = probe_provider_capacity(provider_config, http_json=http_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


def prepare_scheduler_inputs(
    *,
    repo_root: Path,
    config_path: Path = DEFAULT_CONFIG_PATH,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    taskboard_path: Path | None = None,
    http_json: Callable[[str, float], tuple[object, int]] = _http_json,
) -> dict[str, Any]:
    """Build fresh index and provider telemetry without starting workers."""

    repo_root = repo_root.resolve()
    config = load_scheduler_config(config_path.resolve())
    taskboard = resolve_taskboard(repo_root, config, taskboard_path)
    runtime_root = runtime_root.resolve()
    bundle_index_path = runtime_root / "bundles" / "index.json"
    provider_capacity_path = runtime_root / "provider_capacity.json"
    provider_config = config["provider"]
    index = build_taskboard_bundle_index(
        repo_root=repo_root,
        taskboard_path=taskboard,
        bundle_index_path=bundle_index_path,
        task_prefix=str(config.get("task_prefix") or DEFAULT_TASK_PREFIX),
        provider_id=str(provider_config["provider_id"]).strip().lower(),
    )
    capacity = write_provider_capacity(
        provider_capacity_path,
        provider_config,
        http_json=http_json,
    )
    return {
        "schema": "ipfs_datasets_py.benchmarks.semantic_roundtrip.scheduler_preparation@1",
        "generated_at": _utc_now(),
        "repo_root": str(repo_root),
        "taskboard_path": str(taskboard),
        "taskboard_raw_cid": cid_for_bytes(taskboard.read_bytes()),
        "taskboard_cid_codec": "raw",
        "runtime_root": str(runtime_root),
        "bundle_index_path": str(bundle_index_path),
        "bundle_index_duckdb_path": str(bundle_index_path.with_suffix(".duckdb")),
        "provider_capacity_path": str(provider_capacity_path),
        "provider_capacity_cid": str(capacity["provider_capacity_cid"]),
        "provider_capacity_cid_codec": "dag-json",
        "srt014_downstream_gate": dict(index["srt014_downstream_gate"]),
        "no_eligible_remediation_manifest_gate": dict(
            index["no_eligible_remediation_manifest_gate"]
        ),
        "replacement_selection_gate": dict(
            index["replacement_selection_gate"]
        ),
        "canonical_design_gate": dict(index["canonical_design_gate"]),
        "srt015_launch_authorized": bool(
            index["canonical_design_gate"]["launch_authorized"]
        ),
        "bundle_count": len(index["bundles"]),
        "task_count": sum(
            len(bundle["tasks"]) for bundle in index["bundles"].values()
        ),
        "provider_healthy": bool(
            capacity["providers"][provider_config["provider_id"]]["healthy"]
        ),
        "provider_max_concurrency": int(
            capacity["providers"][provider_config["provider_id"]][
                "max_concurrency"
            ]
        ),
        "provider_probe_errors": list(capacity["probe_errors"]),
    }


def _current_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        raise SchedulerPreparationError(
            "scheduler launch requires a named merge-target branch"
        )
    return branch


def build_bundle_supervisor_command(
    preparation: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    implement: bool = True,
    max_lanes: int | None = None,
    start: bool = True,
) -> list[str]:
    """Return the supported bundle-supervisor CLI invocation."""

    repo_root = Path(str(preparation["repo_root"])).resolve()
    runtime_root = Path(str(preparation["runtime_root"])).resolve()
    lanes = int(max_lanes or config.get("max_lanes") or 1)
    if lanes < 1:
        raise SchedulerPreparationError("max_lanes must be positive")
    command = [
        sys.executable,
        "-m",
        "ipfs_accelerate_py.agent_supervisor.bundle_supervisor",
        "--bundle-index-path",
        str(preparation["bundle_index_path"]),
        "--repo-root",
        str(repo_root),
        "--state-root",
        str(runtime_root / "state"),
        "--worktree-root",
        str(runtime_root / "worktrees"),
        "--log-dir",
        str(runtime_root / "logs"),
        "--manifest-path",
        str(runtime_root / "bundle_lanes.json"),
        "--metrics-path",
        str(runtime_root / "scheduler_metrics.json"),
        "--coordination-path",
        str(runtime_root / "coordination.duckdb"),
        "--provider-capacity-path",
        str(preparation["provider_capacity_path"]),
        "--task-prefix",
        str(config.get("task_prefix") or DEFAULT_TASK_PREFIX),
        "--max-lanes",
        str(lanes),
        "--poll-interval",
        str(config.get("poll_interval_seconds") or 5),
        "--daemon-interval",
        str(config.get("daemon_interval_seconds") or 300),
        "--stale-seconds",
        str(config.get("stale_seconds") or 1800),
        "--check-interval",
        str(config.get("check_interval_seconds") or 60),
        "--max-restarts",
        str(config.get("max_restarts") or 0),
        "--max-task-attempts",
        str(config.get("max_task_attempts") or 0),
        "--implementation-timeout",
        str(config.get("implementation_timeout_seconds") or 1800),
        "--merge-target-branch",
        _current_branch(repo_root),
    ]
    for submodule_path in config.get("worktree_submodule_paths") or ():
        command.extend(["--worktree-submodule-path", str(submodule_path)])
    command.append("--implement" if implement else "--no-implement")
    if start:
        command.append("--start")
    return command


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the semantic round-trip taskboard into a bundle index and "
            "delegate execution to DynamicBundleScheduler"
        )
    )
    parser.add_argument(
        "action",
        choices=(
            "validate",
            "remediation-gate",
            "manifest-gate",
            "gate",
            "prepare",
            "plan",
            "launch",
        ),
        nargs="?",
        default="prepare",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--taskboard-path", type=Path, default=None)
    parser.add_argument("--max-lanes", type=int, default=None)
    parser.add_argument(
        "--require-authorized",
        action="store_true",
        help=(
            "For gate, return nonzero unless replacement evidence authorizes "
            "SRT-015"
        ),
    )
    parser.add_argument(
        "--validate-artifact",
        type=Path,
        default=None,
        help=(
            "For gate, require this CID-bound JSON artifact to equal the "
            "independently recomputed canonical-design gate"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="For launch, replace this process with the persistent scheduler",
    )
    parser.add_argument(
        "--no-implement",
        dest="implement",
        action="store_false",
        help="Plan/start reconciliation supervisors without implementation agents",
    )
    parser.set_defaults(implement=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    config = load_scheduler_config(args.config_path.resolve())
    taskboard = resolve_taskboard(repo_root, config, args.taskboard_path)
    if args.action == "validate":
        tasks = parse_task_file(
            taskboard,
            str(config.get("task_prefix") or DEFAULT_TASK_PREFIX),
        )
        validate_taskboard_for_dynamic_scheduler(
            tasks,
            provider_id=str(config["provider"]["provider_id"]),
        )
        print(
            json.dumps(
                {
                    "valid": True,
                    "task_count": len(tasks),
                    "taskboard_path": str(taskboard),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.action == "gate":
        gate = evaluate_canonical_design_gate(repo_root)
        artifact_validation = None
        if args.validate_artifact is not None:
            artifact_validation = _evaluate_canonical_design_gate_artifact(
                repo_root,
                artifact_path=args.validate_artifact,
                canonical_gate=gate,
            )
        print(
            json.dumps(
                (
                    {
                        "canonical_design_gate": gate,
                        "artifact_validation": artifact_validation,
                    }
                    if artifact_validation is not None
                    else gate
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return int(
            (
                bool(args.require_authorized)
                and gate.get("launch_authorized") is not True
            )
            or (
                artifact_validation is not None
                and artifact_validation.get("valid") is not True
            )
        )
    if args.action == "remediation-gate":
        gate = evaluate_srt014_downstream_gate(repo_root)
        print(json.dumps(gate, indent=2, sort_keys=True))
        return int(gate.get("status") != "remediation_required")
    if args.action == "manifest-gate":
        gate = evaluate_no_eligible_remediation_manifest_gate(repo_root)
        print(json.dumps(gate, indent=2, sort_keys=True))
        return int(gate.get("valid") is not True)

    preparation = prepare_scheduler_inputs(
        repo_root=repo_root,
        config_path=args.config_path,
        runtime_root=args.runtime_root,
        taskboard_path=taskboard,
    )
    if args.action == "prepare":
        print(json.dumps(preparation, indent=2, sort_keys=True))
        return 0

    command = build_bundle_supervisor_command(
        preparation,
        config,
        implement=args.implement,
        max_lanes=args.max_lanes,
        start=args.action == "launch",
    )
    if args.action == "plan":
        # Omitting --start uses the supervisor's side-effect-free lane planner.
        completed = subprocess.run(command, cwd=repo_root, check=False)
        return int(completed.returncode)

    if not args.execute:
        print(shlex.join(command))
        return 0
    os.execvpe(command[0], command, os.environ.copy())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
