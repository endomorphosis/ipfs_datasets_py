"""Regression tests for closed IPS-005 evidence classes, modes, kinds, statuses."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import (
    EVIDENCE_SUBSET,
    DirectExecutionProof,
    EvidenceClass,
    EvidenceClassError,
    IncrementalCommitSeal,
    IntegrityCommitment,
    ProofMode,
    ProofTerminalStatus,
    ProofUnitKind,
    ReceiptAggregationZkProof,
    SealStatus,
    SignedExecutionReceipt,
    assert_production_seal_allowed,
    closed_evidence_class_names,
    closed_proof_mode_values,
    closed_proof_unit_kind_values,
    closed_seal_status_values,
    closed_terminal_status_values,
    evidence_from_canonical,
    parse_proof_mode,
    parse_proof_unit_kind,
    parse_seal_status,
    parse_terminal_status,
    production_seal_allowed,
    require_direct_execution_for_claim,
    status_satisfies_class,
)

_DIGEST = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)
_DIGEST_C = "sha256:" + ("ef" * 32)


def test_closed_sets_match_the_plan() -> None:
    assert closed_proof_mode_values() == {
        "direct_execution_proof",
        "theorem_certificate",
        "signed_receipt",
        "receipt_aggregation",
        "integrity_only",
        "simulated",
    }
    assert closed_proof_unit_kind_values() == {
        "static_analysis",
        "type_check",
        "unit_test",
        "integration_test",
        "property_test",
        "formal_obligation",
        "direct_zk_computation",
        "receipt_aggregation",
        "release_invariant",
    }
    assert "proved" in closed_terminal_status_values()
    assert "integrity_verified" in closed_terminal_status_values()
    assert "signed_assertion_verified" in closed_terminal_status_values()
    assert "passed" not in closed_terminal_status_values()
    assert closed_seal_status_values() >= {
        "sealed_full",
        "sealed_incremental",
        "simulated_only",
        "full_reproof_required",
    }
    assert closed_evidence_class_names() == {
        "IntegrityCommitment",
        "SignedExecutionReceipt",
        "ReceiptAggregationZkProof",
        "DirectExecutionProof",
        "IncrementalCommitSeal",
    }
    assert EVIDENCE_SUBSET == "ips/proof-evidence-classes@1"


def test_unknown_mode_kind_and_status_are_rejected() -> None:
    with pytest.raises(EvidenceClassError, match="unknown ProofMode"):
        parse_proof_mode("zk_verified")
    with pytest.raises(EvidenceClassError, match="unknown ProofUnitKind"):
        parse_proof_unit_kind("generic_test")
    with pytest.raises(EvidenceClassError, match="unknown ProofTerminalStatus"):
        parse_terminal_status("passed")
    with pytest.raises(EvidenceClassError, match="unknown SealStatus"):
        parse_seal_status("ok")


@pytest.mark.parametrize(
    "enum_cls, parser",
    [
        (ProofMode, parse_proof_mode),
        (ProofUnitKind, parse_proof_unit_kind),
        (ProofTerminalStatus, parse_terminal_status),
        (SealStatus, parse_seal_status),
    ],
)
def test_closed_enums_round_trip(enum_cls, parser) -> None:
    for item in enum_cls:
        assert parser(item.value) is item
        assert parser(item) is item


def test_integrity_commitment_round_trip_and_nonclaim() -> None:
    record = IntegrityCommitment(
        digest=_DIGEST,
        cid=_DIGEST_B,
        merkle_inclusion="leaf:0",
        byte_length=16,
    )
    payload = json.loads(record.to_canonical_json())
    restored = IntegrityCommitment.from_canonical(payload)
    assert restored == record
    assert "execution" in record.DOES_NOT_ESTABLISH
    assert payload["evidence_class"] == "IntegrityCommitment"


def test_signed_receipt_does_not_establish_independent_execution() -> None:
    record = SignedExecutionReceipt(
        signer_id="allowlist/operator-1",
        receipt_digest=_DIGEST,
        signature="ed25519:sig",
        statement="pytest ran",
    )
    restored = SignedExecutionReceipt.from_canonical(record.to_canonical())
    assert restored == record
    assert "without trusting the signer" in record.DOES_NOT_ESTABLISH


def test_receipt_aggregation_requires_sorted_unique_digests() -> None:
    record = ReceiptAggregationZkProof(
        circuit_id="agg@v1",
        receipt_digests=(_DIGEST, _DIGEST_B),
        proof_cid=_DIGEST_C,
    )
    assert ReceiptAggregationZkProof.from_canonical(record.to_canonical()) == record
    with pytest.raises(EvidenceClassError, match="sorted"):
        ReceiptAggregationZkProof(
            circuit_id="agg@v1",
            receipt_digests=(_DIGEST_B, _DIGEST),
            proof_cid=_DIGEST_C,
        )


def test_direct_execution_is_the_only_direct_computation_claim() -> None:
    record = DirectExecutionProof(
        program_id="verifier/main",
        input_commitment=_DIGEST,
        output_commitment=_DIGEST_B,
        proof_system_id="groth16",
        proof_cid=_DIGEST_C,
    )
    payload = record.to_canonical()
    assert payload["direct_computation_claim"] is True
    assert DirectExecutionProof.from_canonical(payload) == record
    integrity = IntegrityCommitment(
        digest=_DIGEST,
        cid=_DIGEST_B,
        merkle_inclusion="leaf:0",
        byte_length=4,
    ).to_canonical()
    integrity["direct_computation_claim"] = True
    with pytest.raises(EvidenceClassError, match="DirectExecutionProof"):
        require_direct_execution_for_claim(integrity)
    assert require_direct_execution_for_claim(payload) == record


def test_incremental_seal_round_trip() -> None:
    record = IncrementalCommitSeal(
        parent_seal_cid=_DIGEST,
        transition_id="delta:1",
        reused_leaf_cids=(_DIGEST_B,),
        replacement_leaf_cids=(),
        manifest_cid=_DIGEST_C,
        verification_root=_DIGEST,
    )
    assert IncrementalCommitSeal.from_canonical(record.to_canonical()) == record


def test_generic_overclaims_are_rejected() -> None:
    payload = IntegrityCommitment(
        digest=_DIGEST,
        cid=_DIGEST_B,
        merkle_inclusion="leaf:0",
        byte_length=1,
    ).to_canonical()
    payload["zk_verified"] = True
    with pytest.raises(EvidenceClassError, match="overclaim"):
        evidence_from_canonical(payload)
    with pytest.raises(EvidenceClassError, match="unknown evidence class"):
        evidence_from_canonical({"evidence_class": "GenericZkProof", "digest": _DIGEST})


def test_simulated_mode_cannot_produce_production_seals() -> None:
    assert production_seal_allowed(ProofMode.SIMULATED, SealStatus.SIMULATED_ONLY)
    assert not production_seal_allowed(ProofMode.SIMULATED, SealStatus.SEALED_FULL)
    assert not production_seal_allowed(ProofMode.SIMULATED, SealStatus.SEALED_INCREMENTAL)
    with pytest.raises(EvidenceClassError, match="simulated_only"):
        assert_production_seal_allowed(ProofMode.SIMULATED, SealStatus.SEALED_FULL)
    assert production_seal_allowed(
        ProofMode.DIRECT_EXECUTION_PROOF, SealStatus.SEALED_FULL
    )


def test_terminal_status_acceptance_is_class_specific() -> None:
    assert status_satisfies_class(
        ProofTerminalStatus.INTEGRITY_VERIFIED,
        EvidenceClass.INTEGRITY_COMMITMENT,
    )
    assert not status_satisfies_class(
        ProofTerminalStatus.INTEGRITY_VERIFIED,
        EvidenceClass.DIRECT_EXECUTION_PROOF,
    )
    assert status_satisfies_class(
        ProofTerminalStatus.SIGNED_ASSERTION_VERIFIED,
        EvidenceClass.SIGNED_EXECUTION_RECEIPT,
    )
    assert not status_satisfies_class(
        ProofTerminalStatus.SIGNED_ASSERTION_VERIFIED,
        EvidenceClass.INTEGRITY_COMMITMENT,
    )
    assert status_satisfies_class(
        ProofTerminalStatus.PROVED,
        EvidenceClass.DIRECT_EXECUTION_PROOF,
    )
    assert not status_satisfies_class(
        ProofTerminalStatus.PROVED,
        EvidenceClass.INTEGRITY_COMMITMENT,
    )
    assert not status_satisfies_class(
        ProofTerminalStatus.FAILED,
        EvidenceClass.INTEGRITY_COMMITMENT,
    )
