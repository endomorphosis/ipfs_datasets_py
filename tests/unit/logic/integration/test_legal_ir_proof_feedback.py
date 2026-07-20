"""Tests for versioned, source-free Legal IR proof-feedback records."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerPremise,
    HammerResult,
    HammerStatus,
    PremiseSelection,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION,
    KernelReconstructionFeedback,
    LegalIRProofFeedbackRecord,
    MinimalFailingContractFeedback,
    ProofFeedbackError,
    ProofFeedbackIntegrityError,
    ProofFeedbackLabel,
    ProofFeedbackPartition,
    ProofFeedbackPartitionPolicy,
    ProofFeedbackStore,
    ProofFeedbackTrustStatus,
    ProofFeedbackVersions,
    VerifiedCounterexampleFeedback,
    build_legal_ir_proof_feedback_record,
    deterministic_proof_feedback_partition,
    load_proof_feedback_jsonl,
    write_proof_feedback_jsonl,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_router import (
    LegalIRProofRouteResult,
    ProofRouteAttempt,
    ProofRouteStage,
    ProofRouteStatus,
    ProofTrustLevel,
)


RAW_LEGAL_TEXT = "The Secretary shall publish every applicant's confidential filing."
RAW_LEANSTRAL_ASSERTION = "Leanstral says exact proof: by simpa using secret_statute"


def _versions(compiler: str = "compiler-2026.07") -> ProofFeedbackVersions:
    return ProofFeedbackVersions(
        compiler_version=compiler,
        solver_toolchain_version="z3-4.13.0",
        lean_toolchain_version="lean-4.19.0",
        theorem_registry_version="legal-ir-theorems-7",
    )


def _trusted_record(**overrides) -> LegalIRProofFeedbackRecord:
    values = {
        "obligation_id": "lir-obligation-abc",
        "obligation_type": "exception_scope",
        "legal_ir_view": "deontic.ir",
        "semantic_family": "conditional_normative",
        "semantic_slots": {
            "actor": "The Secretary",
            "condition": ["after receiving the confidential filing"],
            "exception": "present",
        },
        "selected_premise_families": ("theorem_template", "sample_local_assumption"),
        "route_availability": {"deterministic_contract": True, "native_lean_reconstruction": True},
        "route_statuses": {"deterministic_contract": "passed"},
        "backend_outcomes": {"z3": "proved"},
        "deterministic_trusted": True,
        "repair_label": "exception_scope_projection",
        "evidence_ids": ("evidence-contract-17",),
        "receipt_ids": ("receipt-deterministic-17",),
        "partition_key": "sample-private-17",
        "versions": _versions(),
    }
    values.update(overrides)
    return LegalIRProofFeedbackRecord.create(**values)


def test_content_address_is_stable_and_record_is_source_free() -> None:
    obligation = {
        "obligation_id": "lir-obligation-source-free",
        "kind": "deontic_polarity",
        "legal_ir_view": "deontic.ir",
        "logic_family": "deontic",
        "sample_id": "sample-source-free",
        "statement": RAW_LEGAL_TEXT,
        "metadata": {
            "semantic_slots": {"actor": "The Secretary", "action": "publish the filing"},
            "repair_label": "operator_polarity",
        },
    }
    first = build_legal_ir_proof_feedback_record(
        obligation,
        deterministic_trusted=True,
        evidence_ids=("evidence-1",),
        receipt_ids=("receipt-1",),
        versions=_versions(),
        unverified_leanstral_assertions=RAW_LEANSTRAL_ASSERTION,
    )
    second = build_legal_ir_proof_feedback_record(
        obligation,
        deterministic_trusted=True,
        evidence_ids=("evidence-1",),
        receipt_ids=("receipt-1",),
        versions=_versions(),
        unverified_leanstral_assertions="a completely different unverified claim",
    )

    payload = first.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    assert first.record_id == second.record_id
    assert first.record_id == f"legal-ir-proof-feedback-{first.content_hash}"
    assert payload["schema_version"] == LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION
    assert payload["semantic_slots"] == {"action": "present", "actor": "present"}
    assert set(payload["semantic_slot_value_digests"]) == {"action", "actor"}
    assert RAW_LEGAL_TEXT not in encoded
    assert "The Secretary" not in encoded
    assert "publish the filing" not in encoded
    assert RAW_LEANSTRAL_ASSERTION not in encoded
    assert "statement" not in payload
    assert "proof_script" not in payload
    assert "raw_output" not in payload
    assert payload["evidence_ids"] == ["evidence-1"]
    assert payload["receipt_ids"] == ["receipt-1"]


def test_kernel_receipt_is_the_only_positive_authority_for_backend_proof() -> None:
    kernel = KernelReconstructionFeedback(
        status="verified",
        attempted=True,
        verified=True,
        checker="lean-kernel-4.19",
        receipt_id="hammer-receipt-kernel-1",
    )
    record = _trusted_record(
        deterministic_trusted=False,
        route_statuses={"smt_atp_portfolio": "proved", "native_lean_reconstruction": "proved"},
        kernel_reconstruction=kernel,
    )

    assert record.training_label == ProofFeedbackLabel.KERNEL_OR_DETERMINISTIC_TRUSTED
    assert record.trust_status == ProofFeedbackTrustStatus.TRUSTED
    assert record.eligible_for_training is True
    assert record.positive is True
    assert "hammer-receipt-kernel-1" in record.receipt_ids

    backend_only = LegalIRProofFeedbackRecord.create(
        obligation_id="backend-only",
        obligation_type="external_prover",
        legal_ir_view="external_provers.router",
        semantic_family="proof_translation",
        route_availability={"smt_atp_portfolio": True},
        route_statuses={"smt_atp_portfolio": "proved"},
        backend_outcomes={"vampire": "proved"},
        versions=_versions(),
    )
    assert backend_only.training_label == ProofFeedbackLabel.NO_TRUSTED_SIGNAL
    assert backend_only.trust_status == ProofFeedbackTrustStatus.UNTRUSTED
    assert backend_only.eligible_for_training is False


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "counterexample": {
                    "kind": "finite_model",
                    "witness": RAW_LEGAL_TEXT,
                    "verified": True,
                    "verifier": "cec-model-checker",
                    "evidence_ids": ["counterexample-evidence-1"],
                    "receipt_id": "cec-receipt-1",
                }
            },
            ProofFeedbackLabel.VERIFIED_COUNTEREXAMPLE,
        ),
        (
            {
                "minimal_failing_contract": {
                    "contract_id": "legal-ir-view/deontic-ir/v1",
                    "failure_code": "missing_exception_scope",
                    "failing_fields": ["formulas.exceptions"],
                    "deterministic": True,
                    "evidence_id": "contract-evidence-1",
                }
            },
            ProofFeedbackLabel.CONTRACT_FAILURE,
        ),
        (
            {
                "kernel_reconstruction": KernelReconstructionFeedback(
                    status="verification_failed",
                    attempted=True,
                    verified=False,
                    checker="lean-kernel-4.19",
                    receipt_id="lean-failure-receipt-1",
                )
            },
            ProofFeedbackLabel.RECONSTRUCTION_FAILURE,
        ),
        (
            {
                "route_availability": {"smt_atp_portfolio": False},
                "route_statuses": {"smt_atp_portfolio": "unsupported_translation"},
            },
            ProofFeedbackLabel.UNSUPPORTED_TRANSLATION,
        ),
    ],
)
def test_all_verified_negative_labels_are_training_eligible(kwargs, expected) -> None:
    record = LegalIRProofFeedbackRecord.create(
        obligation_id=f"negative-{expected.value}",
        obligation_type="proof_failure",
        legal_ir_view="external_provers.router",
        semantic_family="proof_translation",
        repair_label="bounded_failure_repair",
        versions=_versions(),
        **kwargs,
    )
    encoded = json.dumps(record.to_dict(), sort_keys=True)

    assert record.training_label == expected
    assert record.trust_status == ProofFeedbackTrustStatus.TRUSTED
    assert record.eligible_for_training is True
    assert RAW_LEGAL_TEXT not in encoded


def test_unverified_counterexample_and_leanstral_claim_cannot_become_labels() -> None:
    record = LegalIRProofFeedbackRecord.create(
        obligation_id="unverified-claim",
        obligation_type="candidate_audit",
        legal_ir_view="deontic.ir",
        semantic_family="deontic",
        counterexample={
            "verified": False,
            "witness": RAW_LEGAL_TEXT,
            "assertion": RAW_LEANSTRAL_ASSERTION,
        },
        versions=_versions(),
    )

    assert record.counterexample is None
    assert record.training_label == ProofFeedbackLabel.NO_TRUSTED_SIGNAL
    assert record.eligible_for_training is False
    encoded = json.dumps(record.to_dict())
    assert RAW_LEGAL_TEXT not in encoded
    assert RAW_LEANSTRAL_ASSERTION not in encoded


def test_result_projection_extracts_only_categorical_route_backend_and_premise_data() -> None:
    premise = HammerPremise(
        name="secret_statute_premise",
        statement=RAW_LEGAL_TEXT,
        metadata={"premise_kind": "theorem_template", "source_text": RAW_LEGAL_TEXT},
    )
    hammer_result = HammerResult(
        status=HammerStatus.PROVED,
        goal=HammerGoal(RAW_LEGAL_TEXT, name="goal-source-free"),
        premise_selection=PremiseSelection(
            selected=[premise], scores={premise.name: 1.0}, considered_count=1, max_premises=1
        ),
        translations={},
        backend_results=[
            HammerBackendResult(
                backend="z3",
                status=HammerBackendStatus.PROVED,
                proved=True,
                elapsed_seconds=0.01,
                translation_format="smt-lib",
                proof_trace=RAW_LEANSTRAL_ASSERTION,
                raw_output=RAW_LEGAL_TEXT,
            )
        ],
    )
    attempts = (
        ProofRouteAttempt(
            stage=ProofRouteStage.DETERMINISTIC,
            route="deterministic_contract",
            status=ProofRouteStatus.PASSED,
            trust_level=ProofTrustLevel.DETERMINISTIC,
            allocated_seconds=0.1,
        ),
        ProofRouteAttempt(
            stage=ProofRouteStage.SMT_ATP,
            route="smt_atp_portfolio",
            status=ProofRouteStatus.PROVED,
            trust_level=ProofTrustLevel.BACKEND,
            allocated_seconds=1.0,
        ),
    )
    route_result = LegalIRProofRouteResult(
        obligation_id="lir-obligation-projected",
        status=ProofRouteStatus.PROVED,
        trust_level=ProofTrustLevel.DETERMINISTIC,
        required_trust=ProofTrustLevel.DETERMINISTIC,
        attempts=attempts,
        hammer_result=hammer_result,
        elapsed_seconds=0.02,
        stop_reason="trust_satisfied",
    )
    record = build_legal_ir_proof_feedback_record(
        {
            "obligation_id": "lir-obligation-projected",
            "kind": "contract_preservation",
            "legal_ir_view": "deontic.ir",
            "logic_family": "deontic",
            "sample_id": "sample-projected",
            "statement": RAW_LEGAL_TEXT,
        },
        route_result=route_result,
        versions=_versions(),
    )
    encoded = json.dumps(record.to_dict(), sort_keys=True)

    assert record.selected_premise_families == ("theorem_template",)
    assert record.route_availability == {
        "deterministic_contract": True,
        "smt_atp_portfolio": True,
    }
    assert record.route_statuses["deterministic_contract"] == "passed"
    assert record.backend_outcomes == {"z3": "proved"}
    assert record.deterministic_trusted is True
    assert record.training_label == ProofFeedbackLabel.KERNEL_OR_DETERMINISTIC_TRUSTED
    assert RAW_LEGAL_TEXT not in encoded
    assert RAW_LEANSTRAL_ASSERTION not in encoded
    assert "secret_statute_premise" not in encoded


def test_round_trip_detects_tampering_and_unknown_source_fields() -> None:
    record = _trusted_record()
    assert LegalIRProofFeedbackRecord.from_dict(record.to_dict()) == record

    tampered = record.to_dict()
    tampered["repair_label"] = "different_repair"
    with pytest.raises(ProofFeedbackIntegrityError, match="record_id"):
        LegalIRProofFeedbackRecord.from_dict(tampered)

    unsafe = record.to_dict()
    unsafe["raw_legal_text"] = RAW_LEGAL_TEXT
    with pytest.raises(ProofFeedbackError, match="unknown proof-feedback fields"):
        LegalIRProofFeedbackRecord.from_dict(unsafe)


def test_partitioning_is_deterministic_grouped_and_policy_versioned() -> None:
    train_policy = ProofFeedbackPartitionPolicy(holdout_fraction=0.0, salt="frozen-corpus-a")
    holdout_policy = ProofFeedbackPartitionPolicy(holdout_fraction=1.0, salt="frozen-corpus-a")
    assert train_policy.assign("sample-a") == ProofFeedbackPartition.TRAIN
    assert holdout_policy.assign("sample-a") == ProofFeedbackPartition.HOLDOUT
    assert deterministic_proof_feedback_partition(
        "sample-a", holdout_fraction=1.0, salt="frozen-corpus-a"
    ) == ProofFeedbackPartition.HOLDOUT

    first = _trusted_record(partition_key="same-private-sample")
    second = _trusted_record(
        obligation_id="another-obligation-for-sample",
        partition_key="same-private-sample",
    )
    assert first.partition_key_digest == second.partition_key_digest
    assert first.partition == second.partition
    assert "same-private-sample" not in json.dumps(first.to_dict())


def test_store_persists_idempotently_and_replays_in_content_order(tmp_path) -> None:
    first = _trusted_record(obligation_id="record-z")
    second = _trusted_record(obligation_id="record-a")
    stale = _trusted_record(obligation_id="record-stale", versions=_versions("compiler-old"))
    store = ProofFeedbackStore(tmp_path / "proof-feedback")

    assert store.put(first) is True
    assert store.put(first) is False
    assert store.put_many([second, stale]) == 2
    assert store.get(first.record_id) == first

    replay = store.replay(versions=_versions(), trusted_only=True)
    assert [item.record_id for item in replay.records] == sorted([first.record_id, second.record_id])
    assert stale.record_id not in replay.to_dict()["record_ids"]
    assert replay.replay_id == store.replay(versions=_versions(), trusted_only=True).replay_id

    exported = tmp_path / "replay.jsonl"
    exported_replay = store.export_jsonl(exported, versions=_versions(), trusted_only=True)
    assert exported_replay.replay_id == replay.replay_id
    assert load_proof_feedback_jsonl(exported) == replay.records

    other_export = tmp_path / "ordered.jsonl"
    written = write_proof_feedback_jsonl(other_export, [second, first])
    assert written.replay_id == replay.replay_id
    assert load_proof_feedback_jsonl(other_export) == replay.records


def test_verified_artifact_types_round_trip_without_witness_values() -> None:
    counterexample = VerifiedCounterexampleFeedback.from_verified(
        {
            "kind": "finite_model",
            "witness": {"raw_source": RAW_LEGAL_TEXT, "assignment": "private party"},
            "verifier": "cec",
            "verified": True,
            "evidence_ids": ["evidence-cec"],
        }
    )
    contract = MinimalFailingContractFeedback.from_verified(
        {
            "contract_id": "legal-ir-view/deontic-ir/v1",
            "failure_code": "polarity_mismatch",
            "failing_fields": ["formulas.operator.symbol"],
            "deterministic": True,
        }
    )

    assert counterexample is not None
    assert len(counterexample.witness_digest) == 64
    assert VerifiedCounterexampleFeedback.from_dict(counterexample.to_dict()) == counterexample
    assert contract is not None
    assert MinimalFailingContractFeedback.from_dict(contract.to_dict()) == contract
    assert RAW_LEGAL_TEXT not in json.dumps(counterexample.to_dict())
