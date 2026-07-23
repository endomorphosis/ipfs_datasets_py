"""Fail-closed gates for the complete Hammer/Leanstral rollout sequence."""

from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    LEGAL_IR_VIEW_FAMILIES,
    STAGED_ROLLOUT_STAGES,
    RolloutStageSpec,
    StagedRolloutConfig,
    staged_rollout_gate,
)


EXPECTED_STAGES = (
    ("short_smoke", 10 * 60),
    ("one_hour_hparam", 60 * 60),
    ("eight_hour_canary", 8 * 60 * 60),
    ("twenty_four_hour_production", 24 * 60 * 60),
)
ROOT = Path(__file__).resolve().parents[4]
ROLLOUT_LAUNCHER = ROOT / "scripts" / "ops" / "legal_ir" / "run_hammer_leanstral_hparam.sh"
HPARAM_HELPER = ROOT / "scripts" / "ops" / "logic" / "run_hparam_then_8h.sh"


def _clean_family_metrics() -> dict[str, dict[str, bool]]:
    return {
        family: {
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


def _clean_snapshots() -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for index, (stage, duration_seconds) in enumerate(EXPECTED_STAGES, start=1):
        digest = f"sha256:trusted-feedback-{index}"
        snapshots.append(
            {
                "stage": stage,
                "duration_seconds": duration_seconds,
                # Promotion is based on measured wall time, not a requested duration.
                "elapsed_seconds": duration_seconds,
                "snapshot_complete": True,
                "status": "succeeded",
                "managed_processes": [
                    {
                        "name": "paired-hammer-leanstral",
                        "pid": 4100 + index,
                        "status": "exited",
                        "exit_code": 0,
                        "orphaned": False,
                    },
                    {
                        "name": "snapshot-evaluator",
                        "pid": 4200 + index,
                        "status": "exited",
                        "exit_code": 0,
                        "orphaned": False,
                    },
                ],
                "family_metrics": _clean_family_metrics(),
                "trusted_feedback": {
                    "trusted_count": index,
                    "autoencoder_received_count": index,
                    "source_digest": digest,
                    "autoencoder_source_digest": digest,
                },
                "promotion_lineage": {
                    "rollout_id": "unit-rollout",
                    "stage": stage,
                    "baseline_digest": f"sha256:{index:064x}",
                    "input_digest": f"sha256:{index + 10:064x}",
                    "output_digest": f"sha256:{index + 20:064x}",
                    "promotion_revision": f"revision-{index}",
                    "produced_by": "unit-test",
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
                # Every stage sustains twelve accepted patches per measured hour.
                "accepted_patches": 2 * index * duration_seconds // 600 // index,
                "wall_clock_seconds": duration_seconds,
                "queue_lag": {"p95_seconds": 10.0},
                "rollback_evidence": {
                    "artifact_path": f"workspace/rollout/{stage}/rollback.json",
                    "sha256": f"{index:064x}",
                    "baseline_revision": f"baseline-{index}",
                    "restorable": True,
                },
            }
        )
    return snapshots


def _failure_has(result: Any, prefix: str) -> bool:
    return any(str(failure).startswith(prefix) for failure in result.failures)


def test_staged_rollout_contract_has_strict_order_and_durations() -> None:
    assert isinstance(STAGED_ROLLOUT_STAGES, tuple)
    assert all(isinstance(stage, RolloutStageSpec) for stage in STAGED_ROLLOUT_STAGES)
    assert tuple(
        (stage.name, stage.duration_seconds) for stage in STAGED_ROLLOUT_STAGES
    ) == EXPECTED_STAGES


def test_staged_rollout_accepts_complete_non_regressing_sequence() -> None:
    result = staged_rollout_gate(_clean_snapshots())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["completed_stages"] == [name for name, _ in EXPECTED_STAGES]
    assert result.metrics["accepted_patches_per_hour"] == pytest.approx(
        {name: 12.0 for name, _ in EXPECTED_STAGES}
    )
    assert set(result.metrics["rollback_evidence"]) == {
        name for name, _ in EXPECTED_STAGES
    }
    assert result.metrics["trusted_feedback_reached_autoencoder"] is True


@pytest.mark.parametrize(
    ("mutate", "failure_prefix"),
    [
        (
            lambda snapshots: snapshots.pop(1),
            "stage_sequence",
        ),
        (
            lambda snapshots: snapshots.__setitem__(
                1,
                {**snapshots[1], "stage": "eight_hour_canary"},
            ),
            "stage_sequence",
        ),
        (
            lambda snapshots: snapshots[1].update(elapsed_seconds=3599),
            "stage_duration:one_hour_hparam",
        ),
        (
            lambda snapshots: snapshots[2].update(duration_seconds=86400),
            "stage_duration:eight_hour_canary",
        ),
    ],
)
def test_staged_rollout_rejects_missing_reordered_or_short_stages(
    mutate: Callable[[list[dict[str, Any]]], object],
    failure_prefix: str,
) -> None:
    snapshots = _clean_snapshots()
    mutate(snapshots)

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(result, failure_prefix)


@pytest.mark.parametrize("complete_value", [False, None])
def test_staged_rollout_fails_closed_on_incomplete_snapshot(
    complete_value: bool | None,
) -> None:
    snapshots = _clean_snapshots()
    if complete_value is None:
        snapshots[2].pop("snapshot_complete")
    else:
        snapshots[2]["snapshot_complete"] = complete_value

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(result, "incomplete_snapshot:eight_hour_canary")


@pytest.mark.parametrize(
    "process_update",
    [
        {"orphaned": True},
        {"status": "running"},
        {"status": "exited", "exit_code": 9},
    ],
)
def test_staged_rollout_fails_closed_on_orphaned_or_failed_managed_process(
    process_update: dict[str, object],
) -> None:
    snapshots = _clean_snapshots()
    snapshots[3]["managed_processes"][0].update(process_update)

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(
        result,
        "orphaned_managed_process:twenty_four_hour_production",
    ) or _failure_has(
        result,
        "managed_process_failure:twenty_four_hour_production",
    )


@pytest.mark.parametrize(
    "regression_key",
    [
        "semantic_regression",
        "provenance_regression",
        "anti_copy_regression",
        "hammer_proof_regression",
        "lean_reconstruction_regression",
        "process_lifecycle_regression",
        "queue_lag_regression",
    ],
)
def test_staged_rollout_rejects_every_hard_per_family_regression(
    regression_key: str,
) -> None:
    snapshots = _clean_snapshots()
    snapshots[2]["family_metrics"]["deontic"][regression_key] = True

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(
        result,
        f"{regression_key}:eight_hour_canary:deontic",
    )


@pytest.mark.parametrize(
    "feedback",
    [
        {},
        {
            "trusted_count": 2,
            "autoencoder_received_count": 0,
            "source_digest": "sha256:source",
            "autoencoder_source_digest": "sha256:source",
        },
        {
            "trusted_count": 2,
            "autoencoder_received_count": 2,
            "source_digest": "sha256:source",
            "autoencoder_source_digest": "sha256:different",
        },
    ],
)
def test_staged_rollout_requires_trusted_feedback_to_reach_autoencoder(
    feedback: dict[str, object],
) -> None:
    snapshots = _clean_snapshots()
    snapshots[1]["trusted_feedback"] = feedback

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(result, "trusted_feedback_not_applied:one_hour_hparam")


def test_productivity_uses_actual_wall_clock_and_must_not_regress() -> None:
    snapshots = _clean_snapshots()
    # The requested duration and raw count look healthy in isolation, but actual
    # wall time reveals a 50% throughput regression from the canary.
    snapshots[3].update(accepted_patches=144, wall_clock_seconds=24 * 60 * 60)

    result = staged_rollout_gate(
        snapshots,
        StagedRolloutConfig(max_accepted_patches_per_hour_regression=0.0),
    )

    assert result.accepted is False
    assert result.metrics["accepted_patches_per_hour"][
        "twenty_four_hour_production"
    ] == pytest.approx(6.0)
    assert _failure_has(
        result,
        "accepted_patches_per_hour_regression:twenty_four_hour_production",
    )


def test_observed_queue_lag_regression_is_a_hard_failure() -> None:
    snapshots = _clean_snapshots()
    snapshots[3]["queue_lag"]["p95_seconds"] = 10.01

    result = staged_rollout_gate(
        snapshots,
        StagedRolloutConfig(max_queue_lag_regression=0.0),
    )

    assert result.accepted is False
    assert _failure_has(
        result,
        "queue_lag_regression:twenty_four_hour_production",
    )


@pytest.mark.parametrize(
    ("mutate", "failure_prefix"),
    [
        (
            lambda snapshots: snapshots[1].pop("promotion_lineage"),
            "promotion_lineage_missing:one_hour_hparam",
        ),
        (
            lambda snapshots: snapshots[2]["promotion_lineage"].update(
                output_digest="sha256:not-a-digest"
            ),
            "promotion_lineage_incomplete:eight_hour_canary:output_digest",
        ),
        (
            lambda snapshots: snapshots[3]["promotion_thresholds"][
                "projection_p95_seconds"
            ].update(candidate=61.0),
            "projection_p95_reduction_below_threshold:twenty_four_hour_production",
        ),
        (
            lambda snapshots: snapshots[3]["promotion_thresholds"][
                "task_to_accepted_patch_rate"
            ].update(candidate=0.59),
            "task_to_accepted_patch_rate_improvement_below_threshold:twenty_four_hour_production",
        ),
        (
            lambda snapshots: snapshots[3]["promotion_thresholds"][
                "state_to_merged_patch_lag_seconds"
            ].update(candidate=760.0),
            "state_to_merged_patch_lag_reduction_below_threshold:twenty_four_hour_production",
        ),
    ],
)
def test_staged_rollout_requires_promotion_lineage_and_final_improvement_thresholds(
    mutate: Callable[[list[dict[str, Any]]], object],
    failure_prefix: str,
) -> None:
    snapshots = _clean_snapshots()
    mutate(snapshots)

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(result, failure_prefix)


@pytest.mark.parametrize(
    "rollback_evidence",
    [
        {},
        {
            "artifact_path": "workspace/rollout/canary/rollback.json",
            "sha256": "not-a-digest",
            "baseline_revision": "baseline-3",
            "restorable": True,
        },
        {
            "artifact_path": "workspace/rollout/canary/rollback.json",
            "sha256": "3" * 64,
            "baseline_revision": "baseline-3",
            "restorable": False,
        },
    ],
)
def test_staged_rollout_requires_durable_restorable_rollback_evidence(
    rollback_evidence: dict[str, object],
) -> None:
    snapshots = _clean_snapshots()
    snapshots[2]["rollback_evidence"] = rollback_evidence

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(result, "rollback_evidence_missing:eight_hour_canary") or _failure_has(
        result,
        "rollback_evidence_invalid:eight_hour_canary",
    )


def test_staged_rollout_does_not_mutate_operator_evidence() -> None:
    snapshots = _clean_snapshots()
    original = deepcopy(snapshots)

    staged_rollout_gate(snapshots)

    assert snapshots == original


def test_staged_rollout_recomputes_paired_metrics_instead_of_trusting_flags() -> None:
    snapshots = _clean_snapshots()
    family = snapshots[2]["family_metrics"]["deontic"]
    family["baseline"] = {"hammer_proof_success_rate": 0.9}
    family["candidate"] = {"hammer_proof_success_rate": 0.8}
    family["hammer_proof_regression"] = False

    result = staged_rollout_gate(snapshots)

    assert result.accepted is False
    assert _failure_has(result, "hammer_proof_regression:eight_hour_canary:deontic")


def test_staged_gate_cli_persists_an_accepted_prefix_decision(tmp_path: Path) -> None:
    manifest = tmp_path / "prefix.json"
    decision = tmp_path / "decision.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "legal-ir-hammer-leanstral-rollout-v1",
                "rollout_id": "test-prefix",
                "snapshots": _clean_snapshots()[:2],
            }
        ),
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
            str(decision),
            "--allow-prefix",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    stored = json.loads(decision.read_text(encoding="utf-8"))
    assert stored["accepted"] is True
    assert stored["metrics"]["next_stage"] == "eight_hour_canary"
    assert len(stored["snapshot_sha256"]) == 64


def test_hparam_promotion_hook_runs_before_canary_process() -> None:
    helper = HPARAM_HELPER.read_text(encoding="utf-8")
    launcher = ROLLOUT_LAUNCHER.read_text(encoding="utf-8")

    assert helper.index('"${RUN_HPARAM_BEFORE_FINAL_FUNCTION}" "${best_run_id}"') < helper.index(
        '"${PYTHON_BIN}" -m "${MODULE}" "${final_args[@]}"'
    )
    assert "gate_completed_hparam_sweep" in launcher
    assert "RUN_HPARAM_BEFORE_FINAL_FUNCTION=gate_completed_hparam_sweep" in launcher
    assert launcher.index("append_snapshot one_hour_hparam") < launcher.index(
        "append_snapshot eight_hour_canary"
    )
