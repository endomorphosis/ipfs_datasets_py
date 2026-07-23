from __future__ import annotations

from scripts.ops.legal_ir.evaluate_autoencoder_feature_transfer import (
    gate_transfer_metrics,
)


def test_gate_accepts_strict_multiobjective_improvement() -> None:
    target = {
        "autoencoder_cross_entropy_loss": 1.05,
        "autoencoder_cosine_similarity": 0.83,
        "ir_view_cross_entropy_loss": 1.79,
        "ir_view_cosine_similarity": 0.78,
    }
    candidate = {
        "autoencoder_cross_entropy_loss": 1.049,
        "autoencoder_cosine_similarity": 0.83,
        "ir_view_cross_entropy_loss": 1.789,
        "ir_view_cosine_similarity": 0.781,
    }
    target_fidelity = {
        "embedding_cosine_similarity": 0.95,
        "family_kl_excess_loss": 0.01,
        "view_cosine_similarity": 0.96,
    }
    candidate_fidelity = {
        "embedding_cosine_similarity": 0.95,
        "family_kl_excess_loss": 0.009,
        "view_cosine_similarity": 0.97,
    }

    gate = gate_transfer_metrics(
        target,
        candidate,
        target_fidelity,
        candidate_fidelity,
    )

    assert gate["accepted"] is True
    assert all(gate["checks"].values())


def test_gate_rejects_ir_ce_or_teacher_fidelity_regression() -> None:
    target = {
        "autoencoder_cross_entropy_loss": 1.05,
        "autoencoder_cosine_similarity": 0.83,
        "ir_view_cross_entropy_loss": 1.79,
        "ir_view_cosine_similarity": 0.78,
    }
    candidate = {
        **target,
        "ir_view_cross_entropy_loss": 1.790001,
    }
    target_fidelity = {
        "family_kl_excess_loss": 0.01,
    }
    candidate_fidelity = {
        "family_kl_excess_loss": 0.011,
    }

    gate = gate_transfer_metrics(
        target,
        candidate,
        target_fidelity,
        candidate_fidelity,
    )

    assert gate["accepted"] is False
    assert gate["checks"]["ground:ir_view_cross_entropy_loss"] is False
    assert gate["checks"]["teacher_fidelity:family_kl_excess_loss"] is False
