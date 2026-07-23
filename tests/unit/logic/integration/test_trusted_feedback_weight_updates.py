"""Production guard tests for trusted Hammer/Leanstral weight updates."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_learned_guidance import (
    TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION,
    evaluate_trusted_feedback_ablation,
)
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
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.trusted_feedback_trainer import (
    TRUSTED_FEEDBACK_TRAINER_SCHEMA_VERSION,
    TrustedFeedbackTrainer,
    TrustedFeedbackTrainerConfig,
    apply_trusted_feedback_weight_updates,
)


def _versions(compiler: str = "trusted-feedback-compiler-v1") -> ProofFeedbackVersions:
    return ProofFeedbackVersions(
        compiler_version=compiler,
        solver_toolchain_version="z3-trusted-feedback-v1",
        lean_toolchain_version="lean-trusted-feedback-v1",
        theorem_registry_version="trusted-feedback-theorems-v1",
    )


@pytest.fixture(scope="module")
def samples():
    train = build_us_code_sample(
        title="5",
        section="551-feedback-train",
        text="The agency shall publish notice unless a verified exception applies.",
    )
    holdout = build_us_code_sample(
        title="5",
        section="551-feedback-holdout",
        text="An officer may inspect a record after receiving approval.",
    )
    return train, holdout


def _ablation(train_id: str, holdout_id: str, *, improves: bool = True):
    return evaluate_trusted_feedback_ablation(
        {
            "holdout_id": "trusted-feedback-fixed-holdout-v1",
            "legal_ir_view_cross_entropy_loss": 0.8,
            "source_copy_penalty": 0.0,
            "symbolic_validity_success_rate": 1.0,
        },
        {
            "holdout_id": "trusted-feedback-fixed-holdout-v1",
            "legal_ir_view_cross_entropy_loss": 0.6 if improves else 0.9,
            "source_copy_penalty": 0.0,
            "symbolic_validity_success_rate": 1.0,
        },
        heldout_sample_ids=(holdout_id,),
        training_sample_ids=(train_id,),
        holdout_id="trusted-feedback-fixed-holdout-v1",
        minimum_improvement=0.01,
    )


def _hammer(sample_id: str, guidance_id: str, versions: ProofFeedbackVersions, **updates):
    item = {
        "accepted": True,
        "backend_statuses": {"z3": "proved"},
        "guidance_id": guidance_id,
        "legal_ir_view": "deontic.ir",
        "partition": "train",
        "proof_checked": True,
        "proved": True,
        "proof_feedback_version_fingerprint": versions.fingerprint,
        "reconstruction_status": "verified",
        "sample_id": sample_id,
        "schema_version": "legal-ir-hammer-guidance-v1",
        "source": "hammer_verified_guidance",
        "target_component": "deontic.ir",
        "trusted": True,
    }
    item.update(updates)
    return item


def _leanstral(sample_id: str, guidance_id: str, versions: ProofFeedbackVersions, **updates):
    item = {
        "accepted": True,
        "guidance_id": guidance_id,
        "legal_ir_view": "deontic.ir",
        "leanstral_verified": True,
        "partition": "train",
        "proof_feedback_version_fingerprint": versions.fingerprint,
        "sample_id": sample_id,
        "source": "leanstral_shadow_proof",
        "target_component": "deontic.ir",
        "trusted": True,
    }
    item.update(updates)
    return item


def test_ablation_requires_fixed_isolated_heldout_benefit(samples) -> None:
    train, holdout = samples
    passed = _ablation(train.sample_id, holdout.sample_id)
    regressed = _ablation(train.sample_id, holdout.sample_id, improves=False)
    leaked = evaluate_trusted_feedback_ablation(
        {
            "holdout_id": "same",
            "legal_ir_view_cross_entropy_loss": 1.0,
            "source_copy_penalty": 0.0,
            "symbolic_validity_success_rate": 1.0,
        },
        {
            "holdout_id": "same",
            "legal_ir_view_cross_entropy_loss": 0.5,
            "source_copy_penalty": 0.0,
            "symbolic_validity_success_rate": 1.0,
        },
        heldout_sample_ids=(train.sample_id,),
        training_sample_ids=(train.sample_id,),
        holdout_id="same",
    )

    assert passed.schema_version == TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION
    assert passed.production_writes_allowed is True
    assert passed.heldout_improvement == pytest.approx(0.2)
    assert regressed.production_writes_allowed is False
    assert "heldout_benefit_not_demonstrated" in regressed.block_reasons
    assert leaked.production_writes_allowed is False
    assert "train_holdout_overlap" in leaked.block_reasons


def test_production_updates_apply_accepted_hammer_and_verified_leanstral(samples) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    feedback = [
        _hammer(train.sample_id, "feedback-hammer-applied", versions),
        _leanstral(train.sample_id, "feedback-leanstral-applied", versions),
    ]

    report = trainer.train(
        feedback,
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.status == "applied"
    assert report.schema_version == TRUSTED_FEEDBACK_TRAINER_SCHEMA_VERSION
    assert report.applied_count == 2
    assert report.accounted_count == report.candidate_count == 2
    assert report.write_to_autoencoder_weights is True
    assert report.trainable_legal_ir_head_norms["finite"] is True
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is True
    assert report.update_norms_by_head["legal_ir_view_logits"] > 0.0
    assert report.update_norms_by_head["feature_legal_ir_view_logits"] > 0.0
    assert report.head_family_update_norms["compiler_facing_legal_ir_view"] > 0.0
    assert report["skipped_stale_count"] == 0
    assert autoencoder.state.applied_leanstral_guidance_ids == [
        "feedback-hammer-applied",
        "feedback-leanstral-applied",
    ]
    assert autoencoder.state.feature_legal_ir_view_logits
    assert train.text not in json.dumps(autoencoder.state.feature_legal_ir_view_logits)


def test_all_required_skip_counters_are_explicit_and_weights_are_unchanged(samples) -> None:
    train, holdout = samples
    versions = _versions()
    stale_versions = _versions("stale-compiler-v0")
    autoencoder = AdaptiveModalAutoencoder()
    good = _hammer(train.sample_id, "feedback-duplicate", versions)
    ablation = _ablation(train.sample_id, holdout.sample_id)
    apply_trusted_feedback_weight_updates(
        autoencoder,
        [good],
        {train.sample_id: train},
        expected_versions=versions,
        ablation_evidence=ablation,
    )
    before = autoencoder.state.to_dict()
    feedback = [
        good,
        _hammer(train.sample_id, "feedback-stale", stale_versions),
        _leanstral(
            train.sample_id,
            "feedback-untrusted",
            versions,
            trusted=False,
            accepted=False,
            leanstral_verified=False,
        ),
        _hammer("sample-does-not-exist", "feedback-missing", versions),
        _hammer(
            train.sample_id,
            "feedback-source-copy",
            versions,
            source_copy_rejected=True,
        ),
        _hammer(
            holdout.sample_id,
            "feedback-holdout",
            versions,
            partition="holdout",
        ),
    ]
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )

    report = trainer.apply_weight_updates(
        feedback,
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=ablation,
    )
    payload = report.to_dict()

    assert report.applied_count == 0
    assert report.duplicate_count == 1
    assert report.stale_count == 1
    assert report.untrusted_count == 1
    assert report.missing_sample_count == 1
    assert report.guardrail_blocked_count == 2
    assert report.holdout_count == 1
    assert report.accounted_count == report.candidate_count == 6
    assert payload["skipped_duplicate_count"] == 1
    assert payload["skipped_stale_count"] == 1
    assert payload["skipped_untrusted_count"] == 1
    assert payload["skipped_missing_sample_count"] == 1
    assert payload["skipped_guardrail_blocked_count"] == 2
    assert payload["trainable_legal_ir_head_norms"]["nonzero_update"] is False
    assert payload["update_norms_by_head"] == {}
    assert payload["gradient_norms_by_head"] == {}
    assert autoencoder.state.to_dict() == before


def test_production_enablement_and_passing_ablation_are_both_required(samples) -> None:
    train, holdout = samples
    versions = _versions()
    item = _hammer(train.sample_id, "feedback-gated", versions)
    autoencoder = AdaptiveModalAutoencoder()
    before = autoencoder.state.to_dict()
    disabled = TrustedFeedbackTrainer(autoencoder, expected_versions=versions).train(
        [item],
        {train.sample_id: train},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )
    failed_ablation = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    ).train(
        [item],
        {train.sample_id: train},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id, improves=False),
    )

    assert disabled.block_reasons == {"production_weight_writes_disabled": 1}
    assert failed_ablation.block_reasons == {"heldout_ablation_not_passed": 1}
    assert disabled.write_to_autoencoder_weights is False
    assert failed_ablation.write_to_autoencoder_weights is False
    assert disabled.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert failed_ablation.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert autoencoder.state.to_dict() == before


def test_content_addressed_proof_feedback_updates_primary_and_auxiliary_heads(samples) -> None:
    train, holdout = samples
    versions = _versions()
    record = LegalIRProofFeedbackRecord.create(
        obligation_id=train.sample_id,
        obligation_type="exception_scope",
        legal_ir_view="deontic.ir",
        semantic_family="conditional_normative",
        semantic_slots={"exception": "present"},
        selected_premise_families=("theorem_template",),
        route_availability={"deterministic_contract": True},
        route_statuses={"deterministic_contract": "passed"},
        backend_outcomes={"z3": "proved"},
        deterministic_trusted=True,
        evidence_ids=("proof-feedback-evidence",),
        receipt_ids=("proof-feedback-receipt",),
        partition_key=train.sample_id,
        partition_policy=ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
        versions=versions,
    )
    autoencoder = AdaptiveModalAutoencoder()

    report = apply_trusted_feedback_weight_updates(
        autoencoder,
        [record],
        {train.sample_id: train},
        expected_versions=versions,
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.applied_count == 1
    assert report.trainable_legal_ir_head_norms["finite"] is True
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is True
    assert report.update_norms_by_head["proof_auxiliary_head_logits"] > 0.0
    assert autoencoder.state.applied_leanstral_guidance_ids == [record.record_id]
    assert autoencoder.state.applied_proof_feedback_ids == [record.record_id]
    assert autoencoder.state.proof_auxiliary_head_logits
