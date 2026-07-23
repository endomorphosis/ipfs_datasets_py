"""Tests for hammer/Leanstral rollout gates and operator scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    RolloutGateConfig,
    hard_guardrail_metrics_csv,
    rollout_gate,
)


ROOT = Path(__file__).resolve().parents[4]
SMOKE_SCRIPT = ROOT / "scripts" / "ops" / "legal_ir" / "run_hammer_leanstral_smoke.sh"
HPARAM_SCRIPT = ROOT / "scripts" / "ops" / "legal_ir" / "run_hammer_leanstral_hparam.sh"
HPARAM_PIPELINE = ROOT / "scripts" / "ops" / "logic" / "run_hparam_then_8h.sh"


def _summary_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "cycles": 2,
        "latest_validation_ce_delta": 0.0,
        "latest_validation_cosine_delta": 0.0,
        "compiler_ir_validation_last_delta": {
            "compiler_ir_cross_entropy_loss": 0.0,
            "compiler_ir_cosine_similarity": 0.0,
        },
        "latest_compiler_ir_source_copy_reward_hack_penalty": 0.01,
        "latest_daemon_hammer_guidance": {
            "hammer_metrics": {
                "hammer_backend_unavailable_ratio": 0.0,
                "hammer_proof_success_rate": 1.0,
                "hammer_reconstruction_success_rate": 1.0,
            },
            "obligation_failure_count": 0,
            "runtime_failure_count": 0,
            "status": "completed",
        },
        "program_synthesis_claimed": 0,
        "program_synthesis_completed": 1,
        "program_synthesis_deduped_total": 0,
        "program_synthesis_pending": 0,
        "program_synthesis_seeded": 1,
        "status": "succeeded",
    }
    payload.update(overrides)
    return payload


def test_rollout_gate_accepts_clean_hammer_summary() -> None:
    result = rollout_gate(_summary_payload())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["hammer_report_present"] is True
    assert "source_copy_penalties" in result.metrics


@pytest.mark.parametrize(
    ("overrides", "failure_prefix"),
    [
        ({"latest_validation_ce_delta": 0.25}, "validation_ce_regression"),
        ({"latest_validation_cosine_delta": -0.25}, "validation_cosine_regression"),
        (
            {
                "compiler_ir_validation_last_delta": {
                    "compiler_ir_cross_entropy_loss": 0.25,
                    "compiler_ir_cosine_similarity": 0.0,
                },
            },
            "compiler_ir_ce_regression",
        ),
        ({"latest_compiler_ir_source_copy_reward_hack_penalty": 0.9}, "source_copy_penalty"),
        ({"latest_daemon_hammer_guidance": {}}, "missing_daemon_hammer_guidance_report"),
        ({"status": "failed"}, "summary_status_failed"),
        ({"latest_stop_reason": "target_metric_regression"}, "fatal_stop_reason"),
    ],
)
def test_rollout_gate_rejects_guardrail_failures(
    overrides: dict[str, object],
    failure_prefix: str,
) -> None:
    result = rollout_gate(_summary_payload(**overrides))

    assert result.accepted is False
    assert any(failure.startswith(failure_prefix) for failure in result.failures)


def test_rollout_gate_rejects_stalled_todo_generation_after_cycle() -> None:
    result = rollout_gate(
        _summary_payload(
            program_synthesis_claimed=0,
            program_synthesis_completed=0,
            program_synthesis_deduped_total=0,
            program_synthesis_pending=0,
            program_synthesis_seeded=0,
        )
    )

    assert result.accepted is False
    assert "todo_generation_stalled:no_program_synthesis_activity" in result.failures


def test_rollout_gate_reports_unavailable_backends_without_default_failure() -> None:
    summary = _summary_payload(
        latest_daemon_hammer_guidance={
            "hammer_metrics": {"hammer_backend_unavailable_ratio": 1.0},
            "status": "completed_no_hammer_artifacts",
        }
    )

    default_result = rollout_gate(summary)
    strict_result = rollout_gate(
        summary,
        RolloutGateConfig(
            require_available_hammer_backend=True,
            max_hammer_backend_unavailable_ratio=0.5,
        ),
    )

    assert default_result.accepted is True
    assert "all_hammer_backends_unavailable" in default_result.warnings
    assert strict_result.accepted is False
    assert any(
        failure.startswith("hammer_backend_unavailable_ratio")
        for failure in strict_result.failures
    )


def test_rollout_gate_cli_accepts_and_rejects_summary(tmp_path: Path) -> None:
    good_path = tmp_path / "good.summary"
    bad_path = tmp_path / "bad.summary"
    good_path.write_text(json.dumps(_summary_payload()), encoding="utf-8")
    bad_path.write_text(
        json.dumps(_summary_payload(latest_compiler_ir_source_copy_reward_hack_penalty=0.8)),
        encoding="utf-8",
    )

    good = subprocess.run(
        [
            os.environ.get("PYTHON_BIN", sys.executable),
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
            "gate",
            "--summary-path",
            str(good_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    bad = subprocess.run(
        [
            os.environ.get("PYTHON_BIN", sys.executable),
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
            "gate",
            "--summary-path",
            str(bad_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert good.returncode == 0
    assert bad.returncode == 1
    assert "source_copy_penalty" in bad.stdout


def test_rollout_scripts_dry_run_include_hammer_leanstral_gates() -> None:
    smoke = subprocess.run(
        [str(SMOKE_SCRIPT), "--dry-run", "--run-id", "dry-smoke"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    hparam = subprocess.run(
        [str(HPARAM_SCRIPT), "--dry-run", "--run-id", "dry-hparam"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    expected_metrics = hard_guardrail_metrics_csv()
    assert "--daemon-hammer-guidance-enabled true" in smoke.stdout
    assert "--leanstral-direct-guidance-projection-enabled true" in smoke.stdout
    assert "--leanstral-rule-gap-wait-seconds 180" in smoke.stdout
    assert "--autoencoder-device cuda" in smoke.stdout
    assert "--paired-leanstral-worker-enabled true" in smoke.stdout
    assert "--paired-leanstral-require-cuda true" in smoke.stdout
    smoke_script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "integrated_stack_verified" in smoke_script
    assert "Codex did not claim or execute queue work" in smoke_script
    assert "autoencoder did not receive Leanstral report in-cycle" in smoke_script
    assert "Hammer integration verification failed" in smoke_script
    assert f"gate_metrics={expected_metrics}" in smoke.stdout
    assert "summary_path=" in smoke.stdout
    assert "final_seconds=86400" in hparam.stdout
    assert "final_run_label=24h" in hparam.stdout
    assert "--daemon-hammer-guidance-enabled true" in hparam.stdout
    assert f"gate_metrics={expected_metrics}" in hparam.stdout
    assert "representation_gate_required=true" in smoke.stdout
    assert "representation_gate_require_successful=false" in smoke.stdout
    assert "representation_gate_require_complete_evidence=false" in smoke.stdout
    assert "representation_gate_required=true" in hparam.stdout
    assert "representation_gate_require_successful=true" in hparam.stdout
    assert "representation_gate_require_complete_evidence=true" in hparam.stdout
    assert (
        "summary_gate_module=scripts.ops.legal_ir.hammer_leanstral_rollout_gate"
        in hparam.stdout
    )

    pipeline = HPARAM_PIPELINE.read_text(encoding="utf-8")
    assert 'run_summary_gate "${summary_path}" "hparam_trial"' in pipeline
    assert 'run_summary_gate "${LOG_DIR}/${final_run_id}-autoencoder.summary"' in pipeline
