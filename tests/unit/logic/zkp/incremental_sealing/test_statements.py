"""Regression tests for canonical proof statements (IPS-010)."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import EvidenceClass
from ipfs_datasets_py.logic.zkp.incremental_sealing.statements import (
    DOMAIN_DIRECT_EXECUTION,
    DOMAIN_RECEIPT_AGGREGATION,
    STATEMENTS_SUBSET,
    CanonicalProofStatement,
    DirectExecutionStatement,
    ForestTransitionStatement,
    PrivateInputCommitment,
    PublicInputDeclaration,
    PublicInputField,
    ReceiptAggregationStatement,
    StatementError,
    StatementKind,
    build_direct_execution_statement,
    build_forest_transition_statement,
    build_receipt_aggregation_statement,
    closed_statement_kind_values,
    parse_statement_kind,
    sample_direct_execution_statement,
    sample_forest_transition_statement,
    sample_receipt_aggregation_statement,
    statement_from_canonical,
)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Closed sets and domain separation
# ---------------------------------------------------------------------------


def test_statement_subset_and_closed_kinds() -> None:
    assert STATEMENTS_SUBSET == "ips/canonical-statements@1"
    assert closed_statement_kind_values() == {
        "canonical",
        "direct_execution",
        "receipt_aggregation",
        "forest_transition",
    }
    with pytest.raises(StatementError, match="unknown StatementKind"):
        parse_statement_kind("zk_verified")


def test_domain_separators_are_distinct() -> None:
    direct = sample_direct_execution_statement()
    aggregation = sample_receipt_aggregation_statement()
    forest = sample_forest_transition_statement()
    assert direct.domain_separator == DOMAIN_DIRECT_EXECUTION
    assert aggregation.domain_separator == DOMAIN_RECEIPT_AGGREGATION
    assert direct.domain_separator != aggregation.domain_separator
    assert forest.domain_separator not in {
        direct.domain_separator,
        aggregation.domain_separator,
    }
    assert direct.statement_cid() != aggregation.statement_cid()
    assert direct.statement_cid() != forest.statement_cid()


# ---------------------------------------------------------------------------
# Acceptance: receipt aggregation cannot serialize a direct-execution claim
# ---------------------------------------------------------------------------


def test_receipt_aggregation_cannot_serialize_direct_execution_claim() -> None:
    aggregation = sample_receipt_aggregation_statement()
    payload = aggregation.to_canonical()
    assert "direct_computation_claim" not in payload
    assert payload["statement_kind"] == "receipt_aggregation"
    assert payload["evidence_class"] == EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value
    assert aggregation.direct_computation_claim is False

    # Injecting a direct-execution claim is rejected on load and refuse helper.
    poisoned = dict(payload)
    poisoned["direct_computation_claim"] = True
    with pytest.raises(StatementError, match="cannot serialize a direct-execution claim"):
        ReceiptAggregationStatement.from_canonical(poisoned)
    with pytest.raises(StatementError, match="cannot serialize a direct-execution claim"):
        ReceiptAggregationStatement.refuse_direct_execution_claim(poisoned)

    # Even an explicit false claim field is rejected: aggregation never speaks it.
    with_false = dict(payload)
    with_false["direct_computation_claim"] = False
    with pytest.raises(StatementError, match="cannot serialize a direct-execution claim"):
        ReceiptAggregationStatement.from_canonical(with_false)

    # A direct-execution payload cannot be loaded as receipt aggregation.
    direct_payload = sample_direct_execution_statement().to_canonical()
    with pytest.raises(StatementError, match="cannot serialize a direct-execution claim"):
        ReceiptAggregationStatement.refuse_direct_execution_claim(direct_payload)
    with pytest.raises(StatementError, match="cannot serialize a direct-execution claim"):
        ReceiptAggregationStatement.from_canonical(direct_payload)


def test_receipt_aggregation_serialize_round_trip() -> None:
    original = sample_receipt_aggregation_statement()
    encoded = original.serialize()
    assert "direct_computation_claim" not in encoded
    restored = ReceiptAggregationStatement.from_canonical(encoded)
    assert restored.statement_cid() == original.statement_cid()
    assert restored.receipt_digests == original.receipt_digests
    assert "underlying tests ran" in restored.DOES_NOT_ESTABLISH
    assert "direct program execution" in restored.DOES_NOT_ESTABLISH


# ---------------------------------------------------------------------------
# Acceptance: direct proof statement binds declared computation
# ---------------------------------------------------------------------------


def test_direct_proof_statement_binds_declared_computation() -> None:
    statement = build_direct_execution_statement(
        program_id="program/sort@v1",
        circuit_id="sort_circuit@v1",
        proof_system_id="groth16",
        input_commitment=_digest("input"),
        output_commitment=_digest("output"),
        private_commitment=_digest("private"),
    )
    assert statement.direct_computation_claim is True
    assert statement.binds_declared_computation() is True
    assert statement.computation_id == "program/sort@v1"
    assert statement.evidence_class is EvidenceClass.DIRECT_EXECUTION_PROOF

    payload = statement.to_canonical()
    assert payload["direct_computation_claim"] is True
    assert payload["program_id"] == "program/sort@v1"
    assert payload["circuit_id"] == "sort_circuit@v1"
    assert payload["input_commitment"] == _digest("input")
    assert payload["output_commitment"] == _digest("output")
    assert payload["proof_system_id"] == "groth16"
    public = payload["public_inputs"]
    bound = {field["name"]: field["value"] for field in public["fields"]}
    assert bound["program_id"] == "program/sort@v1"
    assert bound["circuit_id"] == "sort_circuit@v1"
    assert bound["input_commitment"] == _digest("input")
    assert bound["output_commitment"] == _digest("output")

    # Mutating any declared computation binding changes the statement identity.
    altered = build_direct_execution_statement(
        program_id="program/sort@v2",
        circuit_id="sort_circuit@v1",
        proof_system_id="groth16",
        input_commitment=_digest("input"),
        output_commitment=_digest("output"),
        private_commitment=_digest("private"),
    )
    assert altered.statement_cid() != statement.statement_cid()

    # Public input that disagrees with declared program is rejected.
    with pytest.raises(StatementError, match="does not bind declared computation"):
        DirectExecutionStatement(
            program_id="program/sort@v1",
            circuit_id="sort_circuit@v1",
            proof_system_id="groth16",
            input_commitment=_digest("input"),
            output_commitment=_digest("output"),
            public_inputs=PublicInputDeclaration.from_mapping(
                {
                    "circuit_id": "sort_circuit@v1",
                    "input_commitment": _digest("input"),
                    "output_commitment": _digest("output"),
                    "program_id": "program/OTHER",
                    "proof_system_id": "groth16",
                }
            ),
            private_input_commitment=PrivateInputCommitment(
                commitment=_digest("private")
            ),
        )


def test_direct_execution_requires_direct_claim_flag() -> None:
    statement = sample_direct_execution_statement()
    payload = statement.to_canonical()
    del payload["direct_computation_claim"]
    with pytest.raises(StatementError, match="direct_computation_claim"):
        DirectExecutionStatement.from_canonical(payload)
    payload["direct_computation_claim"] = False
    with pytest.raises(StatementError, match="direct_computation_claim"):
        DirectExecutionStatement.from_canonical(payload)


def test_direct_execution_round_trip_and_dispatch() -> None:
    original = sample_direct_execution_statement()
    restored = DirectExecutionStatement.from_canonical(
        json.loads(original.to_canonical_json())
    )
    assert restored.statement_cid() == original.statement_cid()
    assert restored.binds_declared_computation()
    dispatched = statement_from_canonical(original.to_canonical())
    assert isinstance(dispatched, DirectExecutionStatement)
    assert dispatched.statement_cid() == original.statement_cid()


# ---------------------------------------------------------------------------
# Acceptance: private commitments reveal no witness
# ---------------------------------------------------------------------------


def test_private_commitments_reveal_no_witness() -> None:
    witness = b"super-secret-witness-bytes"
    commitment = PrivateInputCommitment.commit_witness_bytes(witness)
    assert commitment.reveals_witness() is False
    payload = commitment.to_canonical()
    assert payload["reveals_witness"] is False
    encoded = commitment.to_canonical_json()
    assert "super-secret" not in encoded
    assert "witness_bytes" not in encoded
    assert witness.hex() not in encoded
    assert payload["commitment"] == "sha256:" + hashlib.sha256(witness).hexdigest()

    # Opening / witness fields are rejected on the commitment surface.
    with pytest.raises(StatementError, match="witness"):
        PrivateInputCommitment.from_canonical(
            {**payload, "witness": witness.hex()}
        )
    with pytest.raises(StatementError, match="witness"):
        PrivateInputCommitment.from_canonical(
            {**payload, "witness_bytes": witness.hex()}
        )
    with pytest.raises(StatementError, match="reveal"):
        PrivateInputCommitment.from_canonical({**payload, "reveals_witness": True})

    # Public inputs reject witness-shaped field names.
    with pytest.raises(StatementError, match="private material"):
        PublicInputField(name="witness", value=_digest("x"))
    with pytest.raises(StatementError, match="private material"):
        PublicInputDeclaration.from_mapping({"secret_token": _digest("x")})

    # Full statements never embed witness openings.
    direct = sample_direct_execution_statement()
    public_json = direct.to_canonical_json()
    assert "private-witness-opening" not in public_json
    assert "witness_bytes" not in public_json
    assert direct.private_input_commitment.reveals_witness() is False

    aggregation = sample_receipt_aggregation_statement()
    assert aggregation.private_input_commitment.reveals_witness() is False
    agg_payload = aggregation.to_canonical()
    assert "witness" not in agg_payload
    assert "witness_bytes" not in agg_payload
    assert "witness_bytes_hex" not in agg_payload
    assert agg_payload["private_input_commitment"]["reveals_witness"] is False


def test_public_and_private_input_declarations_round_trip() -> None:
    public = PublicInputDeclaration.from_mapping(
        {
            "circuit_id": "c@v1",
            "program_id": "p@v1",
        }
    )
    private = PrivateInputCommitment(commitment=_digest("priv"))
    assert public.public_input_cid().startswith("sha256:")
    restored_public = PublicInputDeclaration.from_canonical(public.to_canonical())
    restored_private = PrivateInputCommitment.from_canonical(private.to_canonical())
    assert restored_public.public_input_cid() == public.public_input_cid()
    assert restored_private.commitment == private.commitment
    assert restored_private.reveals_witness() is False


# ---------------------------------------------------------------------------
# Forest transition and envelope
# ---------------------------------------------------------------------------


def test_forest_transition_statement_round_trip() -> None:
    original = sample_forest_transition_statement()
    assert original.evidence_class is EvidenceClass.INCREMENTAL_COMMIT_SEAL
    assert original.direct_computation_claim is False
    restored = ForestTransitionStatement.from_canonical(original.to_canonical())
    assert restored.statement_cid() == original.statement_cid()
    assert restored.transition_id == original.transition_id
    assert restored.reused_leaf_cids == original.reused_leaf_cids

    poisoned = original.to_canonical()
    poisoned["direct_computation_claim"] = True
    with pytest.raises(StatementError, match="direct-execution claim"):
        ForestTransitionStatement.from_canonical(poisoned)


def test_forest_transition_rejects_overlapping_leaves() -> None:
    shared = _digest("leaf")
    with pytest.raises(StatementError, match="disjoint"):
        build_forest_transition_statement(
            parent_seal_cid=_digest("parent"),
            transition_id="t1",
            old_verification_root=_digest("old"),
            new_verification_root=_digest("new"),
            reused_leaf_cids=(shared,),
            replacement_leaf_cids=(shared,),
            manifest_cid=_digest("manifest"),
            logical_epoch=1,
            private_commitment=_digest("priv"),
        )


def test_canonical_envelope_and_dispatch() -> None:
    public = PublicInputDeclaration.from_mapping({"circuit_id": "integrity@v1"})
    private = PrivateInputCommitment(commitment=_digest("priv"))
    envelope = CanonicalProofStatement(
        statement_kind=StatementKind.CANONICAL,
        evidence_class=EvidenceClass.INTEGRITY_COMMITMENT,
        domain_separator="ips.statement.canonical.v1",
        computation_id="integrity/bytes",
        public_inputs=public,
        private_input_commitment=private,
        establishes="exact bytes and digest",
        does_not_establish="execution",
        trusted_assumptions=("hash_function",),
        proof_system_id="none",
        circuit_id="integrity@v1",
    )
    assert envelope.direct_computation_claim is False
    payload = envelope.to_canonical()
    assert payload["statements_subset"] == STATEMENTS_SUBSET
    restored = statement_from_canonical(payload)
    assert isinstance(restored, CanonicalProofStatement)
    assert restored.statement_cid() == envelope.statement_cid()

    # Direct claim on a non-direct kind is rejected by the dispatcher path.
    bad = deepcopy(payload)
    bad["direct_computation_claim"] = True
    with pytest.raises(StatementError, match="direct-execution claim"):
        statement_from_canonical(bad)


def test_statement_from_canonical_dispatches_all_kinds() -> None:
    cases = [
        sample_direct_execution_statement(),
        sample_receipt_aggregation_statement(),
        sample_forest_transition_statement(),
    ]
    for sample in cases:
        loaded = statement_from_canonical(sample.to_canonical())
        assert type(loaded) is type(sample)
        assert loaded.statement_cid() == sample.statement_cid()


def test_unsorted_receipts_and_public_fields_fail_closed() -> None:
    low = "sha256:" + ("00" * 32)
    high = "sha256:" + ("ff" * 32)
    assert [high, low] != sorted([high, low])
    with pytest.raises(StatementError, match="sorted"):
        ReceiptAggregationStatement(
            circuit_id="agg@v1",
            proof_system_id="groth16",
            receipt_digests=(high, low),
            public_inputs=PublicInputDeclaration.from_mapping({"circuit_id": "agg@v1"}),
            private_input_commitment=PrivateInputCommitment(commitment=_digest("p")),
        )
    with pytest.raises(StatementError, match="sorted"):
        PublicInputDeclaration(
            fields=(
                PublicInputField(name="b", value="1"),
                PublicInputField(name="a", value="2"),
            )
        )


def test_build_helpers_produce_valid_samples() -> None:
    aggregation = build_receipt_aggregation_statement(
        circuit_id="agg@v1",
        proof_system_id="groth16",
        receipt_digests=[_digest("r2"), _digest("r1")],
        private_commitment=_digest("priv"),
    )
    assert list(aggregation.receipt_digests) == sorted(aggregation.receipt_digests)
    assert aggregation.statement_kind is StatementKind.RECEIPT_AGGREGATION

    direct = sample_direct_execution_statement()
    assert direct.private_input_commitment.commitment.startswith("sha256:")
    # Witness used at construction is not retained on the public record.
    assert not hasattr(direct.private_input_commitment, "witness_bytes")
