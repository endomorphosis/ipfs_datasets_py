"""Tests for closed-loop compiler repair lineage attribution."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.compiler_repair_lineage import (
    CODEX_ATTEMPT,
    HAMMER_RECEIPT,
    LEANSTRAL_AUDIT,
    MERGE,
    METRIC_GAP,
    NEXT_CYCLE_OBSERVATION,
    REQUIRED_REPAIR_EVIDENCE_KINDS,
    RULE_GAP_REPORT,
    STATE_SNAPSHOT,
    TODO,
    VALIDATION,
    CompilerRepairLineageValidationError,
    CompilerRepairOutcome,
    CompilerRepairLineage,
    build_compiler_repair_lineage,
    compiler_repair_lineage_from_json,
    compiler_repair_lineage_to_json,
    future_prioritization_records,
)


BASE_TIME = "2026-07-21T08:00:00+00:00"


def _evidence(
    kind: str,
    stable_id: str,
    *,
    offset: int,
    deterministic: bool | None = None,
    observed: bool = True,
    **payload,
) -> dict:
    hour = 8 + offset // 60
    minute = offset % 60
    data = {
        "kind": kind,
        "observed_at": f"2026-07-21T{hour:02d}:{minute:02d}:00+00:00",
        "stable_id": stable_id,
        "observed": observed,
        "payload": payload,
    }
    if deterministic is not None:
        data["deterministic"] = deterministic
    return data


def _lineage(**overrides):
    payloads = {
        "state_snapshot": _evidence(
            STATE_SNAPSHOT,
            "state-snapshot-1",
            offset=0,
            state_hash="state-1",
            compiler_commit="commit-1",
        ),
        "metric_gap": _evidence(
            METRIC_GAP,
            "metric-gap-1",
            offset=1,
            metric_gap_id="metric-gap-1",
            target_metrics=["modal_ir_formula_recall"],
            pre_patch_metrics={"modal_ir_formula_recall": 0.50},
            status="observed",
        ),
        "leanstral_audit": _evidence(
            LEANSTRAL_AUDIT,
            "leanstral-audit-1",
            offset=2,
            deterministic=False,
            request_id="leanstral-audit-1",
            response_hash="response-hash-1",
            classification="issue",
            status="verified_by_local_checks",
        ),
        "hammer_receipt": _evidence(
            HAMMER_RECEIPT,
            "hammer-receipt-1",
            offset=3,
            proof_obligation_ids=["PO-1"],
            proof_checked=True,
            reconstruction_status="not_reconstructed",
            status="failed_obligation_observed",
        ),
        "rule_gap_report": _evidence(
            RULE_GAP_REPORT,
            "rule-gap-report-1",
            offset=4,
            gap_id="gap-modal-cue",
            report_id="rule-gap-report-1",
            status="accepted",
        ),
        "todo": _evidence(
            TODO,
            "todo-accepted",
            offset=5,
            metadata={
                "leanstral_gap_id": "gap-modal-cue",
                "semantic_bundle_key": "leanstral-rule-gap:modal-cue-shall",
                "target_metrics": ["modal_ir_formula_recall"],
            },
            status="completed",
            todo_id="todo-accepted",
        ),
        "codex_attempt": _evidence(
            CODEX_ATTEMPT,
            "codex-attempt-1",
            offset=6,
            deterministic=False,
            packet_id="packet-1",
            status="succeeded",
        ),
        "validation": _evidence(
            VALIDATION,
            "validation-1",
            offset=7,
            main_apply_validation_status="passed",
            metric_deltas={"modal_ir_formula_recall": 0.04},
            objective_delta=0.04,
            target_metric_status="passed",
        ),
        "merge": _evidence(
            MERGE,
            "merge-1",
            offset=8,
            commit_sha="merge-commit-1",
            merge_status="merged",
            status="merged",
        ),
        "next_cycle_observation": _evidence(
            NEXT_CYCLE_OBSERVATION,
            "next-cycle-1",
            offset=60,
            metric_deltas={"modal_ir_formula_recall": 0.03},
            objective_delta=0.03,
            source_compiler_commit="commit-1",
            source_state_hash="state-1",
            status="measured",
            target_metric_status="passed",
        ),
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and "payload" in value:
            payloads[key] = value
        elif isinstance(value, dict):
            updated = dict(payloads[key])
            updated["payload"] = {**dict(updated.get("payload") or {}), **value}
            payloads[key] = updated
        else:
            payloads[key] = value
    return build_compiler_repair_lineage(
        task_id="PORTAL-LIR-HAMMER-061",
        attempt=1,
        created_at=BASE_TIME,
        **payloads,
    )


def test_lineage_links_required_evidence_with_stable_ids_and_timestamps() -> None:
    lineage = _lineage()
    encoded = compiler_repair_lineage_to_json(lineage)
    parsed = json.loads(encoded)

    assert parsed["schema_version"] == "legal-ir-compiler-repair-lineage-v1"
    assert parsed["stable_id"].startswith("compiler-repair-lineage:")
    assert [item["kind"] for item in parsed["evidence_refs"]] == list(
        REQUIRED_REPAIR_EVIDENCE_KINDS
    )
    assert all(item["stable_id"] for item in parsed["evidence_refs"])
    assert all(item["observed_at"].endswith("+00:00") for item in parsed["evidence_refs"])
    assert [(link["source_kind"], link["target_kind"]) for link in parsed["links"]] == [
        (left, right)
        for left, right in zip(
            REQUIRED_REPAIR_EVIDENCE_KINDS,
            REQUIRED_REPAIR_EVIDENCE_KINDS[1:],
        )
    ]
    assert parsed["classification"]["outcome"] == "accepted_benefit"

    round_trip = compiler_repair_lineage_from_json(encoded)
    assert round_trip.stable_id == lineage.stable_id
    assert round_trip.todo_id == "todo-accepted"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {
                "next_cycle_observation": {
                    "metric_deltas": {"modal_ir_formula_recall": 0.0},
                    "objective_delta": 0.0,
                    "target_metric_status": "passed",
                },
            },
            CompilerRepairOutcome.NEUTRAL_CHANGE,
        ),
        (
            {
                "next_cycle_observation": {
                    "metric_deltas": {},
                    "target_metric_status": "improved",
                },
            },
            CompilerRepairOutcome.ACCEPTED_BENEFIT,
        ),
        (
            {
                "next_cycle_observation": {
                    "hard_regressed_metrics": ["modal_ir_formula_recall"],
                    "metric_deltas": {"modal_ir_formula_recall": -0.02},
                    "objective_delta": -0.02,
                    "target_metric_status": "regressed",
                },
            },
            CompilerRepairOutcome.QUALITY_REGRESSION,
        ),
        (
            {
                "validation": {
                    "failure_reason": "program_synthesis_validation_rejected",
                    "main_apply_validation_status": "failed",
                    "metric_deltas": {},
                    "objective_delta": 0.0,
                    "target_metric_status": "failed",
                },
                "next_cycle_observation": {
                    "metric_deltas": {},
                    "objective_delta": 0.0,
                    "target_metric_status": "rejected",
                },
            },
            CompilerRepairOutcome.DISPROVEN_HYPOTHESIS,
        ),
        (
            {
                "next_cycle_observation": {
                    "source_state_hash": "old-state",
                    "stale": True,
                    "status": "stale",
                },
            },
            CompilerRepairOutcome.STALE_EVIDENCE,
        ),
        (
            {
                "codex_attempt": _evidence(
                    CODEX_ATTEMPT,
                    "codex-attempt-timeout",
                    offset=6,
                    deterministic=False,
                    status="timeout",
                ),
            },
            CompilerRepairOutcome.OPERATIONAL_FAILURE,
        ),
    ],
)
def test_classifier_covers_closed_loop_outcomes(overrides, expected) -> None:
    assert _lineage(**overrides).classify().outcome is expected


def test_prioritization_uses_only_observed_deterministic_next_cycle_outcomes() -> None:
    accepted = _lineage()
    model_asserted = _lineage(
        next_cycle_observation=_evidence(
            NEXT_CYCLE_OBSERVATION,
            "next-cycle-model-assertion",
            offset=60,
            deterministic=False,
            observed=True,
            metric_deltas={"modal_ir_formula_recall": 0.50},
            objective_delta=0.50,
            status="measured",
            target_metric_status="passed",
        )
    )
    unobserved = _lineage(
        next_cycle_observation=_evidence(
            NEXT_CYCLE_OBSERVATION,
            "next-cycle-unobserved",
            offset=60,
            deterministic=True,
            observed=False,
            metric_deltas={"modal_ir_formula_recall": 0.50},
            objective_delta=0.50,
            status="measured",
            target_metric_status="passed",
        )
    )

    records = future_prioritization_records([model_asserted, accepted, unobserved])

    assert len(records) == 1
    record = records[0]
    assert record["lineage_id"] == accepted.stable_id
    assert record["outcome"] == "accepted_benefit"
    assert record["todo_id"] == "todo-accepted"
    assert record["target_metrics"] == ["modal_ir_formula_recall"]
    assert record["weight_delta"] == 0.03


def test_incomplete_lineage_fails_closed() -> None:
    with pytest.raises(CompilerRepairLineageValidationError):
        CompilerRepairLineage(
            task_id="bad",
            attempt=1,
            evidence_refs=(
                _evidence(STATE_SNAPSHOT, "state", offset=0),
                _evidence(METRIC_GAP, "metric", offset=1),
            ),
        )
