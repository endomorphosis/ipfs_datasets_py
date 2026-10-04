"""Integration tests for ProofReceiptAttestation@1 (LFV-G063 / LFV-034).

Acceptance:

* Public inputs bind theorem/property, translation, receipt, tree, policy,
  circuit, CRS/setup ceremony, proving-key and verification-key identities,
  backend, revocation policy, and freshness.
* Private witnesses never serialize.
* Simulated, circuit-mismatched, stale, and revoked attestations fail.
* Attestation is orthogonal to and preserves underlying semantic authority.
"""

from __future__ import annotations

import copy
import json
import pickle
from typing import Any

import pytest

from ipfs_datasets_py.logic.backends.results import (
    AttestationResult,
    AuthoritySubstitutionError,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.bridge.proof_receipt_attestation import (
    PROOF_RECEIPT_ATTESTATION_INTERFACE,
    PROOF_RECEIPT_ATTESTATION_SCHEMA_VERSION,
    REQUIRED_PUBLIC_INPUT_KEYS,
    AttestationBackendMode,
    AttestationBackendPolicy,
    AttestationEnvelope,
    AttestationGate,
    AttestationRecord,
    AttestationRequest,
    AttestationStatement,
    AttestationVerificationVerdict,
    CircuitMismatchError,
    CryptographicBackendFailure,
    PrivateWitness,
    ProofReceiptAttestationError,
    RevocationPolicy,
    RevokedAttestationError,
    StaleAttestationError,
    TrustedProofReceipt,
    WitnessDisclosureError,
    build_attestation_record,
    build_attestation_statement,
    build_trusted_receipt_from_backend_result,
    create_attestation_envelope,
    execute_cryptographic_attestation,
    prepare_receipt_attestation,
    preserve_underlying_authority,
    public_artifact_contains,
    public_attestation_artifact,
    record_attestation_verification,
    verify_statement_against_policy,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds

NOW = "2026-07-23T12:00:00Z"
LATER = "2026-07-23T12:04:00Z"
EXPIRES = "2026-07-23T12:05:00Z"
STALE = "2026-07-23T12:06:00Z"
KEY_EXPIRES = "2030-01-01T00:00:00Z"
SECRET = "private-witness-REF-LFV034-secret-axiom"


def _theorem(**changes: Any) -> TheoremResult:
    fields: dict[str, Any] = {
        "result_id": "result:theorem-lfv034",
        "backend_id": "solver.lean",
        "backend_version": "4.19.0",
        "authority": ResultAuthority.THEOREM,
        "status": ResultStatus.PROVED,
        "assumptions": ("assumption:int",),
        "bounds": ExecutionBounds(timeout_ms=1000, max_steps=100),
        "translation_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _receipt(result: TheoremResult | None = None) -> TrustedProofReceipt:
    source = result or _theorem()
    return build_trusted_receipt_from_backend_result(
        source,
        theorem_id="theorem:sort-correct",
        property_id="property:functional-correctness",
        translation_receipt_id="translation:fol-to-lean:v1",
        tree_id="tree:repo@abc123",
        policy_id="policy:formal@1",
    )


def _policy(
    *,
    backend_id: str = "backend:provekit",
    backend_mode: AttestationBackendMode = AttestationBackendMode.CRYPTOGRAPHIC,
    circuit_id: str = "circuit:receipt-binding",
    circuit_version: str = "2.1.0",
    verification_key_id: str = "vk:receipt-binding:sha256-beef",
    proving_key_id: str = "pk:receipt-binding:sha256-cafe",
    ceremony_id: str = "ceremony:mpc-2026-07",
    crs_id: str = "crs:powers-of-tau:28",
    revocation_policy_id: str = "revocation:production@1",
    verification_key_expires_at: str = KEY_EXPIRES,
) -> AttestationBackendPolicy:
    return AttestationBackendPolicy(
        backend_id=backend_id,
        backend_version="0.2.0",
        circuit_id=circuit_id,
        circuit_version=circuit_version,
        ceremony_id=ceremony_id,
        crs_id=crs_id,
        proving_key_id=proving_key_id,
        verification_key_id=verification_key_id,
        revocation_policy_id=revocation_policy_id,
        backend_mode=backend_mode,
        verification_key_expires_at=verification_key_expires_at,
    )


def _revocation(**changes: Any) -> RevocationPolicy:
    fields: dict[str, Any] = {
        "policy_id": "revocation:production@1",
        "as_of": NOW,
    }
    fields.update(changes)
    return RevocationPolicy(**fields)


def _witness(secret: str = SECRET) -> PrivateWitness:
    return PrivateWitness({"private_premise": secret, "private_trace": [1, 2, 3]})


def _request(
    *,
    receipt: TrustedProofReceipt | None = None,
    policy: AttestationBackendPolicy | None = None,
    revocation: RevocationPolicy | None = None,
    secret: str = SECRET,
) -> AttestationRequest:
    return prepare_receipt_attestation(
        receipt or _receipt(),
        backend_policy=policy or _policy(),
        witness=_witness(secret),
        issued_at=NOW,
        expires_at=EXPIRES,
        revocation_policy=revocation if revocation is not None else _revocation(),
    )


def _verification(
    *,
    verified: bool = True,
    policy: AttestationBackendPolicy | None = None,
    secret: str = SECRET,
) -> Any:
    request = _request(policy=policy, secret=secret)

    def prover(req: AttestationRequest) -> dict[str, str]:
        # Prover may read the private witness in-process only.
        seen: dict[str, Any] = {}

        def capture(values: Any) -> None:
            seen.update(values)

        req.use_witness(capture)
        assert secret in seen.values() or secret in json.dumps(seen, default=str)
        return {
            "proof_artifact_id": "artifact:zkp:public",
            "proof_digest": "sha256:public-proof-digest",
        }

    return execute_cryptographic_attestation(
        request,
        prover=prover,
        verifier=lambda _envelope: verified,
        prover_id="prover:provekit@0.2.0",
        verifier_id="verifier:provekit@0.2.0",
        revocation_policy=_revocation(),
        now=NOW,
    )


def test_interface_and_schema_versions_are_pinned() -> None:
    assert PROOF_RECEIPT_ATTESTATION_INTERFACE == "ProofReceiptAttestation@1"
    assert PROOF_RECEIPT_ATTESTATION_SCHEMA_VERSION == "proof-receipt-attestation/v1"
    receipt = _receipt()
    assert receipt.INTERFACE == PROOF_RECEIPT_ATTESTATION_INTERFACE


def test_public_inputs_bind_all_required_dimensions() -> None:
    statement = build_attestation_statement(
        _receipt(),
        backend_policy=_policy(),
        issued_at=NOW,
        expires_at=EXPIRES,
        revocation_policy=_revocation(),
    )
    public_inputs = statement.require_complete_public_inputs()

    for key in REQUIRED_PUBLIC_INPUT_KEYS:
        assert key in public_inputs
        assert public_inputs[key], f"public input {key} must be non-empty"

    assert public_inputs["theorem_id"] == "theorem:sort-correct"
    assert public_inputs["property_id"] == "property:functional-correctness"
    assert public_inputs["translation_receipt_id"] == "translation:fol-to-lean:v1"
    assert public_inputs["tree_id"] == "tree:repo@abc123"
    assert public_inputs["policy_id"] == "policy:formal@1"
    assert public_inputs["circuit_id"] == "circuit:receipt-binding"
    assert public_inputs["circuit_version"] == "2.1.0"
    assert public_inputs["ceremony_id"] == "ceremony:mpc-2026-07"
    assert public_inputs["crs_id"] == "crs:powers-of-tau:28"
    assert public_inputs["proving_key_id"] == "pk:receipt-binding:sha256-cafe"
    assert public_inputs["verification_key_id"] == "vk:receipt-binding:sha256-beef"
    assert public_inputs["backend_id"] == "backend:provekit"
    assert public_inputs["backend_mode"] == "cryptographic"
    assert public_inputs["revocation_policy_id"] == "revocation:production@1"
    assert public_inputs["issued_at"] == NOW
    assert public_inputs["expires_at"] == EXPIRES
    assert public_inputs["underlying_authority"] == "theorem"
    assert public_inputs["underlying_status"] == "proved"
    assert statement.public_input_digest
    assert statement.statement_id == statement.public_input_digest


def test_each_public_input_dimension_change_produces_distinct_digest() -> None:
    base = build_attestation_statement(
        _receipt(),
        backend_policy=_policy(),
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    variants = [
        build_attestation_statement(
            _receipt(),
            backend_policy=_policy(circuit_id="circuit:other"),
            issued_at=NOW,
            expires_at=EXPIRES,
        ),
        build_attestation_statement(
            _receipt(),
            backend_policy=_policy(ceremony_id="ceremony:other"),
            issued_at=NOW,
            expires_at=EXPIRES,
        ),
        build_attestation_statement(
            _receipt(),
            backend_policy=_policy(verification_key_id="vk:other"),
            issued_at=NOW,
            expires_at=EXPIRES,
        ),
        build_attestation_statement(
            build_trusted_receipt_from_backend_result(
                _theorem(),
                theorem_id="theorem:other",
                property_id="property:functional-correctness",
                translation_receipt_id="translation:fol-to-lean:v1",
                tree_id="tree:repo@abc123",
                policy_id="policy:formal@1",
            ),
            backend_policy=_policy(),
            issued_at=NOW,
            expires_at=EXPIRES,
        ),
        build_attestation_statement(
            build_trusted_receipt_from_backend_result(
                _theorem(),
                theorem_id="theorem:sort-correct",
                property_id="property:functional-correctness",
                translation_receipt_id="translation:other",
                tree_id="tree:repo@abc123",
                policy_id="policy:formal@1",
            ),
            backend_policy=_policy(),
            issued_at=NOW,
            expires_at=EXPIRES,
        ),
        build_attestation_statement(
            build_trusted_receipt_from_backend_result(
                _theorem(),
                theorem_id="theorem:sort-correct",
                property_id="property:functional-correctness",
                translation_receipt_id="translation:fol-to-lean:v1",
                tree_id="tree:other",
                policy_id="policy:formal@1",
            ),
            backend_policy=_policy(),
            issued_at=NOW,
            expires_at=EXPIRES,
        ),
    ]
    digests = {base.public_input_digest, *(item.public_input_digest for item in variants)}
    assert len(digests) == 1 + len(variants)


def test_trusted_receipt_rejects_non_conclusive_and_attestation_authority() -> None:
    with pytest.raises(ProofReceiptAttestationError, match="conclusive"):
        build_trusted_receipt_from_backend_result(
            _theorem(status=ResultStatus.UNKNOWN),
            theorem_id="theorem:x",
            property_id="property:x",
            translation_receipt_id="translation:x",
            tree_id="tree:x",
            policy_id="policy:x",
        )

    with pytest.raises(AuthoritySubstitutionError):
        TrustedProofReceipt(
            receipt_id="receipt:x",
            theorem_id="theorem:x",
            property_id="property:x",
            translation_receipt_id="translation:x",
            tree_id="tree:x",
            policy_id="policy:x",
            underlying_authority=ResultAuthority.ATTESTATION,
            underlying_status=ResultStatus.ATTESTED,
            source_result_digest="digest",
            backend_id="backend:x",
            backend_version="1",
        )


def test_private_witness_never_serializes() -> None:
    witness = _witness()
    request = _request()

    with pytest.raises(WitnessDisclosureError):
        witness.to_dict()
    with pytest.raises(WitnessDisclosureError):
        copy.copy(witness)
    with pytest.raises(WitnessDisclosureError):
        copy.deepcopy(witness)
    with pytest.raises(WitnessDisclosureError):
        pickle.dumps(witness)
    with pytest.raises(WitnessDisclosureError):
        pickle.dumps(request)
    with pytest.raises(WitnessDisclosureError):
        request.to_cache_record()

    public = public_attestation_artifact(request)
    assert public["private_witness_redacted"] is True
    assert SECRET not in json.dumps(public, default=str)
    assert not public_artifact_contains(request, SECRET)
    assert not public_artifact_contains(request.statement, SECRET)

    verification = _verification()
    record = build_attestation_record(verification, created_at=NOW)
    for artifact in (
        verification.to_public_artifact(),
        record.to_public_artifact(),
        create_attestation_envelope(
            request,
            backend_mode=AttestationBackendMode.CRYPTOGRAPHIC,
            proof_artifact_id="artifact:x",
            proof_digest="sha256:x",
        ).to_public_artifact(),
    ):
        encoded = json.dumps(artifact, default=str)
        assert SECRET not in encoded
        assert "private_premise" not in encoded


def test_cryptographic_execution_succeeds_and_projects_attestation_authority() -> None:
    verification = _verification(verified=True)
    assert verification.verdict is AttestationVerificationVerdict.VERIFIED
    assert verification.authoritative_for_attestation is True
    assert verification.satisfies_gate(AttestationGate.PRODUCTION)
    assert verification.satisfies_gate(AttestationGate.COMPLETION)

    record = build_attestation_record(verification, created_at=NOW)
    assert record.receipt_id == verification.envelope.statement.receipt.receipt_id
    assert record.underlying_authority is ResultAuthority.THEOREM
    assert record.is_current_at(LATER)

    projection = record.to_attestation_result()
    assert isinstance(projection, AttestationResult)
    assert projection.authority is ResultAuthority.ATTESTATION
    assert projection.status is ResultStatus.ATTESTED
    assert projection.metadata["underlying_authority"] == "theorem"
    assert projection.metadata["underlying_status"] == "proved"

    source = verification.envelope.statement.receipt
    assert (
        preserve_underlying_authority(source, projection) is ResultAuthority.THEOREM
    )
    assert preserve_underlying_authority(source, record) is ResultAuthority.THEOREM
    assert preserve_underlying_authority(source, verification) is ResultAuthority.THEOREM


def test_attestation_does_not_raise_underlying_semantic_authority() -> None:
    theorem = _theorem()
    receipt = _receipt(theorem)
    verification = _verification()
    record = build_attestation_record(verification, created_at=NOW)
    projection = record.to_attestation_result()

    # Orthogonal authorities: theorem stays theorem; attestation stays attestation.
    assert theorem.authority is ResultAuthority.THEOREM
    assert projection.authority is ResultAuthority.ATTESTATION
    assert receipt.underlying_authority is ResultAuthority.THEOREM
    assert record.underlying_authority is ResultAuthority.THEOREM

    with pytest.raises(AuthoritySubstitutionError):
        projection.require_authority(ResultAuthority.THEOREM)

    # Requiring theorem authority on the source still works.
    theorem.require_authority(ResultAuthority.THEOREM)


def test_simulated_backend_fails_production_gates() -> None:
    with pytest.raises(ProofReceiptAttestationError, match="simulated backend identity"):
        _policy(backend_id="backend:simulated-provekit")

    sim_policy = AttestationBackendPolicy(
        backend_id="backend:provekit-shadow",
        backend_version="0.2.0",
        circuit_id="circuit:receipt-binding",
        circuit_version="2.1.0",
        ceremony_id="ceremony:mpc-2026-07",
        crs_id="crs:powers-of-tau:28",
        proving_key_id="pk:receipt-binding:sha256-cafe",
        verification_key_id="vk:receipt-binding:sha256-beef",
        revocation_policy_id="revocation:production@1",
        backend_mode=AttestationBackendMode.SIMULATED,
        verification_key_expires_at=KEY_EXPIRES,
    )
    request = prepare_receipt_attestation(
        _receipt(),
        backend_policy=sim_policy,
        witness=_witness(),
        issued_at=NOW,
        expires_at=EXPIRES,
        revocation_policy=_revocation(),
    )
    with pytest.raises(CryptographicBackendFailure, match="simulated"):
        execute_cryptographic_attestation(
            request,
            prover=lambda _r: {
                "proof_artifact_id": "artifact:sim",
                "proof_digest": "sha256:sim",
            },
            verifier=lambda _e: True,
            prover_id="prover:sim",
            verifier_id="verifier:sim",
            now=NOW,
        )

    envelope = create_attestation_envelope(
        request,
        backend_mode=AttestationBackendMode.SIMULATED,
        proof_artifact_id="artifact:sim",
        proof_digest="sha256:sim",
        prover_id="prover:sim",
    )
    assert envelope.simulated is True
    assert envelope.authoritative is False
    with pytest.raises(ProofReceiptAttestationError, match="simulated"):
        record_attestation_verification(
            envelope,
            verified=True,
            verifier_id="verifier:sim",
            verified_at=NOW,
        )

    rejected = record_attestation_verification(
        envelope,
        verified=False,
        verifier_id="verifier:sim",
        verified_at=NOW,
        diagnostic_code="simulated_rejected",
    )
    assert rejected.satisfies_gate(AttestationGate.TEST)
    assert not rejected.satisfies_gate(AttestationGate.PRODUCTION)
    assert not rejected.satisfies_gate(AttestationGate.COMPLETION)


def test_circuit_mismatch_fails_closed() -> None:
    statement = build_attestation_statement(
        _receipt(),
        backend_policy=_policy(circuit_id="circuit:receipt-binding"),
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    other = _policy(circuit_id="circuit:other-binding")
    with pytest.raises(CircuitMismatchError):
        statement.require_matches_backend_policy(other)
    with pytest.raises(CircuitMismatchError):
        verify_statement_against_policy(
            statement,
            backend_policy=other,
            revocation_policy=_revocation(),
            now=NOW,
        )


def test_stale_attestation_fails() -> None:
    statement = build_attestation_statement(
        _receipt(),
        backend_policy=_policy(),
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    assert statement.is_fresh_at(LATER)
    with pytest.raises(StaleAttestationError):
        statement.require_fresh_at(STALE)

    expired_key_policy = _policy(verification_key_expires_at="2026-07-23T12:01:00Z")
    statement_key = build_attestation_statement(
        _receipt(),
        backend_policy=expired_key_policy,
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    with pytest.raises(StaleAttestationError):
        statement_key.require_fresh_at(LATER)

    verification = _verification()
    record = build_attestation_record(verification, created_at=NOW)
    assert record.is_current_at(LATER)
    assert not record.is_current_at(STALE)


def test_revoked_material_fails() -> None:
    policy = _policy()
    revoked = _revocation(revoked_verification_key_ids=(policy.verification_key_id,))
    with pytest.raises(RevokedAttestationError, match="verification_key_revoked"):
        build_attestation_statement(
            _receipt(),
            backend_policy=policy,
            issued_at=NOW,
            expires_at=EXPIRES,
            revocation_policy=revoked,
        )

    revoked_circuit = _revocation(revoked_circuit_ids=(policy.circuit_id,))
    with pytest.raises(RevokedAttestationError, match="circuit_revoked"):
        revoked_circuit.require_current(policy)

    revoked_crs = _revocation(revoked_crs_ids=(policy.crs_id,))
    with pytest.raises(RevokedAttestationError, match="crs_revoked"):
        revoked_crs.require_current(policy)

    revoked_pk = _revocation(revoked_proving_key_ids=(policy.proving_key_id,))
    with pytest.raises(RevokedAttestationError, match="proving_key_revoked"):
        revoked_pk.require_current(policy)


def test_rejected_and_error_verdicts_are_non_authoritative() -> None:
    rejected = _verification(verified=False)
    assert rejected.verdict is AttestationVerificationVerdict.REJECTED
    assert rejected.authoritative_for_attestation is False
    assert not rejected.satisfies_gate(AttestationGate.PRODUCTION)

    request = _request()

    def bad_verifier(_envelope: AttestationEnvelope) -> bool:
        raise RuntimeError("boom")

    errored = execute_cryptographic_attestation(
        request,
        prover=lambda _r: {
            "proof_artifact_id": "artifact:x",
            "proof_digest": "sha256:x",
        },
        verifier=bad_verifier,
        prover_id="prover:x",
        verifier_id="verifier:x",
        now=NOW,
    )
    assert errored.verdict is AttestationVerificationVerdict.ERROR
    assert errored.diagnostic_code == "cryptographic_verifier_error"
    assert not errored.authoritative_for_attestation


def test_malformed_prover_output_fails_closed() -> None:
    request = _request()
    with pytest.raises(CryptographicBackendFailure, match="malformed"):
        execute_cryptographic_attestation(
            request,
            prover=lambda _r: "not-a-mapping",  # type: ignore[return-value]
            verifier=lambda _e: True,
            prover_id="prover:x",
            verifier_id="verifier:x",
            now=NOW,
        )
    with pytest.raises(CryptographicBackendFailure, match="generation failed"):
        execute_cryptographic_attestation(
            request,
            prover=lambda _r: (_ for _ in ()).throw(RuntimeError("prove failed")),
            verifier=lambda _e: True,
            prover_id="prover:x",
            verifier_id="verifier:x",
            now=NOW,
        )


def test_statement_and_record_round_trip() -> None:
    statement = build_attestation_statement(
        _receipt(),
        backend_policy=_policy(),
        issued_at=NOW,
        expires_at=EXPIRES,
    )
    restored = AttestationStatement.from_dict(statement.to_public_artifact())
    assert restored.statement_id == statement.statement_id
    assert restored.public_inputs == statement.public_inputs

    verification = _verification()
    record = build_attestation_record(verification, created_at=NOW)
    payload = record.to_public_artifact()
    assert payload["underlying_authority"] == "theorem"
    assert payload["receipt_id"] == record.receipt_id
    assert AttestationEnvelope.from_dict(
        verification.envelope.to_public_artifact()
    ).envelope_id == verification.envelope.envelope_id


def test_request_repr_redacts_witness() -> None:
    request = _request()
    text = repr(request)
    assert "redacted" in text
    assert SECRET not in text
    assert "PrivateWitness redacted" in repr(_witness())
