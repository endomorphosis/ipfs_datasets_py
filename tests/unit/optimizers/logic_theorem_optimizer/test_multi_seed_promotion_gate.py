"""Multi-seed statistical promotion gates for Hammer/Leanstral rollout."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    MULTI_SEED_PROMOTION_METRICS,
    MULTI_SEED_PROMOTION_SCHEMA_VERSION,
    RolloutGateConfig,
    StagedRolloutConfig,
    multi_seed_promotion_gate,
    rollout_gate,
    staged_rollout_gate,
)


ROOT = Path(__file__).resolve().parents[4]


def _metric_payload(
    *,
    effects: tuple[float, ...] = (0.050, 0.055, 0.052, 0.058),
    family: str = "none",
) -> dict[str, Any]:
    seeds = (101, 103, 107, 109)
    return {
        "direction": "higher",
        "minimum_effect": 0.01,
        "seed_set": list(seeds[: len(effects)]),
        "seed_results": [
            {
                "seed": seed,
                "baseline": 0.70,
                "candidate": 0.70 + effect,
                "failure_family": family,
            }
            for seed, effect in zip(seeds, effects)
        ],
    }


def _multi_seed_evidence() -> dict[str, Any]:
    return {
        "schema_version": MULTI_SEED_PROMOTION_SCHEMA_VERSION,
        "promotion_id": "multi-seed-unit-promotion",
        "compiler_commit": "compiler-commit-unit",
        "confidence_level": 0.95,
        "min_seed_count": 3,
        "metrics": {metric: _metric_payload() for metric in MULTI_SEED_PROMOTION_METRICS},
    }


def _rollout_summary(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "cycles": 2,
        "status": "succeeded",
        "latest_validation_ce_delta": 0.0,
        "latest_validation_cosine_delta": 0.0,
        "compiler_ir_validation_last_delta": {
            "compiler_ir_cross_entropy_loss": 0.0,
            "compiler_ir_cosine_similarity": 0.0,
        },
        "latest_compiler_ir_source_copy_reward_hack_penalty": 0.01,
        "latest_daemon_hammer_guidance": {
            "status": "completed",
            "runtime_failure_count": 0,
            "obligation_failure_count": 0,
            "hammer_metrics": {"hammer_backend_unavailable_ratio": 0.0},
        },
        "program_synthesis_seeded": 1,
        "program_synthesis_completed": 1,
    }
    if evidence is not None:
        summary["multi_seed_statistical_promotion"] = evidence
    return summary


def _stage_snapshot(
    stage: str = "twenty_four_hour_production",
    duration_seconds: int = 86400,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "stage": stage,
        "duration_seconds": duration_seconds,
        "elapsed_seconds": duration_seconds,
        "snapshot_complete": True,
        "status": "succeeded",
        "managed_processes": [
            {"name": "supervisor", "status": "exited", "exit_code": 0, "orphaned": False}
        ],
        "family_metrics": {},
        "trusted_feedback": {
            "trusted_count": 1,
            "autoencoder_received_count": 1,
            "source_digest": "sha256:feedback",
            "autoencoder_source_digest": "sha256:feedback",
        },
        "promotion_lineage": {
            "rollout_id": "multi-seed-unit",
            "stage": stage,
            "baseline_digest": "sha256:" + "1" * 64,
            "input_digest": "sha256:" + "2" * 64,
            "output_digest": "sha256:" + "3" * 64,
            "promotion_revision": "revision-unit",
            "produced_by": "hammer_leanstral_rollout_gate.py",
        },
        "queue_lag": {"p95_seconds": 10},
        "accepted_patches": 4,
        "wall_clock_seconds": 3600,
        "rollback_evidence": {
            "artifact_path": "workspace/rollout/production/rollback.json",
            "sha256": "4" * 64,
            "baseline_revision": "baseline-unit",
            "restorable": True,
        },
        "promotion_thresholds": {
            "projection_p95_seconds": {"baseline": 100, "candidate": 50},
            "task_to_accepted_patch_rate": {"baseline": 0.50, "candidate": 0.65},
            "state_to_merged_patch_lag_seconds": {"baseline": 1000, "candidate": 700},
        },
    }
    for family in (
        "deontic",
        "frame_logic",
        "tdfol",
        "kg",
        "cec",
        "external_provers",
        "decompiler",
    ):
        snapshot["family_metrics"][family] = {
            "baseline": {"compiler_ir_cosine": 0.8, "source_copy_penalty": 0.05},
            "candidate": {"compiler_ir_cosine": 0.81, "source_copy_penalty": 0.04},
            "semantic_regression": False,
            "provenance_regression": False,
            "anti_copy_regression": False,
            "hammer_proof_regression": False,
            "lean_reconstruction_regression": False,
            "process_lifecycle_regression": False,
            "queue_lag_regression": False,
        }
    if evidence is not None:
        snapshot["multi_seed_statistical_promotion"] = evidence
    return snapshot


def _stage_sequence(final_evidence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    stages = (
        ("short_smoke", 600),
        ("one_hour_hparam", 3600),
        ("eight_hour_canary", 28800),
        ("twenty_four_hour_production", 86400),
    )
    return [
        _stage_snapshot(stage, duration, final_evidence if index == 3 else None)
        for index, (stage, duration) in enumerate(stages)
    ]


def test_multi_seed_gate_accepts_complete_confidence_interval_evidence() -> None:
    result = multi_seed_promotion_gate(_multi_seed_evidence())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["seed_set"] == ["101", "103", "107", "109"]
    learned = result.metrics["multi_seed_metrics"]["learned_quality"]
    assert learned["effect_size"] == pytest.approx(0.05375)
    assert learned["variance"] > 0
    assert learned["confidence_interval"]["lower"] > learned["minimum_effect"]
    assert learned["failure_family_attribution"] == {"none": 4}


def test_multi_seed_gate_rejects_single_lucky_run_promotion() -> None:
    evidence = _multi_seed_evidence()
    evidence["metrics"]["learned_quality"] = _metric_payload(effects=(0.20,))

    result = multi_seed_promotion_gate(evidence)

    assert result.accepted is False
    assert "multi_seed_metric_seed_count:learned_quality:1<3" in result.failures
    assert "multi_seed_metric_ci_missing:learned_quality" in result.failures


def test_multi_seed_gate_rejects_high_variance_lucky_mean() -> None:
    evidence = _multi_seed_evidence()
    evidence["metrics"]["accepted_patch_rate"] = _metric_payload(
        effects=(0.25, 0.20, -0.18, -0.15),
        family="accepted_patch_validation",
    )

    result = multi_seed_promotion_gate(evidence)

    assert result.accepted is False
    assert any(
        failure.startswith("multi_seed_metric_ci_below_threshold:accepted_patch_rate")
        for failure in result.failures
    )
    attribution = result.metrics["multi_seed_metrics"]["accepted_patch_rate"][
        "failure_family_attribution"
    ]
    assert attribution == {"accepted_patch_validation": 4}


def test_multi_seed_gate_requires_all_promotion_metric_families() -> None:
    evidence = _multi_seed_evidence()
    evidence["metrics"].pop("semantic_equivalence")

    result = multi_seed_promotion_gate(evidence)

    assert result.accepted is False
    assert "multi_seed_metric_missing:semantic_equivalence" in result.failures


def test_rollout_gate_can_require_multi_seed_statistical_promotion() -> None:
    strict_missing = rollout_gate(
        _rollout_summary(),
        RolloutGateConfig(require_multi_seed_statistical_promotion=True),
    )
    strict_present = rollout_gate(
        _rollout_summary(_multi_seed_evidence()),
        RolloutGateConfig(require_multi_seed_statistical_promotion=True),
    )

    assert strict_missing.accepted is False
    assert "missing_multi_seed_statistical_evidence" in strict_missing.failures
    assert strict_present.accepted is True
    assert strict_present.metrics["multi_seed_statistical_promotion"]["seed_set"] == [
        "101",
        "103",
        "107",
        "109",
    ]


def test_staged_gate_requires_multi_seed_evidence_at_production_boundary() -> None:
    missing = staged_rollout_gate(
        _stage_sequence(),
        StagedRolloutConfig(
            require_multi_seed_statistical_promotion=True,
        ),
    )
    present = staged_rollout_gate(
        _stage_sequence(_multi_seed_evidence()),
        StagedRolloutConfig(
            require_multi_seed_statistical_promotion=True,
        ),
    )

    assert missing.accepted is False
    assert "missing_multi_seed_statistical_evidence" in missing.failures
    assert present.accepted is True
    assert present.metrics["multi_seed_statistical_promotion"]["seed_set"] == [
        "101",
        "103",
        "107",
        "109",
    ]


def test_multi_seed_gate_cli_persists_decision(tmp_path: Path) -> None:
    evidence_path = tmp_path / "multi-seed.json"
    decision_path = tmp_path / "decision.json"
    evidence_path.write_text(json.dumps(_multi_seed_evidence()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
            "multi-seed-gate",
            "--evidence-path",
            str(evidence_path),
            "--evidence-output",
            str(decision_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["accepted"] is True
    assert decision["schema_version"] == MULTI_SEED_PROMOTION_SCHEMA_VERSION
    assert len(decision["evidence_sha256"]) == 64
