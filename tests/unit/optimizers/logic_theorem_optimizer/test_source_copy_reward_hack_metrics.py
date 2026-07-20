"""Metric and admission tests for adversarial source-copy replay pairs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as runner,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AutoencoderEvaluation,
    _evaluation_improved_for_training,
    _evaluation_objective_for_training,
    _evaluation_regressions_for_training,
)


ROOT = Path(__file__).resolve().parents[4]
FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "source_copy_reward_hack_replay.jsonl"
)


def _load_rollout_gate():
    module_name = "source_copy_reward_hack_rollout_gate_under_test"
    module_path = ROOT / "scripts" / "ops" / "legal_ir" / "hammer_leanstral_rollout_gate.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - repository invariant
        raise ImportError(f"cannot load rollout gate from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.rollout_gate


rollout_gate = _load_rollout_gate()


TARGET_METRICS = (
    "compiler_ir_cross_entropy_loss",
    "compiler_ir_cosine_similarity",
    "source_decompiled_text_embedding_cosine_similarity",
    "source_copy_reward_hack_penalty",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "hammer_reconstruction_success_rate",
    "round_trip_reconstruction_success_rate",
    "structural_text_reconstruction_loss",
)


def _records() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _target_packet(metrics: Mapping[str, float]) -> dict[str, Any]:
    return {
        "metrics": dict(metrics),
        "status": "measured",
        "target_metrics": list(TARGET_METRICS),
    }


def _evaluation(metrics: Mapping[str, float]) -> AutoencoderEvaluation:
    cosine = float(metrics["compiler_ir_cosine_similarity"])
    symbolic_success = float(metrics["symbolic_validity_success_rate"])
    legal_ir_losses = {
        "hammer_proof_success_rate": float(metrics["hammer_proof_success_rate"]),
        "hammer_reconstruction_success_rate": float(
            metrics["hammer_reconstruction_success_rate"]
        ),
        "round_trip_reconstruction_success_rate": float(
            metrics["round_trip_reconstruction_success_rate"]
        ),
        "round_trip_source_copy_guardrail_loss": float(
            metrics["source_copy_reward_hack_penalty"]
        ),
        "round_trip_structural_reconstruction_loss": float(
            metrics["structural_text_reconstruction_loss"]
        ),
        "source_copy_reward_hack_penalty": float(
            metrics["source_copy_reward_hack_penalty"]
        ),
        "symbolic_validity_penalty": max(0.0, 1.0 - symbolic_success),
        "symbolic_validity_success_rate": symbolic_success,
    }
    return AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=cosine,
        cosine_loss=max(0.0, 1.0 - cosine),
        reconstruction_loss=float(metrics["reconstruction_loss"]),
        cross_entropy_loss=float(metrics["compiler_ir_cross_entropy_loss"]),
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=max(0.0, 1.0 - symbolic_success),
        decoded_embeddings={},
        legal_ir_losses=legal_ir_losses,
    )


def _rollout_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    baseline = record["baseline"]["metrics"]
    candidate = record["candidate"]["metrics"]
    return {
        "cycles": 1,
        "latest_validation_ce_delta": (
            candidate["compiler_ir_cross_entropy_loss"]
            - baseline["compiler_ir_cross_entropy_loss"]
        ),
        "latest_validation_cosine_delta": (
            candidate["compiler_ir_cosine_similarity"]
            - baseline["compiler_ir_cosine_similarity"]
        ),
        "compiler_ir_validation_last_delta": {
            "compiler_ir_cross_entropy_loss": 0.0,
            "compiler_ir_cosine_similarity": (
                candidate["compiler_ir_cosine_similarity"]
                - baseline["compiler_ir_cosine_similarity"]
            ),
        },
        "latest_compiler_ir_source_copy_reward_hack_penalty": candidate[
            "source_copy_reward_hack_penalty"
        ],
        "latest_daemon_hammer_guidance": {
            "hammer_metrics": {
                "hammer_backend_unavailable_ratio": 0.0,
                "hammer_proof_success_rate": candidate["hammer_proof_success_rate"],
                "hammer_reconstruction_success_rate": candidate[
                    "hammer_reconstruction_success_rate"
                ],
                "symbolic_validity_success_rate": candidate[
                    "symbolic_validity_success_rate"
                ],
            },
            "obligation_failure_count": len(
                record["expected"]["failed_obligation_kinds"]
            ),
            "runtime_failure_count": 0,
            "status": "completed",
        },
        "program_synthesis_completed": 1,
        "status": "succeeded",
    }


@pytest.mark.parametrize("record", _records(), ids=lambda item: item["case_id"])
def test_hparam_scoring_cannot_trade_hard_guardrails_for_cosine(
    record: dict[str, Any],
) -> None:
    baseline = record["baseline"]["metrics"]
    candidate = record["candidate"]["metrics"]

    report = runner._codex_target_metric_validation_report(
        before=_target_packet(baseline),
        after=_target_packet(candidate),
    )

    assert report["metric_deltas"]["compiler_ir_cosine_similarity"] > 0.0
    assert report["metric_deltas"]["compiler_ir_cross_entropy_loss"] > 0.0
    assert report["objective_delta"] < 0.0
    assert report["status"] == "regressed"
    assert {
        "source_copy_reward_hack_penalty",
        "symbolic_validity_success_rate",
        "hammer_proof_success_rate",
        "hammer_reconstruction_success_rate",
    } <= set(report["hard_regressed_metrics"])
    assert report["tolerated_regressed_metrics"] == []


@pytest.mark.parametrize("record", _records(), ids=lambda item: item["case_id"])
def test_rollout_gate_rejects_copy_hack_despite_positive_cosine_delta(
    record: dict[str, Any],
) -> None:
    result = rollout_gate(_rollout_summary(record))

    assert result.metrics["latest_validation_cosine_delta"] > 0.0
    assert result.accepted is False
    assert any(
        failure.startswith("source_copy_penalty:") for failure in result.failures
    )


@pytest.mark.parametrize("record", _records(), ids=lambda item: item["case_id"])
def test_autoencoder_objective_and_training_gate_reject_cosine_reward_hack(
    record: dict[str, Any],
) -> None:
    before = _evaluation(record["baseline"]["metrics"])
    after = _evaluation(record["candidate"]["metrics"])

    regressions = _evaluation_regressions_for_training(
        before,
        after,
        max_legal_ir_loss_regression=0.0,
    )

    assert after.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert after.cross_entropy_loss < before.cross_entropy_loss
    assert _evaluation_objective_for_training(after) > (
        _evaluation_objective_for_training(before)
    )
    assert _evaluation_improved_for_training(
        before,
        after,
        max_legal_ir_loss_regression=0.0,
    ) is False
    assert "legal_ir:source_copy_reward_hack_penalty" in regressions
    assert "legal_ir:symbolic_validity_success_rate" in regressions
    assert "legal_ir:hammer_proof_success_rate" in regressions
