"""Evidence-driven benchmark and staged-promotion acceptance tests."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benchmarks.bench_legal_ir_optimizer_pipeline import (
    aggregate_pipeline_summaries,
    benchmark_document,
    dry_run_trials,
)
from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    LEGAL_IR_VIEW_FAMILIES,
    STAGED_ROLLOUT_SCHEMA_VERSION,
    RolloutStageSpec,
    StagedRolloutConfig,
    staged_rollout_gate,
)
from scripts.ops.legal_ir.tune_hammer_leanstral_parallelism import (
    tune_benchmark_trials,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (
    BenchmarkTrial,
    ParallelismProfile,
    canonical_digest,
)


ROOT = Path(__file__).resolve().parents[4]
REPORT = (
    ROOT
    / "docs"
    / "implementation"
    / "reports"
    / "HAMMER_LEANSTRAL_LEGAL_IR_OPTIMIZATION_REPORT.md"
)


def _quality() -> dict[str, float]:
    return {
        "compiler_ir_cosine": 0.90,
        "structural_validity": 0.98,
        "symbolic_validity_success_rate": 0.97,
        "hammer_proof_success_rate": 0.94,
        "hammer_reconstruction_success_rate": 0.92,
        "source_copy_penalty": 0.05,
    }


def _summary(cache_state: str, *, profile_name: str = "fixed_baseline") -> dict[str, Any]:
    resources = {
        "cpu_percent": 82.0,
        "gpu_utilization_percent": 72.0,
        "gpu_memory_percent": 74.0,
        "gpu_telemetry_available": True,
        "memory_percent": 66.0,
        "memory_used_bytes": 4096,
        "swap_percent": 0.0,
        "swap_used_bytes": 0,
        "child_process_count": 9,
        "queue_depth": 2,
    }
    spans = [
        {
            "phase": "projection_training",
            "duration_seconds": 4.0,
            "unit_count": 1,
            "resources_start": resources,
            "resources_end": resources,
        },
        {
            "phase": "solver_execution",
            "duration_seconds": 2.0,
            "unit_count": 10,
            "resources_start": resources,
            "resources_end": resources,
        },
        {
            "phase": "lean_reconstruction",
            "duration_seconds": 2.0,
            "unit_count": 8,
            "resources_start": resources,
            "resources_end": resources,
        },
        {
            "phase": "codex_queue_wait",
            "duration_seconds": 1.0,
            "unit_count": 1,
            "resources_start": resources,
            "resources_end": resources,
        },
    ]
    return {
        "benchmark_profile": ParallelismProfile(name=profile_name).to_dict(),
        "benchmark_cache_state": cache_state,
        "benchmark_elapsed_seconds": 20.0,
        "benchmark_completed_units": 30,
        "benchmark_quality_metrics": _quality(),
        "codex_main_apply_count": 2,
        "program_synthesis_transient_failure_rate": 0.02,
        "runtime_telemetry": {
            "cache_hit_rate": 0.0 if cache_state == "cold" else 0.9,
            "spans": spans,
        },
        "leanstral_batch_telemetry": {
            "dispatched_item_count": 8,
            "formed_batch_count": 1,
            "batch_sizes": [8],
        },
    }


def _family_metrics() -> dict[str, dict[str, Any]]:
    return {
        family: {
            "baseline": {
                "compiler_ir_cosine": 0.80,
                "source_copy_penalty": 0.08,
                "hammer_proof_success_rate": 0.88,
                "hammer_reconstruction_success_rate": 0.86,
                "queue_lag_p95_seconds": 20.0,
            },
            "candidate": {
                "compiler_ir_cosine": 0.81,
                "source_copy_penalty": 0.07,
                "hammer_proof_success_rate": 0.89,
                "hammer_reconstruction_success_rate": 0.87,
                "queue_lag_p95_seconds": 18.0,
            },
            "semantic_regression": False,
            "provenance_regression": False,
            "anti_copy_regression": False,
            "hammer_proof_regression": False,
            "lean_reconstruction_regression": False,
            "process_lifecycle_regression": False,
            "queue_lag_regression": False,
        }
        for family in LEGAL_IR_VIEW_FAMILIES
    }


def _lineage(index: int, stage: str) -> dict[str, str]:
    return {
        "rollout_id": "evidence-driven-unit",
        "stage": stage,
        "baseline_digest": f"sha256:{index + 1:064x}",
        "input_digest": f"sha256:{index + 11:064x}",
        "output_digest": f"sha256:{index + 21:064x}",
        "promotion_revision": f"revision-{index}",
        "produced_by": "hammer_leanstral_rollout_gate.py",
    }


def _snapshots() -> list[dict[str, Any]]:
    stages = (
        RolloutStageSpec("short_smoke", 600),
        RolloutStageSpec("one_hour_hparam", 3600),
        RolloutStageSpec("eight_hour_canary", 28800),
        RolloutStageSpec("twenty_four_hour_production", 86400),
    )
    result: list[dict[str, Any]] = []
    for index, stage in enumerate(stages, start=1):
        result.append(
            {
                "stage": stage.name,
                "duration_seconds": stage.duration_seconds,
                "elapsed_seconds": stage.duration_seconds,
                "snapshot_complete": True,
                "status": "succeeded",
                "managed_processes": [
                    {
                        "name": f"{stage.name}-supervisor",
                        "pid": 5000 + index,
                        "status": "exited",
                        "exit_code": 0,
                        "orphaned": False,
                    }
                ],
                "family_metrics": _family_metrics(),
                "trusted_feedback": {
                    "trusted_count": index,
                    "autoencoder_received_count": index,
                    "source_digest": f"sha256:feedback-{index}",
                    "autoencoder_source_digest": f"sha256:feedback-{index}",
                },
                "promotion_lineage": _lineage(index, stage.name),
                "queue_lag": {"p95_seconds": 18.0},
                "accepted_patches": 2 * index,
                "wall_clock_seconds": 600.0,
                "rollback_evidence": {
                    "artifact_path": f"workspace/rollout/{stage.name}/rollback.json",
                    "sha256": f"{index + 31:064x}",
                    "baseline_revision": f"baseline-{index}",
                    "restorable": True,
                },
                "promotion_thresholds": {
                    "projection_p95_seconds": {
                        "baseline": 100.0,
                        "candidate": 55.0,
                    },
                    "task_to_accepted_patch_rate": {
                        "baseline": 0.50,
                        "candidate": 0.62,
                    },
                    "state_to_merged_patch_lag_seconds": {
                        "baseline": 1000.0,
                        "candidate": 700.0,
                    },
                },
            }
        )
    return result


def test_benchmark_publishes_matched_cold_warm_baseline_and_complete_contract() -> None:
    trial = aggregate_pipeline_summaries(
        [_summary("cold"), _summary("warm")],
        ParallelismProfile(name="fixed_baseline"),
    )
    document = benchmark_document([trial], dry_run=False)

    assert document["dry_run"] is False
    assert {"cold_cache_throughput_per_hour", "warm_cache_throughput_per_hour"} <= set(
        document["trials"][0]["metrics"]
    )
    assert document["trials"][0]["metrics"]["cold_cache_hit_rate"] == 0.0
    assert document["trials"][0]["metrics"]["warm_cache_hit_rate"] == pytest.approx(0.9)
    assert canonical_digest(
        {key: value for key, value in document.items() if key != "evidence_digest"}
    ) == document["evidence_digest"]


def test_dry_run_autotune_evidence_meets_projection_p95_and_resource_gates() -> None:
    trials = dry_run_trials()
    result = tune_benchmark_trials(trials)
    selected = result.selected
    baseline = result.baseline
    projection_before = baseline.metrics.phase_latency["projection_training"].p95_seconds
    projection_after = selected.metrics.phase_latency["projection_training"].p95_seconds

    assert result.promoted is True
    assert selected.profile.name == "balanced_dgx_spark"
    assert (projection_before - projection_after) / projection_before >= 0.40
    assert selected.metrics.gpu_telemetry_known is True
    assert selected.metrics.swap_used_bytes_peak == 0
    assert selected.profile.trainer_count == 1


def test_faster_candidate_with_hard_quality_regression_is_never_promoted() -> None:
    baseline, candidate, _ = dry_run_trials()
    regressing_quality = dict(candidate.metrics.quality_metrics)
    regressing_quality["source_copy_penalty"] = (
        baseline.metrics.quality_metrics["source_copy_penalty"] + 0.01
    )
    regressing = BenchmarkTrial(
        candidate.profile,
        replace(candidate.metrics, quality_metrics=regressing_quality),
    )

    result = tune_benchmark_trials([baseline, regressing])

    assert result.promoted is False
    assert result.selected.profile.name == "fixed_baseline"
    assert any(
        "quality_regression:source_copy_penalty" in violation
        for evaluation in result.evaluations
        for violation in evaluation.violations
    )


def test_staged_gate_accepts_complete_evidence_driven_promotion() -> None:
    result = staged_rollout_gate(_snapshots())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["schema_version"] == STAGED_ROLLOUT_SCHEMA_VERSION
    assert result.metrics["completed_stages"] == [
        "short_smoke",
        "one_hour_hparam",
        "eight_hour_canary",
        "twenty_four_hour_production",
    ]
    assert result.metrics["trusted_feedback_reached_autoencoder"] is True
    assert result.metrics["promotion_thresholds"]["projection_p95_reduction"][
        "observed"
    ] == pytest.approx(0.45)


@pytest.mark.parametrize(
    ("path", "value", "failure_prefix"),
    [
        (
            ("promotion_thresholds", "projection_p95_seconds", "candidate"),
            61.0,
            "projection_p95_reduction_below_threshold",
        ),
        (
            ("promotion_thresholds", "task_to_accepted_patch_rate", "candidate"),
            0.59,
            "task_to_accepted_patch_rate_improvement_below_threshold",
        ),
        (
            ("promotion_thresholds", "state_to_merged_patch_lag_seconds", "candidate"),
            760.0,
            "state_to_merged_patch_lag_reduction_below_threshold",
        ),
    ],
)
def test_staged_gate_blocks_promotion_when_required_final_threshold_regresses(
    path: tuple[str, str, str],
    value: float,
    failure_prefix: str,
) -> None:
    snapshots = _snapshots()
    target = snapshots[-1]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert any(item.startswith(f"{failure_prefix}:twenty_four_hour_production") for item in result.failures)


def test_staged_gate_cli_persists_complete_lineage_and_threshold_metrics(tmp_path: Path) -> None:
    manifest = tmp_path / "rollout.json"
    decision_path = tmp_path / "decision.json"
    manifest.write_text(
        json.dumps({"schema_version": STAGED_ROLLOUT_SCHEMA_VERSION, "snapshots": _snapshots()}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
            "staged-gate",
            "--snapshot-path",
            str(manifest),
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
    assert len(decision["snapshot_sha256"]) == 64
    assert set(decision["metrics"]["promotion_lineage"]) == {
        "short_smoke",
        "one_hour_hparam",
        "eight_hour_canary",
        "twenty_four_hour_production",
    }
    assert decision["metrics"]["promotion_thresholds"][
        "state_to_merged_patch_lag_reduction"
    ]["observed"] == pytest.approx(0.30)


def test_staged_gate_does_not_mutate_promotion_evidence() -> None:
    snapshots = _snapshots()
    original = deepcopy(snapshots)

    staged_rollout_gate(snapshots, StagedRolloutConfig())

    assert snapshots == original


def test_optimization_report_documents_evidence_and_promotion_contract() -> None:
    text = REPORT.read_text(encoding="utf-8")

    assert "PORTAL-LIR-HAMMER-072" in text
    assert "matched cold/warm baseline" in text
    assert "one-hour" in text
    assert "eight-hour canary" in text
    assert "twenty-four-hour production" in text
    assert "projection p95" in text
    assert "task-to-accepted-patch" in text
    assert "state-to-merged-patch" in text
