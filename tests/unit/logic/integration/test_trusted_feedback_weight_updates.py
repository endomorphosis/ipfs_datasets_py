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
    ProofFeedbackTrainingTarget,
    ProofFeedbackVersions,
    proof_feedback_content_digest,
    proof_feedback_sample_digest,
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


def _unattested_current_feedback_fixture(train, versions):
    from dataclasses import replace

    sample_sha256 = proof_feedback_sample_digest(train)
    obligation = {
        "obligation_id": "fictional-notice-exception-obligation",
        "obligation_type": "exception_scope",
        "legal_ir_view": "deontic.ir",
        "statement": "The fictional notice obligation preserves its verified exception.",
    }
    target = ProofFeedbackTrainingTarget(
        sample_id=train.sample_id,
        sample_sha256=sample_sha256,
        obligation_id=obligation["obligation_id"],
        obligation_type=obligation["obligation_type"],
        legal_ir_view=obligation["legal_ir_view"],
        formal_obligation_sha256=proof_feedback_content_digest(obligation),
        reviewed_target_sha256=proof_feedback_content_digest({
            "interpretation_id": "fictional-selected-notice-interpretation",
            "sample_sha256": sample_sha256,
        }),
        dependency_manifest_sha256=proof_feedback_content_digest({
            "fictional-notice-exception-definition": "revision-1",
        }),
    )
    record = LegalIRProofFeedbackRecord.create(
        obligation_id=target.obligation_id,
        obligation_type=target.obligation_type,
        legal_ir_view=target.legal_ir_view,
        obligation_digest=target.obligation_digest,
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
    return record, replace(target, expected_feedback_record_id=record.record_id)


def _current_feedback_fixture(train, versions):
    from dataclasses import replace
    from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
        build_legal_ir_proof_feedback_record,
    )
    from ipfs_datasets_py.logic.ir_core.claims import stable_digest
    from tests.unit.logic.legal_ir.test_proof_cache import _bound_feedback_fixture

    # The fictional fixture selects the existing sampled obligation's identity
    # while the canonical proof-cache owner constructs and verifies its proof.
    legacy, _ = _unattested_current_feedback_fixture(train, versions)
    sample, proof, obligation, context = _bound_feedback_fixture(train, legacy.obligation_id)
    receipt, = proof.theorem_receipt_results(
        expected_context=context, obligation_id=obligation.obligation_id,
    )
    target = ProofFeedbackTrainingTarget(
        sample_id=sample.sample_id,
        sample_sha256=proof_feedback_sample_digest(sample),
        obligation_id=obligation.obligation_id,
        obligation_type=legacy.obligation_type,
        legal_ir_view=legacy.legal_ir_view,
        formal_obligation_sha256=obligation.digest,
        reviewed_target_sha256=context["interpretation_digest"],
        dependency_manifest_sha256=stable_digest(context["dependency_versions"]),
        current_sample=sample,
        legal_proof_record=proof,
        expected_artifact_digest=proof.artifact_digest,
        expected_legal_proof_digest=proof.content_digest,
        expected_proof_receipt_digest=receipt.digest,
        expected_proof_context=context,
    )
    record = build_legal_ir_proof_feedback_record(
        obligation, training_target=target, semantic_slots={"exception": "present"},
        evidence_ids=("proof-feedback-evidence",),
        partition_policy=ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
        versions=versions,
    )
    return record, replace(target, expected_feedback_record_id=record.record_id)


def test_content_addressed_proof_feedback_updates_primary_and_auxiliary_heads(samples) -> None:
    train, holdout = samples
    versions = _versions()
    record, target = _current_feedback_fixture(train, versions)
    autoencoder = AdaptiveModalAutoencoder()

    report = apply_trusted_feedback_weight_updates(
        autoencoder,
        [record],
        {train.sample_id: train},
        current_proof_targets={target.obligation_id: target},
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


@pytest.mark.parametrize(
    ("nested_key", "rejection_field"),
    (
        ("guidance", "accepted"),
        ("guidance", "trusted"),
        ("feedback", "accepted"),
        ("feedback", "trusted"),
    ),
    ids=(
        "guidance-outer-accepted-false",
        "guidance-outer-trusted-false",
        "feedback-outer-accepted-false",
        "feedback-outer-trusted-false",
    ),
)
def test_nested_feedback_outer_rejection_prevents_weight_updates(
    samples, nested_key, rejection_field
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    inner = _hammer(
        train.sample_id,
        f"feedback-{nested_key}-outer-{rejection_field}-false",
        versions,
    )

    report = trainer.train(
        [{rejection_field: False, nested_key: inner}],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.applied_count == 0
    assert report.untrusted_count == 1
    assert report.candidate_count == report.accounted_count == 1
    assert report.block_reasons == {"untrusted_or_unverified_feedback": 1}
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize(
    "nested_key", ("guidance", "feedback"), ids=("guidance-valid", "feedback-valid")
)
def test_nested_feedback_valid_envelope_preserves_weight_updates(samples, nested_key) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    feedback_id = f"feedback-{nested_key}-valid-nested-envelope"
    inner = _hammer(train.sample_id, feedback_id, versions)

    report = trainer.train(
        [{"accepted": True, "trusted": True, nested_key: inner}],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.applied_count == 1
    assert report.untrusted_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.block_reasons == {}
    assert report.write_to_autoencoder_weights is True
    assert report.trainable_legal_ir_head_norms["finite"] is True
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is True
    assert report.update_norms_by_head["legal_ir_view_logits"] > 0.0
    assert report.update_norms_by_head["feature_legal_ir_view_logits"] > 0.0
    assert autoencoder.state.applied_leanstral_guidance_ids == [feedback_id]
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) != before


def _trusted_feedback_record_for_nested_envelope(train, versions):
    return LegalIRProofFeedbackRecord.create(
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


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
@pytest.mark.parametrize(
    ("outer_fields", "expected_reason"),
    (
        ({'source_copy_rejected': True}, 'source_copy_rejected'),
        ({'copy_source_span_rejected': True}, 'source_copy_rejected'),
        ({'copied_source_span_rejected': True}, 'source_copy_rejected'),
        ({'source_copy_guard_passed': False}, 'source_copy_guard_failed'),
        ({'source_copy_passed': False}, 'source_copy_guard_failed'),
        ({'source_copy_penalty': 0.5}, 'source_copy_penalty_exceeded'),
        ({'source_copy_reward_hack_penalty': 0.5}, 'source_copy_penalty_exceeded'),
        ({'source_span_copy_ratio': 0.5}, 'source_copy_penalty_exceeded'),
        ({'source_copy_penalty': 'invalid'}, 'source_copy_metric_invalid'),
        ({'source_copy_penalty': 'NaN'}, 'source_copy_penalty_exceeded'),
        ({'rejection_reason': 'source_copy'}, 'source_copy_rejected'),
        ({'rejection_reasons': ['drafted_logic_candidate_copies_source']}, 'source_copy_rejected'),
    ),
    ids=('copy-rejected', 'copy-span-rejected', 'copied-span-rejected', 'copy-guard-failed', 'copy-passed-false', 'penalty-exceeded', 'reward-penalty-exceeded', 'span-ratio-exceeded', 'penalty-invalid', 'penalty-nonfinite', 'copy-reason', 'copy-reasons'),
)
def test_nested_feedback_outer_source_copy_guards_prevent_weight_updates(
    samples, nested_key, outer_fields, expected_reason
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    inner = _hammer(train.sample_id, "feedback-outer-copy-guard", versions)
    envelope = dict(outer_fields)
    envelope[nested_key] = inner

    report = trainer.train(
        [envelope],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.guardrail_blocked_count == 1
    assert report.untrusted_count == report.stale_count == report.invalid_count == 0
    assert report.block_reasons == {expected_reason: 1}
    assert report.applied_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert report.update_norms_by_head == {}
    assert report.gradient_norms_by_head == {}
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
@pytest.mark.parametrize("partition_field", ("partition", "feedback_partition"))
def test_nested_feedback_outer_holdout_prevents_weight_updates(
    samples, nested_key, partition_field
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    inner = _hammer(train.sample_id, "feedback-outer-holdout", versions)

    report = trainer.train(
        [{partition_field: "holdout", nested_key: inner}],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.holdout_count == 1
    assert report.guardrail_blocked_count == 1
    assert report.untrusted_count == report.stale_count == report.invalid_count == 0
    assert report.block_reasons == {"holdout_feedback_isolation": 1}
    assert report.applied_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert report.update_norms_by_head == {}
    assert report.gradient_norms_by_head == {}
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
@pytest.mark.parametrize("rejection_field", ("accepted", "trusted"))
def test_typed_nested_feedback_outer_rejection_prevents_weight_updates(
    samples, nested_key, rejection_field
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    record = _trusted_feedback_record_for_nested_envelope(train, versions)
    inner = _hammer(train.sample_id, "feedback-typed-outer-rejection", versions)

    report = trainer.train(
        [{"proof_feedback_record": record, rejection_field: False, nested_key: inner}],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.untrusted_count == 1
    assert report.guardrail_blocked_count == report.stale_count == report.invalid_count == 0
    assert report.block_reasons == {"untrusted_or_unverified_feedback": 1}
    assert report.applied_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert report.update_norms_by_head == {}
    assert report.gradient_norms_by_head == {}
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
@pytest.mark.parametrize("view_field", ("legal_ir_view", "target_component", "target_view"))
def test_typed_nested_feedback_outer_view_conflict_prevents_weight_updates(
    samples, nested_key, view_field
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    record = _trusted_feedback_record_for_nested_envelope(train, versions)
    inner = _hammer(train.sample_id, "feedback-typed-outer-view-conflict", versions)

    report = trainer.train(
        [{"proof_feedback_record": record, view_field: "temporal.ir", nested_key: inner}],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.invalid_count == 1
    assert report.untrusted_count == report.stale_count == report.guardrail_blocked_count == 0
    assert report.block_reasons == {"invalid_feedback": 1}
    assert report.applied_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert report.update_norms_by_head == {}
    assert report.gradient_norms_by_head == {}
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
@pytest.mark.parametrize(
    "version_field",
    ("proof_feedback_version_fingerprint", "version_fingerprint", "model_version_fingerprint"),
)
def test_typed_nested_feedback_outer_version_conflict_prevents_weight_updates(
    samples, nested_key, version_field
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    record = _trusted_feedback_record_for_nested_envelope(train, versions)
    stale_versions = _versions("trusted-feedback-stale-outer-envelope")
    inner = _hammer(train.sample_id, "feedback-typed-outer-version-conflict", versions)

    report = trainer.train(
        [{
            "proof_feedback_record": record,
            version_field: stale_versions.fingerprint,
            nested_key: inner,
        }],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.stale_count == 1
    assert report.untrusted_count == report.invalid_count == report.guardrail_blocked_count == 0
    assert report.block_reasons == {"version_missing_or_mismatched": 1}
    assert report.applied_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert report.update_norms_by_head == {}
    assert report.gradient_norms_by_head == {}
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
def test_typed_nested_feedback_matching_envelope_preserves_weight_updates(
    samples, nested_key
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder(compute_device="python")
    autoencoder.state.legal_ir_view_logits["CEC.native"] = 0.0
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    record, target = _current_feedback_fixture(train, versions)
    inner = _hammer(train.sample_id, "feedback-typed-matching-envelope", versions)
    envelope = {
        "proof_feedback_record": record,
        "accepted": True,
        "trusted": True,
        "partition": "train",
        "feedback_partition": "train",
        "legal_ir_view": record.legal_ir_view,
        "target_component": record.legal_ir_view,
        "target_view": record.legal_ir_view,
        "proof_feedback_version_fingerprint": record.version_fingerprint,
        "version_fingerprint": record.version_fingerprint,
        "model_version_fingerprint": record.version_fingerprint,
        nested_key: inner,
    }

    report = trainer.train(
        [envelope],
        {train.sample_id: train, holdout.sample_id: holdout},
        current_proof_targets={target.obligation_id: target},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.applied_count == 1
    assert report.candidate_count == report.accounted_count == 1
    assert report.untrusted_count == report.stale_count == report.invalid_count == 0
    assert report.guardrail_blocked_count == 0
    assert report.block_reasons == {}
    assert report.write_to_autoencoder_weights is True
    assert report.applied_feedback_ids == (record.record_id,)
    assert report.trainable_legal_ir_head_norms["finite"] is True
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is True
    # The same selected record has the same bounded effect whether it
    # arrives bare or inside compatible guidance and guard metadata.
    reference = AdaptiveModalAutoencoder(compute_device="python")
    reference.state.legal_ir_view_logits["CEC.native"] = 0.0
    direct = TrustedFeedbackTrainer(
        reference,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    ).train(
        [record],
        {train.sample_id: train, holdout.sample_id: holdout},
        current_proof_targets={target.obligation_id: target},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )
    assert direct.applied_count == report.applied_count
    assert direct.update_norms_by_head == report.update_norms_by_head
    assert report.update_norms_by_head["legal_ir_view_logits"] > 0.0
    assert autoencoder.state.legal_ir_view_logits["CEC.native"] < 0.0
    assert autoencoder.state.legal_ir_view_logits["deontic.ir"] > 0.0
    assert reference.state.to_dict() == autoencoder.state.to_dict()
    assert report.update_norms_by_head["feature_legal_ir_view_logits"] > 0.0
    assert report.update_norms_by_head["proof_auxiliary_head_logits"] > 0.0
    assert autoencoder.state.applied_leanstral_guidance_ids == [record.record_id]
    assert autoencoder.state.applied_proof_feedback_ids == [record.record_id]
    assert autoencoder.state.feature_legal_ir_view_logits
    assert autoencoder.state.proof_auxiliary_head_logits
    assert train.text not in json.dumps(autoencoder.state.feature_legal_ir_view_logits)
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) != before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
@pytest.mark.parametrize(
    "child_case", ("accepted-false", "trusted-false", "missing-trust", "unverified")
)
def test_nested_feedback_outer_approval_cannot_promote_untrusted_child(
    samples, nested_key, child_case
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    inner = _hammer(train.sample_id, f"feedback-{nested_key}-{child_case}", versions)
    if child_case == "accepted-false":
        inner["accepted"] = False
    elif child_case == "trusted-false":
        inner["trusted"] = False
    elif child_case == "missing-trust":
        inner.pop("accepted")
        inner.pop("trusted")
    else:
        assert child_case == "unverified"
        for key in ("leanstral_verified", "verifier_confirmed", "verified", "proof_checked"):
            inner.pop(key, None)
        inner["proved"] = False
        inner["reconstruction_status"] = "unverified"

    report = trainer.train(
        [{"accepted": True, "trusted": True, nested_key: inner}],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert report.applied_count == 0
    assert report.untrusted_count == 1
    assert report.candidate_count == report.accounted_count == 1
    assert report.stale_count == report.invalid_count == report.guardrail_blocked_count == 0
    assert report.block_reasons == {"untrusted_or_unverified_feedback": 1}
    assert report.write_to_autoencoder_weights is False
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is False
    assert report.update_norms_by_head == {}
    assert report.gradient_norms_by_head == {}
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == before


@pytest.mark.parametrize("nested_key", ("guidance", "feedback"))
def test_nested_feedback_guard_metadata_never_enters_real_update_payload(
    samples, nested_key, monkeypatch
) -> None:
    train, holdout = samples
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    feedback_id = f"feedback-{nested_key}-real-payload-spy"
    inner = _hammer(train.sample_id, feedback_id, versions)
    expected_payload = json.loads(json.dumps(inner))
    namespace = TrustedFeedbackTrainer.train.__globals__
    original_update = namespace["_apply_bounded_sample_update"]
    observed_payloads = []

    def recording_update(autoencoder_arg, item, sample, *, feedback_id, learning_rate):
        observed_payloads.append(json.loads(json.dumps(item)))
        assert item == expected_payload
        assert "outer_metadata_sentinel" not in item
        return original_update(
            autoencoder_arg,
            item,
            sample,
            feedback_id=feedback_id,
            learning_rate=learning_rate,
        )

    monkeypatch.setitem(namespace, "_apply_bounded_sample_update", recording_update)
    report = trainer.train(
        [{
            "accepted": True,
            "trusted": True,
            "outer_metadata_sentinel": {"scope": "guard_only", "token": "outer-sentinel-v1"},
            nested_key: inner,
        }],
        {train.sample_id: train, holdout.sample_id: holdout},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
    )

    assert observed_payloads == [expected_payload]
    assert inner == expected_payload
    assert report.applied_count == 1
    assert report.untrusted_count == report.stale_count == report.invalid_count == 0
    assert report.guardrail_blocked_count == 0
    assert report.candidate_count == report.accounted_count == 1
    assert report.block_reasons == {}
    assert report.write_to_autoencoder_weights is True
    assert report.applied_feedback_ids == (feedback_id,)
    assert report.trainable_legal_ir_head_norms["finite"] is True
    assert report.trainable_legal_ir_head_norms["nonzero_update"] is True
    assert report.update_norms_by_head["legal_ir_view_logits"] > 0.0
    assert report.update_norms_by_head["feature_legal_ir_view_logits"] > 0.0
    assert autoencoder.state.applied_leanstral_guidance_ids == [feedback_id]
    assert train.text not in json.dumps(autoencoder.state.feature_legal_ir_view_logits)
    assert json.dumps(
        autoencoder.state.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ) != before



@pytest.mark.parametrize("route", ["inner-guidance", "inner-feedback", "outer", "inner-alias", "wrong-index-value"])
def test_typed_proof_feedback_cannot_update_an_unrelated_training_sample(samples, route) -> None:
    train, holdout = samples
    other = build_us_code_sample(
        title="5", section="551-other-feedback-train",
        text="A board may retain the filing while an application remains pending.")
    assert len({train.sample_id, holdout.sample_id, other.sample_id}) == 3
    versions = _versions()
    record = _trusted_feedback_record_for_nested_envelope(train, versions)
    autoencoder = AdaptiveModalAutoencoder()
    before = json.dumps(autoencoder.state.to_dict(), sort_keys=True, allow_nan=False)
    key = "feedback" if route == "inner-feedback" else "guidance"
    item = _hammer(train.sample_id, "typed-proof-sample-guard", versions)
    envelope = {"proof_feedback_record": record, key: item}
    supplied = {train.sample_id: train, other.sample_id: other, holdout.sample_id: holdout}
    ablation_train = train.sample_id
    if route.startswith("inner-") and route != "inner-alias":
        item["sample_id"] = ablation_train = other.sample_id
    elif route == "outer":
        envelope["sample_id"] = other.sample_id
    elif route == "inner-alias":
        item["training_sample_id"] = other.sample_id
    else:
        supplied[train.sample_id] = other

    trainer = TrustedFeedbackTrainer(
        autoencoder, expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True))
    report = trainer.train(
        [envelope], supplied, ablation_evidence=_ablation(ablation_train, holdout.sample_id))

    assert report.applied_count == 0, "unbound typed proof feedback reached a weight update"
    assert report.guardrail_blocked_count == 1
    assert report.block_reasons == {"proof_feedback_sample_mismatch": 1}
    assert report.candidate_count == report.accounted_count == 1
    assert not report.write_to_autoencoder_weights
    assert not report.trainable_legal_ir_head_norms["nonzero_update"]
    assert autoencoder.state.applied_leanstral_guidance_ids == []
    assert autoencoder.state.applied_proof_feedback_ids == []
    assert json.dumps(autoencoder.state.to_dict(), sort_keys=True, allow_nan=False) == before


@pytest.mark.parametrize("change", ("matching", "legacy", "sample", "interpretation", "dependency"))
def test_typed_feedback_uses_current_semantic_target_before_update(samples, monkeypatch, change):
    from dataclasses import replace

    train, holdout = samples
    versions = _versions()
    record, target = _current_feedback_fixture(train, versions)
    selected = train
    if change == "legacy":
        record = _trusted_feedback_record_for_nested_envelope(train, versions)
    elif change == "sample":
        formulas = list(train.modal_ir.formulas)
        index = next(i for i, formula in enumerate(formulas) if formula.exceptions)
        formulas[index] = replace(formulas[index], exceptions=[])
        selected = replace(train, modal_ir=replace(train.modal_ir, formulas=formulas))
        assert selected.sample_id == train.sample_id
        assert selected.text == train.text
        assert proof_feedback_sample_digest(selected) != target.sample_sha256
    elif change == "interpretation":
        target = replace(target, reviewed_target_sha256=proof_feedback_content_digest({
            "interpretation_id": "fictional-revised-notice-interpretation",
            "sample_sha256": target.sample_sha256,
        }))
    elif change == "dependency":
        target = replace(target, dependency_manifest_sha256=proof_feedback_content_digest({
            "fictional-notice-exception-definition": "revision-2",
        }))

    autoencoder = AdaptiveModalAutoencoder(compute_device="python")
    before = autoencoder.state.to_dict()
    trainer = TrustedFeedbackTrainer(autoencoder, expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True))
    updates = []

    def stop_before_update(model, guidance, sample, **kwargs):
        updates.append((kwargs["feedback_id"], proof_feedback_sample_digest(sample)))
        return False

    monkeypatch.setitem(trainer.train.__globals__, "_apply_bounded_sample_update", stop_before_update)
    targets = {target.obligation_id: target}
    report = trainer.train([record.to_dict()], {selected.sample_id: selected},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id), current_proof_targets=targets)
    if change == "matching":
        assert updates == [(record.record_id, target.sample_sha256)]
        assert report.block_reasons == {"no_bounded_learning_target": 1}
    else:
        assert updates == []
        key = ("proof_feedback_current_sample_mismatch" if change == "sample"
               else "proof_feedback_current_target_mismatch")
        assert report.block_reasons == {key: 1}
    assert report.applied_count == 0
    assert autoencoder.state.to_dict() == before

    # The auxiliary entry point enforces the same target, without fitting.
    # A revised sample reaches it only through the trainer's sample check.
    auxiliary = autoencoder.train_proof_auxiliary_heads([record], expected_versions=versions,
        current_proof_targets=targets, learning_rate=0)
    assert auxiliary["eligible_count"] == int(change in ("matching", "sample"))
    assert auxiliary["skipped_current_target_count"] == int(change not in ("matching", "sample"))
    assert autoencoder.state.to_dict() == before


@pytest.mark.parametrize("change", ("other_receipt", "other_label_same_receipt"))
def test_typed_feedback_refuses_substituted_record_with_same_target(samples, monkeypatch, change):
    from dataclasses import replace

    train, holdout = samples
    versions = _versions()
    selected, target = _current_feedback_fixture(train, versions)
    changes = ({"receipt_ids": ("fictional-other-receipt",)} if change == "other_receipt"
               else {"evidence_ids": ("fictional-other-evidence",), "semantic_family": "other_family"})
    offered = replace(selected, record_id="", **changes)
    offered = replace(offered, record_id=offered.expected_record_id)
    assert offered.obligation_digest == target.obligation_digest == selected.obligation_digest
    assert offered.record_id != target.expected_feedback_record_id
    if change == "other_label_same_receipt":
        assert offered.receipt_ids == selected.receipt_ids

    encoder = AdaptiveModalAutoencoder(compute_device="python")
    before = encoder.state.to_dict()
    trainer = TrustedFeedbackTrainer(encoder, expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True))
    called = []

    def stop_before_update(*args, **kwargs):
        called.append(True)
        return False

    monkeypatch.setitem(trainer.train.__globals__, "_apply_bounded_sample_update", stop_before_update)
    targets = {target.obligation_id: target}
    report = trainer.train([offered], {train.sample_id: train},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id), current_proof_targets=targets)
    assert not called
    assert report.block_reasons == {"proof_feedback_current_target_mismatch": 1}
    auxiliary = encoder.train_proof_auxiliary_heads([offered.to_dict()], expected_versions=versions,
        current_proof_targets=targets, learning_rate=0)
    assert auxiliary["eligible_count"] == 0 and auxiliary["skipped_current_target_count"] == 1
    assert encoder.state.to_dict() == before


@pytest.mark.parametrize("change", ("copied_id", "unselected_id"))
def test_current_target_requires_independent_id_and_canonical_feedback(samples, monkeypatch, change):
    from dataclasses import replace

    train, holdout = samples
    versions = _versions()
    selected, target = _current_feedback_fixture(train, versions)
    offered = LegalIRProofFeedbackRecord.from_dict(selected.to_dict())
    if change == "copied_id":
        # The mutable nested mapping models a previously decoded record that
        # drifted. It still carries the selected canonical ID on its outer object.
        offered.semantic_slots["exception"] = "single"
        assert offered.record_id == target.expected_feedback_record_id
        assert offered.expected_record_id != offered.record_id
    else:
        target = replace(target, expected_feedback_record_id="")

    encoder = AdaptiveModalAutoencoder(compute_device="python")
    before = encoder.state.to_dict()
    trainer = TrustedFeedbackTrainer(encoder, expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True))
    called = []

    def stop_before_update(*args, **kwargs):
        called.append(True)
        return False

    monkeypatch.setitem(trainer.train.__globals__, "_apply_bounded_sample_update", stop_before_update)
    targets = {target.obligation_id: target}
    report = trainer.train([offered], {train.sample_id: train},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id), current_proof_targets=targets)
    auxiliary = encoder.train_proof_auxiliary_heads([offered], expected_versions=versions,
        current_proof_targets=targets, learning_rate=0)
    assert not called and auxiliary["eligible_count"] == 0
    if change == "copied_id":
        assert report.invalid_count == auxiliary["skipped_invalid_count"] == 1
    else:
        assert report.block_reasons == {"proof_feedback_current_target_mismatch": 1}
        assert auxiliary["skipped_current_target_count"] == 1
    assert encoder.state.to_dict() == before


def test_current_target_metadata_without_checked_receipt_never_reaches_update(samples, monkeypatch):
    # This fixture supplies matching commitments and caller-written trust flags,
    # but no independently bound verifier receipt. These are fictional rows;
    # their identifiers do not establish a checked proof.
    train, holdout = samples
    versions = _versions()
    record, target = _unattested_current_feedback_fixture(train, versions)
    encoder = AdaptiveModalAutoencoder(compute_device="python")
    before = encoder.state.to_dict()
    trainer = TrustedFeedbackTrainer(
        encoder, expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    updates = []

    def stop_before_update(*args, **kwargs):
        updates.append(True)
        return False

    monkeypatch.setitem(trainer.train.__globals__, "_apply_bounded_sample_update", stop_before_update)
    targets = {target.obligation_id: target}
    report = trainer.train(
        [record.to_dict()], {train.sample_id: train},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
        current_proof_targets=targets,
    )
    auxiliary = encoder.train_proof_auxiliary_heads(
        [record], expected_versions=versions,
        current_proof_targets=targets, learning_rate=0,
    )
    assert report.applied_count == 0
    assert encoder.state.to_dict() == before
    assert {"update_calls": len(updates), "auxiliary_eligible": auxiliary["eligible_count"]} == {
        "update_calls": 0, "auxiliary_eligible": 0,
    }


@pytest.mark.parametrize(
    ("scenario", "producer_error"),
    [
        ("selected", None),
        ("same_receipt_id", "exact checked receipt and formal obligation"),
        ("stale_raw_source", "checked obligation does not bind the current sample source"),
        ("changed_interpretation", "failed current receipt replay"),
        ("changed_dependency", "failed current receipt replay"),
        ("unreviewed_source", "requires a reviewed sample source"),
        ("missing_modal_binding", "does not bind the current modal interpretation"),
    ],
)
def test_checked_legal_proof_producer_and_consumers_bind_exact_current_evidence(
    samples, monkeypatch, scenario, producer_error
):
    from dataclasses import replace

    from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
        ProofFeedbackTrustError,
        build_legal_ir_proof_feedback_record,
    )
    from ipfs_datasets_py.logic.ir_core.claims import stable_digest
    from ipfs_datasets_py.logic.legal_ir.proof_cache import LegalProofRecord
    from ipfs_datasets_py.logic.ir_core.provenance import SourceReviewStatus
    from tests.unit.logic.legal_ir.test_proof_cache import _bound_feedback_fixture, _legal_artifact

    train, holdout = samples
    train, proof, obligation, context = _bound_feedback_fixture(
        train, "obligation:checked-feedback-trainer-fixture"
    )
    receipt, = proof.theorem_receipt_results(
        expected_context=context, obligation_id=obligation.obligation_id
    )
    assert receipt.obligation_digest == obligation.digest
    versions = _versions()
    target = ProofFeedbackTrainingTarget(
        sample_id=train.sample_id,
        sample_sha256=proof_feedback_sample_digest(train),
        obligation_id=obligation.obligation_id,
        obligation_type="exception_scope",
        legal_ir_view="deontic.ir",
        formal_obligation_sha256=obligation.digest,
        reviewed_target_sha256=context["interpretation_digest"],
        dependency_manifest_sha256=stable_digest(dict(context["dependency_versions"])),
        legal_proof_record=proof,
        current_sample=train,
        expected_artifact_digest=proof.artifact_digest,
        expected_legal_proof_digest=proof.content_digest,
        expected_proof_receipt_digest=receipt.digest,
        expected_proof_context=context,
    )

    def project(selected):
        return build_legal_ir_proof_feedback_record(
            obligation,
            training_target=selected,
            semantic_slots={"exception": "present"},
            versions=versions,
            partition_policy=ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
        )

    record = project(target)
    assert record.positive and record.kernel_reconstruction.verified
    receipt_reference = f"protocol-proof-sha256:{receipt.digest}"
    assert record.receipt_ids == (receipt_reference,)
    assert record.kernel_reconstruction.receipt_id == receipt_reference
    assert record.obligation_digest == target.obligation_digest

    selected_sample = train
    if scenario == "same_receipt_id":
        other_receipt = replace(receipt, verifier=receipt.verifier + "-alternate")
        assert other_receipt.receipt_id == receipt.receipt_id
        assert other_receipt.digest != receipt.digest
        binding, = proof.proof_bindings
        other_binding = binding.to_dict() | {"receipt_digest": other_receipt.digest}
        other_proof = LegalProofRecord.build(
            proof.formalization_artifact(),
            profile=proof.profile,
            jurisdiction=proof.jurisdiction,
            theorem_receipts=(other_receipt,),
            proof_bindings=(other_binding,),
        )
        assert other_proof.theorem_receipt_results(
            expected_context=context, obligation_id=obligation.obligation_id
        ) == (other_receipt,)
        target = replace(
            target,
            legal_proof_record=other_proof,
            expected_legal_proof_digest=other_proof.content_digest,
        )
    elif scenario == "stale_raw_source":
        selected_sample = replace(train, text=train.text + " ")
        assert selected_sample.sample_id == train.sample_id
        assert selected_sample.modal_ir.to_dict() == train.modal_ir.to_dict()
        assert proof_feedback_sample_digest(selected_sample) != target.sample_sha256
        target = replace(
            target,
            current_sample=selected_sample,
            sample_sha256=proof_feedback_sample_digest(selected_sample),
        )
    elif scenario == "changed_interpretation":
        changed_digest = stable_digest({"fictional_interpretation": "revised"})
        assert changed_digest != target.reviewed_target_sha256
        target = replace(
            target,
            reviewed_target_sha256=changed_digest,
            expected_proof_context=dict(context, interpretation_digest=changed_digest),
        )
    elif scenario == "changed_dependency":
        dependencies = dict(context["dependency_versions"])
        dependencies["fictional-definition"] = stable_digest({"definition": "revised"})
        assert stable_digest(dependencies) != target.dependency_manifest_sha256
        target = replace(
            target,
            dependency_manifest_sha256=stable_digest(dependencies),
            expected_proof_context=dict(context, dependency_versions=dependencies),
        )

    elif scenario in {"unreviewed_source", "missing_modal_binding"}:
        artifact = _legal_artifact(train)
        if scenario == "unreviewed_source":
            source_map = replace(
                artifact.source_map,
                sources=tuple(
                    replace(ref, review_status=SourceReviewStatus.UNREVIEWED)
                    for ref in artifact.source_map.sources
                ),
            )
            artifact = replace(artifact, source_map=source_map)
        else:
            metadata = artifact.metadata.to_dict()
            metadata.pop("legacy_modal_ir_canonical_hash")
            artifact = replace(artifact, metadata=metadata)
        _, altered_proof, altered_obligation, altered_context = _bound_feedback_fixture(
            train, obligation.obligation_id, artifact=artifact,
        )
        assert altered_obligation == obligation and altered_context == context
        checked_receipt, = altered_proof.theorem_receipt_results(
            expected_context=context, obligation_id=obligation.obligation_id,
        )
        target = replace(
            target,
            legal_proof_record=altered_proof,
            expected_artifact_digest=altered_proof.artifact_digest,
            expected_legal_proof_digest=altered_proof.content_digest,
            expected_proof_receipt_digest=checked_receipt.digest,
        )

    if producer_error is not None:
        with pytest.raises(ProofFeedbackTrustError, match=producer_error):
            project(target)
        # Rebind the offered record's two structural pins so the consumers
        # must replay checked evidence before they can refuse it.
        offered = replace(record, record_id="", obligation_digest=target.obligation_digest)
        offered = replace(offered, record_id=offered.expected_record_id)
    else:
        offered = record

    target = replace(target, expected_feedback_record_id=offered.record_id)
    wire = json.loads(json.dumps(offered.to_dict()))
    detached = LegalIRProofFeedbackRecord.from_dict(wire)
    assert detached.to_dict() == wire
    assert detached.record_id == target.expected_feedback_record_id
    assert detached.obligation_digest == target.obligation_digest
    accepted = producer_error is None
    assert target.matches(detached) is accepted

    encoder = AdaptiveModalAutoencoder(compute_device="python")
    before = encoder.state.to_dict()
    trainer = TrustedFeedbackTrainer(
        encoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    updates = []

    def stop_before_update(model, guidance, sample, *, feedback_id, learning_rate):
        updates.append((feedback_id, proof_feedback_sample_digest(sample)))
        return False

    monkeypatch.setitem(
        trainer.train.__globals__, "_apply_bounded_sample_update", stop_before_update
    )
    targets = {target.obligation_id: target}
    result = trainer.train(
        [wire],
        {selected_sample.sample_id: selected_sample},
        ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
        current_proof_targets=targets,
    )
    if accepted:
        assert updates == [(record.record_id, target.sample_sha256)]
        assert result.block_reasons == {"no_bounded_learning_target": 1}
    else:
        assert not updates
        assert result.block_reasons == {"proof_feedback_current_target_mismatch": 1}
    auxiliary = encoder.train_proof_auxiliary_heads(
        [wire], expected_versions=versions, current_proof_targets=targets, learning_rate=0
    )
    assert auxiliary["eligible_count"] == int(accepted)
    assert auxiliary["skipped_current_target_count"] == int(not accepted)
    assert result.applied_count == auxiliary["applied_count"] == 0
    assert encoder.state.to_dict() == before


def test_checked_proof_nested_guidance_cannot_redirect_primary_update(samples, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
        build_trusted_hammer_leanstral_feature_bus,
    )

    train, holdout = samples
    versions = _versions()
    record, target = _current_feedback_fixture(train, versions)
    wire = json.loads(json.dumps(record.to_dict()))
    assert target.matches(LegalIRProofFeedbackRecord.from_dict(wire))
    encoder = AdaptiveModalAutoencoder(compute_device="python")
    trainer = TrustedFeedbackTrainer(
        encoder,
        expected_versions=versions,
        config=TrustedFeedbackTrainerConfig(production_weight_writes_enabled=True),
    )
    before = encoder.state.to_dict()
    observed = []

    def stop_before_update(model, guidance, sample, *, feedback_id, learning_rate):
        # Exercise the production feature projection and stop before nudging
        # either the global or the feature head.
        bus = build_trusted_hammer_leanstral_feature_bus(guidance, require_trusted=False)
        distribution = model._leanstral_guidance_target_distribution(bus.learning_payload)
        observed.append((feedback_id, proof_feedback_sample_digest(sample), bus.feature_keys, distribution))
        return False

    monkeypatch.setitem(
        trainer.train.__globals__, "_apply_bounded_sample_update", stop_before_update
    )
    envelope = {
        "proof_feedback_record": wire,
        "guidance": {
            "sample_id": train.sample_id,
            "legal_ir_view": record.legal_ir_view,
            "premise_views": ["CEC.native"],
        },
    }
    for offered in (wire, envelope):
        report = trainer.train(
            [offered],
            {train.sample_id: train},
            ablation_evidence=_ablation(train.sample_id, holdout.sample_id),
            current_proof_targets={target.obligation_id: target},
        )
        assert report.applied_count == 0
        assert report.block_reasons == {"no_bounded_learning_target": 1}
        assert encoder.state.to_dict() == before

    direct, nested = observed
    assert direct[:2] == nested[:2] == (record.record_id, target.sample_sha256)
    assert direct[3].get("deontic.ir", 0.0) > 0.0 and "CEC.native" not in direct[3]
    assert nested == direct
