"""Proof-aware auxiliary head tests for the modal autoencoder."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    KernelReconstructionFeedback,
    LegalIRProofFeedbackRecord,
    ProofFeedbackPartitionPolicy,
    ProofFeedbackTrainingTarget,
    ProofFeedbackVersions,
    build_legal_ir_proof_feedback_record,
    proof_feedback_content_digest,
    proof_feedback_sample_digest,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_ARCHITECTURE_VERSION,
    MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
    PROOF_AUXILIARY_HEAD_NAMES,
    PROOF_AUXILIARY_HEAD_SCHEMA_VERSION,
    PROOF_AUXILIARY_MAX_LABELS_PER_HEAD,
    PROOF_AUXILIARY_PROTECTED_OBJECTIVES,
    AdaptiveModalAutoencoder,
    ModalAutoencoderTrainingState,
)


def _versions(compiler: str = "compiler-proof-heads-v1") -> ProofFeedbackVersions:
    return ProofFeedbackVersions(
        compiler_version=compiler,
        solver_toolchain_version="z3-test-v1",
        lean_toolchain_version="lean-test-v1",
        theorem_registry_version="theorems-test-v1",
    )


def _record(
    suffix: str = "1",
    *,
    versions: ProofFeedbackVersions | None = None,
    partition_policy: ProofFeedbackPartitionPolicy | None = None,
    deterministic_trusted: bool = True,
    **overrides,
) -> LegalIRProofFeedbackRecord:
    values = {
        "obligation_id": f"proof-head-obligation-{suffix}",
        "obligation_type": "exception_scope",
        "legal_ir_view": "deontic.ir",
        "semantic_family": "conditional_normative",
        "semantic_slots": {
            "actor": "present",
            "condition": "single",
            "exception": "present",
        },
        "selected_premise_families": (
            "sample_local_assumption",
            "theorem_template",
        ),
        "route_availability": {
            "deterministic_contract": True,
            "native_lean_reconstruction": False,
        },
        "route_statuses": {"deterministic_contract": "passed"},
        "backend_outcomes": {"z3": "proved"},
        "deterministic_trusted": deterministic_trusted,
        "repair_label": "exception_scope_projection",
        "evidence_ids": (f"evidence-{suffix}",),
        "receipt_ids": (f"receipt-{suffix}",),
        "partition_key": f"sample-{suffix}",
        "partition_policy": partition_policy or ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
        "versions": versions or _versions(),
    }
    values.update(overrides)
    return LegalIRProofFeedbackRecord.create(**values)


@pytest.fixture(scope="module")
def current_proof_sample():
    return build_us_code_sample(
        title="5",
        section="fictional-proof-auxiliary-heads",
        text="A fictional agency shall publish notice unless the board grants an exception.",
    )


def _bound_record(sample, suffix, *, obligation_type="exception_scope", **options):
    if options.get("deterministic_trusted", True):
        from ipfs_datasets_py.logic.ir_core.claims import stable_digest
        from tests.unit.logic.legal_ir.test_proof_cache import _bound_feedback_fixture

        sample, proof, obligation, context = _bound_feedback_fixture(
            sample, f"proof-head-obligation-{suffix}"
        )
        receipt, = proof.theorem_receipt_results(
            expected_context=context, obligation_id=obligation.obligation_id
        )
        target = ProofFeedbackTrainingTarget(
            sample_id=sample.sample_id,
            sample_sha256=proof_feedback_sample_digest(sample),
            obligation_id=obligation.obligation_id,
            obligation_type=obligation_type,
            legal_ir_view="deontic.ir",
            formal_obligation_sha256=obligation.digest,
            reviewed_target_sha256=context["interpretation_digest"],
            dependency_manifest_sha256=stable_digest(context["dependency_versions"]),
            legal_proof_record=proof,
            current_sample=sample,
            expected_artifact_digest=proof.artifact_digest,
            expected_legal_proof_digest=proof.content_digest,
            expected_proof_receipt_digest=receipt.digest,
            expected_proof_context=context,
        )
        selected = build_legal_ir_proof_feedback_record(
            obligation,
            training_target=target,
            semantic_slots={"actor": "present", "condition": "single", "exception": "present"},
            selected_premises=(
                {"metadata": {"premise_family": "sample_local_assumption"}},
                {"metadata": {"premise_family": "theorem_template"}},
            ),
            repair_label="exception_scope_projection",
            evidence_ids=(f"evidence-{suffix}",),
            partition_policy=ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
            versions=options.get("versions") or _versions(),
        )
        offered = LegalIRProofFeedbackRecord.from_dict(selected.to_dict())
        return offered, replace(target, expected_feedback_record_id=selected.record_id)

    sample_sha256 = proof_feedback_sample_digest(sample)
    obligation = {
        "obligation_id": f"proof-head-obligation-{suffix}",
        "obligation_type": obligation_type,
        "legal_ir_view": "deontic.ir",
        "statement": "The fictional notice exception has the selected scope.",
    }
    target = ProofFeedbackTrainingTarget(
        sample_id=sample.sample_id,
        sample_sha256=sample_sha256,
        obligation_id=obligation["obligation_id"],
        obligation_type=obligation["obligation_type"],
        legal_ir_view=obligation["legal_ir_view"],
        formal_obligation_sha256=proof_feedback_content_digest(obligation),
        reviewed_target_sha256=proof_feedback_content_digest({
            "interpretation_id": "fictional-selected-proof-head-interpretation",
            "sample_sha256": sample_sha256,
        }),
        dependency_manifest_sha256=proof_feedback_content_digest({
            "fictional-proof-head-exception-definition": "revision-1",
        }),
    )
    fixture_record = _record(
        suffix,
        obligation_id=target.obligation_id,
        obligation_type=target.obligation_type,
        legal_ir_view=target.legal_ir_view,
        obligation_digest=target.obligation_digest,
        **options,
    )
    target = replace(target, expected_feedback_record_id=fixture_record.record_id)
    offered_record = LegalIRProofFeedbackRecord.from_dict(fixture_record.to_dict())
    return offered_record, target


def test_architecture_declares_all_bounded_isolated_heads() -> None:
    autoencoder = AdaptiveModalAutoencoder()

    architecture = autoencoder.proof_auxiliary_head_architecture()

    assert architecture["architecture_version"] == MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    assert architecture["schema_version"] == PROOF_AUXILIARY_HEAD_SCHEMA_VERSION
    assert tuple(architecture["heads"]) == PROOF_AUXILIARY_HEAD_NAMES
    assert architecture["head_count"] == 7
    assert all(
        head["max_labels"] <= PROOF_AUXILIARY_MAX_LABELS_PER_HEAD
        for head in architecture["heads"].values()
    )
    assert architecture["objective_isolation"] == {
        "proof_loss_weight_in_primary_objective": 0.0,
        "protected_objectives": list(PROOF_AUXILIARY_PROTECTED_OBJECTIVES),
        "separate_parameters": True,
    }


def test_trusted_version_matched_feedback_trains_every_head_and_reports_family_metrics(current_proof_sample) -> None:
    versions = _versions()
    positive, positive_target = _bound_record(current_proof_sample, "positive", versions=versions)
    contract_failure, contract_target = _bound_record(
        current_proof_sample,
        "contract",
        versions=versions,
        deterministic_trusted=False,
        route_statuses={},
        backend_outcomes={},
        minimal_failing_contract={
            "contract_id": "legal-ir-view/deontic-ir/v1",
            "failure_code": "missing_exception_scope",
            "failing_fields": ["formulas.exceptions"],
            "deterministic": True,
            "evidence_id": "contract-evidence",
        },
    )
    reconstruction_failure, reconstruction_target = _bound_record(
        current_proof_sample,
        "reconstruction",
        versions=versions,
        deterministic_trusted=False,
        route_statuses={},
        backend_outcomes={},
        kernel_reconstruction=KernelReconstructionFeedback(
            status="verification_failed",
            attempted=True,
            verified=False,
            checker="lean-kernel-test",
            receipt_id="kernel-failure-receipt",
        ),
    )
    autoencoder = AdaptiveModalAutoencoder(proof_head_abstention_threshold=0.0)

    report = autoencoder.train_proof_auxiliary_heads(
        [positive, contract_failure, reconstruction_failure],
        current_proof_targets={
            target.obligation_id: target
            for target in (positive_target, contract_target, reconstruction_target)
        },
        expected_versions=versions,
        learning_rate=0.5,
    )

    assert report["status"] == "applied"
    assert report["applied_count"] == 3
    assert report["proof_feedback_version_fingerprint"] == versions.fingerprint
    assert set(report["head_update_counts"]) == set(PROOF_AUXILIARY_HEAD_NAMES)
    assert all(value == 3 for value in report["head_update_counts"].values())
    assert report["record_count"] == 3
    assert report["loss"] >= 0.0
    assert report["calibration_error"] >= 0.0
    assert report["coverage"] == pytest.approx(1.0)
    assert report["abstention_rate"] == pytest.approx(0.0)
    assert set(report["by_legal_ir_family"]) == {"deontic"}
    family = report["by_legal_ir_family"]["deontic"]
    assert family["record_count"] == 3
    assert set(family["heads"]) == set(PROOF_AUXILIARY_HEAD_NAMES)
    assert report["per_family_loss"]["deontic"] == family["loss"]
    assert report["calibration_by_family"]["deontic"] == family["calibration_error"]

    prediction = autoencoder.predict_proof_auxiliary_heads(
        "deontic.ir",
        abstention_threshold=0.0,
    )
    assert prediction["bounded"] is True
    assert set(prediction["heads"]) == set(PROOF_AUXILIARY_HEAD_NAMES)
    assert (
        "failure:missing_exception_scope"
        in prediction["heads"]["minimal_failing_contract"]["probabilities"]
    )
    assert set(prediction["heads"]["reconstruction_success"]["probabilities"]) == {
        "success",
        "failure",
        "not_attempted",
    }


def test_untrusted_stale_holdout_invalid_and_duplicate_feedback_never_train(current_proof_sample) -> None:
    versions = _versions()
    trusted, target = _bound_record(current_proof_sample, "trusted", versions=versions)
    targets = {target.obligation_id: target}
    untrusted = _record(
        "untrusted",
        versions=versions,
        deterministic_trusted=False,
        route_statuses={},
        backend_outcomes={},
    )
    stale = _record("stale", versions=_versions("compiler-stale"))
    holdout = _record(
        "holdout",
        versions=versions,
        partition_policy=ProofFeedbackPartitionPolicy(holdout_fraction=1.0),
    )
    tampered = trusted.to_dict()
    tampered["obligation_type"] = "tampered_after_addressing"
    autoencoder = AdaptiveModalAutoencoder()

    report = autoencoder.train_proof_auxiliary_heads(
        [trusted, untrusted, stale, holdout, tampered],
        current_proof_targets=targets,
        expected_versions=versions,
    )
    duplicate = autoencoder.apply_proof_feedback(
        [trusted],
        current_proof_targets=targets,
        expected_versions=versions,
    )

    assert report["applied_count"] == 1
    assert report["skipped_untrusted_count"] == 1
    assert report["skipped_version_mismatch_count"] == 1
    assert report["skipped_holdout_count"] == 1
    assert report["skipped_invalid_count"] == 1
    assert duplicate["applied_count"] == 0
    assert duplicate["duplicate_count"] == 1
    assert autoencoder.state.applied_proof_feedback_ids == [trusted.record_id]


def test_proof_updates_cannot_override_primary_objective_parameters(current_proof_sample) -> None:
    state = ModalAutoencoderTrainingState(
        decoded_embeddings={"sample": [0.1, 0.2]},
        family_logits={"sample": {"deontic": 0.4}},
        feature_embedding_weights={
            "structural:contract": [0.3, -0.2],
            "provenance-alignment:exact": [0.1, 0.1],
        },
        feature_family_logits={"compiler:ce": {"deontic": 0.8}},
        legal_ir_view_logits={"deontic.ir": 0.7},
    )
    autoencoder = AdaptiveModalAutoencoder(state=state)
    before = state.to_dict()

    record, target = _bound_record(current_proof_sample, "isolation")
    report = autoencoder.train_proof_feedback_heads(
        [record],
        current_proof_targets={target.obligation_id: target},
        expected_versions=_versions(),
        learning_rate=1.0,
    )
    assert report["applied_count"] == 1
    after = state.to_dict()

    for key in (
        "decoded_embeddings",
        "family_logits",
        "feature_embedding_weights",
        "feature_family_logits",
        "legal_ir_view_logits",
    ):
        assert after[key] == before[key]
    assert report["objective_isolation"]["separate_parameters"] is True
    assert report["objective_isolation"]["protected_parameters_unchanged"] is True
    assert report["objective_isolation"]["proof_loss_weight_in_primary_objective"] == 0.0


def test_head_vocabulary_is_bounded_under_many_trusted_labels(current_proof_sample) -> None:
    versions = _versions()
    bound_records = [
        _bound_record(
            current_proof_sample,
            str(index),
            versions=versions,
            obligation_type=f"obligation_family_{index:03d}",
        )
        for index in range(12)
    ]
    autoencoder = AdaptiveModalAutoencoder(proof_head_max_labels=3)

    report = autoencoder.train_proof_auxiliary_heads(
        [record for record, _ in bound_records],
        current_proof_targets={target.obligation_id: target for _, target in bound_records},
        expected_versions=versions,
        learning_rate=0.2,
    )
    prediction = autoencoder.predict_proof_auxiliary_heads("deontic.ir")

    assert report["applied_count"] == 12
    assert report["dropped_label_count"] > 0
    assert len(prediction["heads"]["obligation_family"]["probabilities"]) <= 3
    assert all(
        len(logits) <= 3
        for contexts in autoencoder.state.proof_auxiliary_head_logits.values()
        for logits in contexts.values()
    )


def test_architecture_and_proof_heads_serialize_with_legacy_compatibility(tmp_path, current_proof_sample) -> None:
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    record, target = _bound_record(current_proof_sample, "serialize", versions=versions)
    autoencoder.train_proof_auxiliary_heads(
        [record],
        current_proof_targets={target.obligation_id: target},
        expected_versions=versions,
    )
    path = tmp_path / "proof-aware-state.json"
    autoencoder.state.save_json(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    restored = ModalAutoencoderTrainingState.load_json(path)
    legacy = ModalAutoencoderTrainingState.from_dict(
        {
            "architecture_version": MODAL_AUTOENCODER_LEGACY_ARCHITECTURE_VERSION,
            "feature_embedding_weights": {"legacy-feature": [0.1, 0.2]},
        }
    )

    assert payload["architecture_version"] == MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    assert payload["proof_auxiliary_head_schema_version"] == PROOF_AUXILIARY_HEAD_SCHEMA_VERSION
    assert restored.to_dict() == autoencoder.state.to_dict()
    assert restored.proof_feedback_version_fingerprint == versions.fingerprint
    assert restored.proof_auxiliary_head_logits
    assert legacy.architecture_version == MODAL_AUTOENCODER_ARCHITECTURE_VERSION
    assert legacy.feature_embedding_weights == {"legacy-feature": [0.1, 0.2]}

    with pytest.raises(ValueError, match="unsupported modal autoencoder architecture"):
        ModalAutoencoderTrainingState.from_dict(
            {"architecture_version": "unknown-future-architecture"}
        )
