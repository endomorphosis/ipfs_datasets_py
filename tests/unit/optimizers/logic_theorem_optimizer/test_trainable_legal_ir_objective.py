"""Regression tests for the trainable LegalIR objective surface."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
    AutoencoderEvaluation,
    _evaluation_objective_for_training,
    _legal_ir_objective_component,
)


def test_legal_ir_objective_component_tracks_view_family_and_proof_losses() -> None:
    base = _legal_ir_objective_component(
        {
            "legal_ir_multiview_total_loss": 0.05,
            "legal_ir_view_cross_entropy_excess_loss": 0.03,
            "legal_ir_view_family_cross_entropy_excess_loss": 0.03,
            "legal_ir_view_family_cosine_gap_loss": 0.02,
            "legal_ir_multiview_proof_failure_ratio": 0.0,
            "legal_ir_multiview_graph_failure_penalty": 0.0,
        }
    )
    worse = _legal_ir_objective_component(
        {
            "legal_ir_multiview_total_loss": 0.15,
            "legal_ir_view_cross_entropy_excess_loss": 0.09,
            "legal_ir_view_family_cross_entropy_excess_loss": 0.12,
            "legal_ir_view_family_cosine_gap_loss": 0.08,
            "legal_ir_multiview_proof_failure_ratio": 0.25,
            "legal_ir_multiview_graph_failure_penalty": 0.10,
        }
    )

    assert worse > base
    assert worse <= 6.0


def test_training_objective_can_weight_legal_ir_independently() -> None:
    evaluation = AutoencoderEvaluation(
        sample_count=1,
        embedding_cosine_similarity=0.90,
        cosine_loss=0.10,
        reconstruction_loss=0.20,
        cross_entropy_loss=0.30,
        cross_entropy_excess_loss=0.04,
        frame_ranking_loss=0.0,
        symbolic_validity_penalty=0.0,
        decoded_embeddings={},
        legal_ir_losses={
            "legal_ir_multiview_total_loss": 0.20,
            "legal_ir_view_cross_entropy_excess_loss": 0.30,
            "legal_ir_view_family_cosine_gap_loss": 0.10,
        },
    )

    without_legal = _evaluation_objective_for_training(evaluation, legal_ir=0.0)
    with_legal = _evaluation_objective_for_training(evaluation, legal_ir=2.0)

    assert with_legal > without_legal
    assert with_legal - without_legal == pytest.approx(
        2.0 * _legal_ir_objective_component(evaluation.legal_ir_losses)
    )


def test_generalizable_projection_trains_legal_ir_view_head_from_cached_targets() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552-trainable-legal-ir",
        text="The agency shall provide notice before the hearing.",
    )
    target = SimpleNamespace(
        losses={"legal_ir_multiview_total_loss": 0.05},
        view_distribution={
            "deontic.ir": 0.70,
            "TDFOL.prover": 0.20,
            "modal.frame_logic": 0.10,
        },
        document=SimpleNamespace(canonical_hash=lambda: "trainable-legal-ir-target"),
    )
    autoencoder = AdaptiveModalAutoencoder(compute_device="python")

    before = autoencoder.evaluate([sample], legal_ir_targets={sample.sample_id: target})
    report = autoencoder.train_generalizable_projection(
        [sample],
        validation_samples=[sample],
        legal_ir_targets={sample.sample_id: target},
        epochs=1,
        learning_rate=0.2,
        max_line_search_attempts=1,
        objective_cross_entropy_weight=0.0,
        objective_reconstruction_weight=0.0,
        objective_cosine_gap_weight=0.0,
        objective_legal_ir_weight=1.0,
        projection_update_backend="native",
    )
    after = autoencoder.evaluate([sample], legal_ir_targets={sample.sample_id: target})

    assert report["sample_memory_used"] is False
    assert "legal_ir_view_global_logits" in report["candidate_update_order"]
    assert after.legal_ir_losses["legal_ir_view_cross_entropy_loss"] <= (
        before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )
