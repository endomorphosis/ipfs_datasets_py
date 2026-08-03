"""Conformance tests for proof-backed test-execution certificates."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.zkp import ZKPProof
from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend
from ipfs_datasets_py.logic.zkp.provekit.test_pass_circuit import (
    TEST_PASS_CIRCUIT_BINDING_INTERFACE,
    TestPassCircuitBinding,
    TestPassCircuitBindingError,
)
from ipfs_datasets_py.logic.zkp.statements.test_pass import (
    TestPassStatementV1,
    build_public_inputs,
    build_statement,
)
from ipfs_datasets_py.logic.zkp.test_execution_certificate import (
    TEST_PROOF_CERTIFICATE_INTERFACE,
    CertificateAuthority,
    CertificateVerificationReason,
    CertificateVerificationStatus,
    TestExecutionCertificate,
    verify_test_execution_certificate,
)

_SIGNING_KEY = b"offline-test-pass-conformance-key"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _signed_fixture_bytes(
    backend_id: str, proof_system_id: str, public_inputs: dict[str, Any]
) -> bytes:
    message = b"\0".join(
        (
            backend_id.encode(),
            proof_system_id.encode(),
            _canonical_bytes(public_inputs),
        )
    )
    return hmac.digest(_SIGNING_KEY, message, "sha256")


class ConformanceBackend:
    """Offline verifier exercising the real backend protocol boundary."""

    available = True

    def __init__(self, backend_id: str, proof_system_id: str) -> None:
        self.backend_id = backend_id
        self.proof_system_id = proof_system_id
        self.calls = 0
        self.last_proof: ZKPProof | None = None

    def verify_proof(self, proof: ZKPProof) -> bool:
        self.calls += 1
        self.last_proof = proof
        expected = _signed_fixture_bytes(
            self.backend_id,
            self.proof_system_id,
            dict(proof.public_inputs),
        )
        return hmac.compare_digest(proof.proof_data, expected)


class OfflineBackend:
    available = False

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id
        self.calls = 0

    def verify_proof(self, proof: ZKPProof) -> bool:
        self.calls += 1
        raise AssertionError("an unavailable backend must not be called")


class BrokenBackend:
    available = True

    def __init__(self, backend_id: str, message: str) -> None:
        self.backend_id = backend_id
        self.message = message
        self.calls = 0

    def verify_proof(self, proof: ZKPProof) -> bool:
        self.calls += 1
        raise RuntimeError(self.message)


class SimulatedBackend:
    available = True
    backend_id = "groth16"

    def __init__(self) -> None:
        self.calls = 0

    def verify_proof(self, proof: ZKPProof) -> bool:
        self.calls += 1
        return True


@dataclass(frozen=True)
class CertificateFixture:
    backend_id: str
    proof_system_id: str
    statement: TestPassStatementV1
    binding: TestPassCircuitBinding
    proof: ZKPProof
    certificate: TestExecutionCertificate
    verifier: ConformanceBackend
    artifact_paths: tuple[Path, ...]


def _make_fixture(tmp_path: Path, backend_id: str) -> CertificateFixture:
    proof_system_id = "groth16" if backend_id == "groth16" else "provekit-whir"
    key_bytes = b"pinned-provekit-verifier-key-v1"
    verifying_key_cid = (
        _digest(key_bytes)
        if backend_id == "provekit"
        else "cid:vk:test-pass-groth16-v1"
    )
    statement = build_statement(
        build_public_inputs(
            receipt_cid=_digest(b"admitted complete-pass receipt"),
            execution_key_cid="cid:execution-key:fixture-v1",
            policy_cid="cid:policy:strict-reuse-v1",
            statement_cid="cid:statement:TestPassStatementV1",
            circuit_cid="cid:circuit:test-pass-v1",
            verifying_key_cid=verifying_key_cid,
            issuer_id="issuer:trusted-runner",
            epoch="epoch:2026-07-31",
            locator_cid="cid:locator:fixture-node",
            completeness_policy_cid="cid:completeness:strict-v1",
        )
    )
    public_inputs = statement.to_public_inputs()
    proof_bytes = _signed_fixture_bytes(
        backend_id, proof_system_id, public_inputs
    )
    artifacts: dict[str, str] = {}
    artifact_paths: tuple[Path, ...] = ()
    if backend_id == "provekit":
        key_path = tmp_path / "test-pass.pkv"
        proof_path = tmp_path / "test-pass.proof"
        key_path.write_bytes(key_bytes)
        proof_path.write_bytes(proof_bytes)
        artifacts = {
            "verifier_key_path": str(key_path),
            "proof_path": str(proof_path),
        }
        artifact_paths = (key_path, proof_path)

    binding = TestPassCircuitBinding(
        statement,
        backend_id=backend_id,
        proof_system_id=proof_system_id,
        verifier_artifacts=artifacts,
    )
    proof = ZKPProof(
        proof_data=proof_bytes,
        public_inputs=public_inputs,
        metadata={
            "backend": backend_id,
            "proof_system": proof_system_id,
            # Certificate-provided paths must be discarded by the binding.
            "proof_path": "/untrusted/certificate-selected-proof",
            "verifier_key_path": "/untrusted/certificate-selected-key",
        },
        timestamp=1_775_000_000.0,
        size_bytes=len(proof_bytes),
    )
    proof_digest = _digest(proof_bytes)
    certificate = TestExecutionCertificate(
        receipt_cid=statement.public_inputs.receipt_cid,
        execution_key_cid=statement.public_inputs.execution_key_cid,
        statement_cid=statement.public_inputs.statement_cid,
        circuit_cid=statement.public_inputs.circuit_cid,
        verifying_key_cid=statement.public_inputs.verifying_key_cid,
        proof_system_id=proof_system_id,
        proof=proof,
        proof_artifact_cid=proof_digest,
        proof_digest=proof_digest,
        backend_mode="cryptographic",
        authority="authoritative",
        issuer_id=statement.public_inputs.issuer_id,
        policy_cid=statement.public_inputs.policy_cid,
        epoch=statement.public_inputs.epoch,
        public_inputs=public_inputs,
        metadata={"fixture": "offline-real-interface-v1"},
    )
    verifier = ConformanceBackend(backend_id, proof_system_id)
    return CertificateFixture(
        backend_id=backend_id,
        proof_system_id=proof_system_id,
        statement=statement,
        binding=binding,
        proof=proof,
        certificate=certificate,
        verifier=verifier,
        artifact_paths=artifact_paths,
    )


@pytest.fixture(params=("groth16", "provekit"))
def real_fixture(tmp_path: Path, request: pytest.FixtureRequest) -> CertificateFixture:
    return _make_fixture(tmp_path, str(request.param))


def _binding_with(
    fixture: CertificateFixture, **changes: Any
) -> TestPassCircuitBinding:
    kwargs: dict[str, Any] = {
        "backend_id": fixture.binding.backend_id,
        "proof_system_id": fixture.binding.proof_system_id,
        "verifier_artifacts": fixture.binding.verifier_artifacts,
        "max_proof_bytes": fixture.binding.max_proof_bytes,
    }
    kwargs.update(changes)
    return TestPassCircuitBinding(fixture.statement, **kwargs)


def _assert_rejected(
    result: Any, reason: CertificateVerificationReason
) -> None:
    assert result.status is CertificateVerificationStatus.REJECTED
    assert result.reason is reason
    assert result.authority is CertificateAuthority.NON_ATTESTED
    assert result.verified is False
    assert result.authoritative is False
    assert result.can_authorize_skip is False
    assert result.test_action == "run"


def test_interfaces_are_explicit(real_fixture: CertificateFixture) -> None:
    assert real_fixture.certificate.interface == TEST_PROOF_CERTIFICATE_INTERFACE
    assert TEST_PROOF_CERTIFICATE_INTERFACE == "TestProofCertificate@1"
    assert real_fixture.binding.interface == TEST_PASS_CIRCUIT_BINDING_INTERFACE
    assert TEST_PASS_CIRCUIT_BINDING_INTERFACE == "TestPassCircuitBinding@1"


def test_correct_real_backend_fixtures_are_authoritative(
    real_fixture: CertificateFixture,
) -> None:
    result = verify_test_execution_certificate(
        real_fixture.certificate,
        real_fixture.binding,
        real_fixture.verifier,
    )

    assert result.status is CertificateVerificationStatus.VERIFIED
    assert result.reason is CertificateVerificationReason.VERIFIED
    assert result.authority is CertificateAuthority.AUTHORITATIVE
    assert result.verified is True
    assert result.authoritative is True
    assert result.can_authorize_skip is True
    assert result.test_action == "skip"
    assert real_fixture.verifier.calls == 1
    assert real_fixture.verifier.last_proof is not None
    if real_fixture.backend_id == "provekit":
        metadata = real_fixture.verifier.last_proof.metadata
        assert metadata["provekit_artifacts"] == dict(
            real_fixture.binding.verifier_artifacts
        )
        assert "proof_path" not in metadata
        assert "verifier_key_path" not in metadata


@pytest.mark.parametrize(
    ("field_name", "replacement", "reason"),
    (
        (
            "circuit_cid",
            "cid:circuit:wrong-v1",
            CertificateVerificationReason.CIRCUIT_MISMATCH,
        ),
        (
            "verifying_key_cid",
            "cid:vk:wrong-v1",
            CertificateVerificationReason.VERIFYING_KEY_MISMATCH,
        ),
        (
            "issuer_id",
            "issuer:untrusted",
            CertificateVerificationReason.ISSUER_MISMATCH,
        ),
        (
            "policy_cid",
            "cid:policy:wrong-v1",
            CertificateVerificationReason.POLICY_MISMATCH,
        ),
    ),
)
def test_wrong_certificate_bindings_fail_with_typed_reasons(
    real_fixture: CertificateFixture,
    field_name: str,
    replacement: str,
    reason: CertificateVerificationReason,
) -> None:
    certificate = replace(
        real_fixture.certificate, **{field_name: replacement}
    )

    result = verify_test_execution_certificate(
        certificate, real_fixture.binding, real_fixture.verifier
    )

    _assert_rejected(result, reason)
    assert real_fixture.verifier.calls == 0


def test_wrong_proof_system_fails_before_backend(
    real_fixture: CertificateFixture,
) -> None:
    certificate = replace(
        real_fixture.certificate, proof_system_id="different-proof-system"
    )
    result = verify_test_execution_certificate(
        certificate, real_fixture.binding, real_fixture.verifier
    )
    _assert_rejected(result, CertificateVerificationReason.BACKEND_MISMATCH)
    assert real_fixture.verifier.calls == 0


@pytest.mark.parametrize("location", ("certificate", "proof"))
def test_wrong_public_inputs_fail_with_typed_reason(
    real_fixture: CertificateFixture, location: str
) -> None:
    changed_inputs = dict(real_fixture.statement.to_public_inputs())
    changed_inputs["call_outcome"] = "fail"
    if location == "certificate":
        certificate = replace(
            real_fixture.certificate, public_inputs=changed_inputs
        )
    else:
        proof = replace(real_fixture.proof, public_inputs=changed_inputs)
        certificate = replace(real_fixture.certificate, proof=proof)

    result = verify_test_execution_certificate(
        certificate, real_fixture.binding, real_fixture.verifier
    )

    _assert_rejected(result, CertificateVerificationReason.PUBLIC_INPUTS_MISMATCH)
    assert real_fixture.verifier.calls == 0


@pytest.mark.parametrize(
    "proof",
    (
        None,
        ZKPProof(
            proof_data=b"",
            public_inputs={},
            metadata={"backend": "groth16", "proof_system": "groth16"},
            timestamp=0.0,
            size_bytes=0,
        ),
        ZKPProof(
            proof_data=b"x",
            public_inputs={},
            metadata={"backend": "groth16", "proof_system": "groth16"},
            timestamp=0.0,
            size_bytes=2,
        ),
    ),
)
def test_missing_or_malformed_proof_is_typed(
    real_fixture: CertificateFixture, proof: ZKPProof | None
) -> None:
    if proof is not None:
        proof = replace(
            proof,
            public_inputs=real_fixture.statement.to_public_inputs(),
            metadata={
                "backend": real_fixture.backend_id,
                "proof_system": real_fixture.proof_system_id,
            },
        )
    certificate = replace(real_fixture.certificate, proof=proof)

    result = verify_test_execution_certificate(
        certificate, real_fixture.binding, real_fixture.verifier
    )

    _assert_rejected(result, CertificateVerificationReason.MALFORMED_PROOF)
    assert real_fixture.verifier.calls == 0


@pytest.mark.parametrize("bad_timestamp", (float("nan"), -1.0, "now"))
def test_malformed_direct_proof_timestamp_is_typed(
    real_fixture: CertificateFixture, bad_timestamp: Any
) -> None:
    proof = replace(real_fixture.proof, timestamp=bad_timestamp)
    result = verify_test_execution_certificate(
        replace(real_fixture.certificate, proof=proof),
        real_fixture.binding,
        real_fixture.verifier,
    )
    _assert_rejected(result, CertificateVerificationReason.MALFORMED_PROOF)
    assert real_fixture.verifier.calls == 0


def test_malformed_certificate_mapping_is_typed(
    real_fixture: CertificateFixture,
) -> None:
    payload = real_fixture.certificate.to_dict()
    payload["receipt_cid"] = 7
    result = verify_test_execution_certificate(
        payload, real_fixture.binding, real_fixture.verifier
    )
    _assert_rejected(result, CertificateVerificationReason.MALFORMED_CERTIFICATE)
    assert real_fixture.verifier.calls == 0


@pytest.mark.parametrize(
    "mutation",
    (
        {"interface": None, "contract_version": None},
        {"schema": "unknown/test-proof-certificate@1"},
        {"unknown_field": "must-not-be-ignored"},
    ),
)
def test_ambiguous_or_unknown_certificate_envelopes_are_malformed(
    real_fixture: CertificateFixture, mutation: dict[str, Any]
) -> None:
    payload = real_fixture.certificate.to_dict()
    payload.update(mutation)

    result = verify_test_execution_certificate(
        payload, real_fixture.binding, real_fixture.verifier
    )

    _assert_rejected(result, CertificateVerificationReason.MALFORMED_CERTIFICATE)
    assert real_fixture.verifier.calls == 0


def test_proof_digest_and_artifact_substitution_are_typed(
    real_fixture: CertificateFixture,
) -> None:
    digest_result = verify_test_execution_certificate(
        replace(
            real_fixture.certificate,
            proof_digest=_digest(b"different-proof"),
        ),
        real_fixture.binding,
        real_fixture.verifier,
    )
    _assert_rejected(
        digest_result, CertificateVerificationReason.PROOF_DIGEST_MISMATCH
    )

    artifact_result = verify_test_execution_certificate(
        replace(
            real_fixture.certificate,
            proof_artifact_cid=_digest(b"different-artifact"),
        ),
        real_fixture.binding,
        real_fixture.verifier,
    )
    _assert_rejected(
        artifact_result, CertificateVerificationReason.PROOF_ARTIFACT_MISMATCH
    )
    assert real_fixture.verifier.calls == 0


@pytest.mark.parametrize(
    "replay_field",
    (
        "replayed_certificate_ids",
        "replayed_proof_digests",
        "replayed_tokens",
    ),
)
def test_replay_snapshots_fail_closed_without_mutation(
    real_fixture: CertificateFixture, replay_field: str
) -> None:
    value = {
        "replayed_certificate_ids": real_fixture.certificate.certificate_id,
        "replayed_proof_digests": real_fixture.certificate.proof_digest,
        "replayed_tokens": real_fixture.binding.replay_token(),
    }[replay_field]
    binding = _binding_with(real_fixture, **{replay_field: (value,)})
    before = (
        binding.replayed_certificate_ids,
        binding.replayed_proof_digests,
        binding.replayed_tokens,
    )

    result = verify_test_execution_certificate(
        real_fixture.certificate, binding, real_fixture.verifier
    )

    _assert_rejected(result, CertificateVerificationReason.REPLAY_DETECTED)
    assert before == (
        binding.replayed_certificate_ids,
        binding.replayed_proof_digests,
        binding.replayed_tokens,
    )
    assert real_fixture.verifier.calls == 0


def test_old_epoch_is_reported_as_replay(
    real_fixture: CertificateFixture,
) -> None:
    certificate = replace(real_fixture.certificate, epoch="epoch:2025-01-01")
    result = verify_test_execution_certificate(
        certificate, real_fixture.binding, real_fixture.verifier
    )
    _assert_rejected(result, CertificateVerificationReason.REPLAY_DETECTED)
    assert real_fixture.verifier.calls == 0


@pytest.mark.parametrize(
    ("changes", "proof_metadata"),
    (
        ({"backend_mode": "simulated"}, None),
        ({"authority": "non_attested"}, None),
        ({}, {"backend": "simulated", "proof_system": "simulated"}),
    ),
)
def test_simulated_artifacts_never_authorize_skip(
    real_fixture: CertificateFixture,
    changes: dict[str, str],
    proof_metadata: dict[str, str] | None,
) -> None:
    certificate = replace(real_fixture.certificate, **changes)
    if proof_metadata is not None:
        certificate = replace(
            certificate,
            proof=replace(real_fixture.proof, metadata=proof_metadata),
        )

    result = verify_test_execution_certificate(
        certificate, real_fixture.binding, real_fixture.verifier
    )

    _assert_rejected(result, CertificateVerificationReason.NON_ATTESTED)
    assert real_fixture.verifier.calls == 0


def test_simulated_verifier_instance_never_authorizes_skip(
    real_fixture: CertificateFixture,
) -> None:
    backend = SimulatedBackend()
    result = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding, backend
    )
    _assert_rejected(result, CertificateVerificationReason.NON_ATTESTED)
    assert backend.calls == 0


def test_unavailable_backend_is_non_authoritative_and_has_no_side_effects(
    real_fixture: CertificateFixture,
) -> None:
    backend = OfflineBackend(real_fixture.backend_id)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in real_fixture.artifact_paths
    }

    result = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding, backend
    )

    assert result.status is CertificateVerificationStatus.UNAVAILABLE
    assert result.reason is CertificateVerificationReason.BACKEND_UNAVAILABLE
    assert result.available is False
    assert result.authoritative is False
    assert result.can_authorize_skip is False
    assert result.test_action == "run"
    assert backend.calls == 0
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in real_fixture.artifact_paths
    }


@pytest.mark.parametrize("backend_id", ("groth16", "provekit"))
def test_unavailable_repository_backend_is_not_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_id: str,
) -> None:
    fixture = _make_fixture(tmp_path, backend_id)
    if backend_id == "groth16":
        monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "0")
        backend: Any = Groth16Backend()
    else:
        backend = ProveKitBackend(
            binary_path=str(tmp_path / "missing-provekit-binary")
        )
    calls = 0

    def must_not_verify(proof: ZKPProof) -> bool:
        nonlocal calls
        calls += 1
        raise AssertionError("unavailable repository backend was called")

    monkeypatch.setattr(backend, "verify_proof", must_not_verify)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in fixture.artifact_paths
    }

    result = verify_test_execution_certificate(
        fixture.certificate, fixture.binding, backend
    )

    assert result.status is CertificateVerificationStatus.UNAVAILABLE
    assert result.reason is CertificateVerificationReason.BACKEND_UNAVAILABLE
    assert result.authoritative is False
    assert calls == 0
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in fixture.artifact_paths
    }


def test_backend_load_failure_is_typed_and_non_mutating(
    real_fixture: CertificateFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def unavailable_loader(backend_id: str) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.zkp.test_execution_certificate.get_backend",
        unavailable_loader,
    )
    replay_before = real_fixture.binding.replayed_proof_digests

    result = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding
    )

    assert result.status is CertificateVerificationStatus.UNAVAILABLE
    assert result.reason is CertificateVerificationReason.BACKEND_UNAVAILABLE
    assert result.authoritative is False
    assert calls == 1
    assert real_fixture.binding.replayed_proof_digests is replay_before


def test_backend_rejection_and_failure_are_distinct_typed_results(
    real_fixture: CertificateFixture,
) -> None:
    invalid = ConformanceBackend(
        real_fixture.backend_id, real_fixture.proof_system_id
    )
    invalid.proof_system_id = "wrong-domain"
    rejected = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding, invalid
    )
    _assert_rejected(rejected, CertificateVerificationReason.PROOF_INVALID)

    broken = BrokenBackend(real_fixture.backend_id, "internal verifier fault")
    failed = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding, broken
    )
    _assert_rejected(failed, CertificateVerificationReason.BACKEND_ERROR)
    assert invalid.calls == 1
    assert broken.calls == 1


def test_runtime_unavailability_is_not_a_backend_error(
    real_fixture: CertificateFixture,
) -> None:
    backend = BrokenBackend(real_fixture.backend_id, "tool unavailable")
    result = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding, backend
    )
    assert result.status is CertificateVerificationStatus.UNAVAILABLE
    assert result.reason is CertificateVerificationReason.BACKEND_UNAVAILABLE
    assert result.authoritative is False
    assert backend.calls == 1


def test_backend_identity_mismatch_fails_before_verification(
    real_fixture: CertificateFixture,
) -> None:
    other = (
        "provekit" if real_fixture.backend_id == "groth16" else "groth16"
    )
    backend = ConformanceBackend(other, real_fixture.proof_system_id)
    result = verify_test_execution_certificate(
        real_fixture.certificate, real_fixture.binding, backend
    )
    _assert_rejected(result, CertificateVerificationReason.BACKEND_MISMATCH)
    assert backend.calls == 0


def test_provekit_pinned_artifact_mismatch_fails_before_backend(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path, "provekit")
    fixture.artifact_paths[0].write_bytes(b"substituted verifier key")

    result = verify_test_execution_certificate(
        fixture.certificate, fixture.binding, fixture.verifier
    )

    _assert_rejected(
        result, CertificateVerificationReason.VERIFYING_KEY_MISMATCH
    )
    assert fixture.verifier.calls == 0


def test_provekit_pinned_proof_substitution_has_artifact_reason(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path, "provekit")
    fixture.artifact_paths[1].write_bytes(b"substituted proof artifact")

    result = verify_test_execution_certificate(
        fixture.certificate, fixture.binding, fixture.verifier
    )

    _assert_rejected(
        result, CertificateVerificationReason.PROOF_ARTIFACT_MISMATCH
    )
    assert fixture.verifier.calls == 0


def test_accelerator_certificate_id_is_preserved_for_replay(
    real_fixture: CertificateFixture,
) -> None:
    accelerator_id = "bafyreih-test-proof-certificate-id"

    class AcceleratorCertificateProxy:
        certificate_id = accelerator_id

        def to_dict(self) -> dict[str, Any]:
            return real_fixture.certificate.to_dict(
                include_proof=False, include_ids=False
            )

    binding = _binding_with(
        real_fixture, replayed_certificate_ids=(accelerator_id,)
    )
    result = verify_test_execution_certificate(
        AcceleratorCertificateProxy(),
        binding,
        real_fixture.verifier,
        proof=real_fixture.proof,
    )

    _assert_rejected(result, CertificateVerificationReason.REPLAY_DETECTED)
    assert real_fixture.verifier.calls == 0


def test_certificate_roundtrip_and_external_proof_argument(
    real_fixture: CertificateFixture,
) -> None:
    payload = real_fixture.certificate.to_dict()
    restored = TestExecutionCertificate.from_dict(payload)
    assert restored.to_dict() == payload

    envelope_only = real_fixture.certificate.to_dict(include_proof=False)
    result = verify_test_execution_certificate(
        envelope_only,
        real_fixture.binding,
        real_fixture.verifier,
        proof=real_fixture.proof,
    )
    assert result.verified is True
    assert result.authoritative is True


def test_binding_reconstructs_inputs_and_rejects_conflicting_pins(
    real_fixture: CertificateFixture,
) -> None:
    binding = TestPassCircuitBinding(
        expected_public_inputs=real_fixture.statement.to_public_inputs(),
        backend_id=real_fixture.backend_id,
        verifier_artifacts=real_fixture.binding.verifier_artifacts,
    )
    assert binding.expected_public_inputs == real_fixture.statement.to_public_inputs()

    with pytest.raises(TestPassCircuitBindingError, match="circuit_cid"):
        TestPassCircuitBinding(
            real_fixture.statement,
            backend_id=real_fixture.backend_id,
            circuit_cid="cid:circuit:substituted",
        )


def test_typed_result_cannot_be_used_as_an_ambiguous_boolean(
    real_fixture: CertificateFixture,
) -> None:
    result = verify_test_execution_certificate(
        real_fixture.certificate,
        real_fixture.binding,
        real_fixture.verifier,
    )
    with pytest.raises(TypeError, match="inspect .verified"):
        bool(result)
