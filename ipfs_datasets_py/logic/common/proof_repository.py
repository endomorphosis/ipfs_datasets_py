"""ProofRepository@1 — unified backend-neutral proof repository interface.

Interface generation: ``ProofRepository@1`` (LPC-081 / LPC-G080).

One datasets-owned surface covers plans, attempts, evidence, receipts,
counterexamples, attestations, lookup, freshness, invalidation, and lineage.
Storage backends (in-memory, DuckDB, remote) implement the protocol; they do
not redefine the semantic inventory or promote cache hits into trust roots.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.common.canonical_cache_key import (
    CandidateAsKernelError,
    CanonicalCacheKeyError,
    CanonicalProofCacheKey,
    CrossEnvironmentHitError,
    admit_cache_hit,
    admit_canonical_cache_key,
    reject_candidate_as_kernel,
    require_digest,
)
from ipfs_datasets_py.logic.ir_core.axes import (
    LogicEvidenceAuthority,
    LogicEvidenceKind,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROOF_REPOSITORY_INTERFACE: Final = "ProofRepository@1"
PROOF_REPOSITORY_GENERATION: Final = "ProofRepository@1"
PROOF_REPOSITORY_MODULE_VERSION: Final = "1.0.0"
PROOF_REPOSITORY_SCHEMA: Final = "ipfs_datasets_py/proof-repository@1"
PROOF_REPOSITORY_SCHEMA_VERSION: Final = "proof-repository/v1"

# Closed capability inventory required by LPC-081 acceptance.
PROOF_REPOSITORY_CAPABILITIES: Final[tuple[str, ...]] = (
    "plans",
    "attempts",
    "evidence",
    "receipts",
    "counterexamples",
    "attestations",
    "lookup",
    "freshness",
    "invalidation",
    "lineage",
)

PROOF_REPOSITORY_CAPABILITY_SET: Final[frozenset[str]] = frozenset(
    PROOF_REPOSITORY_CAPABILITIES
)

DEFAULT_FRESHNESS_TTL_SECONDS: Final = 86_400.0
DEFAULT_MAX_RECORDS: Final = 65_536
IN_MEMORY_BACKEND_ID: Final = "backend:in-memory"

# Per-record schema pins.
PROOF_PLAN_RECORD_SCHEMA: Final = "proof-repository-plan/v1"
PROOF_ATTEMPT_RECORD_SCHEMA: Final = "proof-repository-attempt/v1"
PROOF_EVIDENCE_RECORD_SCHEMA: Final = "proof-repository-evidence/v1"
PROOF_RECEIPT_RECORD_SCHEMA: Final = "proof-repository-receipt/v1"
PROOF_COUNTEREXAMPLE_RECORD_SCHEMA: Final = "proof-repository-counterexample/v1"
PROOF_ATTESTATION_RECORD_SCHEMA: Final = "proof-repository-attestation/v1"
PROOF_INVALIDATION_RECORD_SCHEMA: Final = "proof-repository-invalidation/v1"
PROOF_LINEAGE_EDGE_SCHEMA: Final = "proof-repository-lineage/v1"
PROOF_LOOKUP_RESULT_SCHEMA: Final = "proof-repository-lookup/v1"
PROOF_FRESHNESS_REPORT_SCHEMA: Final = "proof-repository-freshness/v1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProofRepositoryError(ValueError):
    """Base error for the unified proof repository."""


class ProofRepositoryIntegrityError(ProofRepositoryError):
    """Raised when digests, schemas, or identity checks fail closed."""


class ProofRepositoryNotFoundError(ProofRepositoryError):
    """Raised when a required record is missing."""


class ProofRepositoryFreshnessError(ProofRepositoryError):
    """Raised when a record is stale, invalidated, or environment-mismatched."""


class ProofRepositoryAdmissionError(ProofRepositoryError):
    """Raised when a record fails fail-closed admission."""


class ProofRepositoryCapabilityError(ProofRepositoryError):
    """Raised when a backend advertises incomplete capabilities."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PlanStatus(StrEnum):
    """Lifecycle of a proof plan."""

    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALIDATED = "invalidated"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    """Lifecycle of one proof attempt."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class EvidenceDisposition(StrEnum):
    """How stored evidence may be used (does not raise authority)."""

    CANDIDATE = "candidate"
    DRAFT = "draft"
    ADMITTED = "admitted"
    REVOKED = "revoked"


class ReceiptKind(StrEnum):
    """Closed receipt vocabulary."""

    EVIDENCE = "evidence"
    TRANSLATION = "translation"
    RECONSTRUCTION = "reconstruction"
    KERNEL_CHECK = "kernel_check"
    POLICY = "policy"
    ATTEMPT = "attempt"


class AttestationKind(StrEnum):
    """Closed attestation vocabulary (not a trust root by itself)."""

    PRODUCER = "producer"
    INDEPENDENT_CHECK = "independent_check"
    KERNEL = "kernel"
    POLICY = "policy"
    CORPUS = "corpus"
    EXTERNAL = "external"


class InvalidationReason(StrEnum):
    """Why a cache/key slot was invalidated."""

    MANUAL = "manual"
    STALE = "stale"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    ENVIRONMENT_DRIFT = "environment_drift"
    POLICY_CHANGE = "policy_change"
    LINEAGE_BREAK = "lineage_break"
    TAMPER = "tamper"


class LineageRelation(StrEnum):
    """Directed relation between repository records."""

    PARENT = "parent"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"
    ATTESTS = "attests"
    EVIDENCES = "evidences"
    RECEIPT_OF = "receipt_of"
    ATTEMPT_OF = "attempt_of"
    COUNTEREXAMPLE_OF = "counterexample_of"
    INVALIDATES = "invalidates"


class LookupDisposition(StrEnum):
    """Closed lookup outcomes."""

    HIT = "hit"
    MISS = "miss"
    STALE = "stale"
    INVALIDATED = "invalidated"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    REJECTED = "rejected"


class RecordKind(StrEnum):
    """Kinds of first-class repository records."""

    PLAN = "plan"
    ATTEMPT = "attempt"
    EVIDENCE = "evidence"
    RECEIPT = "receipt"
    COUNTEREXAMPLE = "counterexample"
    ATTESTATION = "attestation"
    INVALIDATION = "invalidation"
    LINEAGE = "lineage"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if value is None or value == "":
        if optional:
            return ""
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a non-empty string"
        )
    if not isinstance(value, str):
        raise ProofRepositoryAdmissionError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        if optional:
            return ""
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a non-empty string"
        )
    if text != value:
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in text:
        raise ProofRepositoryAdmissionError(
            f"{field_name} must not contain NUL bytes"
        )
    return text


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(getattr(value, "value", value)))
    except (TypeError, ValueError) as error:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be one of {allowed}; got {value!r}"
        ) from error


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a finite number"
        )
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a finite number"
        )
    return number


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            raise ProofRepositoryAdmissionError(
                "non-finite float is not JSON-safe"
            )
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    if hasattr(value, "value"):
        return _json_ready(value.value)
    raise ProofRepositoryAdmissionError(
        f"value of type {type(value).__name__} is not JSON-safe"
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def repository_content_digest(value: Any) -> str:
    """Stable ``sha256:…`` digest over a JSON-ready payload."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


def _optional_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ProofRepositoryAdmissionError(f"{field_name} must be a mapping")
    return MappingProxyType(_json_ready(dict(value)))


def _optional_tuple_str(
    value: object, field_name: str
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a sequence of strings, not a string"
        )
    if not isinstance(value, Sequence):
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a sequence of strings"
        )
    items: list[str] = []
    for index, item in enumerate(value):
        items.append(_text(item, f"{field_name}[{index}]"))
    return tuple(items)


def _admit_key(
    value: CanonicalProofCacheKey | Mapping[str, Any] | str | None,
    field_name: str = "cache_key",
) -> CanonicalProofCacheKey | None:
    if value is None or value == "":
        return None
    if isinstance(value, CanonicalProofCacheKey):
        return admit_canonical_cache_key(value)
    if isinstance(value, Mapping):
        try:
            return admit_canonical_cache_key(value)
        except CanonicalCacheKeyError as error:
            raise ProofRepositoryAdmissionError(
                f"{field_name} is not an admissible CanonicalProofCacheKey: "
                f"{error}"
            ) from error
    if isinstance(value, str):
        # Bare key_id / digest reference is not enough for full admission;
        # callers that only store a key_id must pass the typed key on lookup.
        raise ProofRepositoryAdmissionError(
            f"{field_name} must be a CanonicalProofCacheKey or mapping body, "
            f"not a bare string"
        )
    raise ProofRepositoryAdmissionError(
        f"{field_name} must be a CanonicalProofCacheKey or mapping"
    )


def _key_id_of(
    value: CanonicalProofCacheKey | Mapping[str, Any] | str | None,
) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, CanonicalProofCacheKey):
        return value.key_id
    if isinstance(value, Mapping):
        key = _admit_key(value)
        return "" if key is None else key.key_id
    return _text(value, "key_id")


def capabilities_cover_acceptance(
    capabilities: Iterable[str] | None = None,
) -> bool:
    """Return True when *capabilities* covers the LPC-081 inventory."""

    declared = (
        PROOF_REPOSITORY_CAPABILITY_SET
        if capabilities is None
        else frozenset(str(item) for item in capabilities)
    )
    return PROOF_REPOSITORY_CAPABILITY_SET <= declared


def require_full_capabilities(capabilities: Iterable[str]) -> frozenset[str]:
    """Require the closed LPC-081 capability inventory (fail-closed)."""

    declared = frozenset(str(item) for item in capabilities)
    missing = sorted(PROOF_REPOSITORY_CAPABILITY_SET - declared)
    if missing:
        raise ProofRepositoryCapabilityError(
            "proof repository missing required capabilities: "
            + ", ".join(missing)
        )
    return declared


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofPlanRecord:
    """Backend-neutral proof plan (DAG of attempt slots)."""

    plan_id: str
    cache_key: CanonicalProofCacheKey
    status: PlanStatus = PlanStatus.DRAFT
    node_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0
    owner_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_PLAN_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _text(self.plan_id, "plan_id"))
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(
            self, "status", _enum(self.status, PlanStatus, "status")
        )
        object.__setattr__(
            self, "node_ids", _optional_tuple_str(self.node_ids, "node_ids")
        )
        object.__setattr__(
            self,
            "depends_on",
            _optional_tuple_str(self.depends_on, "depends_on"),
        )
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", _finite_number(self.updated_at, "updated_at")
        )
        object.__setattr__(
            self, "owner_id", _text(self.owner_id, "owner_id", optional=True)
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_PLAN_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported plan schema: {self.schema_version!r}"
            )

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key.to_dict(),
            "created_at": self.created_at,
            "depends_on": list(self.depends_on),
            "metadata": dict(self.metadata),
            "node_ids": list(self.node_ids),
            "owner_id": self.owner_id,
            "plan_id": self.plan_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofPlanRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError("plan must be a mapping")
        return cls(
            plan_id=str(value.get("plan_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            status=value.get("status", PlanStatus.DRAFT.value),
            node_ids=tuple(value.get("node_ids") or ()),
            depends_on=tuple(value.get("depends_on") or ()),
            created_at=float(value.get("created_at") or 0.0),
            updated_at=float(value.get("updated_at") or 0.0),
            owner_id=str(value.get("owner_id") or ""),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_PLAN_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        plan_id: str | None = None,
        status: PlanStatus | str = PlanStatus.DRAFT,
        node_ids: Sequence[str] = (),
        depends_on: Sequence[str] = (),
        owner_id: str = "",
        metadata: Mapping[str, Any] | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> ProofPlanRecord:
        now = time.time() if created_at is None else float(created_at)
        return cls(
            plan_id=plan_id or _new_id("plan"),
            cache_key=cache_key,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            node_ids=tuple(node_ids),
            depends_on=tuple(depends_on),
            created_at=now,
            updated_at=now if updated_at is None else float(updated_at),
            owner_id=owner_id,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class ProofAttemptRecord:
    """One execution attempt against a cache key / plan node."""

    attempt_id: str
    cache_key: CanonicalProofCacheKey
    status: AttemptStatus = AttemptStatus.PENDING
    plan_id: str = ""
    node_id: str = ""
    provider_id: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    outcome_digest: str = ""
    error: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_ATTEMPT_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attempt_id", _text(self.attempt_id, "attempt_id")
        )
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(
            self, "status", _enum(self.status, AttemptStatus, "status")
        )
        object.__setattr__(
            self, "plan_id", _text(self.plan_id, "plan_id", optional=True)
        )
        object.__setattr__(
            self, "node_id", _text(self.node_id, "node_id", optional=True)
        )
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", optional=True),
        )
        object.__setattr__(
            self, "started_at", _finite_number(self.started_at, "started_at")
        )
        object.__setattr__(
            self,
            "finished_at",
            _finite_number(self.finished_at, "finished_at"),
        )
        if self.outcome_digest:
            object.__setattr__(
                self,
                "outcome_digest",
                require_digest(self.outcome_digest, "outcome_digest"),
            )
        else:
            object.__setattr__(self, "outcome_digest", "")
        object.__setattr__(
            self, "error", _text(self.error, "error", optional=True)
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_ATTEMPT_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported attempt schema: {self.schema_version!r}"
            )

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "cache_key": self.cache_key.to_dict(),
            "error": self.error,
            "finished_at": self.finished_at,
            "metadata": dict(self.metadata),
            "node_id": self.node_id,
            "outcome_digest": self.outcome_digest,
            "plan_id": self.plan_id,
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofAttemptRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError("attempt must be a mapping")
        return cls(
            attempt_id=str(value.get("attempt_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            status=value.get("status", AttemptStatus.PENDING.value),
            plan_id=str(value.get("plan_id") or ""),
            node_id=str(value.get("node_id") or ""),
            provider_id=str(value.get("provider_id") or ""),
            started_at=float(value.get("started_at") or 0.0),
            finished_at=float(value.get("finished_at") or 0.0),
            outcome_digest=str(value.get("outcome_digest") or ""),
            error=str(value.get("error") or ""),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_ATTEMPT_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        attempt_id: str | None = None,
        status: AttemptStatus | str = AttemptStatus.PENDING,
        plan_id: str = "",
        node_id: str = "",
        provider_id: str = "",
        started_at: float | None = None,
        finished_at: float = 0.0,
        outcome_digest: str = "",
        error: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ProofAttemptRecord:
        return cls(
            attempt_id=attempt_id or _new_id("attempt"),
            cache_key=cache_key,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            plan_id=plan_id,
            node_id=node_id,
            provider_id=provider_id,
            started_at=time.time() if started_at is None else float(started_at),
            finished_at=float(finished_at),
            outcome_digest=outcome_digest,
            error=error,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class ProofEvidenceRecord:
    """Stored evidence blob bound to a cache key (not a trust root)."""

    evidence_id: str
    cache_key: CanonicalProofCacheKey
    evidence_kind: LogicEvidenceKind
    authority_ceiling: LogicEvidenceAuthority
    content_digest: str
    disposition: EvidenceDisposition = EvidenceDisposition.CANDIDATE
    attempt_id: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    schema_version: str = PROOF_EVIDENCE_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _text(self.evidence_id, "evidence_id")
        )
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(
            self,
            "evidence_kind",
            _enum(self.evidence_kind, LogicEvidenceKind, "evidence_kind"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(
                self.authority_ceiling,
                LogicEvidenceAuthority,
                "authority_ceiling",
            ),
        )
        object.__setattr__(
            self,
            "content_digest",
            require_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, EvidenceDisposition, "disposition"),
        )
        object.__setattr__(
            self,
            "attempt_id",
            _text(self.attempt_id, "attempt_id", optional=True),
        )
        object.__setattr__(
            self, "payload", _optional_mapping(self.payload, "payload")
        )
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_EVIDENCE_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported evidence schema: {self.schema_version!r}"
            )
        # Candidate evidence cannot claim kernel ceilings (LPC-080 / LPC-032).
        try:
            reject_candidate_as_kernel(
                self.evidence_kind, self.authority_ceiling
            )
        except CandidateAsKernelError as error:
            raise ProofRepositoryAdmissionError(str(error)) from error

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "authority_ceiling": self.authority_ceiling.value,
            "cache_key": self.cache_key.to_dict(),
            "content_digest": self.content_digest,
            "created_at": self.created_at,
            "disposition": self.disposition.value,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind.value,
            "payload": dict(self.payload),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofEvidenceRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError("evidence must be a mapping")
        return cls(
            evidence_id=str(value.get("evidence_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            evidence_kind=value.get(
                "evidence_kind", LogicEvidenceKind.CANDIDATE.value
            ),
            authority_ceiling=value.get(
                "authority_ceiling", LogicEvidenceAuthority.NONE.value
            ),
            content_digest=str(value.get("content_digest") or ""),
            disposition=value.get(
                "disposition", EvidenceDisposition.CANDIDATE.value
            ),
            attempt_id=str(value.get("attempt_id") or ""),
            payload=dict(value.get("payload") or {}),
            created_at=float(value.get("created_at") or 0.0),
            schema_version=str(
                value.get("schema_version") or PROOF_EVIDENCE_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        evidence_kind: LogicEvidenceKind | str,
        authority_ceiling: LogicEvidenceAuthority | str,
        payload: Mapping[str, Any] | None = None,
        content: Any = None,
        evidence_id: str | None = None,
        disposition: EvidenceDisposition | str = EvidenceDisposition.CANDIDATE,
        attempt_id: str = "",
        created_at: float | None = None,
    ) -> ProofEvidenceRecord:
        body = dict(payload or {})
        if content is not None:
            body.setdefault("content", _json_ready(content))
        digest = repository_content_digest(
            {
                "authority_ceiling": str(
                    getattr(authority_ceiling, "value", authority_ceiling)
                ),
                "evidence_kind": str(
                    getattr(evidence_kind, "value", evidence_kind)
                ),
                "payload": body,
            }
        )
        return cls(
            evidence_id=evidence_id or _new_id("evidence"),
            cache_key=cache_key,  # type: ignore[arg-type]
            evidence_kind=evidence_kind,  # type: ignore[arg-type]
            authority_ceiling=authority_ceiling,  # type: ignore[arg-type]
            content_digest=digest,
            disposition=disposition,  # type: ignore[arg-type]
            attempt_id=attempt_id,
            payload=body,
            created_at=time.time() if created_at is None else float(created_at),
        )


@dataclass(frozen=True, slots=True)
class ProofReceiptRecord:
    """Auditable receipt binding an action to evidence / attempt identity."""

    receipt_id: str
    cache_key: CanonicalProofCacheKey
    kind: ReceiptKind
    subject_id: str
    content_digest: str
    issued_at: float = 0.0
    issuer_id: str = ""
    attempt_id: str = ""
    evidence_id: str = ""
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_RECEIPT_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _text(self.receipt_id, "receipt_id")
        )
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(self, "kind", _enum(self.kind, ReceiptKind, "kind"))
        object.__setattr__(
            self, "subject_id", _text(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            require_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "issued_at", _finite_number(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "issuer_id", _text(self.issuer_id, "issuer_id", optional=True)
        )
        object.__setattr__(
            self,
            "attempt_id",
            _text(self.attempt_id, "attempt_id", optional=True),
        )
        object.__setattr__(
            self,
            "evidence_id",
            _text(self.evidence_id, "evidence_id", optional=True),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_RECEIPT_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "cache_key": self.cache_key.to_dict(),
            "content_digest": self.content_digest,
            "evidence_id": self.evidence_id,
            "issued_at": self.issued_at,
            "issuer_id": self.issuer_id,
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofReceiptRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError("receipt must be a mapping")
        return cls(
            receipt_id=str(value.get("receipt_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            kind=value.get("kind", ReceiptKind.EVIDENCE.value),
            subject_id=str(value.get("subject_id") or ""),
            content_digest=str(value.get("content_digest") or ""),
            issued_at=float(value.get("issued_at") or 0.0),
            issuer_id=str(value.get("issuer_id") or ""),
            attempt_id=str(value.get("attempt_id") or ""),
            evidence_id=str(value.get("evidence_id") or ""),
            notes=str(value.get("notes") or ""),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_RECEIPT_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        kind: ReceiptKind | str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
        receipt_id: str | None = None,
        issuer_id: str = "",
        attempt_id: str = "",
        evidence_id: str = "",
        notes: str = "",
        issued_at: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProofReceiptRecord:
        body = dict(payload or {})
        digest = repository_content_digest(
            {
                "kind": str(getattr(kind, "value", kind)),
                "payload": body,
                "subject_id": subject_id,
            }
        )
        return cls(
            receipt_id=receipt_id or _new_id("receipt"),
            cache_key=cache_key,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            subject_id=subject_id,
            content_digest=digest,
            issued_at=time.time() if issued_at is None else float(issued_at),
            issuer_id=issuer_id,
            attempt_id=attempt_id,
            evidence_id=evidence_id,
            notes=notes,
            metadata=dict(metadata or body),
        )


@dataclass(frozen=True, slots=True)
class ProofCounterexampleRecord:
    """First-class counterexample; never collapsed into a positive proof."""

    counterexample_id: str
    cache_key: CanonicalProofCacheKey
    content_digest: str
    model: Mapping[str, Any] = field(default_factory=dict)
    attempt_id: str = ""
    evidence_id: str = ""
    created_at: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_COUNTEREXAMPLE_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "counterexample_id",
            _text(self.counterexample_id, "counterexample_id"),
        )
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(
            self,
            "content_digest",
            require_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "model", _optional_mapping(self.model, "model")
        )
        object.__setattr__(
            self,
            "attempt_id",
            _text(self.attempt_id, "attempt_id", optional=True),
        )
        object.__setattr__(
            self,
            "evidence_id",
            _text(self.evidence_id, "evidence_id", optional=True),
        )
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_COUNTEREXAMPLE_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported counterexample schema: {self.schema_version!r}"
            )

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "cache_key": self.cache_key.to_dict(),
            "content_digest": self.content_digest,
            "counterexample_id": self.counterexample_id,
            "created_at": self.created_at,
            "evidence_id": self.evidence_id,
            "metadata": dict(self.metadata),
            "model": dict(self.model),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofCounterexampleRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError(
                "counterexample must be a mapping"
            )
        return cls(
            counterexample_id=str(value.get("counterexample_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            content_digest=str(value.get("content_digest") or ""),
            model=dict(value.get("model") or {}),
            attempt_id=str(value.get("attempt_id") or ""),
            evidence_id=str(value.get("evidence_id") or ""),
            created_at=float(value.get("created_at") or 0.0),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version")
                or PROOF_COUNTEREXAMPLE_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        model: Mapping[str, Any],
        counterexample_id: str | None = None,
        attempt_id: str = "",
        evidence_id: str = "",
        created_at: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProofCounterexampleRecord:
        body = _json_ready(dict(model))
        digest = repository_content_digest({"model": body})
        return cls(
            counterexample_id=counterexample_id or _new_id("cex"),
            cache_key=cache_key,  # type: ignore[arg-type]
            content_digest=digest,
            model=body,
            attempt_id=attempt_id,
            evidence_id=evidence_id,
            created_at=time.time() if created_at is None else float(created_at),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class ProofAttestationRecord:
    """Attestation over a subject; never silently raises authority ceilings."""

    attestation_id: str
    cache_key: CanonicalProofCacheKey
    kind: AttestationKind
    subject_id: str
    content_digest: str
    attestor_id: str = ""
    issued_at: float = 0.0
    expires_at: float = 0.0
    evidence_id: str = ""
    receipt_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_ATTESTATION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attestation_id",
            _text(self.attestation_id, "attestation_id"),
        )
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(
            self, "kind", _enum(self.kind, AttestationKind, "kind")
        )
        object.__setattr__(
            self, "subject_id", _text(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self,
            "content_digest",
            require_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "attestor_id",
            _text(self.attestor_id, "attestor_id", optional=True),
        )
        object.__setattr__(
            self, "issued_at", _finite_number(self.issued_at, "issued_at")
        )
        object.__setattr__(
            self, "expires_at", _finite_number(self.expires_at, "expires_at")
        )
        if self.expires_at and self.issued_at and self.expires_at < self.issued_at:
            raise ProofRepositoryAdmissionError(
                "expires_at must not precede issued_at"
            )
        object.__setattr__(
            self,
            "evidence_id",
            _text(self.evidence_id, "evidence_id", optional=True),
        )
        object.__setattr__(
            self,
            "receipt_id",
            _text(self.receipt_id, "receipt_id", optional=True),
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_ATTESTATION_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported attestation schema: {self.schema_version!r}"
            )

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at <= 0:
            return False
        current = time.time() if now is None else float(now)
        return current > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "attestor_id": self.attestor_id,
            "cache_key": self.cache_key.to_dict(),
            "content_digest": self.content_digest,
            "evidence_id": self.evidence_id,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "kind": self.kind.value,
            "metadata": dict(self.metadata),
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofAttestationRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError("attestation must be a mapping")
        return cls(
            attestation_id=str(value.get("attestation_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            kind=value.get("kind", AttestationKind.PRODUCER.value),
            subject_id=str(value.get("subject_id") or ""),
            content_digest=str(value.get("content_digest") or ""),
            attestor_id=str(value.get("attestor_id") or ""),
            issued_at=float(value.get("issued_at") or 0.0),
            expires_at=float(value.get("expires_at") or 0.0),
            evidence_id=str(value.get("evidence_id") or ""),
            receipt_id=str(value.get("receipt_id") or ""),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_ATTESTATION_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        kind: AttestationKind | str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
        attestation_id: str | None = None,
        attestor_id: str = "",
        issued_at: float | None = None,
        expires_at: float = 0.0,
        evidence_id: str = "",
        receipt_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ProofAttestationRecord:
        body = dict(payload or {})
        digest = repository_content_digest(
            {
                "kind": str(getattr(kind, "value", kind)),
                "payload": body,
                "subject_id": subject_id,
            }
        )
        now = time.time() if issued_at is None else float(issued_at)
        return cls(
            attestation_id=attestation_id or _new_id("attest"),
            cache_key=cache_key,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            subject_id=subject_id,
            content_digest=digest,
            attestor_id=attestor_id,
            issued_at=now,
            expires_at=float(expires_at),
            evidence_id=evidence_id,
            receipt_id=receipt_id,
            metadata=dict(metadata or body),
        )


@dataclass(frozen=True, slots=True)
class ProofInvalidationRecord:
    """Immutable invalidation event for a cache key or record subject."""

    invalidation_id: str
    cache_key: CanonicalProofCacheKey
    reason: InvalidationReason
    subject_id: str = ""
    subject_kind: RecordKind | None = None
    invalidated_at: float = 0.0
    actor_id: str = ""
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_INVALIDATION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "invalidation_id",
            _text(self.invalidation_id, "invalidation_id"),
        )
        key = _admit_key(self.cache_key, "cache_key")
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(
            self, "reason", _enum(self.reason, InvalidationReason, "reason")
        )
        object.__setattr__(
            self,
            "subject_id",
            _text(self.subject_id, "subject_id", optional=True),
        )
        if self.subject_kind is not None:
            object.__setattr__(
                self,
                "subject_kind",
                _enum(self.subject_kind, RecordKind, "subject_kind"),
            )
        object.__setattr__(
            self,
            "invalidated_at",
            _finite_number(self.invalidated_at, "invalidated_at"),
        )
        object.__setattr__(
            self, "actor_id", _text(self.actor_id, "actor_id", optional=True)
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_INVALIDATION_RECORD_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported invalidation schema: {self.schema_version!r}"
            )

    @property
    def key_id(self) -> str:
        return self.cache_key.key_id

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "cache_key": self.cache_key.to_dict(),
            "invalidated_at": self.invalidated_at,
            "invalidation_id": self.invalidation_id,
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "reason": self.reason.value,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "subject_kind": None
            if self.subject_kind is None
            else self.subject_kind.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofInvalidationRecord:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError(
                "invalidation must be a mapping"
            )
        subject_kind = value.get("subject_kind")
        return cls(
            invalidation_id=str(value.get("invalidation_id") or ""),
            cache_key=value.get("cache_key") or {},  # type: ignore[arg-type]
            reason=value.get("reason", InvalidationReason.MANUAL.value),
            subject_id=str(value.get("subject_id") or ""),
            subject_kind=None if not subject_kind else subject_kind,
            invalidated_at=float(value.get("invalidated_at") or 0.0),
            actor_id=str(value.get("actor_id") or ""),
            notes=str(value.get("notes") or ""),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_INVALIDATION_RECORD_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        cache_key: CanonicalProofCacheKey | Mapping[str, Any],
        reason: InvalidationReason | str,
        invalidation_id: str | None = None,
        subject_id: str = "",
        subject_kind: RecordKind | str | None = None,
        actor_id: str = "",
        notes: str = "",
        invalidated_at: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProofInvalidationRecord:
        return cls(
            invalidation_id=invalidation_id or _new_id("inv"),
            cache_key=cache_key,  # type: ignore[arg-type]
            reason=reason,  # type: ignore[arg-type]
            subject_id=subject_id,
            subject_kind=subject_kind,  # type: ignore[arg-type]
            invalidated_at=(
                time.time() if invalidated_at is None else float(invalidated_at)
            ),
            actor_id=actor_id,
            notes=notes,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class ProofLineageEdge:
    """Directed lineage edge between repository records."""

    edge_id: str
    relation: LineageRelation
    parent_id: str
    child_id: str
    parent_kind: RecordKind
    child_kind: RecordKind
    cache_key_id: str = ""
    created_at: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROOF_LINEAGE_EDGE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _text(self.edge_id, "edge_id"))
        object.__setattr__(
            self, "relation", _enum(self.relation, LineageRelation, "relation")
        )
        object.__setattr__(
            self, "parent_id", _text(self.parent_id, "parent_id")
        )
        object.__setattr__(self, "child_id", _text(self.child_id, "child_id"))
        object.__setattr__(
            self,
            "parent_kind",
            _enum(self.parent_kind, RecordKind, "parent_kind"),
        )
        object.__setattr__(
            self, "child_kind", _enum(self.child_kind, RecordKind, "child_kind")
        )
        object.__setattr__(
            self,
            "cache_key_id",
            _text(self.cache_key_id, "cache_key_id", optional=True),
        )
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "metadata", _optional_mapping(self.metadata, "metadata")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_LINEAGE_EDGE_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported lineage schema: {self.schema_version!r}"
            )
        if self.parent_id == self.child_id:
            raise ProofRepositoryAdmissionError(
                "lineage edge parent_id and child_id must differ"
            )

    @property
    def digest(self) -> str:
        return repository_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key_id": self.cache_key_id,
            "child_id": self.child_id,
            "child_kind": self.child_kind.value,
            "created_at": self.created_at,
            "edge_id": self.edge_id,
            "metadata": dict(self.metadata),
            "parent_id": self.parent_id,
            "parent_kind": self.parent_kind.value,
            "relation": self.relation.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofLineageEdge:
        if not isinstance(value, Mapping):
            raise ProofRepositoryAdmissionError("lineage edge must be a mapping")
        return cls(
            edge_id=str(value.get("edge_id") or ""),
            relation=value.get("relation", LineageRelation.PARENT.value),
            parent_id=str(value.get("parent_id") or ""),
            child_id=str(value.get("child_id") or ""),
            parent_kind=value.get("parent_kind", RecordKind.PLAN.value),
            child_kind=value.get("child_kind", RecordKind.ATTEMPT.value),
            cache_key_id=str(value.get("cache_key_id") or ""),
            created_at=float(value.get("created_at") or 0.0),
            metadata=dict(value.get("metadata") or {}),
            schema_version=str(
                value.get("schema_version") or PROOF_LINEAGE_EDGE_SCHEMA
            ),
        )

    @classmethod
    def build(
        cls,
        *,
        relation: LineageRelation | str,
        parent_id: str,
        child_id: str,
        parent_kind: RecordKind | str,
        child_kind: RecordKind | str,
        edge_id: str | None = None,
        cache_key_id: str = "",
        created_at: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProofLineageEdge:
        return cls(
            edge_id=edge_id or _new_id("lineage"),
            relation=relation,  # type: ignore[arg-type]
            parent_id=parent_id,
            child_id=child_id,
            parent_kind=parent_kind,  # type: ignore[arg-type]
            child_kind=child_kind,  # type: ignore[arg-type]
            cache_key_id=cache_key_id,
            created_at=time.time() if created_at is None else float(created_at),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    """Freshness evaluation for a cache key slot."""

    key_id: str
    is_fresh: bool
    disposition: LookupDisposition
    age_seconds: float = 0.0
    ttl_seconds: float = DEFAULT_FRESHNESS_TTL_SECONDS
    stored_at: float = 0.0
    expires_at: float = 0.0
    environment: str = ""
    invalidation_id: str = ""
    reason: str = ""
    schema_version: str = PROOF_FRESHNESS_REPORT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_id", _text(self.key_id, "key_id"))
        if not isinstance(self.is_fresh, bool):
            raise ProofRepositoryAdmissionError("is_fresh must be a bool")
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, LookupDisposition, "disposition"),
        )
        object.__setattr__(
            self, "age_seconds", _finite_number(self.age_seconds, "age_seconds")
        )
        object.__setattr__(
            self, "ttl_seconds", _finite_number(self.ttl_seconds, "ttl_seconds")
        )
        object.__setattr__(
            self, "stored_at", _finite_number(self.stored_at, "stored_at")
        )
        object.__setattr__(
            self, "expires_at", _finite_number(self.expires_at, "expires_at")
        )
        object.__setattr__(
            self,
            "environment",
            _text(self.environment, "environment", optional=True),
        )
        object.__setattr__(
            self,
            "invalidation_id",
            _text(self.invalidation_id, "invalidation_id", optional=True),
        )
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_FRESHNESS_REPORT_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported freshness schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "age_seconds": self.age_seconds,
            "disposition": self.disposition.value,
            "environment": self.environment,
            "expires_at": self.expires_at,
            "invalidation_id": self.invalidation_id,
            "is_fresh": self.is_fresh,
            "key_id": self.key_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "stored_at": self.stored_at,
            "ttl_seconds": self.ttl_seconds,
        }


@dataclass(frozen=True, slots=True)
class ProofLookupResult:
    """Result of a repository lookup under a canonical cache key."""

    disposition: LookupDisposition
    key: CanonicalProofCacheKey | None = None
    freshness: FreshnessReport | None = None
    plan: ProofPlanRecord | None = None
    attempts: tuple[ProofAttemptRecord, ...] = ()
    evidence: tuple[ProofEvidenceRecord, ...] = ()
    receipts: tuple[ProofReceiptRecord, ...] = ()
    counterexamples: tuple[ProofCounterexampleRecord, ...] = ()
    attestations: tuple[ProofAttestationRecord, ...] = ()
    invalidations: tuple[ProofInvalidationRecord, ...] = ()
    lineage: tuple[ProofLineageEdge, ...] = ()
    reason: str = ""
    schema_version: str = PROOF_LOOKUP_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, LookupDisposition, "disposition"),
        )
        if self.key is not None and not isinstance(
            self.key, CanonicalProofCacheKey
        ):
            raise ProofRepositoryAdmissionError(
                "key must be a CanonicalProofCacheKey or None"
            )
        object.__setattr__(self, "attempts", tuple(self.attempts or ()))
        object.__setattr__(self, "evidence", tuple(self.evidence or ()))
        object.__setattr__(self, "receipts", tuple(self.receipts or ()))
        object.__setattr__(
            self, "counterexamples", tuple(self.counterexamples or ())
        )
        object.__setattr__(
            self, "attestations", tuple(self.attestations or ())
        )
        object.__setattr__(
            self, "invalidations", tuple(self.invalidations or ())
        )
        object.__setattr__(self, "lineage", tuple(self.lineage or ()))
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_LOOKUP_RESULT_SCHEMA:
            raise ProofRepositoryAdmissionError(
                f"unsupported lookup schema: {self.schema_version!r}"
            )

    @property
    def is_hit(self) -> bool:
        return self.disposition is LookupDisposition.HIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": [item.to_dict() for item in self.attempts],
            "attestations": [item.to_dict() for item in self.attestations],
            "counterexamples": [
                item.to_dict() for item in self.counterexamples
            ],
            "disposition": self.disposition.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "freshness": None
            if self.freshness is None
            else self.freshness.to_dict(),
            "invalidations": [item.to_dict() for item in self.invalidations],
            "key": None if self.key is None else self.key.to_dict(),
            "lineage": [item.to_dict() for item in self.lineage],
            "plan": None if self.plan is None else self.plan.to_dict(),
            "reason": self.reason,
            "receipts": [item.to_dict() for item in self.receipts],
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProofRepository(Protocol):
    """Backend-neutral proof repository protocol (ProofRepository@1).

    Implementations must cover every capability in
    :data:`PROOF_REPOSITORY_CAPABILITIES`. DuckDB, remote stores, and the
    in-memory reference backend project into this surface without redefining
    semantic fields (LPC-G080 conflict policy).
    """

    @property
    def interface(self) -> str: ...

    @property
    def schema_version(self) -> str: ...

    @property
    def backend_id(self) -> str: ...

    def capabilities(self) -> frozenset[str]: ...

    # -- plans --------------------------------------------------------------

    def put_plan(self, plan: ProofPlanRecord | Mapping[str, Any]) -> ProofPlanRecord: ...

    def get_plan(self, plan_id: str) -> ProofPlanRecord | None: ...

    def list_plans(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofPlanRecord, ...]: ...

    # -- attempts -----------------------------------------------------------

    def put_attempt(
        self, attempt: ProofAttemptRecord | Mapping[str, Any]
    ) -> ProofAttemptRecord: ...

    def get_attempt(self, attempt_id: str) -> ProofAttemptRecord | None: ...

    def list_attempts(
        self,
        *,
        key: CanonicalProofCacheKey | Mapping[str, Any] | None = None,
        plan_id: str = "",
    ) -> tuple[ProofAttemptRecord, ...]: ...

    # -- evidence -----------------------------------------------------------

    def put_evidence(
        self, evidence: ProofEvidenceRecord | Mapping[str, Any]
    ) -> ProofEvidenceRecord: ...

    def get_evidence(self, evidence_id: str) -> ProofEvidenceRecord | None: ...

    def list_evidence(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofEvidenceRecord, ...]: ...

    # -- receipts -----------------------------------------------------------

    def put_receipt(
        self, receipt: ProofReceiptRecord | Mapping[str, Any]
    ) -> ProofReceiptRecord: ...

    def get_receipt(self, receipt_id: str) -> ProofReceiptRecord | None: ...

    def list_receipts(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofReceiptRecord, ...]: ...

    # -- counterexamples ----------------------------------------------------

    def put_counterexample(
        self, counterexample: ProofCounterexampleRecord | Mapping[str, Any]
    ) -> ProofCounterexampleRecord: ...

    def get_counterexample(
        self, counterexample_id: str
    ) -> ProofCounterexampleRecord | None: ...

    def list_counterexamples(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofCounterexampleRecord, ...]: ...

    # -- attestations -------------------------------------------------------

    def put_attestation(
        self, attestation: ProofAttestationRecord | Mapping[str, Any]
    ) -> ProofAttestationRecord: ...

    def get_attestation(
        self, attestation_id: str
    ) -> ProofAttestationRecord | None: ...

    def list_attestations(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofAttestationRecord, ...]: ...

    # -- lookup / freshness / invalidation / lineage ------------------------

    def lookup(
        self,
        key: CanonicalProofCacheKey | Mapping[str, Any],
        *,
        now: float | None = None,
        require_fresh: bool = True,
    ) -> ProofLookupResult: ...

    def freshness(
        self,
        key: CanonicalProofCacheKey | Mapping[str, Any],
        *,
        now: float | None = None,
    ) -> FreshnessReport: ...

    def invalidate(
        self,
        key: CanonicalProofCacheKey | Mapping[str, Any],
        *,
        reason: InvalidationReason | str = InvalidationReason.MANUAL,
        subject_id: str = "",
        subject_kind: RecordKind | str | None = None,
        actor_id: str = "",
        notes: str = "",
        now: float | None = None,
    ) -> ProofInvalidationRecord: ...

    def list_invalidations(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofInvalidationRecord, ...]: ...

    def put_lineage(
        self, edge: ProofLineageEdge | Mapping[str, Any]
    ) -> ProofLineageEdge: ...

    def lineage_of(
        self,
        record_id: str,
        *,
        direction: str = "both",
    ) -> tuple[ProofLineageEdge, ...]: ...

    def list_lineage(
        self, *, key_id: str = ""
    ) -> tuple[ProofLineageEdge, ...]: ...

    def stats(self) -> Mapping[str, int]: ...


# ---------------------------------------------------------------------------
# In-memory reference backend
# ---------------------------------------------------------------------------


class InMemoryProofRepository:
    """Process-local reference implementation of :class:`ProofRepository`.

    Thread-safe, backend-neutral, and free of DuckDB / network / filesystem
    dependencies. Durable backends (for example DuckDB) may implement the same
    protocol while remaining an implementation detail.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_FRESHNESS_TTL_SECONDS,
        max_records: int = DEFAULT_MAX_RECORDS,
        backend_id: str = IN_MEMORY_BACKEND_ID,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds < 0:
            raise ProofRepositoryError("ttl_seconds must be non-negative")
        if max_records <= 0:
            raise ProofRepositoryError("max_records must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._max_records = int(max_records)
        self._backend_id = _text(backend_id, "backend_id")
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._plans: dict[str, ProofPlanRecord] = {}
        self._attempts: dict[str, ProofAttemptRecord] = {}
        self._evidence: dict[str, ProofEvidenceRecord] = {}
        self._receipts: dict[str, ProofReceiptRecord] = {}
        self._counterexamples: dict[str, ProofCounterexampleRecord] = {}
        self._attestations: dict[str, ProofAttestationRecord] = {}
        self._invalidations: dict[str, ProofInvalidationRecord] = {}
        self._lineage: dict[str, ProofLineageEdge] = {}
        # key_id → earliest stored_at for freshness of the key slot
        self._key_stored_at: dict[str, float] = {}
        self._key_invalidated: dict[str, str] = {}  # key_id → inv id
        self._stats = {
            "plans": 0,
            "attempts": 0,
            "evidence": 0,
            "receipts": 0,
            "counterexamples": 0,
            "attestations": 0,
            "invalidations": 0,
            "lineage": 0,
            "lookups": 0,
            "hits": 0,
            "misses": 0,
            "stale": 0,
            "rejected": 0,
        }

    # -- identity -----------------------------------------------------------

    @property
    def interface(self) -> str:
        return PROOF_REPOSITORY_INTERFACE

    @property
    def schema_version(self) -> str:
        return PROOF_REPOSITORY_SCHEMA_VERSION

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def capabilities(self) -> frozenset[str]:
        return PROOF_REPOSITORY_CAPABILITY_SET

    def _now(self, now: float | None = None) -> float:
        return self._clock() if now is None else float(now)

    def _touch_key(self, key: CanonicalProofCacheKey, when: float) -> None:
        existing = self._key_stored_at.get(key.key_id)
        if existing is None or when < existing:
            self._key_stored_at[key.key_id] = when
        # A new write after invalidation re-opens the slot only when an
        # explicit superseding write clears invalidation — fail closed: keep
        # invalidation until a newer put after invalidate is not auto-cleared.
        # Callers re-admit by putting records on a non-invalidated path via
        # clear_invalidation (not exposed) or a new key. Invalidation is sticky.

    def _admit_key(
        self, value: CanonicalProofCacheKey | Mapping[str, Any]
    ) -> CanonicalProofCacheKey:
        key = _admit_key(value)
        if key is None:
            raise ProofRepositoryAdmissionError("cache_key is required")
        return key

    def _enforce_capacity(self) -> None:
        total = (
            len(self._plans)
            + len(self._attempts)
            + len(self._evidence)
            + len(self._receipts)
            + len(self._counterexamples)
            + len(self._attestations)
            + len(self._invalidations)
            + len(self._lineage)
        )
        if total <= self._max_records:
            return
        raise ProofRepositoryError(
            f"repository capacity exceeded ({total} > {self._max_records})"
        )

    # -- plans --------------------------------------------------------------

    def put_plan(
        self, plan: ProofPlanRecord | Mapping[str, Any]
    ) -> ProofPlanRecord:
        record = (
            plan
            if isinstance(plan, ProofPlanRecord)
            else ProofPlanRecord.from_dict(plan)
        )
        with self._lock:
            self._plans[record.plan_id] = record
            self._touch_key(record.cache_key, record.created_at or self._now())
            self._stats["plans"] = len(self._plans)
            self._enforce_capacity()
        return record

    def get_plan(self, plan_id: str) -> ProofPlanRecord | None:
        with self._lock:
            return self._plans.get(_text(plan_id, "plan_id"))

    def list_plans(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofPlanRecord, ...]:
        with self._lock:
            records = tuple(self._plans.values())
        if key is None:
            return records
        key_id = self._admit_key(key).key_id
        return tuple(item for item in records if item.key_id == key_id)

    # -- attempts -----------------------------------------------------------

    def put_attempt(
        self, attempt: ProofAttemptRecord | Mapping[str, Any]
    ) -> ProofAttemptRecord:
        record = (
            attempt
            if isinstance(attempt, ProofAttemptRecord)
            else ProofAttemptRecord.from_dict(attempt)
        )
        with self._lock:
            self._attempts[record.attempt_id] = record
            self._touch_key(
                record.cache_key, record.started_at or self._now()
            )
            self._stats["attempts"] = len(self._attempts)
            self._enforce_capacity()
        return record

    def get_attempt(self, attempt_id: str) -> ProofAttemptRecord | None:
        with self._lock:
            return self._attempts.get(_text(attempt_id, "attempt_id"))

    def list_attempts(
        self,
        *,
        key: CanonicalProofCacheKey | Mapping[str, Any] | None = None,
        plan_id: str = "",
    ) -> tuple[ProofAttemptRecord, ...]:
        with self._lock:
            records = tuple(self._attempts.values())
        if key is not None:
            key_id = self._admit_key(key).key_id
            records = tuple(item for item in records if item.key_id == key_id)
        if plan_id:
            plan_id = _text(plan_id, "plan_id")
            records = tuple(item for item in records if item.plan_id == plan_id)
        return records

    # -- evidence -----------------------------------------------------------

    def put_evidence(
        self, evidence: ProofEvidenceRecord | Mapping[str, Any]
    ) -> ProofEvidenceRecord:
        record = (
            evidence
            if isinstance(evidence, ProofEvidenceRecord)
            else ProofEvidenceRecord.from_dict(evidence)
        )
        with self._lock:
            self._evidence[record.evidence_id] = record
            self._touch_key(
                record.cache_key, record.created_at or self._now()
            )
            self._stats["evidence"] = len(self._evidence)
            self._enforce_capacity()
        return record

    def get_evidence(self, evidence_id: str) -> ProofEvidenceRecord | None:
        with self._lock:
            return self._evidence.get(_text(evidence_id, "evidence_id"))

    def list_evidence(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofEvidenceRecord, ...]:
        with self._lock:
            records = tuple(self._evidence.values())
        if key is None:
            return records
        key_id = self._admit_key(key).key_id
        return tuple(item for item in records if item.key_id == key_id)

    # -- receipts -----------------------------------------------------------

    def put_receipt(
        self, receipt: ProofReceiptRecord | Mapping[str, Any]
    ) -> ProofReceiptRecord:
        record = (
            receipt
            if isinstance(receipt, ProofReceiptRecord)
            else ProofReceiptRecord.from_dict(receipt)
        )
        with self._lock:
            self._receipts[record.receipt_id] = record
            self._touch_key(record.cache_key, record.issued_at or self._now())
            self._stats["receipts"] = len(self._receipts)
            self._enforce_capacity()
        return record

    def get_receipt(self, receipt_id: str) -> ProofReceiptRecord | None:
        with self._lock:
            return self._receipts.get(_text(receipt_id, "receipt_id"))

    def list_receipts(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofReceiptRecord, ...]:
        with self._lock:
            records = tuple(self._receipts.values())
        if key is None:
            return records
        key_id = self._admit_key(key).key_id
        return tuple(item for item in records if item.key_id == key_id)

    # -- counterexamples ----------------------------------------------------

    def put_counterexample(
        self, counterexample: ProofCounterexampleRecord | Mapping[str, Any]
    ) -> ProofCounterexampleRecord:
        record = (
            counterexample
            if isinstance(counterexample, ProofCounterexampleRecord)
            else ProofCounterexampleRecord.from_dict(counterexample)
        )
        with self._lock:
            self._counterexamples[record.counterexample_id] = record
            self._touch_key(
                record.cache_key, record.created_at or self._now()
            )
            self._stats["counterexamples"] = len(self._counterexamples)
            self._enforce_capacity()
        return record

    def get_counterexample(
        self, counterexample_id: str
    ) -> ProofCounterexampleRecord | None:
        with self._lock:
            return self._counterexamples.get(
                _text(counterexample_id, "counterexample_id")
            )

    def list_counterexamples(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofCounterexampleRecord, ...]:
        with self._lock:
            records = tuple(self._counterexamples.values())
        if key is None:
            return records
        key_id = self._admit_key(key).key_id
        return tuple(item for item in records if item.key_id == key_id)

    # -- attestations -------------------------------------------------------

    def put_attestation(
        self, attestation: ProofAttestationRecord | Mapping[str, Any]
    ) -> ProofAttestationRecord:
        record = (
            attestation
            if isinstance(attestation, ProofAttestationRecord)
            else ProofAttestationRecord.from_dict(attestation)
        )
        with self._lock:
            self._attestations[record.attestation_id] = record
            self._touch_key(record.cache_key, record.issued_at or self._now())
            self._stats["attestations"] = len(self._attestations)
            self._enforce_capacity()
        return record

    def get_attestation(
        self, attestation_id: str
    ) -> ProofAttestationRecord | None:
        with self._lock:
            return self._attestations.get(
                _text(attestation_id, "attestation_id")
            )

    def list_attestations(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofAttestationRecord, ...]:
        with self._lock:
            records = tuple(self._attestations.values())
        if key is None:
            return records
        key_id = self._admit_key(key).key_id
        return tuple(item for item in records if item.key_id == key_id)

    # -- freshness ----------------------------------------------------------

    def freshness(
        self,
        key: CanonicalProofCacheKey | Mapping[str, Any],
        *,
        now: float | None = None,
    ) -> FreshnessReport:
        admitted = self._admit_key(key)
        current = self._now(now)
        with self._lock:
            inv_id = self._key_invalidated.get(admitted.key_id, "")
            stored_at = self._key_stored_at.get(admitted.key_id, 0.0)
        if inv_id:
            return FreshnessReport(
                key_id=admitted.key_id,
                is_fresh=False,
                disposition=LookupDisposition.INVALIDATED,
                age_seconds=max(0.0, current - stored_at) if stored_at else 0.0,
                ttl_seconds=self._ttl_seconds,
                stored_at=stored_at,
                expires_at=0.0,
                environment=admitted.environment,
                invalidation_id=inv_id,
                reason="key slot invalidated",
            )
        if stored_at <= 0:
            return FreshnessReport(
                key_id=admitted.key_id,
                is_fresh=False,
                disposition=LookupDisposition.MISS,
                age_seconds=0.0,
                ttl_seconds=self._ttl_seconds,
                stored_at=0.0,
                expires_at=0.0,
                environment=admitted.environment,
                reason="no records for key",
            )
        age = max(0.0, current - stored_at)
        expires_at = (
            0.0 if self._ttl_seconds <= 0 else stored_at + self._ttl_seconds
        )
        if self._ttl_seconds > 0 and age > self._ttl_seconds:
            return FreshnessReport(
                key_id=admitted.key_id,
                is_fresh=False,
                disposition=LookupDisposition.STALE,
                age_seconds=age,
                ttl_seconds=self._ttl_seconds,
                stored_at=stored_at,
                expires_at=expires_at,
                environment=admitted.environment,
                reason="ttl exceeded",
            )
        return FreshnessReport(
            key_id=admitted.key_id,
            is_fresh=True,
            disposition=LookupDisposition.HIT,
            age_seconds=age,
            ttl_seconds=self._ttl_seconds,
            stored_at=stored_at,
            expires_at=expires_at,
            environment=admitted.environment,
            reason="fresh",
        )

    # -- invalidation -------------------------------------------------------

    def invalidate(
        self,
        key: CanonicalProofCacheKey | Mapping[str, Any],
        *,
        reason: InvalidationReason | str = InvalidationReason.MANUAL,
        subject_id: str = "",
        subject_kind: RecordKind | str | None = None,
        actor_id: str = "",
        notes: str = "",
        now: float | None = None,
    ) -> ProofInvalidationRecord:
        admitted = self._admit_key(key)
        record = ProofInvalidationRecord.build(
            cache_key=admitted,
            reason=reason,
            subject_id=subject_id,
            subject_kind=subject_kind,
            actor_id=actor_id,
            notes=notes,
            invalidated_at=self._now(now),
        )
        with self._lock:
            self._invalidations[record.invalidation_id] = record
            self._key_invalidated[admitted.key_id] = record.invalidation_id
            self._stats["invalidations"] = len(self._invalidations)
            # Mark active plans/attempts under this key as invalidated.
            for plan_id, plan in list(self._plans.items()):
                if plan.key_id == admitted.key_id and plan.status not in {
                    PlanStatus.INVALIDATED,
                    PlanStatus.CANCELLED,
                }:
                    self._plans[plan_id] = ProofPlanRecord(
                        plan_id=plan.plan_id,
                        cache_key=plan.cache_key,
                        status=PlanStatus.INVALIDATED,
                        node_ids=plan.node_ids,
                        depends_on=plan.depends_on,
                        created_at=plan.created_at,
                        updated_at=record.invalidated_at,
                        owner_id=plan.owner_id,
                        metadata=dict(plan.metadata),
                    )
            for attempt_id, attempt in list(self._attempts.items()):
                if attempt.key_id == admitted.key_id and attempt.status not in {
                    AttemptStatus.INVALIDATED,
                    AttemptStatus.CANCELLED,
                }:
                    self._attempts[attempt_id] = ProofAttemptRecord(
                        attempt_id=attempt.attempt_id,
                        cache_key=attempt.cache_key,
                        status=AttemptStatus.INVALIDATED,
                        plan_id=attempt.plan_id,
                        node_id=attempt.node_id,
                        provider_id=attempt.provider_id,
                        started_at=attempt.started_at,
                        finished_at=record.invalidated_at,
                        outcome_digest=attempt.outcome_digest,
                        error=attempt.error or "invalidated",
                        metadata=dict(attempt.metadata),
                    )
            self._enforce_capacity()
        # Auto-record lineage edge from invalidation to key subject when given.
        if subject_id:
            self.put_lineage(
                ProofLineageEdge.build(
                    relation=LineageRelation.INVALIDATES,
                    parent_id=record.invalidation_id,
                    child_id=subject_id,
                    parent_kind=RecordKind.INVALIDATION,
                    child_kind=subject_kind or RecordKind.PLAN,
                    cache_key_id=admitted.key_id,
                    created_at=record.invalidated_at,
                )
            )
        return record

    def list_invalidations(
        self, *, key: CanonicalProofCacheKey | Mapping[str, Any] | None = None
    ) -> tuple[ProofInvalidationRecord, ...]:
        with self._lock:
            records = tuple(self._invalidations.values())
        if key is None:
            return records
        key_id = self._admit_key(key).key_id
        return tuple(item for item in records if item.key_id == key_id)

    # -- lineage ------------------------------------------------------------

    def put_lineage(
        self, edge: ProofLineageEdge | Mapping[str, Any]
    ) -> ProofLineageEdge:
        record = (
            edge
            if isinstance(edge, ProofLineageEdge)
            else ProofLineageEdge.from_dict(edge)
        )
        with self._lock:
            self._lineage[record.edge_id] = record
            self._stats["lineage"] = len(self._lineage)
            self._enforce_capacity()
        return record

    def lineage_of(
        self,
        record_id: str,
        *,
        direction: str = "both",
    ) -> tuple[ProofLineageEdge, ...]:
        record_id = _text(record_id, "record_id")
        direction = _text(direction, "direction").lower()
        if direction not in {"both", "parents", "children", "in", "out"}:
            raise ProofRepositoryAdmissionError(
                "direction must be one of both, parents, children, in, out"
            )
        with self._lock:
            edges = tuple(self._lineage.values())
        if direction in {"both"}:
            return tuple(
                edge
                for edge in edges
                if edge.parent_id == record_id or edge.child_id == record_id
            )
        if direction in {"parents", "in"}:
            return tuple(edge for edge in edges if edge.child_id == record_id)
        return tuple(edge for edge in edges if edge.parent_id == record_id)

    def list_lineage(
        self, *, key_id: str = ""
    ) -> tuple[ProofLineageEdge, ...]:
        with self._lock:
            edges = tuple(self._lineage.values())
        if not key_id:
            return edges
        key_id = _text(key_id, "key_id")
        return tuple(edge for edge in edges if edge.cache_key_id == key_id)

    # -- lookup -------------------------------------------------------------

    def lookup(
        self,
        key: CanonicalProofCacheKey | Mapping[str, Any],
        *,
        now: float | None = None,
        require_fresh: bool = True,
    ) -> ProofLookupResult:
        try:
            admitted = self._admit_key(key)
        except (ProofRepositoryAdmissionError, CanonicalCacheKeyError) as error:
            with self._lock:
                self._stats["lookups"] += 1
                self._stats["rejected"] += 1
            return ProofLookupResult(
                disposition=LookupDisposition.REJECTED,
                reason=str(error),
            )

        report = self.freshness(admitted, now=now)
        with self._lock:
            self._stats["lookups"] += 1
            plans = [
                item
                for item in self._plans.values()
                if item.key_id == admitted.key_id
            ]
            attempts = [
                item
                for item in self._attempts.values()
                if item.key_id == admitted.key_id
            ]
            evidence = [
                item
                for item in self._evidence.values()
                if item.key_id == admitted.key_id
            ]
            receipts = [
                item
                for item in self._receipts.values()
                if item.key_id == admitted.key_id
            ]
            counterexamples = [
                item
                for item in self._counterexamples.values()
                if item.key_id == admitted.key_id
            ]
            attestations = [
                item
                for item in self._attestations.values()
                if item.key_id == admitted.key_id
            ]
            invalidations = [
                item
                for item in self._invalidations.values()
                if item.key_id == admitted.key_id
            ]
            lineage = [
                item
                for item in self._lineage.values()
                if item.cache_key_id == admitted.key_id
            ]

        has_payload = bool(
            plans
            or attempts
            or evidence
            or receipts
            or counterexamples
            or attestations
        )

        # Environment equality is re-checked against stored plan/evidence keys.
        stored_keys = [
            item.cache_key
            for item in (
                *plans,
                *attempts,
                *evidence,
                *receipts,
                *counterexamples,
                *attestations,
            )
        ]
        for stored in stored_keys:
            try:
                admit_cache_hit(stored, admitted)
            except CrossEnvironmentHitError as error:
                with self._lock:
                    self._stats["rejected"] += 1
                return ProofLookupResult(
                    disposition=LookupDisposition.ENVIRONMENT_MISMATCH,
                    key=admitted,
                    freshness=FreshnessReport(
                        key_id=admitted.key_id,
                        is_fresh=False,
                        disposition=LookupDisposition.ENVIRONMENT_MISMATCH,
                        environment=admitted.environment,
                        reason=str(error),
                    ),
                    reason=str(error),
                )
            except CanonicalCacheKeyError:
                # Different key_id under same environment is a miss, not error.
                continue

        if not has_payload:
            with self._lock:
                self._stats["misses"] += 1
            return ProofLookupResult(
                disposition=LookupDisposition.MISS,
                key=admitted,
                freshness=report,
                invalidations=tuple(invalidations),
                lineage=tuple(lineage),
                reason=report.reason or "miss",
            )

        if report.disposition is LookupDisposition.INVALIDATED:
            with self._lock:
                self._stats["misses"] += 1
            return ProofLookupResult(
                disposition=LookupDisposition.INVALIDATED,
                key=admitted,
                freshness=report,
                plan=plans[0] if plans else None,
                attempts=tuple(attempts),
                evidence=tuple(evidence),
                receipts=tuple(receipts),
                counterexamples=tuple(counterexamples),
                attestations=tuple(attestations),
                invalidations=tuple(invalidations),
                lineage=tuple(lineage),
                reason=report.reason,
            )

        if require_fresh and report.disposition is LookupDisposition.STALE:
            with self._lock:
                self._stats["stale"] += 1
            return ProofLookupResult(
                disposition=LookupDisposition.STALE,
                key=admitted,
                freshness=report,
                plan=plans[0] if plans else None,
                attempts=tuple(attempts),
                evidence=tuple(evidence),
                receipts=tuple(receipts),
                counterexamples=tuple(counterexamples),
                attestations=tuple(attestations),
                invalidations=tuple(invalidations),
                lineage=tuple(lineage),
                reason=report.reason,
            )

        with self._lock:
            self._stats["hits"] += 1
        return ProofLookupResult(
            disposition=LookupDisposition.HIT,
            key=admitted,
            freshness=report,
            plan=plans[0] if plans else None,
            attempts=tuple(attempts),
            evidence=tuple(evidence),
            receipts=tuple(receipts),
            counterexamples=tuple(counterexamples),
            attestations=tuple(attestations),
            invalidations=tuple(invalidations),
            lineage=tuple(lineage),
            reason="hit",
        )

    def stats(self) -> Mapping[str, int]:
        with self._lock:
            return dict(self._stats)

    def clear(self) -> None:
        """Drop all process-local records (test helper)."""

        with self._lock:
            self._plans.clear()
            self._attempts.clear()
            self._evidence.clear()
            self._receipts.clear()
            self._counterexamples.clear()
            self._attestations.clear()
            self._invalidations.clear()
            self._lineage.clear()
            self._key_stored_at.clear()
            self._key_invalidated.clear()
            for name in self._stats:
                self._stats[name] = 0


def build_proof_repository(
    *,
    backend: str = "memory",
    ttl_seconds: float = DEFAULT_FRESHNESS_TTL_SECONDS,
    max_records: int = DEFAULT_MAX_RECORDS,
    clock: Callable[[], float] | None = None,
) -> ProofRepository:
    """Construct a proof repository backend.

    Currently admits the in-memory reference backend. DuckDB and remote
    backends remain implementations that must project into
    :class:`ProofRepository` without redefining LPC-G080 semantics.
    """

    name = _text(backend, "backend").lower()
    if name in {"memory", "in-memory", "inmemory", IN_MEMORY_BACKEND_ID}:
        return InMemoryProofRepository(
            ttl_seconds=ttl_seconds,
            max_records=max_records,
            clock=clock,
        )
    raise ProofRepositoryError(
        f"unsupported proof repository backend: {backend!r} "
        f"(DuckDB adapters implement ProofRepository@1 separately)"
    )


def repository_covers_acceptance(repo: ProofRepository) -> bool:
    """Return True when *repo* advertises the full LPC-081 capability set."""

    return (
        repo.interface == PROOF_REPOSITORY_INTERFACE
        and capabilities_cover_acceptance(repo.capabilities())
    )


__all__ = [
    "ATTESTATION_KIND",
    "AttestationKind",
    "AttemptStatus",
    "DEFAULT_FRESHNESS_TTL_SECONDS",
    "DEFAULT_MAX_RECORDS",
    "EvidenceDisposition",
    "FreshnessReport",
    "IN_MEMORY_BACKEND_ID",
    "InvalidationReason",
    "InMemoryProofRepository",
    "LineageRelation",
    "LookupDisposition",
    "PROOF_REPOSITORY_CAPABILITIES",
    "PROOF_REPOSITORY_CAPABILITY_SET",
    "PROOF_REPOSITORY_GENERATION",
    "PROOF_REPOSITORY_INTERFACE",
    "PROOF_REPOSITORY_MODULE_VERSION",
    "PROOF_REPOSITORY_SCHEMA",
    "PROOF_REPOSITORY_SCHEMA_VERSION",
    "PlanStatus",
    "ProofAttemptRecord",
    "ProofAttestationRecord",
    "ProofCounterexampleRecord",
    "ProofEvidenceRecord",
    "ProofInvalidationRecord",
    "ProofLineageEdge",
    "ProofLookupResult",
    "ProofPlanRecord",
    "ProofReceiptRecord",
    "ProofRepository",
    "ProofRepositoryAdmissionError",
    "ProofRepositoryCapabilityError",
    "ProofRepositoryError",
    "ProofRepositoryFreshnessError",
    "ProofRepositoryIntegrityError",
    "ProofRepositoryNotFoundError",
    "ReceiptKind",
    "RecordKind",
    "build_proof_repository",
    "capabilities_cover_acceptance",
    "repository_content_digest",
    "repository_covers_acceptance",
    "require_full_capabilities",
]

# Keep a stable alias for documentation / inventory.
ATTESTATION_KIND = AttestationKind
