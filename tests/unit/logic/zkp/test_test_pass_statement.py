"""Unit tests for TestPassStatementV1 public/private inputs and constraints."""

from __future__ import annotations

import math
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    DISQUALIFYING_BITS,
    REQUIRED_PUBLIC_IDENTITY_FIELDS,
    TEST_PASS_CIRCUIT_REF,
    TEST_PASS_STATEMENT_INTERFACE,
    TestPassPrivateWitness,
    TestPassPublicInputs,
    TestPassStatementError,
    TestPassStatementV1,
    assert_witness_satisfies,
    build_public_inputs,
    build_statement,
    build_statement_from_receipt,
    content_digest_of_bytes,
    disqualifying_bits_present,
    phases_all_pass,
    public_identity_bindings,
    validate_public_inputs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ids() -> dict[str, str]:
    return {
        "execution_key_cid": "cid:execution-key:v1",
        "policy_cid": "cid:policy:reuse-v1",
        "statement_cid": "cid:statement:TestPassStatementV1",
        "circuit_cid": "cid:circuit:test_pass@v1",
        "verifying_key_cid": "cid:vk:test_pass@v1",
        "issuer_id": "issuer:runner-local",
        "epoch": "epoch:2026-07-31",
        "locator_cid": "cid:locator:node-alpha",
        "completeness_policy_cid": "cid:completeness:v1",
    }


def _receipt_payload(**changes: object) -> dict[str, object]:
    ids = _ids()
    payload: dict[str, object] = {
        "interface": "TestPassReceipt@1",
        "execution_key_cid": ids["execution_key_cid"],
        "locator_cid": ids["locator_cid"],
        "setup_outcome": "pass",
        "call_outcome": "pass",
        "teardown_outcome": "pass",
        "disqualifying_bits": [],
        "policy_cid": ids["policy_cid"],
        "issuer_id": ids["issuer_id"],
        "epoch": ids["epoch"],
        "completeness_policy_cid": ids["completeness_policy_cid"],
        "admitted": True,
        "nonce": "nonce-fixture-1",
    }
    payload.update(changes)
    return payload


def _honest_pair(**public_changes: object):
    ids = _ids()
    kwargs = {
        "execution_key_cid": ids["execution_key_cid"],
        "policy_cid": ids["policy_cid"],
        "statement_cid": ids["statement_cid"],
        "circuit_cid": ids["circuit_cid"],
        "verifying_key_cid": ids["verifying_key_cid"],
        "issuer_id": ids["issuer_id"],
        "epoch": ids["epoch"],
        "locator_cid": ids["locator_cid"],
        "completeness_policy_cid": ids["completeness_policy_cid"],
    }
    kwargs.update(public_changes)
    return build_statement_from_receipt(_receipt_payload(), **kwargs)


# ---------------------------------------------------------------------------
# Interface / identity bindings
# ---------------------------------------------------------------------------


def test_interface_and_circuit_pinning() -> None:
    statement, _ = _honest_pair()
    assert TEST_PASS_STATEMENT_INTERFACE == "TestPassStatementV1"
    assert statement.interface == TEST_PASS_STATEMENT_INTERFACE
    assert statement.circuit_ref == TEST_PASS_CIRCUIT_REF
    assert TEST_PASS_CIRCUIT_REF == "test_pass@v1"
    assert statement.public_inputs.circuit_ref == TEST_PASS_CIRCUIT_REF


def test_public_inputs_bind_required_identities() -> None:
    statement, witness = _honest_pair()
    public = statement.public_inputs
    bindings = public_identity_bindings(public)

    for field in REQUIRED_PUBLIC_IDENTITY_FIELDS:
        assert field in bindings
        assert bindings[field]
        assert public.to_dict()[field] == bindings[field]

    assert bindings["receipt_cid"] == witness.opening_digest()
    assert bindings["execution_key_cid"] == _ids()["execution_key_cid"]
    assert bindings["policy_cid"] == _ids()["policy_cid"]
    assert bindings["statement_cid"] == _ids()["statement_cid"]
    assert bindings["circuit_cid"] == _ids()["circuit_cid"]
    assert bindings["verifying_key_cid"] == _ids()["verifying_key_cid"]
    assert bindings["issuer_id"] == _ids()["issuer_id"]
    assert bindings["epoch"] == _ids()["epoch"]


def test_statement_digest_is_deterministic() -> None:
    a, _ = _honest_pair()
    b, _ = _honest_pair()
    assert a.statement_digest() == b.statement_digest()
    assert a.statement_digest().startswith("sha256:")
    assert a.to_public_inputs()["statement_digest"] == a.statement_digest()


def test_public_inputs_roundtrip() -> None:
    statement, _ = _honest_pair()
    restored = TestPassPublicInputs.from_dict(statement.public_inputs.to_dict())
    assert restored.identity_payload() == statement.public_inputs.identity_payload()
    assert restored.statement_digest() == statement.public_inputs.statement_digest()
    statement_restored = TestPassStatementV1.from_dict(statement.to_dict())
    assert statement_restored.statement_digest() == statement.statement_digest()


# ---------------------------------------------------------------------------
# Private witness is minimal
# ---------------------------------------------------------------------------


def test_private_witness_is_minimal_receipt_opening() -> None:
    statement, witness = _honest_pair()
    # Only receipt bytes (+ optional structured fields) — no environment secrets.
    assert isinstance(witness.receipt_bytes, bytes)
    assert witness.receipt_bytes
    assert witness.binds_receipt_cid(statement.receipt_cid)
    assert set(witness.to_dict().keys()) <= {
        "receipt_bytes_hex",
        "receipt_fields",
        "opening_digest",
    }
    # Public inputs must not embed witness material.
    public = statement.to_public_inputs()
    assert "witness" not in public
    assert "receipt_bytes" not in public
    assert "receipt_bytes_hex" not in public
    assert "private_witness" not in public


def test_witness_must_open_receipt_cid() -> None:
    statement, witness = _honest_pair()
    assert statement.witness_satisfies(witness) is True
    bad = TestPassPrivateWitness(receipt_bytes=b'{"not":"the-receipt"}')
    assert bad.binds_receipt_cid(statement.receipt_cid) is False
    assert statement.witness_satisfies(bad) is False
    with pytest.raises(TestPassStatementError, match="does not open"):
        assert_witness_satisfies(statement, bad)


def test_structured_witness_field_mismatch_fails() -> None:
    statement, witness = _honest_pair()
    # Same bytes digest path with conflicting structured fields.
    conflicting = TestPassPrivateWitness(
        receipt_bytes=witness.receipt_bytes,
        receipt_fields={
            **dict(witness.receipt_fields),
            "execution_key_cid": "cid:execution-key:OTHER",
        },
    )
    # Digest still matches (bytes unchanged) but constrained field does not.
    assert conflicting.binds_receipt_cid(statement.receipt_cid) is True
    with pytest.raises(TestPassStatementError, match="execution_key_cid"):
        assert_witness_satisfies(statement, conflicting)


# ---------------------------------------------------------------------------
# Three phases pass; disqualifying bits clear
# ---------------------------------------------------------------------------


def test_all_three_phases_must_pass() -> None:
    assert phases_all_pass("pass", "pass", "pass") is True
    assert phases_all_pass("pass", "fail", "pass") is False

    statement, _ = _honest_pair()
    assert statement.public_inputs.all_phases_pass is True
    assert statement.public_inputs.is_admitted_complete_pass() is True

    for phase in ("setup_outcome", "call_outcome", "teardown_outcome"):
        with pytest.raises(TestPassStatementError, match="three pytest phases|must pass"):
            build_statement(
                build_public_inputs(
                    receipt_cid=statement.receipt_cid,
                    execution_key_cid=statement.execution_key_cid,
                    policy_cid=statement.public_inputs.policy_cid,
                    statement_cid=statement.public_inputs.statement_cid,
                    circuit_cid=statement.public_inputs.circuit_cid,
                    verifying_key_cid=statement.public_inputs.verifying_key_cid,
                    issuer_id=statement.public_inputs.issuer_id,
                    epoch=statement.public_inputs.epoch,
                    **{phase: "fail"},
                ),
                require_admitted_pass=True,
            )


def test_disqualifying_bits_must_be_clear() -> None:
    statement, _ = _honest_pair()
    assert statement.public_inputs.disqualifying_bits_clear is True
    assert disqualifying_bits_present(()) == ()
    assert "xfail" in DISQUALIFYING_BITS
    assert "incomplete_trace" in DISQUALIFYING_BITS

    with pytest.raises(TestPassStatementError, match="disqualifying"):
        build_statement(
            build_public_inputs(
                receipt_cid=statement.receipt_cid,
                execution_key_cid=statement.execution_key_cid,
                policy_cid=statement.public_inputs.policy_cid,
                statement_cid=statement.public_inputs.statement_cid,
                circuit_cid=statement.public_inputs.circuit_cid,
                verifying_key_cid=statement.public_inputs.verifying_key_cid,
                issuer_id=statement.public_inputs.issuer_id,
                epoch=statement.public_inputs.epoch,
                disqualifying_bits=("xfail",),
            ),
            require_admitted_pass=True,
        )


def test_receipt_payload_rejects_non_pass_phases() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError, match="setup, call, and teardown"):
        build_statement_from_receipt(
            _receipt_payload(call_outcome="fail"),
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
        )


def test_receipt_payload_rejects_disqualifying_bits() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError, match="disqualifying"):
        build_statement_from_receipt(
            _receipt_payload(disqualifying_bits=["incomplete_trace"]),
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
        )


def test_honest_witness_satisfies_constraints() -> None:
    statement, witness = _honest_pair()
    assert_witness_satisfies(statement, witness)
    assert statement.witness_satisfies(witness) is True
    assert statement.public_inputs.setup_outcome == "pass"
    assert statement.public_inputs.call_outcome == "pass"
    assert statement.public_inputs.teardown_outcome == "pass"
    assert list(statement.public_inputs.disqualifying_bits) == []


# ---------------------------------------------------------------------------
# Rejection: malformed / nonfinite / private public data
# ---------------------------------------------------------------------------


def test_rejects_missing_required_identity() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError, match="non-empty|must be"):
        build_public_inputs(
            receipt_cid="",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
        )


def test_rejects_malformed_types() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError):
        build_public_inputs(
            receipt_cid=123,  # type: ignore[arg-type]
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
        )
    with pytest.raises(TestPassStatementError, match="boolean"):
        build_public_inputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            completeness_admitted=1,  # type: ignore[arg-type]
        )
    with pytest.raises(TestPassStatementError, match="phase|setup_outcome"):
        build_public_inputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            setup_outcome="PASSED",
        )


def test_rejects_nonfinite_and_float_public_data() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError, match="nonfinite|floating"):
        build_public_inputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            extra={"score": float("nan")},
        )
    with pytest.raises(TestPassStatementError, match="nonfinite|floating"):
        build_public_inputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            extra={"score": float("inf")},
        )
    with pytest.raises(TestPassStatementError, match="floating"):
        build_public_inputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            extra={"score": math.pi},
        )
    with pytest.raises(TestPassStatementError, match="nonfinite|floating|private"):
        validate_public_inputs(
            {
                "receipt_cid": "cid:receipt",
                "execution_key_cid": ids["execution_key_cid"],
                "policy_cid": ids["policy_cid"],
                "statement_cid": ids["statement_cid"],
                "circuit_cid": ids["circuit_cid"],
                "verifying_key_cid": ids["verifying_key_cid"],
                "issuer_id": ids["issuer_id"],
                "epoch": ids["epoch"],
                "nested": {"x": float("nan")},
            }
        )


def test_rejects_private_material_in_public_inputs() -> None:
    ids = _ids()
    for private_key in ("private_witness", "api_key", "secret", "witness", "password"):
        with pytest.raises(TestPassStatementError, match="private"):
            build_public_inputs(
                receipt_cid="cid:receipt",
                execution_key_cid=ids["execution_key_cid"],
                policy_cid=ids["policy_cid"],
                statement_cid=ids["statement_cid"],
                circuit_cid=ids["circuit_cid"],
                verifying_key_cid=ids["verifying_key_cid"],
                issuer_id=ids["issuer_id"],
                epoch=ids["epoch"],
                extra={private_key: "synthetic"},
            )
    with pytest.raises(TestPassStatementError, match="private"):
        validate_public_inputs(
            {
                "receipt_cid": "cid:receipt",
                "execution_key_cid": ids["execution_key_cid"],
                "policy_cid": ids["policy_cid"],
                "statement_cid": ids["statement_cid"],
                "circuit_cid": ids["circuit_cid"],
                "verifying_key_cid": ids["verifying_key_cid"],
                "issuer_id": ids["issuer_id"],
                "epoch": ids["epoch"],
                "private_witness": "leak",
            }
        )


def test_rejects_unknown_disqualifying_bit_vocabulary() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError, match="unknown disqualifying"):
        build_public_inputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            disqualifying_bits=("not_a_real_bit",),
        )


def test_rejects_wrong_circuit_ref_and_statement_version() -> None:
    ids = _ids()
    with pytest.raises(TestPassStatementError, match="circuit_ref"):
        TestPassPublicInputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            circuit_ref="other_circuit@v1",
        )
    with pytest.raises(TestPassStatementError, match="statement_version"):
        TestPassPublicInputs(
            receipt_cid="cid:receipt",
            execution_key_cid=ids["execution_key_cid"],
            policy_cid=ids["policy_cid"],
            statement_cid=ids["statement_cid"],
            circuit_cid=ids["circuit_cid"],
            verifying_key_cid=ids["verifying_key_cid"],
            issuer_id=ids["issuer_id"],
            epoch=ids["epoch"],
            statement_version=99,
        )


def test_empty_witness_bytes_rejected() -> None:
    with pytest.raises(TestPassStatementError, match="non-empty"):
        TestPassPrivateWitness(receipt_bytes=b"")


def test_content_digest_of_bytes_matches_opening() -> None:
    payload = _receipt_payload()
    witness = TestPassPrivateWitness.from_receipt_payload(payload)
    assert witness.opening_digest() == content_digest_of_bytes(witness.receipt_bytes)


def test_deep_copy_public_dict_still_validates() -> None:
    statement, _ = _honest_pair()
    payload = deepcopy(statement.public_inputs.to_dict())
    restored = validate_public_inputs(payload)
    assert restored.statement_digest() == statement.public_inputs.statement_digest()
