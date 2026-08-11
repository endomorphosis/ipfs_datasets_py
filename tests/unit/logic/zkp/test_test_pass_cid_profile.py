"""CID / codec profile tests for TestPassStatementV5 (PTR-171)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    TEST_PASS_V5_CAPACITY,
    TEST_PASS_V5_CIRCUIT_PROFILE,
    TestPassStatementError,
    build_statement_v5_from_openings,
    canonical_dag_cbor_bytes,
    canonical_dag_json_bytes,
    decode_canonical_dag_cbor,
    decode_canonical_dag_json,
    native_public_inputs_from_openings,
    pad_v5_opening,
    require_v5_cid,
    v5_cid_for_bytes,
)


def _compact_openings() -> tuple[bytes, bytes]:
    receipt = canonical_dag_json_bytes(
        {
            "interface": "TestPassReceipt@1",
            "execution_key_cid": "e",
            "policy_cid": "p",
        }
    )
    attestation = canonical_dag_cbor_bytes(
        {
            "interface": "RunnerPassAttestation@1",
            "execution_key_cid": "e",
            "policy_cid": "p",
            "signer_key_cid": "k",
            "key_epoch": "1",
            "issuance_nonce": "n",
        }
    )
    assert len(receipt) <= TEST_PASS_V5_CAPACITY
    assert len(attestation) <= TEST_PASS_V5_CAPACITY
    return receipt, attestation


def test_receipt_is_dag_json_cidv1_profile() -> None:
    receipt, _ = _compact_openings()
    cid = v5_cid_for_bytes(receipt, "dag-json")
    require_v5_cid(cid, "receipt_cid", codec="dag-json")
    assert decode_canonical_dag_json(receipt)["interface"] == "TestPassReceipt@1"
    # Alternate JSON (spaces) is rejected.
    with pytest.raises(TestPassStatementError):
        decode_canonical_dag_json(b'{ "interface" : "TestPassReceipt@1" }')


def test_attestation_is_dag_cbor_cidv1_profile() -> None:
    _, attestation = _compact_openings()
    cid = v5_cid_for_bytes(attestation, "dag-cbor")
    require_v5_cid(cid, "attestation_cid", codec="dag-cbor")
    assert decode_canonical_dag_cbor(attestation)["interface"] == "RunnerPassAttestation@1"
    # JSON is never a fallback for attestation openings.
    with pytest.raises(TestPassStatementError):
        decode_canonical_dag_cbor(b'{"interface":"RunnerPassAttestation@1"}')


def test_native_public_inputs_are_ordered_0x32_vector() -> None:
    receipt, attestation = _compact_openings()
    vector = native_public_inputs_from_openings(receipt, attestation)
    assert len(vector) == 7
    assert all(item.startswith("0x") and len(item) == 66 for item in vector)
    r_pad, r_len = pad_v5_opening(receipt)
    a_pad, a_len = pad_v5_opening(attestation)
    assert len(r_pad) == TEST_PASS_V5_CAPACITY and r_pad[r_len:] == b"\x00" * (TEST_PASS_V5_CAPACITY - r_len)
    assert len(a_pad) == TEST_PASS_V5_CAPACITY and a_pad[a_len:] == b"\x00" * (TEST_PASS_V5_CAPACITY - a_len)


def test_statement_binds_content_cids_and_profile() -> None:
    receipt, attestation = _compact_openings()
    statement, witness = build_statement_v5_from_openings(
        receipt,
        attestation,
        candidate_context_cid="c",
        phase_root_cid="h",
        trace_root_cid="t",
        trust_domain="d",
    )
    assert statement.circuit_profile == TEST_PASS_V5_CIRCUIT_PROFILE
    assert statement.public_inputs.receipt_cid == v5_cid_for_bytes(receipt, "dag-json")
    assert statement.public_inputs.attestation_cid == v5_cid_for_bytes(attestation, "dag-cbor")
    statement.assert_witness_satisfies(witness)


def test_oversize_opening_is_rejected() -> None:
    with pytest.raises(TestPassStatementError):
        pad_v5_opening(b"x" * (TEST_PASS_V5_CAPACITY + 1))
