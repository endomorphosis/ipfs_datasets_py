"""Proof-aware auxiliary head tests for the modal autoencoder."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    KernelReconstructionFeedback,
    LegalIRProofFeedbackRecord,
    ProofFeedbackPartitionPolicy,
    ProofFeedbackVersions,
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
        "partition_policy": partition_policy
        or ProofFeedbackPartitionPolicy(holdout_fraction=0.0),
        "versions": versions or _versions(),
    }
    values.update(overrides)
    return LegalIRProofFeedbackRecord.create(**values)


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


def test_trusted_version_matched_feedback_trains_every_head_and_reports_family_metrics() -> None:
    versions = _versions()
    positive = _record("positive", versions=versions)
    contract_failure = _record(
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
    reconstruction_failure = _record(
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
    assert set(
        prediction["heads"]["reconstruction_success"]["probabilities"]
    ) == {"failure", "not_attempted"}


def test_untrusted_stale_holdout_invalid_and_duplicate_feedback_never_train() -> None:
    versions = _versions()
    trusted = _record("trusted", versions=versions)
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
        expected_versions=versions,
    )
    duplicate = autoencoder.apply_proof_feedback(
        [trusted],
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


def test_proof_updates_cannot_override_primary_objective_parameters() -> None:
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

    report = autoencoder.train_proof_feedback_heads(
        [_record("isolation")],
        expected_versions=_versions(),
        learning_rate=1.0,
    )
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


def test_head_vocabulary_is_bounded_under_many_trusted_labels() -> None:
    versions = _versions()
    records = [
        _record(
            str(index),
            versions=versions,
            obligation_type=f"obligation_family_{index:03d}",
        )
        for index in range(12)
    ]
    autoencoder = AdaptiveModalAutoencoder(proof_head_max_labels=3)

    report = autoencoder.train_proof_auxiliary_heads(
        records,
        expected_versions=versions,
        learning_rate=0.2,
    )
    prediction = autoencoder.predict_proof_auxiliary_heads("deontic.ir")

    assert report["applied_count"] == 12
    assert report["dropped_label_count"] > 0
    assert len(
        prediction["heads"]["obligation_family"]["probabilities"]
    ) <= 3
    assert all(
        len(logits) <= 3
        for contexts in autoencoder.state.proof_auxiliary_head_logits.values()
        for logits in contexts.values()
    )


def test_architecture_and_proof_heads_serialize_with_legacy_compatibility(tmp_path) -> None:
    versions = _versions()
    autoencoder = AdaptiveModalAutoencoder()
    autoencoder.train_proof_auxiliary_heads(
        [_record("serialize", versions=versions)],
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
