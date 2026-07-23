"""Production drift monitoring and learned-guidance rollback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_drift_monitor import (
    LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION,
    PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL,
    LegalIRDriftMonitorConfig,
    append_rollback_todos,
    monitor_legal_ir_production_drift,
    persist_legal_ir_drift_report,
)


def _baseline(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "snapshot_id": "baseline-production",
        "schema": {
            "schema_version": "legal-ir-production-v1",
            "families": ["deontic", "kg"],
            "metrics": ["ir_cosine_similarity"],
        },
        "production_distribution": {"deontic": 0.60, "kg": 0.40},
        "view_family_metrics": {
            "deontic": {
                "ir_cosine_similarity": 0.90,
                "hammer_proof_success_rate": 0.96,
                "source_copy_penalty": 0.02,
            },
            "kg": {
                "ir_cosine_similarity": 0.84,
                "hammer_proof_success_rate": 0.94,
                "source_copy_penalty": 0.03,
            },
        },
        "hammer_metrics": {"hammer_proof_success_rate": 0.95},
        "prompt_security": {"rejected_count": 2, "total_count": 100},
        "premise_security": {"rejected_count": 4, "total_count": 100},
        "resource_pressure": {
            "cpu_utilization": 0.40,
            "gpu_memory_pressure": 0.45,
            "gpu_telemetry_known": True,
            "gpu_utilization": 0.82,
            "memory_pressure": 0.50,
            "saturation_events_total": 0,
        },
        "queue_lag": {"p95_seconds": 20},
        "accepted_patches": 12,
        "wall_clock_seconds": 3600,
    }
    payload.update(overrides)
    return payload


def _promotion() -> dict[str, Any]:
    return {
        "schema_version": "legal-ir-learned-guidance-promotion-v1",
        "promotion_id": "lir-guidance-promotion-unit",
        "promoted": True,
        "source_export_id": "lir-feature-export-unit",
        "activation_state": {
            "activation_allowed": True,
            "active": True,
            "active_promotion_id": "lir-guidance-promotion-unit",
            "state": "activated",
        },
        "rollback_metadata": {
            "activation_key": "lir-guidance-promotion-unit",
            "canary_evidence_id": "lir-canary-evidence-unit",
            "disable_action": "remove_promoted_guidance_records",
            "restore_mode": "canary_only",
            "rollback_id": "lir-guidance-rollback-unit",
            "schema_version": "legal-ir-learned-guidance-rollback-v1",
            "source_export_id": "lir-feature-export-unit",
        },
        "guidance_records": [
            {"guidance_id": "lir-guidance-a"},
            {"guidance_id": "lir-guidance-b"},
        ],
    }


def test_clean_production_snapshot_keeps_guidance_active() -> None:
    report = monitor_legal_ir_production_drift(
        _baseline(),
        _baseline(snapshot_id="current-production"),
        promoted_guidance=_promotion(),
    )

    payload = report.to_dict()

    assert payload["schema_version"] == LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION
    assert payload["accepted"] is True
    assert payload["status"] == "stable"
    assert payload["events"] == []
    assert payload["rollback_decision"]["rollback_required"] is False
    assert payload["rollback_decision"]["disabled_promotions"] == []
    assert payload["hard_guardrail"] == PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL


def test_monitor_tracks_all_required_drift_families_and_rolls_back_guidance() -> None:
    current = _baseline(
        snapshot_id="drifted-production",
        schema={
            "schema_version": "legal-ir-production-v2",
            "families": ["deontic", "kg", "tdfol"],
            "metrics": ["ir_cosine_similarity", "new_metric"],
        },
        production_distribution={"deontic": 0.20, "kg": 0.20, "tdfol": 0.60},
        view_family_metrics={
            "deontic": {
                "ir_cosine_similarity": 0.70,
                "hammer_proof_success_rate": 0.72,
                "source_copy_penalty": 0.20,
            },
            "kg": {
                "ir_cosine_similarity": 0.83,
                "hammer_proof_success_rate": 0.93,
                "source_copy_penalty": 0.03,
            },
        },
        hammer_metrics={"hammer_proof_success_rate": 0.70},
        prompt_security={"rejected_count": 18, "total_count": 100},
        premise_security={"rejected_count": 34, "total_count": 100},
        resource_pressure={
            "cpu_utilization": 0.83,
            "gpu_memory_pressure": 0.72,
            "gpu_telemetry_known": False,
            "gpu_utilization": 0.35,
            "memory_pressure": 0.76,
            "saturation_events_total": 2,
        },
        queue_lag={"p95_seconds": 220},
        accepted_patches=3,
        latest_legal_ir_learned_guidance_promotion=_promotion(),
    )

    report = monitor_legal_ir_production_drift(_baseline(), current)
    payload = report.to_dict()
    categories = {event["category"] for event in payload["events"]}

    assert payload["accepted"] is False
    assert payload["status"] == "rollback_required"
    assert {
        "production_distribution_drift",
        "family_metric_drift",
        "proof_failure_drift",
        "prompt_rejection_spike",
        "premise_rejection_spike",
        "schema_drift",
        "gpu_resource_degradation",
        "resource_degradation",
        "accepted_patch_regression",
    }.issubset(categories)

    rollback = payload["rollback_decision"]
    assert rollback["rollback_required"] is True
    disabled = rollback["disabled_promotions"][0]
    assert disabled["promotion_id"] == "lir-guidance-promotion-unit"
    assert disabled["disabled"] is True
    assert disabled["activation_state"]["active"] is False
    assert disabled["activation_state"]["activation_allowed"] is False
    assert disabled["activation_state"]["state"] == "disabled_due_to_production_drift"
    assert disabled["rollback_metadata"]["rollback_id"] == "lir-guidance-rollback-unit"
    assert disabled["affected_guidance_ids"] == ["lir-guidance-a", "lir-guidance-b"]

    todo = rollback["rollback_todos"][0]
    assert todo["todo_id"].startswith("PORTAL-LIR-HAMMER-083-ROLLBACK-")
    assert todo["priority"] == "P0"
    assert todo["action"] == "remove_promoted_guidance_records"
    assert todo["affected_promotion_id"] == "lir-guidance-promotion-unit"
    assert set(todo["drift_event_ids"]) == {
        event["event_id"] for event in payload["events"]
    }


def test_monitor_detects_missing_rollback_metadata_as_guardrail_violation() -> None:
    promotion = _promotion()
    promotion.pop("rollback_metadata")

    report = monitor_legal_ir_production_drift(
        _baseline(),
        _baseline(snapshot_id="current-production"),
        promoted_guidance=promotion,
    )
    payload = report.to_dict()

    assert payload["status"] == "rollback_required"
    assert payload["events"][0]["category"] == "rollback_readiness"
    assert (
        payload["events"][0]["signal"]
        == "promoted_guidance_rollback_metadata_missing"
    )
    disabled = payload["rollback_decision"]["disabled_promotions"][0]
    assert disabled["disabled"] is True
    assert disabled["rollback_metadata"]["rollback_id"].startswith(
        "lir-guidance-rollback-"
    )


def test_thresholds_can_be_tightened_for_specific_signals() -> None:
    current = _baseline(
        view_family_metrics={
            "deontic": {
                "ir_cosine_similarity": 0.875,
                "hammer_proof_success_rate": 0.96,
                "source_copy_penalty": 0.02,
            },
            "kg": {
                "ir_cosine_similarity": 0.84,
                "hammer_proof_success_rate": 0.94,
                "source_copy_penalty": 0.03,
            },
        },
    )

    loose = monitor_legal_ir_production_drift(_baseline(), current)
    strict = monitor_legal_ir_production_drift(
        _baseline(),
        current,
        config=LegalIRDriftMonitorConfig(max_family_metric_regression=0.01),
    )

    assert loose.accepted is True
    assert strict.accepted is False
    assert strict.events[0].category == "family_metric_drift"
    assert strict.events[0].metric == "ir_cosine_similarity"


def test_report_and_rollback_todos_can_be_persisted(tmp_path: Path) -> None:
    current = _baseline(
        production_distribution={"deontic": 0.15, "kg": 0.85},
        latest_legal_ir_learned_guidance_promotion=_promotion(),
    )
    report = monitor_legal_ir_production_drift(_baseline(), current)
    report_path = persist_legal_ir_drift_report(report, tmp_path / "drift.json")
    todo_path = append_rollback_todos(report, tmp_path / "rollback.jsonl")

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    todos = [
        json.loads(line)
        for line in todo_path.read_text(encoding="utf-8").splitlines()
        if line
    ]

    assert saved["report_id"] == report.report_id
    assert saved["status"] == "rollback_required"
    assert len(todos) == 1
    assert todos[0]["affected_promotion_id"] == "lir-guidance-promotion-unit"
