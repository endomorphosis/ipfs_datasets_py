"""ProofReceiptAttestation@1 — bind production ZKP attestations to trusted receipts.

This bridge normalizes Groth16 / ProveKit-style attestation and verification
over *already trusted* software-verification receipts.  It is deliberately
orthogonal to theorem-prover authority:

* a verified ZKP attests a receipt binding; it never becomes theorem proof;
* private witnesses never enter public artifacts, logs, or caches;
* simulated backends, circuit mismatches, stale keys, and revoked material
  fail closed for production gates;
* underlying semantic authority on the source receipt is preserved and never
  raised by attestation.

Conflict policy (LFV-G063): own this adapter; reuse existing ZKP backends and
supervisor policy shapes without changing circuit code or treating ZKP as a
theorem prover.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final, TypeVar

from ipfs_datasets_py.logic.backends.results import (
    AttestationResult,
    AuthoritySubstitutionError,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
    TypedBackendResult,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage

PROOF_RECEIPT_ATTESTATION_INTERFACE: Final = "ProofReceiptAttestation@1"
PROOF_RECEIPT_ATTESTATION_SCHEMA_VERSION: Final = "proof-receipt-attestation/v1"
TRUSTED_PROOF_RECEIPT_SCHEMA_VERSION: Final = "trusted-proof-receipt/v1"
ATTESTATION_BACKEND_POLICY_SCHEMA_VERSION: Final = "attestation-backend-policy/v1"
ATTESTATION_STATEMENT_SCHEMA_VERSION: Final = "proof-receipt-attestation-statement/v1"
ATTESTATION_ENVELOPE_SCHEMA_VERSION: Final = "proof-receipt-attestation-envelope/v1"
ATTESTATION_VERIFICATION_SCHEMA_VERSION: Final = (
    "proof-receipt-attestation-verification/v1"
)
ATTESTATION_RECORD_SCHEMA_VERSION: Final = "proof-receipt-attestation-record/v1"

# Normative public-input keys for production receipt attestation (LFV-G063).
REQUIRED_PUBLIC_INPUT_KEYS: Final = (
    "theorem_id",
    "property_id",
    "translation_receipt_id",
    "receipt_id",
    "tree_id",
    "policy_id",
    "circuit_id",
    "circuit_version",
    "ceremony_id",
    "crs_id",
    "proving_key_id",
    "verification_key_id",
    "backend_id",
    "backend_version",
    "backend_mode",
    "revocation_policy_id",
    "issued_at",
    "expires_at",
    "underlying_authority",
    "underlying_status",
    "source_result_digest",
)

_SIMULATED_BACKEND_MARKERS: Final = frozenset(
    {
        "sim",
        "simulated",
        "simulation",
        "mock",
        "fake",
        "demo",
        "test-sim",
    }
)

_PROOF_ELIGIBLE_STATUSES: Final = frozenset(
    {
        ResultStatus.PROVED,
        ResultStatus.UNSATISFIABLE,
        ResultStatus.SATISFIED,
        ResultStatus.AUTHORIZED,
        ResultStatus.SECURE,
        ResultStatus.RECONSTRUCTED,
    }
)

_PROOF_ELIGIBLE_AUTHORITIES: Final = frozenset(
    {
        ResultAuthority.THEOREM,
        ResultAuthority.SATISFIABILITY,
        ResultAuthority.MODEL_CHECK,
        ResultAuthority.AUTHORIZATION,
        ResultAuthority.PROTOCOL,
        ResultAuthority.RECONSTRUCTION,
    }
)

T = TypeVar("T")


class ProofReceiptAttestationError(ValueError):
    """Raised when receipt-attestation data violates the trust contract."""


class WitnessDisclosureError(ProofReceiptAttestationError):
    """Raised when private witness material reaches a serialization boundary."""


class CryptographicBackendFailure(ProofReceiptAttestationError):
    """Raised when a production cryptographic backend is ineligible or fails."""


class StaleAttestationError(ProofReceiptAttestationError):
    """Raised when keys, windows, or receipts are outside the freshness window."""


class RevokedAttestationError(ProofReceiptAttestationError):
    """Raised when circuit or key material is revoked."""


class CircuitMismatchError(ProofReceiptAttestationError):
    """Raised when statement circuit bindings do not match the backend policy."""


class AttestationBackendMode(StrEnum):
    """Trust class of the proof backend, independent of product name."""

    CRYPTOGRAPHIC = "cryptographic"
    SIMULATED = "simulated"


class AttestationVerificationVerdict(StrEnum):
    """Independent verifier outcome."""

    VERIFIED = "verified"
    REJECTED = "rejected"
    ERROR = "error"


class AttestationGate(StrEnum):
    """Consumption gates.  Production and completion reject simulated proofs."""

    SERIALIZATION = "serialization"
    TEST = "test"
    PRODUCTION = "production"
    COMPLETION = "completion"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value in (None, ""):
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise ProofReceiptAttestationError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL"
        )
    return value


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ProofReceiptAttestationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProofReceiptAttestationError(f"{field_name} must be a bool")
    return value


def _timestamp(value: object, field_name: str, *, optional: bool = False) -> str:
    text = _text(value, field_name, optional=optional)
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ProofReceiptAttestationError(
            f"{field_name} must be an RFC3339 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise ProofReceiptAttestationError(
            f"{field_name} must include a timezone"
        )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(
        value[:-1] + "+00:00" if value.endswith("Z") else value
    )


def _backend_id_is_simulated(backend_id: str) -> bool:
    lowered = backend_id.lower()
    tokens = {
        part
        for part in lowered.replace("/", ":").replace("_", "-").split(":")
        if part
    }
    if tokens & _SIMULATED_BACKEND_MARKERS:
        return True
    return any(marker in lowered for marker in ("simulated", "simulation", "/sim"))


def _identity_digest(value: str) -> str:
    return stable_digest({"identity": value})


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofReceiptAttestationError(f"{field_name} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _canonical_public(value: Any) -> Any:
    if isinstance(value, PrivateWitness):
        raise WitnessDisclosureError(
            "private witness cannot enter a public artifact"
        )
    if isinstance(value, AttestationRequest):
        return value.to_public_artifact()
    if hasattr(value, "to_public_artifact") and callable(value.to_public_artifact):
        return value.to_public_artifact()
    if isinstance(value, Mapping):
        return {str(key): _canonical_public(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_public(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def public_artifact_contains(artifact: Any, secret: str | bytes) -> bool:
    """Return True when a secret appears in a public serialization (test helper)."""

    needle = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if not needle:
        raise ProofReceiptAttestationError("secret probe must not be empty")
    encoded = json.dumps(
        _canonical_public(artifact),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return needle in encoded


# ---------------------------------------------------------------------------
# Trusted receipt surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrustedProofReceipt:
    """Immutable, content-addressed binding of a trusted backend receipt.

    The receipt is *trusted* only when it carries a conclusive semantic status
    under a non-attestation authority.  Attestation later binds this identity
    without changing ``underlying_authority`` or ``underlying_status``.
    """

    receipt_id: str
    theorem_id: str
    property_id: str
    translation_receipt_id: str
    tree_id: str
    policy_id: str
    underlying_authority: ResultAuthority
    underlying_status: ResultStatus
    source_result_digest: str
    backend_id: str
    backend_version: str
    assumptions: tuple[str, ...] = ()
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.NONE
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TRUSTED_PROOF_RECEIPT_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = PROOF_RECEIPT_ATTESTATION_INTERFACE

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "theorem_id",
            "property_id",
            "translation_receipt_id",
            "tree_id",
            "policy_id",
            "source_result_digest",
            "backend_id",
            "backend_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "underlying_authority",
            _enum(self.underlying_authority, ResultAuthority, "underlying_authority"),
        )
        object.__setattr__(
            self,
            "underlying_status",
            _enum(self.underlying_status, ResultStatus, "underlying_status"),
        )
        if self.underlying_authority is ResultAuthority.ATTESTATION:
            raise AuthoritySubstitutionError(
                "trusted proof receipts cannot use attestation as underlying authority"
            )
        if self.underlying_authority not in _PROOF_ELIGIBLE_AUTHORITIES:
            raise ProofReceiptAttestationError(
                f"underlying authority {self.underlying_authority.value} is not "
                "eligible for receipt attestation"
            )
        if self.underlying_status not in _PROOF_ELIGIBLE_STATUSES:
            raise ProofReceiptAttestationError(
                f"underlying status {self.underlying_status.value} is not conclusive"
            )
        object.__setattr__(
            self,
            "translation_ceiling",
            _enum(self.translation_ceiling, EvidenceAuthority, "translation_ceiling"),
        )
        if not isinstance(self.assumptions, Sequence) or isinstance(
            self.assumptions, (str, bytes, bytearray)
        ):
            raise ProofReceiptAttestationError("assumptions must be a sequence of strings")
        assumptions = tuple(_text(item, "assumptions item") for item in self.assumptions)
        if len(assumptions) != len(set(assumptions)):
            raise ProofReceiptAttestationError("assumptions must not contain duplicates")
        object.__setattr__(self, "assumptions", tuple(sorted(assumptions)))
        try:
            object.__setattr__(
                self,
                "metadata",
                self.metadata if isinstance(self.metadata, FrozenMap) else FrozenMap(self.metadata),
            )
        except (TypeError, ValueError) as error:
            raise ProofReceiptAttestationError(
                "metadata must be an immutable JSON mapping"
            ) from error
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TRUSTED_PROOF_RECEIPT_SCHEMA_VERSION:
            raise ProofReceiptAttestationError(
                f"unsupported trusted receipt schema: {self.schema_version}"
            )

    @property
    def content_id(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "metadata": self.metadata.to_dict(),
            "policy_id": self.policy_id,
            "property_id": self.property_id,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "source_result_digest": self.source_result_digest,
            "theorem_id": self.theorem_id,
            "translation_ceiling": self.translation_ceiling.value,
            "translation_receipt_id": self.translation_receipt_id,
            "tree_id": self.tree_id,
            "underlying_authority": self.underlying_authority.value,
            "underlying_status": self.underlying_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrustedProofReceipt:
        payload = _mapping(value, "trusted proof receipt")
        receipt = cls(
            receipt_id=payload.get("receipt_id", ""),
            theorem_id=payload.get("theorem_id", ""),
            property_id=payload.get("property_id", ""),
            translation_receipt_id=payload.get("translation_receipt_id", ""),
            tree_id=payload.get("tree_id", ""),
            policy_id=payload.get("policy_id", ""),
            underlying_authority=payload.get("underlying_authority", ""),
            underlying_status=payload.get("underlying_status", ""),
            source_result_digest=payload.get("source_result_digest", ""),
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            assumptions=tuple(payload.get("assumptions", ())),
            translation_ceiling=payload.get(
                "translation_ceiling", EvidenceAuthority.NONE.value
            ),
            metadata=FrozenMap(payload.get("metadata", {})),
            schema_version=payload.get(
                "schema_version", TRUSTED_PROOF_RECEIPT_SCHEMA_VERSION
            ),
        )
        claimed = payload.get("content_id")
        if claimed and claimed != receipt.content_id:
            raise ProofReceiptAttestationError(
                "trusted proof receipt identity does not match payload"
            )
        return receipt

    @classmethod
    def from_backend_result(
        cls,
        result: TypedBackendResult,
        *,
        theorem_id: str,
        property_id: str,
        translation_receipt_id: str,
        tree_id: str,
        policy_id: str,
        receipt_id: str = "",
    ) -> TrustedProofReceipt:
        """Build a trusted receipt from a conclusive typed backend result."""

        if not isinstance(result, TypedBackendResult):
            raise ProofReceiptAttestationError(
                "trusted receipt requires a TypedBackendResult"
            )
        if not result.is_conclusive:
            raise ProofReceiptAttestationError(
                "trusted receipt requires a conclusive backend result"
            )
        if result.authority is ResultAuthority.ATTESTATION:
            raise AuthoritySubstitutionError(
                "attestation results cannot seed a trusted proof receipt"
            )
        if result.authority not in _PROOF_ELIGIBLE_AUTHORITIES:
            raise ProofReceiptAttestationError(
                f"authority {result.authority.value} cannot seed a trusted receipt"
            )
        if result.status not in _PROOF_ELIGIBLE_STATUSES:
            raise ProofReceiptAttestationError(
                f"status {result.status.value} cannot seed a trusted receipt"
            )
        resolved_receipt_id = receipt_id or f"receipt:{result.digest}"
        return cls(
            receipt_id=resolved_receipt_id,
            theorem_id=theorem_id,
            property_id=property_id,
            translation_receipt_id=translation_receipt_id,
            tree_id=tree_id,
            policy_id=policy_id,
            underlying_authority=result.authority,
            underlying_status=result.status,
            source_result_digest=result.digest,
            backend_id=result.backend_id,
            backend_version=result.backend_version,
            assumptions=result.assumptions,
            translation_ceiling=result.translation_ceiling,
            metadata=result.metadata,
        )


# ---------------------------------------------------------------------------
# Backend policy, ceremony, keys, revocation, freshness
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttestationBackendPolicy:
    """Pinned production backend, circuit, CRS/ceremony, and key identities."""

    backend_id: str
    backend_version: str
    circuit_id: str
    circuit_version: str
    ceremony_id: str
    crs_id: str
    proving_key_id: str
    verification_key_id: str
    revocation_policy_id: str
    backend_mode: AttestationBackendMode = AttestationBackendMode.CRYPTOGRAPHIC
    verification_key_expires_at: str = ""
    schema_version: str = ATTESTATION_BACKEND_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "backend_id",
            "backend_version",
            "circuit_id",
            "circuit_version",
            "ceremony_id",
            "crs_id",
            "proving_key_id",
            "verification_key_id",
            "revocation_policy_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "backend_mode",
            _enum(self.backend_mode, AttestationBackendMode, "backend_mode"),
        )
        object.__setattr__(
            self,
            "verification_key_expires_at",
            _timestamp(
                self.verification_key_expires_at,
                "verification_key_expires_at",
                optional=True,
            ),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ATTESTATION_BACKEND_POLICY_SCHEMA_VERSION:
            raise ProofReceiptAttestationError(
                f"unsupported backend policy schema: {self.schema_version}"
            )
        if (
            self.backend_mode is AttestationBackendMode.CRYPTOGRAPHIC
            and _backend_id_is_simulated(self.backend_id)
        ):
            raise ProofReceiptAttestationError(
                "a simulated backend identity cannot be pinned as cryptographic"
            )

    @property
    def policy_id(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def simulated(self) -> bool:
        return self.backend_mode is AttestationBackendMode.SIMULATED

    def key_is_current_at(self, timestamp: str) -> bool:
        checked = _timestamp(timestamp, "timestamp")
        if not self.verification_key_expires_at:
            return True
        return _timestamp_value(checked) < _timestamp_value(
            self.verification_key_expires_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "backend_mode": self.backend_mode.value,
            "backend_version": self.backend_version,
            "ceremony_id": self.ceremony_id,
            "circuit_id": self.circuit_id,
            "circuit_version": self.circuit_version,
            "crs_id": self.crs_id,
            "proving_key_id": self.proving_key_id,
            "revocation_policy_id": self.revocation_policy_id,
            "schema_version": self.schema_version,
            "verification_key_expires_at": self.verification_key_expires_at,
            "verification_key_id": self.verification_key_id,
        }

    def to_public_artifact(self) -> dict[str, Any]:
        return {**self.to_dict(), "policy_id": self.policy_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AttestationBackendPolicy:
        payload = _mapping(value, "attestation backend policy")
        policy = cls(
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            circuit_id=payload.get("circuit_id", ""),
            circuit_version=payload.get("circuit_version", ""),
            ceremony_id=payload.get("ceremony_id", ""),
            crs_id=payload.get("crs_id", ""),
            proving_key_id=payload.get("proving_key_id", ""),
            verification_key_id=payload.get("verification_key_id", ""),
            revocation_policy_id=payload.get("revocation_policy_id", ""),
            backend_mode=payload.get(
                "backend_mode", AttestationBackendMode.CRYPTOGRAPHIC
            ),
            verification_key_expires_at=payload.get(
                "verification_key_expires_at", ""
            ),
            schema_version=payload.get(
                "schema_version", ATTESTATION_BACKEND_POLICY_SCHEMA_VERSION
            ),
        )
        claimed = payload.get("policy_id")
        if claimed and claimed != policy.policy_id:
            raise ProofReceiptAttestationError(
                "backend policy identity does not match payload"
            )
        return policy


@dataclass(frozen=True, slots=True)
class RevocationPolicy:
    """Explicit revocation set for circuits, CRS, and verification keys."""

    policy_id: str
    revoked_circuit_ids: tuple[str, ...] = ()
    revoked_crs_ids: tuple[str, ...] = ()
    revoked_proving_key_ids: tuple[str, ...] = ()
    revoked_verification_key_ids: tuple[str, ...] = ()
    as_of: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "as_of", _timestamp(self.as_of, "as_of", optional=True)
        )
        for name in (
            "revoked_circuit_ids",
            "revoked_crs_ids",
            "revoked_proving_key_ids",
            "revoked_verification_key_ids",
        ):
            raw = getattr(self, name)
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
                raise ProofReceiptAttestationError(f"{name} must be a sequence of strings")
            items = tuple(sorted({_text(item, f"{name} item") for item in raw}))
            object.__setattr__(self, name, items)

    def rejects(self, policy: AttestationBackendPolicy) -> str:
        """Return a rejection reason, or empty string when material is current."""

        if policy.revocation_policy_id != self.policy_id:
            return "revocation_policy_mismatch"
        if policy.circuit_id in self.revoked_circuit_ids:
            return "circuit_revoked"
        if policy.crs_id in self.revoked_crs_ids:
            return "crs_revoked"
        if policy.proving_key_id in self.revoked_proving_key_ids:
            return "proving_key_revoked"
        if policy.verification_key_id in self.revoked_verification_key_ids:
            return "verification_key_revoked"
        return ""

    def require_current(self, policy: AttestationBackendPolicy) -> None:
        reason = self.rejects(policy)
        if reason:
            raise RevokedAttestationError(
                f"attestation material is revoked: {reason}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "policy_id": self.policy_id,
            "revoked_circuit_ids": list(self.revoked_circuit_ids),
            "revoked_crs_ids": list(self.revoked_crs_ids),
            "revoked_proving_key_ids": list(self.revoked_proving_key_ids),
            "revoked_verification_key_ids": list(self.revoked_verification_key_ids),
        }

    def to_public_artifact(self) -> dict[str, Any]:
        return self.to_dict()


# ---------------------------------------------------------------------------
# Public statement, private witness, request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttestationStatement:
    """Canonical public inputs for one receipt-bound ZKP attestation."""

    receipt: TrustedProofReceipt
    backend_policy: AttestationBackendPolicy
    issued_at: str
    expires_at: str
    schema_version: str = ATTESTATION_STATEMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, TrustedProofReceipt):
            raise ProofReceiptAttestationError(
                "statement requires a TrustedProofReceipt"
            )
        if not isinstance(self.backend_policy, AttestationBackendPolicy):
            raise ProofReceiptAttestationError(
                "statement requires an AttestationBackendPolicy"
            )
        object.__setattr__(self, "issued_at", _timestamp(self.issued_at, "issued_at"))
        object.__setattr__(
            self, "expires_at", _timestamp(self.expires_at, "expires_at")
        )
        if _timestamp_value(self.expires_at) <= _timestamp_value(self.issued_at):
            raise ProofReceiptAttestationError(
                "expires_at must be strictly after issued_at"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ATTESTATION_STATEMENT_SCHEMA_VERSION:
            raise ProofReceiptAttestationError(
                f"unsupported statement schema: {self.schema_version}"
            )
        if self.backend_policy.simulated:
            # Statements may still be built for fencing tests, but they are
            # never production-eligible (enforced at envelope/verification).
            pass
        if (
            self.backend_policy.backend_mode is AttestationBackendMode.CRYPTOGRAPHIC
            and _backend_id_is_simulated(self.backend_policy.backend_id)
        ):
            raise ProofReceiptAttestationError(
                "cryptographic statement cannot use a simulated backend identity"
            )

    @property
    def statement_id(self) -> str:
        return stable_digest(self.public_inputs)

    @property
    def public_input_digest(self) -> str:
        return self.statement_id

    @property
    def public_inputs(self) -> dict[str, str]:
        """Exactly the public identities supplied to the circuit."""

        policy = self.backend_policy
        receipt = self.receipt
        return {
            "backend_id": policy.backend_id,
            "backend_mode": policy.backend_mode.value,
            "backend_version": policy.backend_version,
            "ceremony_id": policy.ceremony_id,
            "circuit_id": policy.circuit_id,
            "circuit_version": policy.circuit_version,
            "crs_id": policy.crs_id,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "policy_id": receipt.policy_id,
            "property_id": receipt.property_id,
            "proving_key_id": policy.proving_key_id,
            "receipt_id": receipt.receipt_id,
            "revocation_policy_id": policy.revocation_policy_id,
            "source_result_digest": receipt.source_result_digest,
            "theorem_id": receipt.theorem_id,
            "translation_receipt_id": receipt.translation_receipt_id,
            "tree_id": receipt.tree_id,
            "underlying_authority": receipt.underlying_authority.value,
            "underlying_status": receipt.underlying_status.value,
            "verification_key_id": policy.verification_key_id,
        }

    def require_complete_public_inputs(self) -> dict[str, str]:
        inputs = self.public_inputs
        missing = [key for key in REQUIRED_PUBLIC_INPUT_KEYS if not inputs.get(key)]
        if missing:
            raise ProofReceiptAttestationError(
                "public inputs missing required bindings: " + ", ".join(missing)
            )
        return dict(inputs)

    def is_fresh_at(self, timestamp: str) -> bool:
        now = _timestamp(timestamp, "timestamp")
        now_dt = _timestamp_value(now)
        return (
            _timestamp_value(self.issued_at) <= now_dt < _timestamp_value(self.expires_at)
            and self.backend_policy.key_is_current_at(now)
        )

    def require_fresh_at(self, timestamp: str) -> None:
        if not self.is_fresh_at(timestamp):
            raise StaleAttestationError(
                "attestation is stale or outside its freshness window"
            )

    def matches_backend_policy(self, policy: AttestationBackendPolicy) -> bool:
        return (
            self.backend_policy.policy_id == policy.policy_id
            and self.backend_policy.circuit_id == policy.circuit_id
            and self.backend_policy.circuit_version == policy.circuit_version
            and self.backend_policy.ceremony_id == policy.ceremony_id
            and self.backend_policy.crs_id == policy.crs_id
            and self.backend_policy.proving_key_id == policy.proving_key_id
            and self.backend_policy.verification_key_id == policy.verification_key_id
            and self.backend_policy.backend_id == policy.backend_id
            and self.backend_policy.backend_version == policy.backend_version
        )

    def require_matches_backend_policy(self, policy: AttestationBackendPolicy) -> None:
        if not self.matches_backend_policy(policy):
            raise CircuitMismatchError(
                "attestation statement circuit/key bindings do not match backend policy"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_policy": self.backend_policy.to_dict(),
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "public_inputs": self.public_inputs,
            "receipt": self.receipt.to_dict(),
            "schema_version": self.schema_version,
        }

    def to_public_artifact(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "backend_policy": self.backend_policy.to_public_artifact(),
            "public_input_digest": self.public_input_digest,
            "statement_id": self.statement_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AttestationStatement:
        payload = _mapping(value, "attestation statement")
        statement = cls(
            receipt=TrustedProofReceipt.from_dict(payload.get("receipt", {})),
            backend_policy=AttestationBackendPolicy.from_dict(
                payload.get("backend_policy", {})
            ),
            issued_at=payload.get("issued_at", ""),
            expires_at=payload.get("expires_at", ""),
            schema_version=payload.get(
                "schema_version", ATTESTATION_STATEMENT_SCHEMA_VERSION
            ),
        )
        claimed = payload.get("statement_id")
        if claimed and claimed != statement.statement_id:
            raise ProofReceiptAttestationError(
                "attestation statement identity does not match payload"
            )
        claimed_digest = payload.get("public_input_digest")
        if claimed_digest and claimed_digest != statement.public_input_digest:
            raise ProofReceiptAttestationError(
                "attestation public-input digest does not match payload"
            )
        return statement


class PrivateWitness:
    """Opaque, redacted, non-serializable private proving inputs.

    Backends receive values only inside :meth:`use`.  The wrapper has no
    mapping protocol, iterator, public value property, JSON method, or pickle
    representation so generic serializers cannot leak secrets.
    """

    __slots__ = ("__values",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        if not isinstance(values, Mapping):
            raise ProofReceiptAttestationError("witness values must be a mapping")
        normalized: dict[str, Any] = {}
        for raw_name, value in values.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise ProofReceiptAttestationError(
                    "witness field names must be non-empty strings"
                )
            normalized[raw_name] = value
        if not normalized:
            raise ProofReceiptAttestationError("witness values must not be empty")
        self.__values = dict(normalized)

    def __repr__(self) -> str:
        return "<PrivateWitness redacted>"

    __str__ = __repr__

    def __copy__(self) -> PrivateWitness:
        raise WitnessDisclosureError("private witness cannot be copied")

    def __deepcopy__(self, memo: Any) -> PrivateWitness:
        del memo
        raise WitnessDisclosureError("private witness cannot be copied")

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise WitnessDisclosureError(
            "private witness cannot be serialized or cached"
        )

    def __getstate__(self) -> Any:
        raise WitnessDisclosureError(
            "private witness cannot be serialized or cached"
        )

    def to_dict(self) -> dict[str, Any]:
        raise WitnessDisclosureError(
            "private witness has no public dictionary representation"
        )

    def use(self, consumer: Callable[[Mapping[str, Any]], T]) -> T:
        if not callable(consumer):
            raise ProofReceiptAttestationError("witness consumer must be callable")
        return consumer(MappingProxyType(self.__values))

    def redacted(self) -> dict[str, bool]:
        return {"private_witness_redacted": True}


@dataclass(frozen=True, repr=False)
class AttestationRequest:
    """Ephemeral proving request; only the public statement is serializable."""

    statement: AttestationStatement
    _witness: PrivateWitness = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.statement, AttestationStatement):
            raise ProofReceiptAttestationError(
                "request requires an AttestationStatement"
            )
        if not isinstance(self._witness, PrivateWitness):
            raise ProofReceiptAttestationError(
                "_witness must be a PrivateWitness"
            )
        # Force complete public-input binding at prepare time.
        self.statement.require_complete_public_inputs()

    def __repr__(self) -> str:
        return (
            "AttestationRequest(statement_id=%r, witness=<redacted>)"
            % self.statement.statement_id
        )

    __str__ = __repr__

    def __reduce_ex__(self, protocol: int) -> Any:
        del protocol
        raise WitnessDisclosureError(
            "attestation proving requests cannot be serialized or cached"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "private_witness_redacted": True,
            "statement": self.statement.to_public_artifact(),
        }

    to_public_artifact = to_dict
    to_log_record = to_dict

    def to_cache_record(self) -> dict[str, Any]:
        raise WitnessDisclosureError(
            "attestation proving requests containing a witness cannot be cached"
        )

    def use_witness(self, consumer: Callable[[Mapping[str, Any]], T]) -> T:
        return self._witness.use(consumer)


# ---------------------------------------------------------------------------
# Envelope, verification, record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttestationEnvelope:
    """Public prover output for one immutable statement (not yet verification)."""

    statement: AttestationStatement
    backend_mode: AttestationBackendMode
    proof_artifact_id: str
    proof_digest: str
    prover_id: str = ""
    schema_version: str = ATTESTATION_ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.statement, AttestationStatement):
            raise ProofReceiptAttestationError(
                "envelope requires an AttestationStatement"
            )
        object.__setattr__(
            self,
            "backend_mode",
            _enum(self.backend_mode, AttestationBackendMode, "backend_mode"),
        )
        for name in ("proof_artifact_id", "proof_digest"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "prover_id", _text(self.prover_id, "prover_id", optional=True)
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ATTESTATION_ENVELOPE_SCHEMA_VERSION:
            raise ProofReceiptAttestationError(
                f"unsupported envelope schema: {self.schema_version}"
            )
        if (
            self.backend_mode is AttestationBackendMode.CRYPTOGRAPHIC
            and (
                self.statement.backend_policy.simulated
                or _backend_id_is_simulated(self.statement.backend_policy.backend_id)
            )
        ):
            raise ProofReceiptAttestationError(
                "a simulated backend cannot emit a cryptographic envelope"
            )
        if self.backend_mode is not self.statement.backend_policy.backend_mode:
            raise ProofReceiptAttestationError(
                "envelope mode does not match backend policy mode"
            )

    @property
    def envelope_id(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def simulated(self) -> bool:
        return self.backend_mode is AttestationBackendMode.SIMULATED

    @property
    def authoritative(self) -> bool:
        # Generation never crosses the independent-verifier boundary.
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_mode": self.backend_mode.value,
            "proof_artifact_id": self.proof_artifact_id,
            "proof_digest": self.proof_digest,
            "prover_id": self.prover_id,
            "public_input_digest": self.statement.public_input_digest,
            "schema_version": self.schema_version,
            "statement": self.statement.to_dict(),
            "statement_id": self.statement.statement_id,
        }

    def to_public_artifact(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "envelope_id": self.envelope_id,
            "statement": self.statement.to_public_artifact(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AttestationEnvelope:
        payload = _mapping(value, "attestation envelope")
        envelope = cls(
            statement=AttestationStatement.from_dict(payload.get("statement", {})),
            backend_mode=payload.get("backend_mode", ""),
            proof_artifact_id=payload.get("proof_artifact_id", ""),
            proof_digest=payload.get("proof_digest", ""),
            prover_id=payload.get("prover_id", ""),
            schema_version=payload.get(
                "schema_version", ATTESTATION_ENVELOPE_SCHEMA_VERSION
            ),
        )
        claimed = payload.get("envelope_id")
        if claimed and claimed != envelope.envelope_id:
            raise ProofReceiptAttestationError(
                "attestation envelope identity does not match payload"
            )
        return envelope


@dataclass(frozen=True, slots=True)
class AttestationVerification:
    """Independent verification result over a public envelope."""

    envelope: AttestationEnvelope
    verdict: AttestationVerificationVerdict
    verifier_id: str
    independent: bool = True
    diagnostic_code: str = ""
    verified_at: str = ""
    schema_version: str = ATTESTATION_VERIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, AttestationEnvelope):
            raise ProofReceiptAttestationError(
                "verification requires an AttestationEnvelope"
            )
        object.__setattr__(
            self,
            "verdict",
            _enum(self.verdict, AttestationVerificationVerdict, "verdict"),
        )
        object.__setattr__(self, "verifier_id", _text(self.verifier_id, "verifier_id"))
        object.__setattr__(
            self, "independent", _bool(self.independent, "independent")
        )
        object.__setattr__(
            self,
            "diagnostic_code",
            _text(self.diagnostic_code, "diagnostic_code", optional=True),
        )
        object.__setattr__(
            self,
            "verified_at",
            _timestamp(self.verified_at, "verified_at", optional=True),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ATTESTATION_VERIFICATION_SCHEMA_VERSION:
            raise ProofReceiptAttestationError(
                f"unsupported verification schema: {self.schema_version}"
            )
        if self.verdict is AttestationVerificationVerdict.VERIFIED:
            if not self.independent:
                raise ProofReceiptAttestationError(
                    "verified attestations must be independent"
                )
            if self.envelope.simulated:
                raise ProofReceiptAttestationError(
                    "simulated envelopes cannot receive a verified verdict"
                )

    @property
    def verification_id(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def verified(self) -> bool:
        return self.verdict is AttestationVerificationVerdict.VERIFIED

    @property
    def authoritative_for_attestation(self) -> bool:
        """Whether this verification may authorize *attestation* authority only."""

        return (
            self.verified
            and self.independent
            and not self.envelope.simulated
            and self.envelope.backend_mode is AttestationBackendMode.CRYPTOGRAPHIC
        )

    def satisfies_gate(self, gate: AttestationGate | str) -> bool:
        checked = _enum(gate, AttestationGate, "gate")
        if checked is AttestationGate.SERIALIZATION:
            return True
        if checked is AttestationGate.TEST:
            return self.verified or self.envelope.simulated
        if checked in (AttestationGate.PRODUCTION, AttestationGate.COMPLETION):
            return self.authoritative_for_attestation
        return False

    def require_gate(self, gate: AttestationGate | str) -> None:
        if not self.satisfies_gate(gate):
            raise CryptographicBackendFailure(
                f"attestation does not satisfy gate {gate!s}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic_code": self.diagnostic_code,
            "envelope": self.envelope.to_dict(),
            "envelope_id": self.envelope.envelope_id,
            "independent": self.independent,
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
            "verified_at": self.verified_at,
            "verifier_id": self.verifier_id,
        }

    def to_public_artifact(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "envelope": self.envelope.to_public_artifact(),
            "verification_id": self.verification_id,
        }


@dataclass(frozen=True, slots=True)
class AttestationRecord:
    """Persisted public attestation bound to a trusted receipt."""

    verification: AttestationVerification
    created_at: str
    expires_at: str
    schema_version: str = ATTESTATION_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.verification, AttestationVerification):
            raise ProofReceiptAttestationError(
                "record requires an AttestationVerification"
            )
        object.__setattr__(
            self, "created_at", _timestamp(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "expires_at", _timestamp(self.expires_at, "expires_at")
        )
        if _timestamp_value(self.expires_at) <= _timestamp_value(self.created_at):
            raise ProofReceiptAttestationError(
                "record expires_at must be strictly after created_at"
            )
        statement = self.verification.envelope.statement
        if self.expires_at != statement.expires_at:
            raise ProofReceiptAttestationError(
                "record expiry must match statement freshness window"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != ATTESTATION_RECORD_SCHEMA_VERSION:
            raise ProofReceiptAttestationError(
                f"unsupported record schema: {self.schema_version}"
            )

    @property
    def record_id(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def receipt_id(self) -> str:
        return self.verification.envelope.statement.receipt.receipt_id

    @property
    def underlying_authority(self) -> ResultAuthority:
        return self.verification.envelope.statement.receipt.underlying_authority

    def is_current_at(self, timestamp: str) -> bool:
        now = _timestamp(timestamp, "timestamp")
        now_dt = _timestamp_value(now)
        return (
            _timestamp_value(self.created_at)
            <= now_dt
            < _timestamp_value(self.expires_at)
            and self.verification.envelope.statement.is_fresh_at(now)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "underlying_authority": self.underlying_authority.value,
            "verification": self.verification.to_dict(),
            "verification_id": self.verification.verification_id,
        }

    def to_public_artifact(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "record_id": self.record_id,
            "verification": self.verification.to_public_artifact(),
        }

    def to_attestation_result(
        self,
        *,
        result_id: str = "",
        bounds: ExecutionBounds | None = None,
        usage: ResourceUsage | None = None,
    ) -> AttestationResult:
        """Project to typed ``ResultAuthority.ATTESTATION`` without raising authority.

        The returned result always uses attestation authority.  Underlying
        theorem (or other) authority remains on the source receipt and is never
        substituted into this projection.
        """

        verified = self.verification.authoritative_for_attestation and self.is_current_at(
            self.created_at
        )
        status = (
            ResultStatus.ATTESTED if verified else ResultStatus.ATTESTATION_INVALID
        )
        statement = self.verification.envelope.statement
        metadata = {
            "attestation_record_id": self.record_id,
            "public_input_digest": statement.public_input_digest,
            "receipt_id": statement.receipt.receipt_id,
            "statement_id": statement.statement_id,
            "underlying_authority": statement.receipt.underlying_authority.value,
            "underlying_status": statement.receipt.underlying_status.value,
            "verification_id": self.verification.verification_id,
        }
        return AttestationResult(
            result_id=result_id or f"attestation:{self.record_id}",
            backend_id=statement.backend_policy.backend_id,
            backend_version=statement.backend_policy.backend_version,
            authority=ResultAuthority.ATTESTATION,
            status=status,
            assumptions=statement.receipt.assumptions,
            bounds=bounds if bounds is not None else ExecutionBounds(),
            translation_ceiling=statement.receipt.translation_ceiling,
            usage=usage if usage is not None else ResourceUsage(),
            witness=FrozenMap({}),
            diagnostics=(),
            reason="" if verified else (self.verification.diagnostic_code or "invalid"),
            metadata=FrozenMap(metadata),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_trusted_receipt_from_backend_result(
    result: TypedBackendResult,
    *,
    theorem_id: str,
    property_id: str,
    translation_receipt_id: str,
    tree_id: str,
    policy_id: str,
    receipt_id: str = "",
) -> TrustedProofReceipt:
    """Normalize a conclusive backend result into a trusted receipt binding."""

    return TrustedProofReceipt.from_backend_result(
        result,
        theorem_id=theorem_id,
        property_id=property_id,
        translation_receipt_id=translation_receipt_id,
        tree_id=tree_id,
        policy_id=policy_id,
        receipt_id=receipt_id,
    )


def build_attestation_statement(
    receipt: TrustedProofReceipt,
    *,
    backend_policy: AttestationBackendPolicy,
    issued_at: str,
    expires_at: str,
    revocation_policy: RevocationPolicy | None = None,
) -> AttestationStatement:
    """Build a public statement after fencing revoked material."""

    if not isinstance(receipt, TrustedProofReceipt):
        raise ProofReceiptAttestationError(
            "attestation requires a TrustedProofReceipt"
        )
    if not isinstance(backend_policy, AttestationBackendPolicy):
        raise ProofReceiptAttestationError(
            "attestation requires an AttestationBackendPolicy"
        )
    if revocation_policy is not None:
        if not isinstance(revocation_policy, RevocationPolicy):
            raise ProofReceiptAttestationError(
                "revocation_policy must be a RevocationPolicy"
            )
        revocation_policy.require_current(backend_policy)
    statement = AttestationStatement(
        receipt=receipt,
        backend_policy=backend_policy,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    statement.require_complete_public_inputs()
    statement.require_fresh_at(issued_at)
    return statement


def prepare_receipt_attestation(
    receipt: TrustedProofReceipt,
    *,
    backend_policy: AttestationBackendPolicy,
    witness: PrivateWitness,
    issued_at: str,
    expires_at: str,
    revocation_policy: RevocationPolicy | None = None,
) -> AttestationRequest:
    """Create an ephemeral proving request after receipt and revocation gates."""

    if not isinstance(witness, PrivateWitness):
        raise ProofReceiptAttestationError("witness must be a PrivateWitness")
    statement = build_attestation_statement(
        receipt,
        backend_policy=backend_policy,
        issued_at=issued_at,
        expires_at=expires_at,
        revocation_policy=revocation_policy,
    )
    return AttestationRequest(statement=statement, _witness=witness)


def create_attestation_envelope(
    request: AttestationRequest,
    *,
    backend_mode: AttestationBackendMode | str,
    proof_artifact_id: str,
    proof_digest: str,
    prover_id: str = "",
) -> AttestationEnvelope:
    """Record public prover output for an already-authorized request."""

    if not isinstance(request, AttestationRequest):
        raise ProofReceiptAttestationError(
            "envelope generation requires a prepared AttestationRequest"
        )
    return AttestationEnvelope(
        statement=request.statement,
        backend_mode=backend_mode,
        proof_artifact_id=proof_artifact_id,
        proof_digest=proof_digest,
        prover_id=prover_id,
    )


def record_attestation_verification(
    envelope: AttestationEnvelope,
    *,
    verified: bool,
    verifier_id: str,
    independent: bool = True,
    diagnostic_code: str = "",
    verified_at: str = "",
    revocation_policy: RevocationPolicy | None = None,
    now: str = "",
) -> AttestationVerification:
    """Create a fail-closed independent verification result."""

    if not isinstance(envelope, AttestationEnvelope):
        raise ProofReceiptAttestationError(
            "verification requires an AttestationEnvelope"
        )
    checked = _bool(verified, "verified")
    evaluated_at = _timestamp(
        verified_at or now or envelope.statement.issued_at,
        "verified_at",
    )
    if revocation_policy is not None:
        revocation_policy.require_current(envelope.statement.backend_policy)
    if checked:
        if envelope.simulated:
            raise ProofReceiptAttestationError(
                "simulated envelopes cannot be marked verified"
            )
        envelope.statement.require_fresh_at(evaluated_at)
        envelope.statement.require_matches_backend_policy(
            envelope.statement.backend_policy
        )
    return AttestationVerification(
        envelope=envelope,
        verdict=(
            AttestationVerificationVerdict.VERIFIED
            if checked
            else AttestationVerificationVerdict.REJECTED
        ),
        verifier_id=verifier_id,
        independent=independent,
        diagnostic_code=diagnostic_code,
        verified_at=evaluated_at,
    )


def execute_cryptographic_attestation(
    request: AttestationRequest,
    *,
    prover: Callable[[AttestationRequest], Mapping[str, Any]],
    verifier: Callable[[AttestationEnvelope], bool],
    prover_id: str,
    verifier_id: str,
    revocation_policy: RevocationPolicy | None = None,
    now: str = "",
) -> AttestationVerification:
    """Execute one managed cryptographic attempt with no simulated fallback.

    ``prover`` returns only ``proof_artifact_id`` and ``proof_digest``.  Private
    witnesses are accessible only through ``request.use_witness``.  Simulation
    is never invoked after failure.
    """

    if not isinstance(request, AttestationRequest):
        raise ProofReceiptAttestationError(
            "cryptographic execution requires a prepared AttestationRequest"
        )
    policy = request.statement.backend_policy
    if policy.backend_mode is not AttestationBackendMode.CRYPTOGRAPHIC:
        raise CryptographicBackendFailure(
            "managed cryptographic execution cannot use a simulated policy"
        )
    if _backend_id_is_simulated(policy.backend_id):
        raise CryptographicBackendFailure(
            "managed cryptographic execution rejects simulated backend identities"
        )
    if revocation_policy is not None:
        revocation_policy.require_current(policy)
    evaluated_at = _timestamp(now or request.statement.issued_at, "now")
    request.statement.require_fresh_at(evaluated_at)
    if not callable(prover) or not callable(verifier):
        raise ProofReceiptAttestationError("prover and verifier must be callable")

    try:
        output = prover(request)
    except Exception as exc:
        raise CryptographicBackendFailure(
            "cryptographic proof generation failed"
        ) from exc
    if not isinstance(output, Mapping):
        raise CryptographicBackendFailure(
            "cryptographic prover returned a malformed result"
        )
    try:
        envelope = create_attestation_envelope(
            request,
            backend_mode=AttestationBackendMode.CRYPTOGRAPHIC,
            proof_artifact_id=str(output.get("proof_artifact_id", "")),
            proof_digest=str(output.get("proof_digest", "")),
            prover_id=prover_id,
        )
    except ProofReceiptAttestationError as exc:
        raise CryptographicBackendFailure(
            "cryptographic prover returned malformed proof metadata"
        ) from exc

    try:
        verified = verifier(envelope)
    except Exception:
        return AttestationVerification(
            envelope=envelope,
            verdict=AttestationVerificationVerdict.ERROR,
            verifier_id=verifier_id,
            independent=True,
            diagnostic_code="cryptographic_verifier_error",
            verified_at=evaluated_at,
        )
    if not isinstance(verified, bool):
        return AttestationVerification(
            envelope=envelope,
            verdict=AttestationVerificationVerdict.ERROR,
            verifier_id=verifier_id,
            independent=True,
            diagnostic_code="cryptographic_verifier_non_boolean",
            verified_at=evaluated_at,
        )
    return record_attestation_verification(
        envelope,
        verified=verified,
        verifier_id=verifier_id,
        independent=True,
        diagnostic_code="" if verified else "cryptographic_proof_rejected",
        verified_at=evaluated_at,
        revocation_policy=revocation_policy,
        now=evaluated_at,
    )


def build_attestation_record(
    verification: AttestationVerification,
    *,
    created_at: str,
    expires_at: str | None = None,
) -> AttestationRecord:
    """Persist a public record from an independent verification result."""

    if not isinstance(verification, AttestationVerification):
        raise ProofReceiptAttestationError(
            "record requires an AttestationVerification"
        )
    return AttestationRecord(
        verification=verification,
        created_at=created_at,
        expires_at=expires_at or verification.envelope.statement.expires_at,
    )


def verify_statement_against_policy(
    statement: AttestationStatement,
    *,
    backend_policy: AttestationBackendPolicy,
    revocation_policy: RevocationPolicy,
    now: str,
) -> None:
    """Fail closed when circuit, revocation, or freshness checks fail."""

    if not isinstance(statement, AttestationStatement):
        raise ProofReceiptAttestationError("statement is required")
    statement.require_matches_backend_policy(backend_policy)
    if statement.backend_policy.simulated or backend_policy.simulated:
        raise CryptographicBackendFailure(
            "simulated backends fail production attestation verification"
        )
    revocation_policy.require_current(backend_policy)
    statement.require_fresh_at(now)


def preserve_underlying_authority(
    source: TrustedProofReceipt | TypedBackendResult,
    attestation: AttestationResult | AttestationRecord | AttestationVerification,
) -> ResultAuthority:
    """Return the source semantic authority; attestation never substitutes it."""

    if isinstance(source, TrustedProofReceipt):
        authority = source.underlying_authority
    elif isinstance(source, TypedBackendResult):
        authority = source.authority
    else:
        raise ProofReceiptAttestationError(
            "source must be a TrustedProofReceipt or TypedBackendResult"
        )
    if authority is ResultAuthority.ATTESTATION:
        raise AuthoritySubstitutionError(
            "source authority must remain non-attestation for preservation checks"
        )
    # Touch attestation only to prove it cannot override the return value.
    if isinstance(attestation, AttestationResult):
        if attestation.authority is not ResultAuthority.ATTESTATION:
            raise AuthoritySubstitutionError(
                "attestation projection must retain attestation authority"
            )
    elif isinstance(attestation, AttestationRecord):
        if attestation.underlying_authority is not authority:
            raise AuthoritySubstitutionError(
                "attestation record must preserve the source underlying authority"
            )
    elif isinstance(attestation, AttestationVerification):
        preserved = attestation.envelope.statement.receipt.underlying_authority
        if preserved is not authority:
            raise AuthoritySubstitutionError(
                "attestation verification must preserve the source underlying authority"
            )
    else:
        raise ProofReceiptAttestationError("unsupported attestation value")
    return authority


def public_attestation_artifact(value: Any) -> Any:
    """Return a canonical public value or reject witness-bearing objects."""

    return _canonical_public(value)


# Aliases aligned with supervisor naming and the ProofReceiptAttestation@1 surface.
ProofReceiptAttestationStatement = AttestationStatement
ProofReceiptAttestationRequest = AttestationRequest
ProofReceiptAttestationEnvelope = AttestationEnvelope
ProofReceiptAttestationVerification = AttestationVerification
ProofReceiptAttestationRecord = AttestationRecord
ProofReceiptPrivateWitness = PrivateWitness

__all__ = [
    "ATTESTATION_BACKEND_POLICY_SCHEMA_VERSION",
    "ATTESTATION_ENVELOPE_SCHEMA_VERSION",
    "ATTESTATION_RECORD_SCHEMA_VERSION",
    "ATTESTATION_STATEMENT_SCHEMA_VERSION",
    "ATTESTATION_VERIFICATION_SCHEMA_VERSION",
    "AttestationBackendMode",
    "AttestationBackendPolicy",
    "AttestationEnvelope",
    "AttestationGate",
    "AttestationRecord",
    "AttestationRequest",
    "AttestationStatement",
    "AttestationVerification",
    "AttestationVerificationVerdict",
    "CircuitMismatchError",
    "CryptographicBackendFailure",
    "PROOF_RECEIPT_ATTESTATION_INTERFACE",
    "PROOF_RECEIPT_ATTESTATION_SCHEMA_VERSION",
    "PrivateWitness",
    "ProofReceiptAttestationEnvelope",
    "ProofReceiptAttestationError",
    "ProofReceiptAttestationRecord",
    "ProofReceiptAttestationRequest",
    "ProofReceiptAttestationStatement",
    "ProofReceiptAttestationVerification",
    "ProofReceiptPrivateWitness",
    "REQUIRED_PUBLIC_INPUT_KEYS",
    "RevocationPolicy",
    "RevokedAttestationError",
    "StaleAttestationError",
    "TRUSTED_PROOF_RECEIPT_SCHEMA_VERSION",
    "TrustedProofReceipt",
    "WitnessDisclosureError",
    "build_attestation_record",
    "build_attestation_statement",
    "build_trusted_receipt_from_backend_result",
    "create_attestation_envelope",
    "execute_cryptographic_attestation",
    "prepare_receipt_attestation",
    "preserve_underlying_authority",
    "public_artifact_contains",
    "public_attestation_artifact",
    "record_attestation_verification",
    "verify_statement_against_policy",
]
