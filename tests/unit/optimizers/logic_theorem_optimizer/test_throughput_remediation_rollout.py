"""Fail-closed throughput-remediation rollout promotion tests.

These tests intentionally build a complete, persisted-evidence-shaped packet.
The gate must not infer a healthy service, a passing quality metric, or a
successful recovery from an unrelated headline flag.
"""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    LEGAL_IR_VIEW_FAMILIES,
    THROUGHPUT_REMEDIATION_SCHEMA_VERSION,
    THROUGHPUT_REMEDIATION_STAGES,
    ThroughputRemediationConfig,
    throughput_remediation_rollout_gate,
    render_throughput_remediation_report,
)


ROOT = Path(__file__).resolve().parents[4]

QUALITY_METRICS = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "semantic_equivalence",
    "proof_success_rate",
    "reconstruction_success_rate",
    "provenance",
    "round_trip",
    "uncertainty",
    "holdout",
    "source_copy_penalty",
)

LOWER_IS_BETTER = frozenset(
    {
        "ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "uncertainty",
        "source_copy_penalty",
    }
)


def _quality_pair() -> dict[str, dict[str, float]]:
    baseline = {
        "ir_cross_entropy_loss": 0.20,
        "ir_cosine_similarity": 0.88,
        "autoencoder_cross_entropy_loss": 0.18,
        "autoencoder_cosine_similarity": 0.90,
        "semantic_equivalence": 0.91,
        "proof_success_rate": 0.90,
        "reconstruction_success_rate": 0.89,
        "provenance": 0.98,
        "round_trip": 0.94,
        "uncertainty": 0.12,
        "holdout": 0.87,
        "source_copy_penalty": 0.08,
    }
    candidate = {
        metric: value - 0.01 if metric in LOWER_IS_BETTER else value + 0.01
        for metric, value in baseline.items()
    }
    return {"baseline": baseline, "candidate": candidate}


def _stage(name: str, duration_seconds: int, index: int) -> dict[str, Any]:
    digest = lambda offset: "sha256:" + f"{index + offset:064x}"  # noqa: E731
    return {
        "name": name,
        "planned_duration_seconds": duration_seconds,
        "active_seconds": duration_seconds,
        "status": "succeeded",
        "snapshot_complete": True,
        "lineage": {
            "run_id": "throughput-remediation-unit",
            "stage": name,
            "configuration_digest": digest(10),
            "input_digest": digest(20),
            "output_digest": digest(30),
        },
        "managed_processes": [
            {
                "name": f"{name}-supervisor",
                "status": "exited",
                "exit_code": 0,
                "orphaned": False,
            }
        ],
        "orphaned_child_count": 0,
        "resume_evidence": {
            "available": True,
            "resumed": True,
            "lineage_verified": True,
            "checkpoint_path": f"workspace/rollout/{name}/resume.json",
            "sha256": digest(40),
        },
        "rollback_evidence": {
            "available": True,
            "restorable": True,
            "rollback_tested": True,
            "baseline_revision": "baseline-throughput-unit",
            "artifact_path": f"workspace/rollout/{name}/rollback.json",
            "sha256": digest(50),
        },
    }


def _complete_evidence() -> dict[str, Any]:
    stage_entries = [
        _stage(spec.name, spec.duration_seconds, index)
        for index, spec in enumerate(THROUGHPUT_REMEDIATION_STAGES, start=1)
    ]
    return {
        "schema_version": THROUGHPUT_REMEDIATION_SCHEMA_VERSION,
        "promotion_id": "throughput-remediation-unit",
        "compiler_commit": "compiler-throughput-unit",
        "stages": stage_entries,
        "matched_benchmark": {
            "reproducible": True,
            "fixture_digest": "sha256:" + "a" * 64,
            "configuration_digest": "sha256:" + "b" * 64,
            "cold": {
                "baseline": {
                    "cycles_per_hour": 90.0,
                    "samples_per_second": 8.0,
                    "state_to_accepted_patch_lag_p95_seconds": 130.0,
                },
                "candidate": {
                    "cycles_per_hour": 135.0,
                    "samples_per_second": 11.0,
                    "state_to_accepted_patch_lag_p95_seconds": 100.0,
                },
            },
            "warm": {
                "baseline": {
                    "cycles_per_hour": 100.0,
                    "samples_per_second": 10.0,
                    "state_to_accepted_patch_lag_p95_seconds": 120.0,
                },
                "candidate": {
                    "cycles_per_hour": 185.0,
                    "samples_per_second": 15.5,
                    "state_to_accepted_patch_lag_p95_seconds": 80.0,
                },
            },
        },
        "services": {
            "cuda_autoencoder": {
                "healthy": True,
                "device": "cuda:0",
                "training": True,
                "cpu_fallback": False,
                "forward_count": 8,
                "loss_count": 8,
                "backward_count": 8,
                "optimizer_step_count": 8,
            },
            "leanstral": {
                "healthy": True,
                "device": "cuda:0",
                "persistent": True,
                "cpu_fallback": False,
                "model_load_count": 1,
                "request_count": 10,
                "reuse_count": 9,
            },
            "hammer": {
                "healthy": True,
                "backend_available": True,
                "obligation_count": 12,
                "proof_attempt_count": 12,
                "reconstruction_count": 10,
                "fatal_failure_count": 0,
            },
            "codex": {
                "healthy": True,
                "invocation_count": 5,
                "focused_validation_count": 5,
                "accepted_patch_count": 4,
                "safe_rejection_count": 1,
                "fatal_failure_count": 0,
            },
        },
        "artifacts": {
            "checkpoint_bytes": 32 * 1024 * 1024,
            "summary_bytes": 256 * 1024,
            "checkpoint_sha256": "sha256:" + "c" * 64,
            "summary_sha256": "sha256:" + "d" * 64,
        },
        "quality_families": {
            family: _quality_pair() for family in LEGAL_IR_VIEW_FAMILIES
        },
        "ablations": {
            "persistent_leanstral_reuse": {
                "attributed": True,
                "cycles_per_hour_gain": 32.0,
                "samples_per_second_gain": 1.8,
                "evidence_digest": "sha256:" + "e" * 64,
            },
            "tensorized_cuda_autoencoder": {
                "attributed": True,
                "cycles_per_hour_gain": 28.0,
                "samples_per_second_gain": 2.1,
                "evidence_digest": "sha256:" + "f" * 64,
            },
            "hammer_codex_pipeline_parallelism": {
                "attributed": True,
                "cycles_per_hour_gain": 25.0,
                "samples_per_second_gain": 1.6,
                "evidence_digest": "sha256:" + "9" * 64,
            },
        },
    }


def _has_failure(result: Any, *tokens: str) -> bool:
    return any(all(token in failure for token in tokens) for failure in result.failures)


def test_stage_contract_and_complete_evidence_promote() -> None:
    config = ThroughputRemediationConfig()
    assert config.min_warm_cycles_per_hour_ratio == 1.8
    assert config.min_samples_per_second_ratio == 1.5
    assert [(stage.name, stage.duration_seconds) for stage in THROUGHPUT_REMEDIATION_STAGES] == [
        ("matched_benchmark", 0),
        ("ten_minute_smoke", 600),
        ("one_hour_hparam", 3600),
        ("eight_hour_canary", 28800),
        ("twenty_four_hour_production", 86400),
    ]

    result = throughput_remediation_rollout_gate(_complete_evidence())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["schema_version"] == THROUGHPUT_REMEDIATION_SCHEMA_VERSION
    assert result.metrics["warm_cycles_per_hour_ratio"] == pytest.approx(1.85)
    assert result.metrics["warm_samples_per_second_ratio"] == pytest.approx(1.55)
    assert result.metrics["state_to_accepted_patch_lag_improved"] is True
    assert result.metrics["evidence_complete"] is True


@pytest.mark.parametrize(
    "missing_key",
    ("stages", "matched_benchmark", "services", "artifacts", "quality_families", "ablations"),
)
def test_gate_fails_closed_when_required_evidence_domain_is_absent(
    missing_key: str,
) -> None:
    evidence = _complete_evidence()
    evidence.pop(missing_key)

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "evidence_missing", missing_key)


@pytest.mark.parametrize(
    ("service", "field", "value"),
    [
        ("cuda_autoencoder", "training", False),
        ("cuda_autoencoder", "device", "cpu"),
        ("cuda_autoencoder", "cpu_fallback", True),
        ("leanstral", "persistent", False),
        ("leanstral", "reuse_count", 0),
        ("leanstral", "cpu_fallback", True),
        ("hammer", "healthy", False),
        ("codex", "focused_validation_count", 0),
    ],
)
def test_gate_requires_real_cuda_reuse_and_healthy_hammer_codex_paths(
    service: str,
    field: str,
    value: Any,
) -> None:
    evidence = _complete_evidence()
    evidence["services"][service][field] = value

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, service)


@pytest.mark.parametrize(
    ("metric", "candidate", "diagnostic"),
    [
        ("cycles_per_hour", 179.99, "warm_cycles_per_hour"),
        ("samples_per_second", 14.99, "warm_samples_per_second"),
        ("state_to_accepted_patch_lag_p95_seconds", 120.0, "state_to_accepted_patch_lag"),
    ],
)
def test_matched_warm_throughput_and_lag_thresholds_are_hard_gates(
    metric: str,
    candidate: float,
    diagnostic: str,
) -> None:
    evidence = _complete_evidence()
    evidence["matched_benchmark"]["warm"]["candidate"][metric] = candidate

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "throughput_threshold", diagnostic)


def test_dry_run_benchmark_is_never_promotion_evidence() -> None:
    evidence = _complete_evidence()
    evidence["matched_benchmark"]["dry_run"] = True

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "dry_run_not_promotion_evidence")


def test_cuda_training_requires_recorded_loss_work() -> None:
    evidence = _complete_evidence()
    evidence["services"]["cuda_autoencoder"].pop("loss_count")

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "cuda_autoencoder")


def test_stage_duration_resume_rollback_artifact_and_process_evidence_are_hard_gates() -> None:
    evidence = _complete_evidence()
    canary = evidence["stages"][3]
    canary["active_seconds"] = 28_799
    canary["resume_evidence"].pop("sha256")
    canary["rollback_evidence"]["restorable"] = False
    canary["orphaned_child_count"] = 1
    evidence["artifacts"]["checkpoint_bytes"] = 10**15
    evidence["artifacts"]["summary_bytes"] = 10**15

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "stage_duration", "eight_hour_canary")
    assert _has_failure(result, "resume", "eight_hour_canary")
    assert _has_failure(result, "rollback", "eight_hour_canary")
    assert _has_failure(result, "orphan", "eight_hour_canary")
    assert _has_failure(result, "checkpoint_bytes")
    assert _has_failure(result, "summary_bytes")


@pytest.mark.parametrize("metric", QUALITY_METRICS)
def test_every_per_family_quality_metric_is_a_no_regression_guardrail(metric: str) -> None:
    evidence = _complete_evidence()
    pair = evidence["quality_families"]["deontic"]
    baseline = pair["baseline"][metric]
    pair["candidate"][metric] = (
        baseline + 0.001 if metric in LOWER_IS_BETTER else baseline - 0.001
    )

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "quality_regression", "deontic", metric)


def test_quality_is_fail_closed_for_a_missing_family_or_metric() -> None:
    missing_family = _complete_evidence()
    missing_family["quality_families"].pop(LEGAL_IR_VIEW_FAMILIES[-1])
    missing_metric = _complete_evidence()
    missing_metric["quality_families"]["kg"]["candidate"].pop("holdout")

    family_result = throughput_remediation_rollout_gate(missing_family)
    metric_result = throughput_remediation_rollout_gate(missing_metric)

    assert family_result.accepted is False
    assert _has_failure(family_result, "evidence_missing", LEGAL_IR_VIEW_FAMILIES[-1])
    assert metric_result.accepted is False
    assert _has_failure(metric_result, "evidence_missing", "kg", "holdout")


def test_ablation_gain_attribution_is_required_not_just_a_headline_speedup() -> None:
    evidence = _complete_evidence()
    evidence["ablations"]["persistent_leanstral_reuse"]["attributed"] = False
    evidence["ablations"]["persistent_leanstral_reuse"].pop("evidence_digest")

    result = throughput_remediation_rollout_gate(evidence)

    assert result.accepted is False
    assert _has_failure(result, "ablation", "persistent_leanstral_reuse")


def test_gate_is_non_mutating_and_report_renders_decision_thresholds_and_ablations() -> None:
    evidence = _complete_evidence()
    original = deepcopy(evidence)

    result = throughput_remediation_rollout_gate(evidence)
    markdown = render_throughput_remediation_report(result)

    assert evidence == original
    assert "accepted" in markdown.lower()
    assert "1.8" in markdown
    assert "1.5" in markdown
    assert "ablation" in markdown.lower()
    assert "persistent_leanstral_reuse" in markdown


def test_cli_persists_machine_decision_and_operator_report(tmp_path: Path) -> None:
    evidence_path = tmp_path / "rollout-evidence.json"
    decision_path = tmp_path / "promotion-decision.json"
    report_path = tmp_path / "promotion-report.md"
    evidence_path.write_text(json.dumps(_complete_evidence()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
            "throughput-remediation-gate",
            "--evidence-path",
            str(evidence_path),
            "--evidence-output",
            str(decision_path),
            "--report-output",
            str(report_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["accepted"] is True
    assert decision["schema_version"] == THROUGHPUT_REMEDIATION_SCHEMA_VERSION
    assert len(decision["evidence_sha256"]) == 64
    assert "accepted" in report_path.read_text(encoding="utf-8").lower()
