"""Tests for hammer-aware Legal IR objective guardrails."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as runner,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AutoencoderEvaluation,
    hammer_guidance_metric_block,
    _evaluation_regressions_for_training,
    _legal_ir_objective_component,
)


def _artifact(
    guidance_id: str,
    *,
    legal_ir_view: str = "deontic.ir",
    proved: bool = True,
    proof_checked: bool = True,
    selected_premises: tuple[str, ...] = ("premise.exception_scope",),
    source_copy_rejected: bool = False,
    trusted: bool = True,
) -> dict:
    return {
        "backend_statuses": {"z3": "proved" if proved else "failed"},
        "failure_reason": "" if proved else "no_backend_proof",
        "goal_name": guidance_id,
        "goal_statement_hash": f"{guidance_id}-hash",
        "guidance_id": guidance_id,
        "legal_ir_view": legal_ir_view,
        "logic_family": legal_ir_view.split(".", 1)[0],
        "obligation_id": guidance_id,
        "premise_views": [legal_ir_view],
        "proof_checked": proof_checked,
        "proof_obligation_ids": [guidance_id],
        "proved": proved,
        "reconstruction_status": "verified" if proof_checked else "kernel_rejected",
        "rejection_reasons": ["source_copy_rejected"] if source_copy_rejected else [],
        "schema_version": "legal-ir-hammer-guidance-v1",
        "selected_premises": list(selected_premises),
        "source": "hammer_verified_guidance",
        "source_copy_rejected": source_copy_rejected,
        "target_component": legal_ir_view,
        "target_metrics": ["hammer_proof_success_rate"],
        "trusted": trusted,
        "winner_backend": "z3" if proved else "",
    }


def _evaluation(*, hammer_proof_success_rate: float) -> AutoencoderEvaluation:
    return AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.9,
        cosine_loss=0.1,
        reconstruction_loss=0.1,
        cross_entropy_loss=0.3,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
        legal_ir_losses={
            "hammer_proof_success_rate": hammer_proof_success_rate,
            "symbolic_validity_penalty": 1.0 - hammer_proof_success_rate,
        },
    )


def test_hammer_guidance_metric_block_reports_rates_and_per_view_validity() -> None:
    metrics = hammer_guidance_metric_block(
        {
            "hammer_guidance_artifacts": [
                _artifact("obl-1", legal_ir_view="deontic.ir"),
                _artifact(
                    "obl-2",
                    legal_ir_view="TDFOL.prover",
                    proved=False,
                    proof_checked=False,
                    selected_premises=(),
                    source_copy_rejected=True,
                    trusted=False,
                ),
            ]
        }
    )

    assert metrics["hammer_artifact_count"] == 2
    assert metrics["hammer_proof_success_rate"] == pytest.approx(0.5)
    assert metrics["hammer_reconstruction_success_rate"] == pytest.approx(0.5)
    assert metrics["hammer_premise_selection_hit_rate"] == pytest.approx(0.5)
    assert metrics["hammer_proof_failure_ratio"] == pytest.approx(0.5)
    assert metrics["source_copy_penalty"] == pytest.approx(0.5)
    assert metrics["symbolic_validity_penalty"] == pytest.approx(0.5)
    assert metrics["symbolic_validity_by_view"]["deontic.ir"][
        "symbolic_validity_success_rate"
    ] == pytest.approx(1.0)
    assert metrics["symbolic_validity_by_view"]["TDFOL.prover"][
        "symbolic_validity_penalty"
    ] == pytest.approx(1.0)


def test_codex_target_metric_gate_rejects_hammer_and_source_copy_regressions() -> None:
    before = {
        "metrics": {
            "compiler_ir_cosine_similarity": 0.40,
            "compiler_ir_hammer_proof_success_rate": 1.0,
            "compiler_ir_source_copy_reward_hack_penalty": 0.0,
            "compiler_ir_symbolic_validity_penalty": 0.0,
        },
        "status": "measured",
        "target_metrics": [
            "compiler_ir_cosine_similarity",
            "compiler_ir_hammer_proof_success_rate",
            "compiler_ir_source_copy_reward_hack_penalty",
            "compiler_ir_symbolic_validity_penalty",
        ],
    }
    after = {
        "metrics": {
            "compiler_ir_cosine_similarity": 0.60,
            "compiler_ir_hammer_proof_success_rate": 0.9,
            "compiler_ir_source_copy_reward_hack_penalty": 0.001,
            "compiler_ir_symbolic_validity_penalty": 0.01,
        },
        "status": "measured",
        "target_metrics": before["target_metrics"],
    }

    report = runner._codex_target_metric_validation_report(before=before, after=after)

    assert report["status"] == "regressed"
    assert report["objective_delta"] > 0.0
    assert report["regressed_metrics"] == [
        "compiler_ir_hammer_proof_success_rate",
        "compiler_ir_source_copy_reward_hack_penalty",
        "compiler_ir_symbolic_validity_penalty",
    ]
    assert report["tolerated_regressed_metrics"] == []


def test_training_objective_treats_hammer_success_rate_drop_as_regression() -> None:
    before = _evaluation(hammer_proof_success_rate=1.0)
    after = _evaluation(hammer_proof_success_rate=0.8)

    regressions = _evaluation_regressions_for_training(
        before,
        after,
        max_legal_ir_loss_regression=0.01,
    )

    assert regressions["legal_ir:hammer_proof_success_rate"] == pytest.approx(0.2)
    assert _legal_ir_objective_component(after.legal_ir_losses) > (
        _legal_ir_objective_component(before.legal_ir_losses)
    )
