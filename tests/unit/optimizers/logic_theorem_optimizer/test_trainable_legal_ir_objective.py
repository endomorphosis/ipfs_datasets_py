"""Regression tests for the trainable LegalIR objective surface."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    LegalIRProofFeedbackRecord,
    ProofFeedbackPartitionPolicy,
    ProofFeedbackVersions,
)
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
    assert "legal_ir:legal_ir_view_cross_entropy_loss" in report[
        "evaluated_objective"
    ]["selected_metric_names"]
    first_attempt = report["epoch_reports"][0]["candidate_reports"][0][
        "attempt_reports"
    ][0]
    assert first_attempt["trainable_legal_ir_head_norms"]["finite"] is True
    assert set(first_attempt["gradient_norms_by_head"]) <= set(
        first_attempt["update_norms_by_head"]
    )
    assert after.legal_ir_losses["legal_ir_view_cross_entropy_loss"] <= (
        before.legal_ir_losses["legal_ir_view_cross_entropy_loss"]
    )


def test_projection_update_reports_compiler_semantic_slot_and_decompiler_norms() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552-trainable-head-families",
        text=(
            "The agency must approve the application unless the applicant fails "
            "to provide notice before final action."
        ),
    )
    target = SimpleNamespace(
        losses={
            "legal_ir_multiview_total_loss": 0.05,
            "hammer_proof_failure_ratio": 0.0,
            "round_trip_structural_reconstruction_loss": 0.0,
        },
        view_distribution={
            "deontic.ir": 0.65,
            "TDFOL.prover": 0.25,
            "modal.frame_logic": 0.10,
        },
        document=SimpleNamespace(canonical_hash=lambda: "trainable-head-family-target"),
    )
    autoencoder = AdaptiveModalAutoencoder(
        decompiler_plan_legal_ir_view_logit_scale=1.0,
        family_semantic_slot_legal_ir_view_logit_scale=1.0,
        semantic_slot_legal_ir_view_logit_scale=1.0,
    )
    autoencoder.evaluate(
        [sample],
        legal_ir_targets={sample.sample_id: target},
        use_sample_memory=False,
    )

    report = autoencoder._apply_projection_update_batch(
        [sample],
        update_targets=("legal_ir_view_logits",),
        learning_rate=0.25,
        l2_regularization=0.0,
        update_backend="native",
    )

    assert report["finite"] is True
    assert report["nonzero_update"] is True
    assert report["update_norms_by_head"]["legal_ir_view_logits"] > 0.0
    assert report["update_norms_by_head"]["semantic_slot_legal_ir_view_logits"] > 0.0
    assert report["update_norms_by_head"]["decompiler_plan_legal_ir_view_logits"] > 0.0
    assert report["head_family_update_norms"]["compiler_facing_legal_ir_view"] > 0.0
    assert report["head_family_update_norms"]["semantic_slot"] > 0.0
    assert report["head_family_update_norms"]["decompiler"] > 0.0
    assert report["update_norms_by_family"]["deontic"] > 0.0
    assert autoencoder.state.family_logits == {}


def test_proof_head_training_reports_finite_nonzero_proof_norms() -> None:
    versions = ProofFeedbackVersions(
        compiler_version="trainable-proof-norms-v1",
        solver_toolchain_version="z3-proof-norms-v1",
        lean_toolchain_version="lean-proof-norms-v1",
        theorem_registry_version="proof-norms-theorems-v1",
    )
    record = LegalIRProofFeedbackRecord.create(
        obligation_id="proof-norms-obligation",
        obligation_type="exception_scope",
        legal_ir_view="deontic.ir",
        semantic_family="conditional_normative",
        semantic_slots={"exception": "present", "condition": "single"},
        selected_premise_families=("theorem_template",),
        route_availability={"deterministic_contract": True},
        route_statuses={"deterministic_contract": "passed"},
        backend_outcomes={"z3": "proved"},
        deterministic_trusted=True,
        evidence_ids=("proof-norms-evidence",),
        receipt_ids=("proof-norms-receipt",),
        partition_key="proof-norms-obligation",
        partition_policy=ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
        versions=versions,
    )
    autoencoder = AdaptiveModalAutoencoder()

    report = autoencoder.train_proof_auxiliary_heads(
        [record],
        expected_versions=versions,
        learning_rate=0.2,
    )

    assert report["applied_count"] == 1
    assert report["trainable_legal_ir_head_norms"]["finite"] is True
    assert report["trainable_legal_ir_head_norms"]["nonzero_update"] is True
    assert report["update_norms_by_head"]["proof_auxiliary_head_logits"] > 0.0
    assert report["head_family_update_norms"]["proof"] > 0.0
