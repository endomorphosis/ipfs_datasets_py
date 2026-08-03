"""Fail-closed conformance verifier for proof-backed test execution.

This module consumes the public shape of ``TestProofCertificate@1`` without
depending on :mod:`ipfs_accelerate_py`.  A local
:class:`~ipfs_datasets_py.logic.zkp.provekit.test_pass_circuit.TestPassCircuitBinding`
reconstructs the complete statement and pins the real backend artifacts.
Certificate metadata is therefore descriptive only; it never selects trust.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from . import ZKPProof
from .backends import get_backend
from .provekit.test_pass_circuit import (
    REAL_TEST_PASS_BACKENDS,
    TestPassCircuitBinding,
    TestPassCircuitBindingError,
    backend_looks_available,
    normalize_backend_id,
    normalize_proof_system_id,
)

TEST_PROOF_CERTIFICATE_INTERFACE: Final = "TestProofCertificate@1"
TEST_EXECUTION_CERTIFICATE_SCHEMA: Final = (
    "ipfs_accelerate_py/agent-supervisor/test-proof-certificate@1"
)
MAX_CERTIFICATE_MAPPING_KEYS: Final = 64
MAX_CERTIFICATE_TEXT_CHARS: Final = 4_096
MAX_CERTIFICATE_JSON_BYTES: Final = 1024 * 1024

_CERTIFICATE_FIELDS: Final = frozenset(
    {
        "authority",
        "backend_mode",
        "certificate_id",
        "circuit_cid",
        "content_id",
        "contract_version",
        "epoch",
        "execution_key_cid",
        "interface",
        "issuer_id",
        "metadata",
        "policy_cid",
        "proof",
        "proof_artifact_cid",
        "proof_digest",
        "proof_system_id",
        "public_inputs",
        "receipt_cid",
        "schema",
        "statement_cid",
        "verifying_key_cid",
        "zkp_proof",
    }
)
_WRAPPER_FIELDS: Final = frozenset({"certificate", "proof", "zkp_proof"})
_PROOF_FIELDS: Final = frozenset(
    {"metadata", "proof_data", "public_inputs", "size_bytes", "timestamp"}
)

_SIMULATION_MARKERS: Final = (
    "demo",
    "fallback",
    "fake",
    "mock",
    "simulated",
    "simulation",
)
_UNAVAILABLE_MARKERS: Final = (
    "disabled",
    "not available",
    "unavailable",
    "not found",
    "missing",
    "configure",
    "not configured",
)


class CertificateVerificationStatus(StrEnum):
    """Exhaustive high-level outcome of local certificate verification."""

    VERIFIED = "verified"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class CertificateVerificationReason(StrEnum):
    """Stable, bounded reason codes for every conformance outcome."""

    VERIFIED = "verified"
    MALFORMED_CERTIFICATE = "malformed_certificate"
    MALFORMED_PROOF = "malformed_proof"
    NON_ATTESTED = "certificate_non_attested"
    UNSUPPORTED_BACKEND = "unsupported_backend"
    BACKEND_MISMATCH = "backend_mismatch"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BACKEND_ERROR = "backend_error"
    PROOF_INVALID = "proof_invalid"
    PROOF_DIGEST_MISMATCH = "proof_digest_mismatch"
    PROOF_ARTIFACT_MISMATCH = "proof_artifact_mismatch"
    CIRCUIT_MISMATCH = "circuit_mismatch"
    VERIFYING_KEY_MISMATCH = "verifying_key_mismatch"
    STATEMENT_MISMATCH = "statement_mismatch"
    RECEIPT_MISMATCH = "receipt_mismatch"
    EXECUTION_KEY_MISMATCH = "execution_key_mismatch"
    ISSUER_MISMATCH = "issuer_mismatch"
    POLICY_MISMATCH = "policy_mismatch"
    PUBLIC_INPUTS_MISMATCH = "public_inputs_mismatch"
    REPLAY_DETECTED = "replay_detected"

    # Readable aliases retained for integrations that phrase substitutions as
    # "wrong X" rather than "X mismatch".
    SIMULATED_ARTIFACT = NON_ATTESTED
    WRONG_CIRCUIT = CIRCUIT_MISMATCH
    WRONG_VERIFYING_KEY = VERIFYING_KEY_MISMATCH
    WRONG_ISSUER = ISSUER_MISMATCH
    WRONG_POLICY = POLICY_MISMATCH
    WRONG_PUBLIC_INPUTS = PUBLIC_INPUTS_MISMATCH


class CertificateAuthority(StrEnum):
    """Authority emitted by this verifier, never copied from the certificate."""

    AUTHORITATIVE = "authoritative"
    NON_ATTESTED = "non_attested"


@dataclass(frozen=True, slots=True)
class CertificateVerificationResult:
    """Typed result; truthiness is intentionally disabled."""

    __test__ = False

    status: CertificateVerificationStatus
    reason: CertificateVerificationReason
    authority: CertificateAuthority = CertificateAuthority.NON_ATTESTED
    detail: str = ""
    backend_id: str = ""
    certificate_id: str = ""

    def __post_init__(self) -> None:
        status = (
            self.status
            if isinstance(self.status, CertificateVerificationStatus)
            else CertificateVerificationStatus(self.status)
        )
        reason = (
            self.reason
            if isinstance(self.reason, CertificateVerificationReason)
            else CertificateVerificationReason(self.reason)
        )
        authority = (
            self.authority
            if isinstance(self.authority, CertificateAuthority)
            else CertificateAuthority(self.authority)
        )
        if status is CertificateVerificationStatus.VERIFIED:
            if reason is not CertificateVerificationReason.VERIFIED:
                raise ValueError("verified status requires verified reason")
            if authority is not CertificateAuthority.AUTHORITATIVE:
                raise ValueError("verified status requires authoritative authority")
        elif authority is CertificateAuthority.AUTHORITATIVE:
            raise ValueError("non-verified results cannot be authoritative")
        if not isinstance(self.detail, str) or len(self.detail) > 512:
            raise ValueError("verification detail must be a string of at most 512 chars")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "authority", authority)

    def __bool__(self) -> bool:
        raise TypeError("inspect .verified; verification results are not truthy")

    @property
    def verified(self) -> bool:
        return self.status is CertificateVerificationStatus.VERIFIED

    @property
    def available(self) -> bool:
        return self.status is not CertificateVerificationStatus.UNAVAILABLE

    @property
    def authoritative(self) -> bool:
        return (
            self.verified
            and self.authority is CertificateAuthority.AUTHORITATIVE
        )

    @property
    def can_authorize_skip(self) -> bool:
        return self.authoritative

    @property
    def reason_code(self) -> str:
        return self.reason.value

    @property
    def test_action(self) -> str:
        return "skip" if self.authoritative else "run"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason.value,
            "reason_code": self.reason.value,
            "authority": self.authority.value,
            "verified": self.verified,
            "available": self.available,
            "authoritative": self.authoritative,
            "can_authorize_skip": self.can_authorize_skip,
            "test_action": self.test_action,
            "detail": self.detail,
            "backend_id": self.backend_id,
            "certificate_id": self.certificate_id,
        }


class TestExecutionCertificateError(ValueError):
    """Raised while normalizing a malformed certificate envelope."""

    __test__ = False


def _require_text(
    value: Any,
    name: str,
    *,
    required: bool = True,
    max_chars: int = MAX_CERTIFICATE_TEXT_CHARS,
) -> str:
    if not isinstance(value, str):
        raise TestExecutionCertificateError(f"{name} must be a string")
    if value != value.strip() or (required and not value):
        qualifier = "non-empty trimmed" if required else "trimmed"
        raise TestExecutionCertificateError(f"{name} must be a {qualifier} string")
    if len(value) > max_chars:
        raise TestExecutionCertificateError(
            f"{name} exceeds {max_chars} characters"
        )
    return value


def _json_bytes(value: Any, name: str) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TestExecutionCertificateError(
            f"{name} must be canonical JSON data"
        ) from exc


def _bounded_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TestExecutionCertificateError(f"{name} must be a mapping")
    if len(value) > MAX_CERTIFICATE_MAPPING_KEYS:
        raise TestExecutionCertificateError(
            f"{name} exceeds {MAX_CERTIFICATE_MAPPING_KEYS} keys"
        )
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 256:
            raise TestExecutionCertificateError(
                f"{name} keys must be bounded non-empty strings"
            )
        normalized[key] = item
    encoded = _json_bytes(normalized, name)
    if len(encoded) > MAX_CERTIFICATE_JSON_BYTES:
        raise TestExecutionCertificateError(
            f"{name} exceeds {MAX_CERTIFICATE_JSON_BYTES} canonical JSON bytes"
        )
    return MappingProxyType(normalized)


def _reject_unknown_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    if any(not isinstance(key, str) or key not in allowed for key in value):
        raise TestExecutionCertificateError(f"{name} contains unknown fields")


def _proof_from_value(value: Any) -> ZKPProof:
    if isinstance(value, ZKPProof):
        return value
    if not isinstance(value, Mapping):
        raise TestExecutionCertificateError("proof must be ZKPProof or a mapping")
    _reject_unknown_fields(value, _PROOF_FIELDS, "proof")
    proof_data = value.get("proof_data")
    if isinstance(proof_data, str):
        try:
            proof_bytes = bytes.fromhex(proof_data)
        except ValueError as exc:
            raise TestExecutionCertificateError(
                "proof_data must be hexadecimal bytes"
            ) from exc
    elif isinstance(proof_data, (bytes, bytearray)):
        proof_bytes = bytes(proof_data)
    else:
        raise TestExecutionCertificateError(
            "proof_data must be bytes or hexadecimal text"
        )
    public_inputs = _bounded_mapping(value.get("public_inputs"), "proof public_inputs")
    metadata = _bounded_mapping(value.get("metadata"), "proof metadata")
    timestamp = value.get("timestamp", 0)
    size_bytes = value.get("size_bytes", len(proof_bytes))
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not math.isfinite(float(timestamp))
        or float(timestamp) < 0
    ):
        raise TestExecutionCertificateError(
            "proof timestamp must be a finite non-negative number"
        )
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
        raise TestExecutionCertificateError("proof size_bytes must be an integer")
    return ZKPProof(
        proof_data=proof_bytes,
        public_inputs=dict(public_inputs),
        metadata=dict(metadata),
        timestamp=float(timestamp),
        size_bytes=size_bytes,
    )


@dataclass(frozen=True, slots=True)
class TestExecutionCertificate:
    """Normalized proof-bearing form of ``TestProofCertificate@1``."""

    __test__: ClassVar[bool] = False

    receipt_cid: str
    execution_key_cid: str
    statement_cid: str
    circuit_cid: str
    verifying_key_cid: str
    proof_system_id: str
    proof: ZKPProof | None = None
    proof_artifact_cid: str = ""
    proof_digest: str = ""
    backend_mode: str = "cryptographic"
    authority: str = "authoritative"
    issuer_id: str = ""
    policy_cid: str = ""
    epoch: str = ""
    public_inputs: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    _claimed_certificate_id: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "receipt_cid",
            "execution_key_cid",
            "statement_cid",
            "circuit_cid",
            "verifying_key_cid",
            "proof_system_id",
        ):
            object.__setattr__(
                self, name, _require_text(getattr(self, name), name)
            )
        for name in (
            "proof_artifact_cid",
            "proof_digest",
            "issuer_id",
            "policy_cid",
            "epoch",
            "_claimed_certificate_id",
        ):
            object.__setattr__(
                self,
                name,
                _require_text(getattr(self, name), name, required=False),
            )
        mode_value = getattr(self.backend_mode, "value", self.backend_mode)
        authority_value = getattr(self.authority, "value", self.authority)
        object.__setattr__(
            self,
            "backend_mode",
            _require_text(mode_value, "backend_mode").lower(),
        )
        object.__setattr__(
            self,
            "authority",
            _require_text(authority_value, "authority").lower(),
        )
        object.__setattr__(
            self, "public_inputs", _bounded_mapping(self.public_inputs, "public_inputs")
        )
        object.__setattr__(
            self, "metadata", _bounded_mapping(self.metadata, "metadata")
        )
        if self.proof is not None and not isinstance(self.proof, ZKPProof):
            object.__setattr__(self, "proof", _proof_from_value(self.proof))

    @property
    def interface(self) -> str:
        return TEST_PROOF_CERTIFICATE_INTERFACE

    @property
    def certificate_id(self) -> str:
        """Stable local ID for immutable replay snapshots."""

        payload = self.to_dict(include_proof=False, include_ids=False)
        return "sha256:" + hashlib.sha256(_json_bytes(payload, "certificate")).hexdigest()

    @property
    def claimed_certificate_id(self) -> str:
        return self._claimed_certificate_id

    def to_dict(
        self, *, include_proof: bool = True, include_ids: bool = True
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": TEST_EXECUTION_CERTIFICATE_SCHEMA,
            "contract_version": 1,
            "interface": TEST_PROOF_CERTIFICATE_INTERFACE,
            "receipt_cid": self.receipt_cid,
            "execution_key_cid": self.execution_key_cid,
            "statement_cid": self.statement_cid,
            "circuit_cid": self.circuit_cid,
            "verifying_key_cid": self.verifying_key_cid,
            "proof_system_id": self.proof_system_id,
            "proof_artifact_cid": self.proof_artifact_cid,
            "proof_digest": self.proof_digest,
            "backend_mode": self.backend_mode,
            "authority": self.authority,
            "issuer_id": self.issuer_id,
            "policy_cid": self.policy_cid,
            "epoch": self.epoch,
            "public_inputs": dict(self.public_inputs),
            "metadata": dict(self.metadata),
        }
        if include_proof and self.proof is not None:
            payload["proof"] = self.proof.to_dict()
        if include_ids:
            payload["certificate_id"] = self.certificate_id
        return payload

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, proof: ZKPProof | Mapping[str, Any] | None = None
    ) -> TestExecutionCertificate:
        if not isinstance(payload, Mapping):
            raise TestExecutionCertificateError("certificate must be a mapping")
        nested = payload.get("certificate")
        if isinstance(nested, Mapping):
            _reject_unknown_fields(payload, _WRAPPER_FIELDS, "certificate wrapper")
            source = dict(nested)
            if proof is None:
                if "proof" in payload:
                    proof = payload["proof"]
                elif "zkp_proof" in payload:
                    proof = payload["zkp_proof"]
        else:
            source = dict(payload)
        _reject_unknown_fields(source, _CERTIFICATE_FIELDS, "certificate")
        interface = source.get("interface")
        version = source.get("contract_version")
        if interface in (None, "") and version in (None, ""):
            raise TestExecutionCertificateError(
                "certificate requires a versioned interface"
            )
        if interface not in (None, "", TEST_PROOF_CERTIFICATE_INTERFACE):
            raise TestExecutionCertificateError(
                f"unsupported certificate interface: {interface!r}"
            )
        if version not in (None, 1):
            raise TestExecutionCertificateError(
                f"unsupported certificate contract_version: {version!r}"
            )
        schema = source.get("schema")
        if schema not in (None, "", TEST_EXECUTION_CERTIFICATE_SCHEMA):
            raise TestExecutionCertificateError(
                f"unsupported certificate schema: {schema!r}"
            )
        if proof is None:
            if "proof" in source:
                proof = source["proof"]
            elif "zkp_proof" in source:
                proof = source["zkp_proof"]
        normalized_proof = _proof_from_value(proof) if proof is not None else None
        public_inputs = source.get("public_inputs", {})
        metadata = source.get("metadata", {})
        if public_inputs is None:
            public_inputs = {}
        if metadata is None:
            metadata = {}
        return cls(
            receipt_cid=source.get("receipt_cid", ""),
            execution_key_cid=source.get("execution_key_cid", ""),
            statement_cid=source.get("statement_cid", ""),
            circuit_cid=source.get("circuit_cid", ""),
            verifying_key_cid=source.get("verifying_key_cid", ""),
            proof_system_id=source.get("proof_system_id", ""),
            proof=normalized_proof,
            proof_artifact_cid=source.get("proof_artifact_cid", ""),
            proof_digest=source.get("proof_digest", ""),
            backend_mode=source.get("backend_mode", "cryptographic"),
            authority=source.get("authority", "authoritative"),
            issuer_id=source.get("issuer_id", ""),
            policy_cid=source.get("policy_cid", ""),
            epoch=source.get("epoch", ""),
            public_inputs=public_inputs,
            metadata=metadata,
            _claimed_certificate_id=(
                source.get("certificate_id") or source.get("content_id") or ""
            ),
        )

    @classmethod
    def from_test_proof_certificate(
        cls, certificate: Any, proof: ZKPProof | Mapping[str, Any]
    ) -> TestExecutionCertificate:
        """Normalize an accelerator contract instance without importing it."""

        if isinstance(certificate, Mapping):
            payload = certificate
        else:
            to_dict = getattr(certificate, "to_dict", None)
            if not callable(to_dict):
                raise TestExecutionCertificateError(
                    "certificate must be a mapping or expose to_dict()"
                )
            payload = to_dict()
            if not isinstance(payload, Mapping):
                raise TestExecutionCertificateError(
                    "certificate to_dict() must return a mapping"
                )
            payload = dict(payload)
            if "certificate_id" not in payload and "content_id" not in payload:
                try:
                    claimed_id = getattr(certificate, "certificate_id", "")
                except Exception as exc:
                    raise TestExecutionCertificateError(
                        "certificate_id could not be read"
                    ) from exc
                if claimed_id:
                    payload["certificate_id"] = claimed_id
        return cls.from_dict(payload, proof=proof)


def _reject(
    reason: CertificateVerificationReason,
    detail: str,
    *,
    backend_id: str = "",
    certificate_id: str = "",
) -> CertificateVerificationResult:
    return CertificateVerificationResult(
        status=CertificateVerificationStatus.REJECTED,
        reason=reason,
        detail=detail[:512],
        backend_id=backend_id,
        certificate_id=certificate_id,
    )


def _unavailable(
    detail: str, *, backend_id: str = "", certificate_id: str = ""
) -> CertificateVerificationResult:
    return CertificateVerificationResult(
        status=CertificateVerificationStatus.UNAVAILABLE,
        reason=CertificateVerificationReason.BACKEND_UNAVAILABLE,
        detail=detail[:512],
        backend_id=backend_id,
        certificate_id=certificate_id,
    )


def _contains_simulation_marker(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(marker in text for marker in _SIMULATION_MARKERS)


def _canonical_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping):
        left = dict(left)
    if isinstance(right, Mapping):
        right = dict(right)
    try:
        return _json_bytes(left, "public inputs") == _json_bytes(
            right, "public inputs"
        )
    except TestExecutionCertificateError:
        return False


def _normalize_certificate(
    certificate: TestExecutionCertificate | Mapping[str, Any] | Any,
    proof: ZKPProof | Mapping[str, Any] | None,
) -> TestExecutionCertificate:
    if isinstance(certificate, TestExecutionCertificate):
        if proof is None:
            return certificate
        payload = certificate.to_dict(include_proof=False, include_ids=False)
        return TestExecutionCertificate.from_dict(payload, proof=proof)
    if isinstance(certificate, Mapping):
        return TestExecutionCertificate.from_dict(certificate, proof=proof)
    if proof is None:
        proof = getattr(certificate, "proof", None)
    return TestExecutionCertificate.from_test_proof_certificate(certificate, proof)


def verify_test_execution_certificate(
    certificate: TestExecutionCertificate | Mapping[str, Any] | Any,
    binding: TestPassCircuitBinding,
    backend: Any | None = None,
    *,
    proof: ZKPProof | Mapping[str, Any] | None = None,
) -> CertificateVerificationResult:
    """Verify an exact test-pass certificate with a pinned real backend.

    All validation failures are returned as typed, non-authoritative results.
    An absent/disabled real backend returns ``unavailable`` and is never called.
    The function performs no writes and mutates neither replay snapshots nor
    backend selection.
    """

    if not isinstance(binding, TestPassCircuitBinding):
        return _reject(
            CertificateVerificationReason.MALFORMED_CERTIFICATE,
            "binding must be TestPassCircuitBinding",
        )
    try:
        cert = _normalize_certificate(certificate, proof)
    except (TestExecutionCertificateError, TypeError, ValueError, KeyError) as exc:
        return _reject(
            CertificateVerificationReason.MALFORMED_CERTIFICATE,
            str(exc),
        )

    backend_id = binding.backend_id
    certificate_id = cert.certificate_id
    proof_obj = cert.proof

    # Authority and downgrade checks precede backend resolution.  No simulated,
    # fallback, fake, or candidate envelope can become authoritative merely
    # because an injected verifier returns True.
    if (
        cert.backend_mode != "cryptographic"
        or cert.authority != "authoritative"
        or _contains_simulation_marker(cert.backend_mode)
        or _contains_simulation_marker(cert.authority)
    ):
        return _reject(
            CertificateVerificationReason.NON_ATTESTED,
            "certificate does not claim cryptographic authoritative provenance",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if backend_id not in REAL_TEST_PASS_BACKENDS:
        reason = (
            CertificateVerificationReason.NON_ATTESTED
            if _contains_simulation_marker(backend_id)
            else CertificateVerificationReason.UNSUPPORTED_BACKEND
        )
        return _reject(
            reason,
            "only pinned Groth16 and ProveKit backends are authoritative",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    certificate_system = normalize_proof_system_id(cert.proof_system_id)
    if certificate_system != binding.proof_system_id:
        return _reject(
            CertificateVerificationReason.BACKEND_MISMATCH,
            "certificate proof system does not match the local binding",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    envelope_checks = (
        (
            cert.circuit_cid,
            binding.circuit_cid,
            CertificateVerificationReason.CIRCUIT_MISMATCH,
            "circuit",
        ),
        (
            cert.verifying_key_cid,
            binding.verifying_key_cid,
            CertificateVerificationReason.VERIFYING_KEY_MISMATCH,
            "verifying key",
        ),
        (
            cert.statement_cid,
            binding.statement_cid,
            CertificateVerificationReason.STATEMENT_MISMATCH,
            "statement",
        ),
        (
            cert.receipt_cid,
            binding.receipt_cid,
            CertificateVerificationReason.RECEIPT_MISMATCH,
            "receipt",
        ),
        (
            cert.execution_key_cid,
            binding.execution_key_cid,
            CertificateVerificationReason.EXECUTION_KEY_MISMATCH,
            "execution key",
        ),
        (
            cert.issuer_id,
            binding.issuer_id,
            CertificateVerificationReason.ISSUER_MISMATCH,
            "issuer",
        ),
        (
            cert.policy_cid,
            binding.policy_cid,
            CertificateVerificationReason.POLICY_MISMATCH,
            "policy",
        ),
    )
    for actual, expected, reason, label in envelope_checks:
        if actual != expected:
            return _reject(
                reason,
                f"certificate {label} does not match the local binding",
                backend_id=backend_id,
                certificate_id=certificate_id,
            )
    if cert.epoch != binding.epoch:
        return _reject(
            CertificateVerificationReason.REPLAY_DETECTED,
            "certificate epoch is outside the current verifier binding",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    expected_inputs = binding.expected_public_inputs
    if not _canonical_equal(cert.public_inputs, expected_inputs):
        return _reject(
            CertificateVerificationReason.PUBLIC_INPUTS_MISMATCH,
            "certificate public inputs differ from verifier reconstruction",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if proof_obj is None:
        return _reject(
            CertificateVerificationReason.MALFORMED_PROOF,
            "certificate does not contain proof bytes",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    try:
        _bounded_mapping(proof_obj.public_inputs, "proof public_inputs")
        _bounded_mapping(proof_obj.metadata, "proof metadata")
    except TestExecutionCertificateError:
        return _reject(
            CertificateVerificationReason.MALFORMED_PROOF,
            "proof public inputs or metadata are malformed or over budget",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if (
        not isinstance(proof_obj.proof_data, (bytes, bytearray))
        or not proof_obj.proof_data
        or len(proof_obj.proof_data) > binding.max_proof_bytes
        or isinstance(proof_obj.size_bytes, bool)
        or not isinstance(proof_obj.size_bytes, int)
        or proof_obj.size_bytes != len(proof_obj.proof_data)
        or isinstance(proof_obj.timestamp, bool)
        or not isinstance(proof_obj.timestamp, (int, float))
        or not math.isfinite(float(proof_obj.timestamp))
        or float(proof_obj.timestamp) < 0
    ):
        return _reject(
            CertificateVerificationReason.MALFORMED_PROOF,
            "proof bytes, size, or mappings are malformed or over budget",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if not _canonical_equal(proof_obj.public_inputs, expected_inputs):
        return _reject(
            CertificateVerificationReason.PUBLIC_INPUTS_MISMATCH,
            "proof public inputs differ from verifier reconstruction",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    proof_backend = normalize_backend_id(proof_obj.metadata.get("backend"))
    proof_system = normalize_proof_system_id(
        proof_obj.metadata.get("proof_system")
    )
    backend_type_name = (
        f"{type(backend).__module__}.{type(backend).__name__}" if backend else ""
    )
    if any(
        _contains_simulation_marker(value)
        for value in (
            proof_obj.metadata.get("backend"),
            proof_obj.metadata.get("proof_system"),
            proof_obj.metadata.get("authority"),
            backend_type_name,
        )
    ):
        return _reject(
            CertificateVerificationReason.NON_ATTESTED,
            "simulated or fallback proof artifacts are non-attested",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if proof_backend != backend_id or proof_system != binding.proof_system_id:
        return _reject(
            CertificateVerificationReason.BACKEND_MISMATCH,
            "proof backend metadata does not match the local binding",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    actual_digest = "sha256:" + hashlib.sha256(proof_obj.proof_data).hexdigest()
    if not cert.proof_digest or cert.proof_digest != actual_digest:
        return _reject(
            CertificateVerificationReason.PROOF_DIGEST_MISMATCH,
            "proof bytes do not match certificate proof_digest",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if not cert.proof_artifact_cid:
        return _reject(
            CertificateVerificationReason.MALFORMED_CERTIFICATE,
            "authoritative certificates require proof_artifact_cid",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if (
        cert.proof_artifact_cid.startswith("sha256:")
        and cert.proof_artifact_cid != actual_digest
    ):
        return _reject(
            CertificateVerificationReason.PROOF_ARTIFACT_MISMATCH,
            "proof bytes do not match proof_artifact_cid",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    replay_ids = {certificate_id}
    if cert.claimed_certificate_id:
        replay_ids.add(cert.claimed_certificate_id)
    if (
        replay_ids.intersection(binding.replayed_certificate_ids)
        or actual_digest in binding.replayed_proof_digests
        or binding.replay_token() in binding.replayed_tokens
    ):
        return _reject(
            CertificateVerificationReason.REPLAY_DETECTED,
            "certificate appears in the immutable replay snapshot",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    if backend is None:
        try:
            backend = get_backend(backend_id)
        except Exception as exc:
            return _unavailable(
                f"real backend could not be loaded: {exc}",
                backend_id=backend_id,
                certificate_id=certificate_id,
            )
    actual_backend_id = normalize_backend_id(getattr(backend, "backend_id", ""))
    if actual_backend_id != backend_id:
        return _reject(
            CertificateVerificationReason.BACKEND_MISMATCH,
            "verifier backend does not match the pinned backend",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if _contains_simulation_marker(backend_type_name or type(backend).__name__):
        return _reject(
            CertificateVerificationReason.NON_ATTESTED,
            "simulated or fallback verifiers are non-attested",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if not backend_looks_available(backend, binding):
        return _unavailable(
            "pinned real verifier backend is unavailable",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    artifact_problem = binding.artifact_problem(bytes(proof_obj.proof_data))
    if artifact_problem is not None:
        kind, detail = artifact_problem
        if kind == "unavailable":
            return _unavailable(
                detail, backend_id=backend_id, certificate_id=certificate_id
            )
        reason = (
            CertificateVerificationReason.PROOF_ARTIFACT_MISMATCH
            if kind == "proof_artifact_mismatch"
            else CertificateVerificationReason.VERIFYING_KEY_MISMATCH
        )
        return _reject(
            reason,
            detail,
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    try:
        backend_proof = binding.prepare_proof_for_backend(proof_obj)
        valid = backend.verify_proof(backend_proof)
    except Exception as exc:
        detail = str(exc)
        if any(marker in detail.lower() for marker in _UNAVAILABLE_MARKERS):
            return _unavailable(
                f"real verifier unavailable: {detail}",
                backend_id=backend_id,
                certificate_id=certificate_id,
            )
        return _reject(
            CertificateVerificationReason.BACKEND_ERROR,
            f"real verifier failed: {detail}",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )
    if valid is not True:
        return _reject(
            CertificateVerificationReason.PROOF_INVALID,
            "real verifier rejected the proof",
            backend_id=backend_id,
            certificate_id=certificate_id,
        )

    return CertificateVerificationResult(
        status=CertificateVerificationStatus.VERIFIED,
        reason=CertificateVerificationReason.VERIFIED,
        authority=CertificateAuthority.AUTHORITATIVE,
        detail="proof and all local certificate bindings verified",
        backend_id=backend_id,
        certificate_id=certificate_id,
    )


__all__ = [
    "CertificateAuthority",
    "CertificateVerificationReason",
    "CertificateVerificationResult",
    "CertificateVerificationStatus",
    "TEST_EXECUTION_CERTIFICATE_SCHEMA",
    "TEST_PROOF_CERTIFICATE_INTERFACE",
    "TestExecutionCertificate",
    "TestExecutionCertificateError",
    "TestPassCircuitBinding",
    "TestPassCircuitBindingError",
    "verify_test_execution_certificate",
]
