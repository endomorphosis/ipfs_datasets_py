"""Solver-neutral backend contracts and non-interchangeable result authority.

The result classes in this module deliberately encode different questions:

* a theorem result reports formal proof or disproof;
* a satisfiability result reports whether a formula has a model;
* a monitor result describes only a bounded runtime trace;
* an evidence-gate result describes evidence readiness; and
* a policy decision records a policy outcome.

No positive outcome in one family can be promoted to theorem proof merely by
changing a status string.  Proof receipts require the theorem-specific result
type, exact theorem authority, an affirmative verdict, and consistent bindings
through the claim, request, backend attempt, and output digest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final, Protocol, runtime_checkable

from .claims import FrozenMap, IRClaim, stable_digest


BACKEND_CAPABILITIES_SCHEMA_VERSION: Final = "proof-backend-capabilities/v1"
BACKEND_REQUEST_SCHEMA_VERSION: Final = "proof-backend-request/v1"
BACKEND_ATTEMPT_SCHEMA_VERSION: Final = "proof-backend-attempt/v1"
BOUNDED_RESULT_SCHEMA_VERSION: Final = "bounded-result/v1"
RESULT_AUTHORITY_SCHEMA_VERSION: Final = "result-authority/v1"
RESULT_RECEIPT_SCHEMA_VERSION: Final = "result-receipt/v1"
PROOF_RECEIPT_SCHEMA_VERSION: Final = "theorem-proof-receipt/v1"


class ProtocolValidationError(ValueError):
    """Raised when a protocol record is malformed or inconsistently bound."""


class AuthorityMismatchError(ProtocolValidationError):
    """Raised when a result is used outside its exact authority family."""


class AuthorityKind(str, Enum):
    """Closed, intentionally non-hierarchical result-authority kinds."""

    THEOREM_PROOF = "theorem_proof"
    SATISFIABILITY = "satisfiability"
    RUNTIME_MONITOR = "runtime_monitor"
    EVIDENCE_READINESS = "evidence_readiness"
    POLICY_APPROVAL = "policy_approval"

    # Descriptive aliases for downstream adapters.
    PROOF = "theorem_proof"
    RUNTIME_MONITORING = "runtime_monitor"
    EVIDENCE_GATE = "evidence_readiness"
    POLICY_DECISION = "policy_approval"


class QueryKind(str, Enum):
    """The semantic question asked by a backend request."""

    THEOREM_PROOF = "theorem_proof"
    SATISFIABILITY = "satisfiability"
    RUNTIME_MONITOR = "runtime_monitor"
    EVIDENCE_READINESS = "evidence_readiness"
    POLICY_APPROVAL = "policy_approval"

    @property
    def authority_kind(self) -> AuthorityKind:
        return AuthorityKind(self.value)


class AttemptStatus(str, Enum):
    """Terminal states for an immutable backend-attempt record."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"


class ResultStatus(str, Enum):
    """Verdicts whose meaning is scoped by a result type and authority kind."""

    PROVED = "proved"
    DISPROVED = "disproved"
    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    MONITOR_SATISFIED = "monitor_satisfied"
    MONITOR_VIOLATED = "monitor_violated"
    READY = "ready"
    NOT_READY = "not_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    ERROR = "error"


_AUTHORITY_STATUSES: Final[dict[AuthorityKind, frozenset[ResultStatus]]] = {
    AuthorityKind.THEOREM_PROOF: frozenset(
        {ResultStatus.PROVED, ResultStatus.DISPROVED, ResultStatus.UNKNOWN, ResultStatus.ERROR}
    ),
    AuthorityKind.SATISFIABILITY: frozenset(
        {
            ResultStatus.SATISFIABLE,
            ResultStatus.UNSATISFIABLE,
            ResultStatus.UNKNOWN,
            ResultStatus.ERROR,
        }
    ),
    AuthorityKind.RUNTIME_MONITOR: frozenset(
        {
            ResultStatus.MONITOR_SATISFIED,
            ResultStatus.MONITOR_VIOLATED,
            ResultStatus.UNKNOWN,
            ResultStatus.ERROR,
        }
    ),
    AuthorityKind.EVIDENCE_READINESS: frozenset(
        {ResultStatus.READY, ResultStatus.NOT_READY, ResultStatus.UNKNOWN, ResultStatus.ERROR}
    ),
    AuthorityKind.POLICY_APPROVAL: frozenset(
        {ResultStatus.APPROVED, ResultStatus.REJECTED, ResultStatus.UNKNOWN, ResultStatus.ERROR}
    ),
}


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProtocolValidationError(f"{field_name} must be a non-empty trimmed string")
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value == "":
        return ""
    return _text(value, field_name)


def _digest(value: Any, field_name: str) -> str:
    normalized = _text(value, field_name)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ProtocolValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _unique(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise ProtocolValidationError(f"{field_name} must be a sequence of strings")
    try:
        normalized = tuple(_text(value, field_name) for value in values)
    except TypeError as exc:
        raise ProtocolValidationError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(normalized) != len(set(normalized)):
        raise ProtocolValidationError(f"{field_name} values must be unique")
    return normalized


def _enum(value: Any, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ProtocolValidationError(f"{field_name} must be one of: {allowed}") from exc


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolValidationError(f"{field_name} must be a mapping")
    return dict(value)


def _reject_unknown(
    value: dict[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProtocolValidationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _payload_digest(payload: FrozenMap) -> str:
    return stable_digest({"output": payload.to_dict()})


@dataclass(frozen=True, slots=True)
class ExecutionBounds:
    """Finite resource limits carried by every backend request."""

    timeout_ms: int = 30_000
    max_steps: int = 100_000
    max_memory_bytes: int = 512 * 1024 * 1024
    max_output_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in (
            "timeout_ms",
            "max_steps",
            "max_memory_bytes",
            "max_output_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ProtocolValidationError(f"{field_name} must be a positive integer")

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, int]:
        return {
            "max_memory_bytes": self.max_memory_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_steps": self.max_steps,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ExecutionBounds":
        payload = _mapping(value, "execution bounds")
        _reject_unknown(
            payload,
            frozenset(
                {"timeout_ms", "max_steps", "max_memory_bytes", "max_output_bytes"}
            ),
            "execution bounds",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    """Observed resource use for one backend attempt."""

    elapsed_ms: int = 0
    steps: int = 0
    peak_memory_bytes: int = 0
    output_bytes: int = 0

    def __post_init__(self) -> None:
        for field_name in ("elapsed_ms", "steps", "peak_memory_bytes", "output_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProtocolValidationError(f"{field_name} must be a non-negative integer")

    def exceeds(self, bounds: ExecutionBounds) -> tuple[str, ...]:
        exceeded: list[str] = []
        if self.elapsed_ms > bounds.timeout_ms:
            exceeded.append("timeout_ms")
        if self.steps > bounds.max_steps:
            exceeded.append("max_steps")
        if self.peak_memory_bytes > bounds.max_memory_bytes:
            exceeded.append("max_memory_bytes")
        if self.output_bytes > bounds.max_output_bytes:
            exceeded.append("max_output_bytes")
        return tuple(exceeded)

    def to_dict(self) -> dict[str, int]:
        return {
            "elapsed_ms": self.elapsed_ms,
            "output_bytes": self.output_bytes,
            "peak_memory_bytes": self.peak_memory_bytes,
            "steps": self.steps,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ResourceUsage":
        payload = _mapping(value, "resource usage")
        _reject_unknown(
            payload,
            frozenset({"elapsed_ms", "steps", "peak_memory_bytes", "output_bytes"}),
            "resource usage",
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Side-effect-free declaration of questions a backend can answer."""

    logic_families: tuple[str, ...]
    query_kinds: tuple[QueryKind, ...]
    deterministic: bool = False
    schema_version: str = BACKEND_CAPABILITIES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "logic_families", _unique(self.logic_families, "logic_family")
        )
        if not self.logic_families:
            raise ProtocolValidationError("logic_families must not be empty")
        try:
            query_kinds = tuple(_enum(item, QueryKind, "query_kind") for item in self.query_kinds)
        except TypeError as exc:
            raise ProtocolValidationError("query_kinds must be a sequence") from exc
        if not query_kinds or len(query_kinds) != len(set(query_kinds)):
            raise ProtocolValidationError("query_kinds must be non-empty and unique")
        object.__setattr__(self, "query_kinds", query_kinds)
        if not isinstance(self.deterministic, bool):
            raise ProtocolValidationError("deterministic must be a boolean")
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BACKEND_CAPABILITIES_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported backend capabilities schema version: {self.schema_version}"
            )

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return logic_family in self.logic_families and QueryKind(query_kind) in self.query_kinds

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic": self.deterministic,
            "logic_families": list(self.logic_families),
            "query_kinds": [item.value for item in self.query_kinds],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "BackendCapabilities":
        payload = _mapping(value, "backend capabilities")
        _reject_unknown(
            payload,
            frozenset(
                {"logic_families", "query_kinds", "deterministic", "schema_version"}
            ),
            "backend capabilities",
        )
        return cls(
            logic_families=tuple(payload.get("logic_families", ())),
            query_kinds=tuple(payload.get("query_kinds", ())),
            deterministic=payload.get("deterministic", False),
            schema_version=payload.get(
                "schema_version", BACKEND_CAPABILITIES_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class BackendRequest:
    """A content-addressed request for one immutable proof obligation."""

    request_id: str
    claim_id: str
    declaration_id: str
    claim_digest: str
    obligation_id: str
    obligation_digest: str
    assumption_ids: tuple[str, ...]
    logic_family: str
    query_kind: QueryKind
    bounds: ExecutionBounds = field(default_factory=ExecutionBounds)
    payload: FrozenMap = field(default_factory=FrozenMap)
    requested_backend_id: str = ""
    schema_version: str = BACKEND_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(
            self, "declaration_id", _text(self.declaration_id, "declaration_id")
        )
        object.__setattr__(self, "claim_digest", _digest(self.claim_digest, "claim_digest"))
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "obligation_digest",
            _digest(self.obligation_digest, "obligation_digest"),
        )
        object.__setattr__(
            self, "assumption_ids", _unique(self.assumption_ids, "assumption_id")
        )
        object.__setattr__(self, "logic_family", _text(self.logic_family, "logic_family"))
        object.__setattr__(self, "query_kind", _enum(self.query_kind, QueryKind, "query_kind"))
        if not isinstance(self.bounds, ExecutionBounds):
            raise ProtocolValidationError("bounds must be an ExecutionBounds value")
        object.__setattr__(
            self,
            "payload",
            self.payload if isinstance(self.payload, FrozenMap) else FrozenMap(self.payload),
        )
        object.__setattr__(
            self,
            "requested_backend_id",
            _optional_text(self.requested_backend_id, "requested_backend_id"),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BACKEND_REQUEST_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported backend request schema version: {self.schema_version}"
            )

    @classmethod
    def for_claim(
        cls,
        claim: IRClaim,
        obligation_id: str,
        *,
        request_id: str,
        query_kind: QueryKind = QueryKind.THEOREM_PROOF,
        bounds: ExecutionBounds | None = None,
        payload: FrozenMap | dict[str, Any] | None = None,
        requested_backend_id: str = "",
    ) -> "BackendRequest":
        if not isinstance(claim, IRClaim):
            raise ProtocolValidationError("claim must be an IRClaim")
        try:
            obligation = claim.obligation(obligation_id)
        except KeyError as exc:
            raise ProtocolValidationError(
                f"claim {claim.claim_id} has no obligation {obligation_id}"
            ) from exc
        return cls(
            request_id=request_id,
            claim_id=claim.claim_id,
            declaration_id=claim.declaration_id,
            claim_digest=claim.digest,
            obligation_id=obligation.obligation_id,
            obligation_digest=obligation.digest,
            assumption_ids=obligation.assumption_ids,
            logic_family=obligation.logic_family,
            query_kind=query_kind,
            bounds=bounds or ExecutionBounds(),
            payload=FrozenMap(payload),
            requested_backend_id=requested_backend_id,
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "bounds": self.bounds.to_dict(),
            "claim_digest": self.claim_digest,
            "claim_id": self.claim_id,
            "declaration_id": self.declaration_id,
            "logic_family": self.logic_family,
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "payload": self.payload.to_dict(),
            "query_kind": self.query_kind.value,
            "request_id": self.request_id,
            "requested_backend_id": self.requested_backend_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "BackendRequest":
        payload = _mapping(value, "backend request")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "request_id",
                    "claim_id",
                    "declaration_id",
                    "claim_digest",
                    "obligation_id",
                    "obligation_digest",
                    "assumption_ids",
                    "logic_family",
                    "query_kind",
                    "bounds",
                    "payload",
                    "requested_backend_id",
                    "schema_version",
                }
            ),
            "backend request",
        )
        return cls(
            request_id=payload.get("request_id", ""),
            claim_id=payload.get("claim_id", ""),
            declaration_id=payload.get("declaration_id", ""),
            claim_digest=payload.get("claim_digest", ""),
            obligation_id=payload.get("obligation_id", ""),
            obligation_digest=payload.get("obligation_digest", ""),
            assumption_ids=tuple(payload.get("assumption_ids", ())),
            logic_family=payload.get("logic_family", ""),
            query_kind=payload.get("query_kind", ""),
            bounds=ExecutionBounds.from_dict(payload.get("bounds", {})),
            payload=FrozenMap(payload.get("payload", {})),
            requested_backend_id=payload.get("requested_backend_id", ""),
            schema_version=payload.get("schema_version", BACKEND_REQUEST_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class BackendAttempt:
    """Complete immutable record of one backend invocation, including failure."""

    attempt_id: str
    request_digest: str
    backend_id: str
    backend_version: str
    status: AttemptStatus
    bounds: ExecutionBounds
    usage: ResourceUsage = field(default_factory=ResourceUsage)
    output_digest: str = ""
    artifact_digests: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    schema_version: str = BACKEND_ATTEMPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        object.__setattr__(self, "status", _enum(self.status, AttemptStatus, "status"))
        if not isinstance(self.bounds, ExecutionBounds):
            raise ProtocolValidationError("bounds must be an ExecutionBounds value")
        if not isinstance(self.usage, ResourceUsage):
            raise ProtocolValidationError("usage must be a ResourceUsage value")
        object.__setattr__(
            self,
            "output_digest",
            _digest(self.output_digest, "output_digest") if self.output_digest else "",
        )
        object.__setattr__(
            self,
            "artifact_digests",
            tuple(_digest(value, "artifact_digest") for value in self.artifact_digests),
        )
        if len(self.artifact_digests) != len(set(self.artifact_digests)):
            raise ProtocolValidationError("artifact digests must be unique")
        object.__setattr__(
            self, "diagnostics", _unique(self.diagnostics, "diagnostic")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BACKEND_ATTEMPT_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported backend attempt schema version: {self.schema_version}"
            )
        exceeded = self.usage.exceeds(self.bounds)
        if exceeded and self.status in {AttemptStatus.SUCCEEDED, AttemptStatus.UNAVAILABLE}:
            raise ProtocolValidationError(
                "a successful/unavailable attempt cannot exceed bounds: "
                + ", ".join(exceeded)
            )
        if self.status is AttemptStatus.SUCCEEDED and not self.output_digest:
            raise ProtocolValidationError("a successful attempt must bind an output_digest")

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digests": list(self.artifact_digests),
            "attempt_id": self.attempt_id,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "bounds": self.bounds.to_dict(),
            "diagnostics": list(self.diagnostics),
            "output_digest": self.output_digest,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "usage": self.usage.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "BackendAttempt":
        payload = _mapping(value, "backend attempt")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "attempt_id",
                    "request_digest",
                    "backend_id",
                    "backend_version",
                    "status",
                    "bounds",
                    "usage",
                    "output_digest",
                    "artifact_digests",
                    "diagnostics",
                    "schema_version",
                }
            ),
            "backend attempt",
        )
        return cls(
            attempt_id=payload.get("attempt_id", ""),
            request_digest=payload.get("request_digest", ""),
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            status=payload.get("status", ""),
            bounds=ExecutionBounds.from_dict(payload.get("bounds", {})),
            usage=ResourceUsage.from_dict(payload.get("usage", {})),
            output_digest=payload.get("output_digest", ""),
            artifact_digests=tuple(payload.get("artifact_digests", ())),
            diagnostics=tuple(payload.get("diagnostics", ())),
            schema_version=payload.get("schema_version", BACKEND_ATTEMPT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ResultAuthority:
    """Exact authority assigned by a configured verifier or decision process."""

    kind: AuthorityKind
    issuer: str
    method: str
    scope_digest: str
    evidence_digests: tuple[str, ...] = ()
    configuration_digest: str = ""
    schema_version: str = RESULT_AUTHORITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, AuthorityKind, "kind"))
        object.__setattr__(self, "issuer", _text(self.issuer, "issuer"))
        object.__setattr__(self, "method", _text(self.method, "method"))
        object.__setattr__(
            self, "scope_digest", _digest(self.scope_digest, "scope_digest")
        )
        object.__setattr__(
            self,
            "evidence_digests",
            tuple(_digest(value, "evidence_digest") for value in self.evidence_digests),
        )
        if len(self.evidence_digests) != len(set(self.evidence_digests)):
            raise ProtocolValidationError("evidence digests must be unique")
        object.__setattr__(
            self,
            "configuration_digest",
            (
                _digest(self.configuration_digest, "configuration_digest")
                if self.configuration_digest
                else ""
            ),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RESULT_AUTHORITY_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported result authority schema version: {self.schema_version}"
            )

    def permits(self, required: AuthorityKind) -> bool:
        """Return true only for the exact authority kind; there is no hierarchy."""

        return self.kind is AuthorityKind(required)

    def require(self, required: AuthorityKind) -> None:
        required_kind = AuthorityKind(required)
        if not self.permits(required_kind):
            raise AuthorityMismatchError(
                f"{self.kind.value} authority cannot be used as {required_kind.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_digest": self.configuration_digest,
            "evidence_digests": list(self.evidence_digests),
            "issuer": self.issuer,
            "kind": self.kind.value,
            "method": self.method,
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ResultAuthority":
        payload = _mapping(value, "result authority")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "kind",
                    "issuer",
                    "method",
                    "scope_digest",
                    "evidence_digests",
                    "configuration_digest",
                    "schema_version",
                }
            ),
            "result authority",
        )
        return cls(
            kind=payload.get("kind", ""),
            issuer=payload.get("issuer", ""),
            method=payload.get("method", ""),
            scope_digest=payload.get("scope_digest", ""),
            evidence_digests=tuple(payload.get("evidence_digests", ())),
            configuration_digest=payload.get("configuration_digest", ""),
            schema_version=payload.get("schema_version", RESULT_AUTHORITY_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class BoundedResult:
    """Base envelope binding a typed conclusion to one bounded attempt."""

    result_type: ClassVar[str] = "bounded_result"
    expected_authority: ClassVar[AuthorityKind | None] = None

    result_id: str
    request_digest: str
    attempt_digest: str
    claim_digest: str
    declaration_id: str
    obligation_id: str
    obligation_digest: str
    backend_id: str
    backend_version: str
    assumption_ids: tuple[str, ...]
    authority: ResultAuthority
    status: ResultStatus
    bounds: ExecutionBounds
    usage: ResourceUsage
    output_digest: str
    payload: FrozenMap = field(default_factory=FrozenMap)
    diagnostics: tuple[str, ...] = ()
    schema_version: str = BOUNDED_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", _text(self.result_id, "result_id"))
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "attempt_digest", _digest(self.attempt_digest, "attempt_digest")
        )
        object.__setattr__(self, "claim_digest", _digest(self.claim_digest, "claim_digest"))
        object.__setattr__(
            self, "declaration_id", _text(self.declaration_id, "declaration_id")
        )
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "obligation_digest",
            _digest(self.obligation_digest, "obligation_digest"),
        )
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "backend_version", _text(self.backend_version, "backend_version")
        )
        object.__setattr__(
            self, "assumption_ids", _unique(self.assumption_ids, "assumption_id")
        )
        if not isinstance(self.authority, ResultAuthority):
            raise ProtocolValidationError("authority must be a ResultAuthority value")
        object.__setattr__(self, "status", _enum(self.status, ResultStatus, "status"))
        allowed = _AUTHORITY_STATUSES[self.authority.kind]
        if self.status not in allowed:
            raise AuthorityMismatchError(
                f"{self.status.value} is not a valid {self.authority.kind.value} conclusion"
            )
        expected_authority = type(self).expected_authority
        if expected_authority is not None and self.authority.kind is not expected_authority:
            raise AuthorityMismatchError(
                f"{type(self).__name__} requires {expected_authority.value} authority, "
                f"not {self.authority.kind.value}"
            )
        if not isinstance(self.bounds, ExecutionBounds):
            raise ProtocolValidationError("bounds must be an ExecutionBounds value")
        if not isinstance(self.usage, ResourceUsage):
            raise ProtocolValidationError("usage must be a ResourceUsage value")
        exceeded = self.usage.exceeds(self.bounds)
        if exceeded:
            raise ProtocolValidationError(
                "bounded result usage exceeds its declared bounds: " + ", ".join(exceeded)
            )
        object.__setattr__(
            self, "output_digest", _digest(self.output_digest, "output_digest")
        )
        object.__setattr__(
            self,
            "payload",
            self.payload if isinstance(self.payload, FrozenMap) else FrozenMap(self.payload),
        )
        payload_size = len(
            json.dumps(
                self.payload.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        )
        if payload_size > self.bounds.max_output_bytes:
            raise ProtocolValidationError("result payload exceeds max_output_bytes")
        object.__setattr__(
            self, "diagnostics", _unique(self.diagnostics, "diagnostic")
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BOUNDED_RESULT_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported bounded result schema version: {self.schema_version}"
            )
        if self.authority.scope_digest != self.request_digest:
            raise ProtocolValidationError(
                "result authority scope_digest must equal request_digest"
            )

    @classmethod
    def for_attempt(
        cls,
        request: BackendRequest,
        attempt: BackendAttempt,
        *,
        result_id: str,
        authority: ResultAuthority,
        status: ResultStatus,
        payload: FrozenMap | dict[str, Any] | None = None,
        diagnostics: tuple[str, ...] = (),
        output_digest: str = "",
    ) -> "BoundedResult":
        if attempt.request_digest != request.digest:
            raise ProtocolValidationError("attempt is not bound to request")
        if attempt.bounds != request.bounds:
            raise ProtocolValidationError("attempt bounds differ from request bounds")
        if request.requested_backend_id and request.requested_backend_id != attempt.backend_id:
            raise ProtocolValidationError("attempt backend differs from requested backend")
        if authority.scope_digest != request.digest:
            raise ProtocolValidationError("authority is not scoped to request")
        if authority.kind is not request.query_kind.authority_kind:
            raise AuthorityMismatchError(
                f"request asks for {request.query_kind.value}, not {authority.kind.value}"
            )
        if attempt.status is not AttemptStatus.SUCCEEDED and ResultStatus(status) not in {
            ResultStatus.UNKNOWN,
            ResultStatus.ERROR,
        }:
            raise ProtocolValidationError(
                "a non-successful attempt can produce only unknown/error"
            )
        frozen_payload = payload if isinstance(payload, FrozenMap) else FrozenMap(payload)
        effective_output_digest = output_digest or attempt.output_digest
        if not effective_output_digest:
            effective_output_digest = _payload_digest(frozen_payload)
        if attempt.output_digest and effective_output_digest != attempt.output_digest:
            raise ProtocolValidationError(
                "result output_digest differs from attempt output_digest"
            )
        return cls(
            result_id=result_id,
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            claim_digest=request.claim_digest,
            declaration_id=request.declaration_id,
            obligation_id=request.obligation_id,
            obligation_digest=request.obligation_digest,
            backend_id=attempt.backend_id,
            backend_version=attempt.backend_version,
            assumption_ids=request.assumption_ids,
            authority=authority,
            status=status,
            bounds=request.bounds,
            usage=attempt.usage,
            output_digest=effective_output_digest,
            payload=frozen_payload,
            diagnostics=diagnostics,
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def is_theorem_proof(self) -> bool:
        return (
            isinstance(self, ProofResult)
            and self.authority.kind is AuthorityKind.THEOREM_PROOF
            and self.status is ResultStatus.PROVED
        )

    def require_theorem_proof(self) -> "ProofResult":
        if not isinstance(self, ProofResult):
            raise AuthorityMismatchError(
                f"{type(self).__name__} cannot be used as theorem proof"
            )
        self.authority.require(AuthorityKind.THEOREM_PROOF)
        if self.status is not ResultStatus.PROVED:
            raise AuthorityMismatchError(
                f"{self.status.value} is not an affirmative theorem proof"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attempt_digest": self.attempt_digest,
            "authority": self.authority.to_dict(),
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "bounds": self.bounds.to_dict(),
            "claim_digest": self.claim_digest,
            "declaration_id": self.declaration_id,
            "diagnostics": list(self.diagnostics),
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "output_digest": self.output_digest,
            "payload": self.payload.to_dict(),
            "request_digest": self.request_digest,
            "result_id": self.result_id,
            "result_type": type(self).result_type,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "usage": self.usage.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "BoundedResult":
        payload = _mapping(value, "bounded result")
        allowed = frozenset(
            {
                "result_id",
                "request_digest",
                "attempt_digest",
                "claim_digest",
                "declaration_id",
                "obligation_id",
                "obligation_digest",
                "backend_id",
                "backend_version",
                "assumption_ids",
                "authority",
                "status",
                "bounds",
                "usage",
                "output_digest",
                "payload",
                "diagnostics",
                "schema_version",
                "result_type",
            }
        )
        _reject_unknown(payload, allowed, "bounded result")
        result_type = payload.pop("result_type", cls.result_type)
        if cls is BoundedResult:
            result_class = _RESULT_CLASSES.get(result_type)
            if result_class is None:
                raise ProtocolValidationError(f"unsupported result_type: {result_type}")
        else:
            result_class = cls
            if result_type != cls.result_type:
                raise ProtocolValidationError(
                    f"{cls.__name__} cannot decode result_type {result_type}"
                )
        return result_class(
            result_id=payload.get("result_id", ""),
            request_digest=payload.get("request_digest", ""),
            attempt_digest=payload.get("attempt_digest", ""),
            claim_digest=payload.get("claim_digest", ""),
            declaration_id=payload.get("declaration_id", ""),
            obligation_id=payload.get("obligation_id", ""),
            obligation_digest=payload.get("obligation_digest", ""),
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            assumption_ids=tuple(payload.get("assumption_ids", ())),
            authority=ResultAuthority.from_dict(payload.get("authority", {})),
            status=payload.get("status", ""),
            bounds=ExecutionBounds.from_dict(payload.get("bounds", {})),
            usage=ResourceUsage.from_dict(payload.get("usage", {})),
            output_digest=payload.get("output_digest", ""),
            payload=FrozenMap(payload.get("payload", {})),
            diagnostics=tuple(payload.get("diagnostics", ())),
            schema_version=payload.get("schema_version", BOUNDED_RESULT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ProofResult(BoundedResult):
    """Formal proof/disproof result under explicit assumptions."""

    result_type: ClassVar[str] = "proof"
    expected_authority: ClassVar[AuthorityKind] = AuthorityKind.THEOREM_PROOF


@dataclass(frozen=True, slots=True)
class SatisfiabilityResult(BoundedResult):
    """Raw model-existence result; never theorem authority."""

    result_type: ClassVar[str] = "satisfiability"
    expected_authority: ClassVar[AuthorityKind] = AuthorityKind.SATISFIABILITY


@dataclass(frozen=True, slots=True)
class MonitorResult(BoundedResult):
    """Observation over one bounded runtime trace."""

    result_type: ClassVar[str] = "runtime_monitor"
    expected_authority: ClassVar[AuthorityKind] = AuthorityKind.RUNTIME_MONITOR


@dataclass(frozen=True, slots=True)
class EvidenceGateResult(BoundedResult):
    """Evidence presence/readiness outcome without proof authority."""

    result_type: ClassVar[str] = "evidence_gate"
    expected_authority: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE_READINESS


@dataclass(frozen=True, slots=True)
class PolicyDecision(BoundedResult):
    """Release/security policy outcome without proof authority."""

    result_type: ClassVar[str] = "policy_decision"
    expected_authority: ClassVar[AuthorityKind] = AuthorityKind.POLICY_APPROVAL


_RESULT_CLASSES: Final[dict[str, type[BoundedResult]]] = {
    BoundedResult.result_type: BoundedResult,
    ProofResult.result_type: ProofResult,
    SatisfiabilityResult.result_type: SatisfiabilityResult,
    MonitorResult.result_type: MonitorResult,
    EvidenceGateResult.result_type: EvidenceGateResult,
    PolicyDecision.result_type: PolicyDecision,
}


def _verify_result_bindings(
    claim: IRClaim,
    request: BackendRequest,
    attempt: BackendAttempt,
    result: BoundedResult,
) -> None:
    if not isinstance(claim, IRClaim):
        raise ProtocolValidationError("claim must be an IRClaim")
    if not isinstance(request, BackendRequest):
        raise ProtocolValidationError("request must be a BackendRequest")
    if not isinstance(attempt, BackendAttempt):
        raise ProtocolValidationError("attempt must be a BackendAttempt")
    if not isinstance(result, BoundedResult):
        raise ProtocolValidationError("result must be a BoundedResult")
    try:
        obligation = claim.obligation(result.obligation_id)
    except KeyError as exc:
        raise ProtocolValidationError("result obligation is not present in claim") from exc
    expected = (
        request.claim_id == claim.claim_id,
        request.declaration_id == claim.declaration_id,
        request.claim_digest == claim.digest,
        request.obligation_id == obligation.obligation_id,
        request.obligation_digest == obligation.digest,
        request.assumption_ids == obligation.assumption_ids,
        attempt.request_digest == request.digest,
        attempt.backend_id == result.backend_id,
        attempt.backend_version == result.backend_version,
        result.request_digest == request.digest,
        result.attempt_digest == attempt.digest,
        result.claim_digest == claim.digest,
        result.declaration_id == claim.declaration_id,
        result.obligation_digest == obligation.digest,
        result.assumption_ids == obligation.assumption_ids,
        result.authority.scope_digest == request.digest,
        result.authority.kind is request.query_kind.authority_kind,
        result.bounds == request.bounds == attempt.bounds,
        not attempt.output_digest or result.output_digest == attempt.output_digest,
        not request.requested_backend_id
        or attempt.backend_id == request.requested_backend_id,
        attempt.status is AttemptStatus.SUCCEEDED
        or result.status in {ResultStatus.UNKNOWN, ResultStatus.ERROR},
    )
    if not all(expected):
        raise ProtocolValidationError(
            "claim, request, attempt, and result bindings are inconsistent"
        )


@dataclass(frozen=True, slots=True)
class ResultReceipt:
    """Content-addressed receipt preserving a result's narrow authority."""

    receipt_id: str
    claim_id: str
    declaration_id: str
    claim_digest: str
    obligation_id: str
    obligation_digest: str
    request_digest: str
    attempt_digest: str
    result_digest: str
    result_type: str
    authority_kind: AuthorityKind
    status: ResultStatus
    backend_id: str
    backend_version: str
    assumption_ids: tuple[str, ...]
    bounds_digest: str
    output_digest: str
    issuer: str
    schema_version: str = RESULT_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "claim_id",
            "declaration_id",
            "obligation_id",
            "result_type",
            "backend_id",
            "backend_version",
            "issuer",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in (
            "claim_digest",
            "obligation_digest",
            "request_digest",
            "attempt_digest",
            "result_digest",
            "bounds_digest",
            "output_digest",
        ):
            object.__setattr__(
                self, field_name, _digest(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "authority_kind", _enum(self.authority_kind, AuthorityKind, "authority_kind")
        )
        object.__setattr__(self, "status", _enum(self.status, ResultStatus, "status"))
        object.__setattr__(
            self, "assumption_ids", _unique(self.assumption_ids, "assumption_id")
        )
        if self.result_type not in _RESULT_CLASSES:
            raise ProtocolValidationError(f"unsupported receipt result_type: {self.result_type}")
        if self.status not in _AUTHORITY_STATUSES[self.authority_kind]:
            raise AuthorityMismatchError(
                f"{self.status.value} is not valid for {self.authority_kind.value} authority"
            )
        expected_authority = _RESULT_CLASSES[self.result_type].expected_authority
        if (
            expected_authority is not None
            and self.authority_kind is not expected_authority
        ):
            raise AuthorityMismatchError(
                f"{self.result_type} receipt cannot carry {self.authority_kind.value} authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RESULT_RECEIPT_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported result receipt schema version: {self.schema_version}"
            )

    @classmethod
    def issue(
        cls,
        claim: IRClaim,
        request: BackendRequest,
        attempt: BackendAttempt,
        result: BoundedResult,
        *,
        receipt_id: str,
        issuer: str,
    ) -> "ResultReceipt":
        _verify_result_bindings(claim, request, attempt, result)
        return cls(
            receipt_id=receipt_id,
            claim_id=claim.claim_id,
            declaration_id=claim.declaration_id,
            claim_digest=claim.digest,
            obligation_id=result.obligation_id,
            obligation_digest=result.obligation_digest,
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            result_digest=result.digest,
            result_type=type(result).result_type,
            authority_kind=result.authority.kind,
            status=result.status,
            backend_id=result.backend_id,
            backend_version=result.backend_version,
            assumption_ids=result.assumption_ids,
            bounds_digest=result.bounds.digest,
            output_digest=result.output_digest,
            issuer=issuer,
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attempt_digest": self.attempt_digest,
            "authority_kind": self.authority_kind.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "bounds_digest": self.bounds_digest,
            "claim_digest": self.claim_digest,
            "claim_id": self.claim_id,
            "declaration_id": self.declaration_id,
            "issuer": self.issuer,
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "output_digest": self.output_digest,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "result_type": self.result_type,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ResultReceipt":
        payload = _mapping(value, "result receipt")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "receipt_id",
                    "claim_id",
                    "declaration_id",
                    "claim_digest",
                    "obligation_id",
                    "obligation_digest",
                    "request_digest",
                    "attempt_digest",
                    "result_digest",
                    "result_type",
                    "authority_kind",
                    "status",
                    "backend_id",
                    "backend_version",
                    "assumption_ids",
                    "bounds_digest",
                    "output_digest",
                    "issuer",
                    "schema_version",
                }
            ),
            "result receipt",
        )
        return cls(
            receipt_id=payload.get("receipt_id", ""),
            claim_id=payload.get("claim_id", ""),
            declaration_id=payload.get("declaration_id", ""),
            claim_digest=payload.get("claim_digest", ""),
            obligation_id=payload.get("obligation_id", ""),
            obligation_digest=payload.get("obligation_digest", ""),
            request_digest=payload.get("request_digest", ""),
            attempt_digest=payload.get("attempt_digest", ""),
            result_digest=payload.get("result_digest", ""),
            result_type=payload.get("result_type", ""),
            authority_kind=payload.get("authority_kind", ""),
            status=payload.get("status", ""),
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            assumption_ids=tuple(payload.get("assumption_ids", ())),
            bounds_digest=payload.get("bounds_digest", ""),
            output_digest=payload.get("output_digest", ""),
            issuer=payload.get("issuer", ""),
            schema_version=payload.get("schema_version", RESULT_RECEIPT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ProofReceipt:
    """Receipt issued only for an affirmative theorem-specific result."""

    receipt_id: str
    claim_id: str
    declaration_id: str
    claim_digest: str
    obligation_id: str
    obligation_digest: str
    request_digest: str
    attempt_digest: str
    result_digest: str
    result_type: str
    proof_authority: AuthorityKind
    status: ResultStatus
    backend_id: str
    backend_version: str
    assumption_ids: tuple[str, ...]
    bounds_digest: str
    output_digest: str
    verifier: str
    schema_version: str = PROOF_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "claim_id",
            "declaration_id",
            "obligation_id",
            "result_type",
            "backend_id",
            "backend_version",
            "verifier",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in (
            "claim_digest",
            "obligation_digest",
            "request_digest",
            "attempt_digest",
            "result_digest",
            "bounds_digest",
            "output_digest",
        ):
            object.__setattr__(
                self, field_name, _digest(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "proof_authority",
            _enum(self.proof_authority, AuthorityKind, "proof_authority"),
        )
        object.__setattr__(self, "status", _enum(self.status, ResultStatus, "status"))
        object.__setattr__(
            self, "assumption_ids", _unique(self.assumption_ids, "assumption_id")
        )
        if self.result_type != ProofResult.result_type:
            raise AuthorityMismatchError(
                f"{self.result_type} cannot label a theorem proof receipt"
            )
        if self.proof_authority is not AuthorityKind.THEOREM_PROOF:
            raise AuthorityMismatchError(
                f"{self.proof_authority.value} cannot label a theorem proof receipt"
            )
        if self.status is not ResultStatus.PROVED:
            raise AuthorityMismatchError(
                f"{self.status.value} cannot label an affirmative theorem proof receipt"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROOF_RECEIPT_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported proof receipt schema version: {self.schema_version}"
            )

    @classmethod
    def issue(
        cls,
        claim: IRClaim,
        request: BackendRequest,
        attempt: BackendAttempt,
        result: BoundedResult,
        *,
        receipt_id: str,
        verifier: str,
    ) -> "ProofReceipt":
        _verify_result_bindings(claim, request, attempt, result)
        proof_result = result.require_theorem_proof()
        return cls(
            receipt_id=receipt_id,
            claim_id=claim.claim_id,
            declaration_id=claim.declaration_id,
            claim_digest=claim.digest,
            obligation_id=proof_result.obligation_id,
            obligation_digest=proof_result.obligation_digest,
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            result_digest=proof_result.digest,
            result_type=type(proof_result).result_type,
            proof_authority=AuthorityKind.THEOREM_PROOF,
            status=proof_result.status,
            backend_id=proof_result.backend_id,
            backend_version=proof_result.backend_version,
            assumption_ids=proof_result.assumption_ids,
            bounds_digest=proof_result.bounds.digest,
            output_digest=proof_result.output_digest,
            verifier=verifier,
        )

    from_result = issue

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attempt_digest": self.attempt_digest,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "bounds_digest": self.bounds_digest,
            "claim_digest": self.claim_digest,
            "claim_id": self.claim_id,
            "declaration_id": self.declaration_id,
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "output_digest": self.output_digest,
            "proof_authority": self.proof_authority.value,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "result_type": self.result_type,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "verifier": self.verifier,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ProofReceipt":
        payload = _mapping(value, "proof receipt")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "receipt_id",
                    "claim_id",
                    "declaration_id",
                    "claim_digest",
                    "obligation_id",
                    "obligation_digest",
                    "request_digest",
                    "attempt_digest",
                    "result_digest",
                    "result_type",
                    "proof_authority",
                    "status",
                    "backend_id",
                    "backend_version",
                    "assumption_ids",
                    "bounds_digest",
                    "output_digest",
                    "verifier",
                    "schema_version",
                }
            ),
            "proof receipt",
        )
        return cls(
            receipt_id=payload.get("receipt_id", ""),
            claim_id=payload.get("claim_id", ""),
            declaration_id=payload.get("declaration_id", ""),
            claim_digest=payload.get("claim_digest", ""),
            obligation_id=payload.get("obligation_id", ""),
            obligation_digest=payload.get("obligation_digest", ""),
            request_digest=payload.get("request_digest", ""),
            attempt_digest=payload.get("attempt_digest", ""),
            result_digest=payload.get("result_digest", ""),
            result_type=payload.get("result_type", ""),
            proof_authority=payload.get("proof_authority", ""),
            status=payload.get("status", ""),
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            assumption_ids=tuple(payload.get("assumption_ids", ())),
            bounds_digest=payload.get("bounds_digest", ""),
            output_digest=payload.get("output_digest", ""),
            verifier=payload.get("verifier", ""),
            schema_version=payload.get("schema_version", PROOF_RECEIPT_SCHEMA_VERSION),
        )


@runtime_checkable
class ProofBackend(Protocol):
    """Structural interface for a bounded solver-neutral backend adapter."""

    @property
    def backend_id(self) -> str:
        """Stable adapter identifier."""

    @property
    def backend_version(self) -> str:
        """Adapter/backend implementation version."""

    @property
    def capabilities(self) -> BackendCapabilities:
        """Side-effect-free capability declaration."""

    def supports(self, request: BackendRequest) -> bool:
        """Return whether this already-available backend supports the request."""

    def run(self, request: BackendRequest) -> tuple[BackendAttempt, BoundedResult]:
        """Execute one bounded request and return a complete attempt and result."""


BackendResult = BoundedResult
ProofAttempt = BackendAttempt
Receipt = ResultReceipt
TheoremProofReceipt = ProofReceipt


__all__ = [
    "AttemptStatus",
    "AuthorityKind",
    "AuthorityMismatchError",
    "BackendAttempt",
    "BackendCapabilities",
    "BackendRequest",
    "BackendResult",
    "BoundedResult",
    "EvidenceGateResult",
    "ExecutionBounds",
    "MonitorResult",
    "PolicyDecision",
    "ProofAttempt",
    "ProofBackend",
    "ProofReceipt",
    "ProofResult",
    "ProtocolValidationError",
    "QueryKind",
    "Receipt",
    "ResourceUsage",
    "ResultAuthority",
    "ResultReceipt",
    "ResultStatus",
    "SatisfiabilityResult",
    "TheoremProofReceipt",
    "BACKEND_ATTEMPT_SCHEMA_VERSION",
    "BACKEND_CAPABILITIES_SCHEMA_VERSION",
    "BACKEND_REQUEST_SCHEMA_VERSION",
    "BOUNDED_RESULT_SCHEMA_VERSION",
    "PROOF_RECEIPT_SCHEMA_VERSION",
    "RESULT_AUTHORITY_SCHEMA_VERSION",
    "RESULT_RECEIPT_SCHEMA_VERSION",
]
