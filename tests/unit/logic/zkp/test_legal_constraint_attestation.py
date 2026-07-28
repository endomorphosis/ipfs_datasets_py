"""Unit tests for LegalConstraintZKP@1 prove/verify attestation path (LIG-008)."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.zkp.statements.legal_constraint import (
    LEGAL_CONSTRAINT_CIRCUIT_REF,
    LEGAL_CONSTRAINT_ZKP_INTERFACE,
    LegalConstraintAttestation,
    LegalConstraintStatement,
    LegalConstraintWitness,
    LegalConstraintZKPError,
    attestation_satisfies_zkp_required,
    build_statement,
    build_statement_from_payload,
    compute_constraint_digest,
    is_simulated_backend,
    prove_and_verify,
    prove_legal_constraint_attestation,
    verify_legal_constraint_attestation,
)


def _source_digest(label: str = "source") -> str:
    return compute_constraint_digest({"kind": "source", "label": label})


def _honest_pair(
    *,
    profile: str = "legal-strict",
    jurisdiction: str = "us-federal",
    artifact_cid: str = "bafylegalartifactfixture0000000000000000001",
):
    payload = {
        "domain": "legal",
        "norms": [
            {
                "modality": "obligation",
                "action": "publish_notice",
                "subject": "agency",
            }
        ],
        "theorem_receipts": [
            {
                "status": "proved",
                "authority": "theorem_proof",
                "claim": "O(publish_notice)",
            }
        ],
    }
    statement, witness = build_statement_from_payload(
        payload,
        source_digest=_source_digest("us-code-5-552"),
        profile=profile,
        jurisdiction=jurisdiction,
        artifact_cid=artifact_cid,
    )
    return statement, witness, payload


def test_interface_and_circuit_pinning() -> None:
    statement, _, _ = _honest_pair()
    assert LEGAL_CONSTRAINT_ZKP_INTERFACE == "LegalConstraintZKP@1"
    assert statement.circuit_ref == LEGAL_CONSTRAINT_CIRCUIT_REF
    assert LEGAL_CONSTRAINT_CIRCUIT_REF == "legal_constraint@v1"


def test_constraint_digest_is_deterministic() -> None:
    payload = {"a": 1, "b": ["x", "y"]}
    assert compute_constraint_digest(payload) == compute_constraint_digest(
        {"b": ["x", "y"], "a": 1}
    )
    assert compute_constraint_digest(payload).startswith("sha256:")


def test_witness_must_open_constraint_digest() -> None:
    statement, witness, _ = _honest_pair()
    assert witness.binds_statement(statement)
    bad = LegalConstraintWitness(payload={"not": "the-opening"})
    assert not bad.binds_statement(statement)
    with pytest.raises(LegalConstraintZKPError, match="does not open"):
        prove_legal_constraint_attestation(statement, bad)


def test_honest_prove_verify_succeeds() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(
            statement, witness, backend="simulated", seed="fixture-seed"
        )
    assert attestation.interface == LEGAL_CONSTRAINT_ZKP_INTERFACE
    assert attestation.is_simulated is True
    assert attestation.backend == "simulated"
    assert "simulated" in attestation.proof_system.lower()
    assert attestation.statement_digest == statement.statement_digest()
    assert attestation.public_inputs["constraint_digest"] == statement.constraint_digest
    assert attestation.public_inputs["source_digest"] == statement.source_digest
    assert attestation.public_inputs["profile"] == statement.profile
    assert attestation.public_inputs["circuit_ref"] == LEGAL_CONSTRAINT_CIRCUIT_REF
    assert verify_legal_constraint_attestation(attestation) is True
    assert (
        verify_legal_constraint_attestation(
            attestation, expected_statement=statement
        )
        is True
    )


def test_prove_and_verify_convenience() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation, ok = prove_and_verify(statement, witness, seed=b"\x01\x02")
    assert ok is True
    assert verify_legal_constraint_attestation(attestation) is True


def test_roundtrip_attestation_dict() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)
    restored = LegalConstraintAttestation.from_dict(attestation.to_dict())
    assert restored.statement_digest == attestation.statement_digest
    assert restored.proof_data == attestation.proof_data
    assert verify_legal_constraint_attestation(restored) is True
    assert verify_legal_constraint_attestation(attestation.to_dict()) is True


def test_verify_fails_on_tampered_constraint_digest() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)

    other_digest = compute_constraint_digest({"tampered": True})
    tampered_statement = replace(statement, constraint_digest=other_digest)
    tampered = LegalConstraintAttestation(
        statement=tampered_statement,
        proof_data=attestation.proof_data,
        public_inputs=dict(attestation.public_inputs),
        metadata=dict(attestation.metadata),
        statement_digest=attestation.statement_digest,
        timestamp=attestation.timestamp,
    )
    assert verify_legal_constraint_attestation(tampered) is False
    assert (
        verify_legal_constraint_attestation(
            attestation, expected_statement=tampered_statement
        )
        is False
    )


def test_verify_fails_on_tampered_profile() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)

    tampered_statement = replace(statement, profile="zkp-required")
    # Fully re-key public inputs and statement_digest to the tampered statement
    # so only the proof embedding can catch the drift.
    tampered = LegalConstraintAttestation(
        statement=tampered_statement,
        proof_data=attestation.proof_data,
        public_inputs=tampered_statement.to_public_inputs(),
        metadata=dict(attestation.metadata),
        statement_digest=tampered_statement.statement_digest(),
        timestamp=attestation.timestamp,
    )
    assert verify_legal_constraint_attestation(tampered) is False


def test_verify_fails_on_tampered_public_inputs() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)

    public = dict(attestation.public_inputs)
    public["profile"] = "dev-offline"
    tampered = LegalConstraintAttestation(
        statement=statement,
        proof_data=attestation.proof_data,
        public_inputs=public,
        metadata=dict(attestation.metadata),
        statement_digest=attestation.statement_digest,
        timestamp=attestation.timestamp,
    )
    assert verify_legal_constraint_attestation(tampered) is False


def test_verify_fails_on_tampered_proof_bytes() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)

    mutated = bytearray(attestation.proof_data)
    mutated[50] ^= 0xFF
    tampered = LegalConstraintAttestation(
        statement=statement,
        proof_data=bytes(mutated),
        public_inputs=dict(attestation.public_inputs),
        metadata=dict(attestation.metadata),
        statement_digest=attestation.statement_digest,
        timestamp=attestation.timestamp,
    )
    assert verify_legal_constraint_attestation(tampered) is False


def test_verify_fails_on_truncated_proof() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)

    truncated = LegalConstraintAttestation(
        statement=statement,
        proof_data=attestation.proof_data[:32],
        public_inputs=dict(attestation.public_inputs),
        metadata=dict(attestation.metadata),
        statement_digest=attestation.statement_digest,
        timestamp=attestation.timestamp,
    )
    assert verify_legal_constraint_attestation(truncated) is False


def test_verify_fails_when_expected_statement_mismatches() -> None:
    statement, witness, _ = _honest_pair()
    other, _, _ = _honest_pair(profile="security-lite")
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)
    assert (
        verify_legal_constraint_attestation(
            attestation, expected_statement=other
        )
        is False
    )


def test_simulated_backend_is_labeled() -> None:
    assert is_simulated_backend("simulated") is True
    assert is_simulated_backend("sim") is True
    assert is_simulated_backend("groth16") is False
    assert is_simulated_backend("provekit") is False
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)
    assert attestation.metadata["is_simulated"] is True
    assert attestation.metadata["security"] == "simulation-only"
    assert attestation.metadata["interface"] == LEGAL_CONSTRAINT_ZKP_INTERFACE


def test_production_backend_unavailable_fails_closed() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.raises(LegalConstraintZKPError, match="not available"):
        prove_legal_constraint_attestation(
            statement, witness, backend="groth16"
        )


def test_unknown_backend_fails_closed() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.raises(LegalConstraintZKPError, match="unsupported"):
        prove_legal_constraint_attestation(
            statement, witness, backend="not-a-backend"
        )


def test_zkp_required_profile_rejects_simulated() -> None:
    """zkp-required profiles can require this path and refuse simulated proofs."""

    statement, witness, _ = _honest_pair(profile="zkp-required")
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)

    # Structural verify still succeeds for the simulated path.
    assert verify_legal_constraint_attestation(attestation) is True

    # Production zkp-required: require verify, do not accept simulated.
    assert (
        attestation_satisfies_zkp_required(
            attestation,
            require_zkp_verify=True,
            accept_simulated_zkp=False,
        )
        is False
    )

    # dev-offline style: may accept labeled simulated ZKP.
    assert (
        attestation_satisfies_zkp_required(
            attestation,
            require_zkp_verify=True,
            accept_simulated_zkp=True,
        )
        is True
    )

    # legal-strict style: ZKP optional; verified simulated still ok when not required.
    assert (
        attestation_satisfies_zkp_required(
            attestation,
            require_zkp_verify=False,
            accept_simulated_zkp=False,
        )
        is True
    )


def test_zkp_required_rejects_invalid_attestation() -> None:
    assert (
        attestation_satisfies_zkp_required(
            {"not": "an attestation"},
            require_zkp_verify=True,
            accept_simulated_zkp=True,
        )
        is False
    )


def test_build_statement_validation() -> None:
    with pytest.raises(LegalConstraintZKPError):
        build_statement(
            constraint_digest="not-a-digest",
            source_digest=_source_digest(),
            profile="legal-strict",
        )
    with pytest.raises(LegalConstraintZKPError):
        build_statement(
            constraint_digest=_source_digest("c"),
            source_digest=_source_digest("s"),
            profile="Legal_Strict",
        )


def test_statement_from_dict_roundtrip() -> None:
    statement, _, _ = _honest_pair()
    restored = LegalConstraintStatement.from_dict(statement.to_dict())
    assert restored.identity_payload() == statement.identity_payload()
    assert restored.statement_digest() == statement.statement_digest()


def test_deep_copy_dict_attestation_still_verifies() -> None:
    statement, witness, _ = _honest_pair()
    with pytest.warns(UserWarning, match="SIMULATED"):
        attestation = prove_legal_constraint_attestation(statement, witness)
    payload = copy.deepcopy(attestation.to_dict())
    assert verify_legal_constraint_attestation(payload) is True
