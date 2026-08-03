"""Pinned verifier binding for ``TestPassStatementV1`` certificates.

The binding is deliberately a verifier-side object.  It is not populated from
certificate metadata: callers construct it from the receipt/execution context
they are deciding about and from reviewed circuit/key artifacts.  This keeps a
certificate from selecting its own circuit, verification key, issuer, policy,
or public inputs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .. import ZKPProof
from ..statements.test_pass import TestPassStatementV1

TEST_PASS_CIRCUIT_BINDING_INTERFACE: Final = "TestPassCircuitBinding@1"
DEFAULT_MAX_TEST_PASS_PROOF_BYTES: Final = 4 * 1024 * 1024
REAL_TEST_PASS_BACKENDS: Final = frozenset({"groth16", "provekit"})

_BACKEND_ALIASES: Final = {
    "g16": "groth16",
    "groth16": "groth16",
    "pk": "provekit",
    "provekit": "provekit",
    "provekit-whir": "provekit",
    "whir": "provekit",
}
_PROOF_SYSTEM_DEFAULTS: Final = {
    "groth16": "groth16",
    "provekit": "provekit-whir",
}
_ARTIFACT_KEYS: Final = frozenset(
    {
        "circuit_path",
        "cwd",
        "package_dir",
        "program_dir",
        "proof_output_path",
        "proof_path",
        "pkv_path",
        "verifier_key_path",
    }
)


class TestPassCircuitBindingError(ValueError):
    """Raised when a verifier-side test-pass binding is unsafe or malformed."""

    __test__ = False


def normalize_backend_id(value: Any) -> str:
    """Return the closed real-backend identifier for *value*.

    Unknown identifiers are retained in normalized form so callers can return
    a typed ``unsupported`` result instead of failing during construction.
    """

    text = str(value or "").strip().lower()
    return _BACKEND_ALIASES.get(text, text)


def normalize_proof_system_id(value: Any) -> str:
    """Normalize harmless spelling differences in proof-system identifiers."""

    text = str(value or "").strip().lower().replace("_", "-")
    if text in {"g16", "groth-16", "groth16-bn254"}:
        return "groth16"
    if text in {"pk", "provekit", "whir", "provekit-whir"}:
        return "provekit-whir"
    return text


def _bounded_text(value: Any, name: str, *, max_chars: int = 4_096) -> str:
    if not isinstance(value, str):
        raise TestPassCircuitBindingError(f"{name} must be a string")
    if not value or value != value.strip():
        raise TestPassCircuitBindingError(
            f"{name} must be a non-empty trimmed string"
        )
    if len(value) > max_chars:
        raise TestPassCircuitBindingError(
            f"{name} exceeds {max_chars} characters"
        )
    return value


def _string_set(values: Iterable[str], name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes, bytearray)):
        raise TestPassCircuitBindingError(f"{name} must be an iterable of strings")
    normalized: set[str] = set()
    for value in values:
        normalized.add(_bounded_text(value, f"{name} item"))
    if len(normalized) > 4_096:
        raise TestPassCircuitBindingError(f"{name} exceeds 4096 entries")
    return frozenset(normalized)


def _artifact_mapping(value: Mapping[str, Any] | None) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TestPassCircuitBindingError("verifier_artifacts must be a mapping")
    if len(value) > len(_ARTIFACT_KEYS):
        raise TestPassCircuitBindingError("verifier_artifacts has too many entries")
    artifacts: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if key not in _ARTIFACT_KEYS:
            raise TestPassCircuitBindingError(
                f"unsupported verifier artifact key: {key!r}"
            )
        path = str(raw_value)
        if not path or "\x00" in path or len(path) > 4_096:
            raise TestPassCircuitBindingError(
                f"verifier artifact {key!r} must be a bounded path"
            )
        artifacts[key] = path
    return MappingProxyType(dict(sorted(artifacts.items())))


@dataclass(frozen=True, slots=True, init=False)
class TestPassCircuitBinding:
    """Exact local trust and public-input binding for one test-pass proof.

    ``statement`` is the authoritative verifier reconstruction.  The remaining
    pins default to its fields but may be supplied explicitly; any discrepancy
    is rejected at construction time.  Replay snapshots are immutable inputs,
    so verification never mutates a cache or replay database.
    """

    __test__ = False

    statement: TestPassStatementV1
    backend_id: str
    proof_system_id: str
    circuit_cid: str
    verifying_key_cid: str
    statement_cid: str
    issuer_id: str
    policy_cid: str
    epoch: str
    verifier_artifacts: Mapping[str, str]
    replayed_certificate_ids: frozenset[str]
    replayed_proof_digests: frozenset[str]
    replayed_tokens: frozenset[str]
    max_proof_bytes: int

    def __init__(
        self,
        statement: TestPassStatementV1 | Mapping[str, Any] | None = None,
        *,
        public_inputs: Mapping[str, Any] | None = None,
        expected_public_inputs: Mapping[str, Any] | None = None,
        backend_id: str,
        proof_system_id: str | None = None,
        circuit_cid: str | None = None,
        verifying_key_cid: str | None = None,
        statement_cid: str | None = None,
        issuer_id: str | None = None,
        policy_cid: str | None = None,
        epoch: str | None = None,
        verifier_artifacts: Mapping[str, Any] | None = None,
        replayed_certificate_ids: Iterable[str] = (),
        replayed_proof_digests: Iterable[str] = (),
        replayed_tokens: Iterable[str] = (),
        max_proof_bytes: int = DEFAULT_MAX_TEST_PASS_PROOF_BYTES,
    ) -> None:
        supplied_inputs = expected_public_inputs or public_inputs
        if statement is None:
            if supplied_inputs is None:
                raise TestPassCircuitBindingError(
                    "statement or expected_public_inputs is required"
                )
            statement_obj = TestPassStatementV1.from_dict(supplied_inputs)
        elif isinstance(statement, TestPassStatementV1):
            statement_obj = statement
        elif isinstance(statement, Mapping):
            statement_obj = TestPassStatementV1.from_dict(statement)
        else:
            raise TestPassCircuitBindingError(
                "statement must be TestPassStatementV1 or a mapping"
            )
        statement_obj.requires_admitted_pass()

        if supplied_inputs is not None:
            supplied_statement = TestPassStatementV1.from_dict(supplied_inputs)
            if supplied_statement.to_public_inputs() != statement_obj.to_public_inputs():
                raise TestPassCircuitBindingError(
                    "expected_public_inputs does not match statement"
                )

        normalized_backend = normalize_backend_id(backend_id)
        normalized_system = normalize_proof_system_id(
            proof_system_id or _PROOF_SYSTEM_DEFAULTS.get(normalized_backend, "")
        )
        if not normalized_system:
            raise TestPassCircuitBindingError("proof_system_id is required")

        pi = statement_obj.public_inputs
        pins = {
            "circuit_cid": (circuit_cid, pi.circuit_cid),
            "verifying_key_cid": (verifying_key_cid, pi.verifying_key_cid),
            "statement_cid": (statement_cid, pi.statement_cid),
            "issuer_id": (issuer_id, pi.issuer_id),
            "policy_cid": (policy_cid, pi.policy_cid),
            "epoch": (epoch, pi.epoch),
        }
        normalized_pins: dict[str, str] = {}
        for name, (provided, expected) in pins.items():
            candidate = expected if provided is None else _bounded_text(provided, name)
            if candidate != expected:
                raise TestPassCircuitBindingError(
                    f"{name} does not match the reconstructed statement"
                )
            normalized_pins[name] = candidate

        if (
            isinstance(max_proof_bytes, bool)
            or not isinstance(max_proof_bytes, int)
            or max_proof_bytes <= 0
            or max_proof_bytes > 64 * 1024 * 1024
        ):
            raise TestPassCircuitBindingError(
                "max_proof_bytes must be an integer in 1..67108864"
            )

        object.__setattr__(self, "statement", statement_obj)
        object.__setattr__(self, "backend_id", normalized_backend)
        object.__setattr__(self, "proof_system_id", normalized_system)
        for name, value in normalized_pins.items():
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "verifier_artifacts", _artifact_mapping(verifier_artifacts)
        )
        object.__setattr__(
            self,
            "replayed_certificate_ids",
            _string_set(replayed_certificate_ids, "replayed_certificate_ids"),
        )
        object.__setattr__(
            self,
            "replayed_proof_digests",
            _string_set(replayed_proof_digests, "replayed_proof_digests"),
        )
        object.__setattr__(
            self, "replayed_tokens", _string_set(replayed_tokens, "replayed_tokens")
        )
        object.__setattr__(self, "max_proof_bytes", max_proof_bytes)

    @property
    def interface(self) -> str:
        return TEST_PASS_CIRCUIT_BINDING_INTERFACE

    @property
    def expected_public_inputs(self) -> dict[str, Any]:
        """Fresh canonical public inputs reconstructed by the verifier."""

        return self.statement.to_public_inputs()

    @property
    def receipt_cid(self) -> str:
        return self.statement.public_inputs.receipt_cid

    @property
    def execution_key_cid(self) -> str:
        return self.statement.public_inputs.execution_key_cid

    def replay_token(self) -> str:
        """Stable context token used by an external replay snapshot."""

        raw = (
            f"{self.receipt_cid}\0{self.execution_key_cid}\0"
            f"{self.policy_cid}\0{self.issuer_id}\0{self.epoch}"
        ).encode()
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def prepare_proof_for_backend(self, proof: ZKPProof) -> ZKPProof:
        """Return a proof using only verifier-pinned backend artifact metadata."""

        metadata = dict(proof.metadata)
        metadata["backend"] = self.backend_id
        metadata["proof_system"] = self.proof_system_id
        if self.backend_id == "provekit":
            # Never allow a certificate to select local paths.  The existing
            # ProveKit adapter accepts this key, so replace it wholesale.
            metadata["provekit_artifacts"] = dict(self.verifier_artifacts)
            for key in _ARTIFACT_KEYS:
                metadata.pop(key, None)
        return ZKPProof(
            proof_data=bytes(proof.proof_data),
            public_inputs=dict(proof.public_inputs),
            metadata=metadata,
            timestamp=proof.timestamp,
            size_bytes=proof.size_bytes,
        )

    def artifact_problem(self, proof_data: bytes) -> tuple[str, str] | None:
        """Validate pinned local artifacts without modifying them.

        Returns ``(kind, detail)`` with an unavailable or artifact-specific
        mismatch kind.  Only explicitly pinned artifacts are read.
        """

        artifacts = self.verifier_artifacts
        if self.backend_id != "provekit":
            return None

        key_value = artifacts.get("verifier_key_path") or artifacts.get("pkv_path")
        proof_value = artifacts.get("proof_path") or artifacts.get(
            "proof_output_path"
        )
        if not key_value or not proof_value:
            return (
                "unavailable",
                "pinned ProveKit verifier-key and proof paths are required",
            )

        key_path = Path(key_value)
        proof_path = Path(proof_value)
        if not key_path.is_file() or not proof_path.is_file():
            return ("unavailable", "a pinned ProveKit verifier artifact is missing")

        try:
            key_bytes = key_path.read_bytes()
            pinned_proof = proof_path.read_bytes()
        except OSError:
            return ("unavailable", "a pinned ProveKit verifier artifact is unreadable")

        if self.verifying_key_cid.startswith("sha256:"):
            actual = "sha256:" + hashlib.sha256(key_bytes).hexdigest()
            if actual != self.verifying_key_cid:
                return (
                    "verifying_key_mismatch",
                    "pinned verifying-key bytes do not match their ID",
                )
        if pinned_proof != proof_data:
            return (
                "proof_artifact_mismatch",
                "pinned proof artifact does not match certificate bytes",
            )
        return None


def backend_looks_available(backend: Any, binding: TestPassCircuitBinding) -> bool:
    """Perform a bounded, non-mutating readiness check for a backend instance."""

    explicit = getattr(backend, "available", None)
    if isinstance(explicit, bool):
        return explicit

    module = type(backend).__module__
    class_name = type(backend).__name__
    is_repository_backend = module.startswith(
        "ipfs_datasets_py.logic.zkp.backends."
    ) and class_name in {"Groth16Backend", "ProveKitBackend"}

    # Test/dedicated adapters may expose an availability probe.  Repository
    # backends use the narrower checks below to avoid broad health operations.
    probe = getattr(backend, "is_available", None)
    if callable(probe) and not is_repository_backend:
        try:
            return bool(probe())
        except Exception:
            return False

    if is_repository_backend and binding.backend_id == "groth16":
        enabled = getattr(backend, "_enabled", None)
        try:
            if not bool(callable(enabled) and enabled()):
                return False
            ffi_factory = getattr(backend, "_ffi", None)
            if not callable(ffi_factory):
                return False
            binary_path = getattr(ffi_factory(), "binary_path", None)
            return bool(binary_path and Path(binary_path).is_file())
        except Exception:
            return False

    if is_repository_backend and binding.backend_id == "provekit":
        binary_available = getattr(backend, "binary_available", None)
        try:
            return bool(callable(binary_available) and binary_available())
        except Exception:
            return False

    # An explicitly injected protocol-compatible verifier is treated as
    # available unless it advertises otherwise.  This supports offline real
    # conformance fixtures without importing or discovering optional tooling.
    return callable(getattr(backend, "verify_proof", None))


__all__ = [
    "DEFAULT_MAX_TEST_PASS_PROOF_BYTES",
    "REAL_TEST_PASS_BACKENDS",
    "TEST_PASS_CIRCUIT_BINDING_INTERFACE",
    "TestPassCircuitBinding",
    "TestPassCircuitBindingError",
    "backend_looks_available",
    "normalize_backend_id",
    "normalize_proof_system_id",
]
