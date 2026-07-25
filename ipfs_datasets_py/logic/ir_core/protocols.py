"""Solver-neutral backend, result-authority, and receipt protocols.

An ``unsat`` solver response can be useful evidence in a proof pipeline, but it
is not itself a theorem proof.  Likewise, a passing monitor, a ready evidence
gate, or an approving policy engine has authority only in its own result
family.  This module preserves those boundaries with closed enums, validated
result pairs, and an exact-authority check at proof-receipt issuance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from .claims import (
    ClaimValidationError,
    FrozenMap,
    IRClaim,
    stable_digest,
)


BACKEND_REQUEST_SCHEMA_VERSION: Final = "proof-backend-request/v1"
BACKEND_ATTEMPT_SCHEMA_VERSION: Final = "proof-backend-attempt/v1"
BOUNDED_RESULT_SCHEMA_VERSION: Final = "bounded-result/v1"
RESULT_AUTHORITY_SCHEMA_VERSION: Final = "result-authority/v1"
RESULT_RECEIPT_SCHEMA_VERSION: Final = "result-receipt/v1"
PROOF_RECEIPT_SCHEMA_VERSION: Final = "theorem-proof-receipt/v1"


class ProtocolValidationError(ValueError):
    """Raised when protocol records are invalid or inconsistently bound."""


class AuthorityMismatchError(ProtocolValidationError):
    """Raised when a result is used outside its exact authority family."""


class AuthorityKind(str, Enum):
    """Closed, intentionally non-hierarchical result-authority families."""

    THEOREM_PROOF = "theorem_proof"
    PROOF = "theorem_proof"
    SATISFIABILITY = "satisfiability"
    RUNTIME_MONITOR = "runtime_monitor"
    RUNTIME_MONITORING = "runtime_monitor"
    EVIDENCE_READINESS = "evidence_readiness"
    EVIDENCE_GATE = "evidence_readiness"
    POLICY_APPROVAL = "policy_approval"
    POLICY_DECISION = "policy_approval"


class QueryKind(str, Enum):
    """The semantic question a request asks a backend to answer."""

    THEOREM_PROOF = "theorem_proof"
    SATISFIABILITY = "satisfiability"
    RUNTIME_MONITOR = "runtime_monitor"
    EVIDENCE_READINESS = "evidence_readiness"
    POLICY_APPROVAL = "policy_approval"

    @property
    def authority_kind(self) -> AuthorityKind:
        return AuthorityKind(self.value)


class AttemptStatus(str, Enum):
    """Immutable attempt snapshot statuses."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"


class ResultStatus(str, Enum):
    """Conclusions whose meaning is scoped by ``AuthorityKind``."""

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


def _digest(value: Any, field_name: str) -> str:
    normalized = _text(value, field_name)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ProtocolValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_text(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ProtocolValidationError(f"{field_name} values must be unique")
    return normalized


def _enum(value: Any, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ProtocolValidationError(f"{field_name} must be one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class ExecutionBounds:
    """Finite resource limits that every request and result must carry."""

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

    def to_dict(self) -> dict[str, int]:
        return {
            "max_memory_bytes": self.max_memory_bytes,
            "max_output_bytes": self.max_output_bytes,
            "max_steps": self.max_steps,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    """Observed resource use for one bounded attempt."""

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
        exceeded = []
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


@dataclass(frozen=True, slots=True)
class BackendRequest:
    """A backend-neutral, content-addressed request for one obligation."""

    request_id: str
    claim_id: str
    claim_digest: str
    obligation_id: str
    assumption_ids: tuple[str, ...]
    logic_family: str
    query_kind: QueryKind
    bounds: ExecutionBounds = field(default_factory=ExecutionBounds)
    payload: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BACKEND_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _text(self.request_id, "request_id"))
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "claim_digest", _digest(self.claim_digest, "claim_digest"))
        object.__setattr__(self, "obligation_id", _text(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self, "assumption_ids", _unique(tuple(self.assumption_ids), "assumption_id")
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
    ) -> "BackendRequest":
        """Build a request whose bindings come only from the immutable claim."""

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
            claim_digest=claim.digest,
            obligation_id=obligation.obligation_id,
            assumption_ids=obligation.assumption_ids,
            logic_family=obligation.logic_family,
            query_kind=query_kind,
            bounds=bounds or ExecutionBounds(),
            payload=FrozenMap(payload),
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
            "logic_family": self.logic_family,
            "obligation_id": self.obligation_id,
            "payload": self.payload.to_dict(),
            "query_kind": self.query_kind.value,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class BackendAttempt:
    """An immutable record of one backend attempt, including failures."""

    attempt_id: str
    request_digest: str
    backend_id: str
    backend_version: str
    status: AttemptStatus
    bounds: ExecutionBounds
    usage: ResourceUsage = field(default_factory=ResourceUsage)
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
            "artifact_digests",
            tuple(_digest(value, "artifact_digest") for value in self.artifact_digests),
        )
        if len(self.artifact_digests) != len(set(self.artifact_digests)):
            raise ProtocolValidationError("artifact digests must be unique")
        object.__setattr__(
            self, "diagnostics", tuple(_text(value, "diagnostic") for value in self.diagnostics)
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != BACKEND_ATTEMPT_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported backend attempt schema version: {self.schema_version}"
            )
        exceeded = self.usage.exceeds(self.bounds)
        if exceeded and self.status not in {
            AttemptStatus.TIMED_OUT,
            AttemptStatus.FAILED,
            AttemptStatus.CANCELLED,
        }:
            raise ProtocolValidationError(
                "a successful/unavailable attempt cannot exceed bounds: "
                + ", ".join(exceeded)
            )

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
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "usage": self.usage.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ResultAuthority:
    """Explicit authority scope for a result.

    Authority kinds are exact labels, not an ordering.  In particular,
    satisfiability authority never implies theorem-proof authority.
    """

    kind: AuthorityKind
    issuer: str
    method: str
    scope_digest: str
    evidence_digests: tuple[str, ...] = ()
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
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != RESULT_AUTHORITY_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported result authority schema version: {self.schema_version}"
            )

    def permits(self, required: AuthorityKind) -> bool:
        """Return true only for the exact authority kind."""

        return self.kind is AuthorityKind(required)

    def require(self, required: AuthorityKind) -> None:
        required_kind = AuthorityKind(required)
        if not self.permits(required_kind):
            raise AuthorityMismatchError(
                f"{self.kind.value} authority cannot be used as {required_kind.value}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_digests": list(self.evidence_digests),
            "issuer": self.issuer,
            "kind": self.kind.value,
            "method": self.method,
            "schema_version": self.schema_version,
            "scope_digest": self.scope_digest,
        }


@dataclass(frozen=True, slots=True)
class BoundedResult:
    """A typed conclusion bound to a finite request and an exact attempt."""

    result_id: str
    request_digest: str
    attempt_digest: str
    claim_digest: str
    obligation_id: str
    authority: ResultAuthority
    status: ResultStatus
    bounds: ExecutionBounds
    usage: ResourceUsage
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
        object.__setattr__(self, "obligation_id", _text(self.obligation_id, "obligation_id"))
        if not isinstance(self.authority, ResultAuthority):
            raise ProtocolValidationError("authority must be a ResultAuthority value")
        object.__setattr__(self, "status", _enum(self.status, ResultStatus, "status"))
        allowed = _AUTHORITY_STATUSES[self.authority.kind]
        if self.status not in allowed:
            raise AuthorityMismatchError(
                f"{self.status.value} is not a valid {self.authority.kind.value} conclusion"
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
            self, "diagnostics", tuple(_text(value, "diagnostic") for value in self.diagnostics)
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
    ) -> "BoundedResult":
        if attempt.request_digest != request.digest:
            raise ProtocolValidationError("attempt is not bound to request")
        if attempt.bounds != request.bounds:
            raise ProtocolValidationError("attempt bounds differ from request bounds")
        if authority.scope_digest != request.digest:
            raise ProtocolValidationError("authority is not scoped to request")
        if authority.kind is not request.query_kind.authority_kind:
            raise AuthorityMismatchError(
                f"request asks for {request.query_kind.value}, "
                f"not {authority.kind.value}"
            )
        if attempt.status is not AttemptStatus.SUCCEEDED and status not in {
            ResultStatus.UNKNOWN,
            ResultStatus.ERROR,
        }:
            raise ProtocolValidationError(
                "a non-successful attempt can produce only unknown/error"
            )
        return cls(
            result_id=result_id,
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            claim_digest=request.claim_digest,
            obligation_id=request.obligation_id,
            authority=authority,
            status=status,
            bounds=request.bounds,
            usage=attempt.usage,
            payload=FrozenMap(payload),
            diagnostics=diagnostics,
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def is_theorem_proof(self) -> bool:
        return (
            self.authority.kind is AuthorityKind.THEOREM_PROOF
            and self.status is ResultStatus.PROVED
        )

    def require_theorem_proof(self) -> "BoundedResult":
        self.authority.require(AuthorityKind.THEOREM_PROOF)
        if self.status is not ResultStatus.PROVED:
            raise AuthorityMismatchError(
                f"{self.status.value} is not an affirmative theorem proof"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_digest": self.attempt_digest,
            "authority": self.authority.to_dict(),
            "bounds": self.bounds.to_dict(),
            "claim_digest": self.claim_digest,
            "diagnostics": list(self.diagnostics),
            "obligation_id": self.obligation_id,
            "payload": self.payload.to_dict(),
            "request_digest": self.request_digest,
            "result_id": self.result_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "usage": self.usage.to_dict(),
        }


def _verify_result_bindings(
    claim: IRClaim,
    request: BackendRequest,
    attempt: BackendAttempt,
    result: BoundedResult,
) -> None:
    try:
        obligation = claim.obligation(result.obligation_id)
    except KeyError as exc:
        raise ProtocolValidationError("result obligation is not present in claim") from exc
    expected = (
        request.claim_id == claim.claim_id,
        request.claim_digest == claim.digest,
        request.obligation_id == obligation.obligation_id,
        request.assumption_ids == obligation.assumption_ids,
        attempt.request_digest == request.digest,
        result.request_digest == request.digest,
        result.attempt_digest == attempt.digest,
        result.claim_digest == claim.digest,
        result.bounds == request.bounds == attempt.bounds,
    )
    if not all(expected):
        raise ProtocolValidationError(
            "claim, request, attempt, and result bindings are inconsistent"
        )


@dataclass(frozen=True, slots=True)
class ResultReceipt:
    """A content-addressed receipt for any typed result family."""

    receipt_id: str
    claim_id: str
    claim_digest: str
    obligation_id: str
    request_digest: str
    attempt_digest: str
    result_digest: str
    authority_kind: AuthorityKind
    issuer: str
    schema_version: str = RESULT_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "claim_digest", _digest(self.claim_digest, "claim_digest"))
        object.__setattr__(self, "obligation_id", _text(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "attempt_digest", _digest(self.attempt_digest, "attempt_digest")
        )
        object.__setattr__(
            self, "result_digest", _digest(self.result_digest, "result_digest")
        )
        object.__setattr__(
            self, "authority_kind", _enum(self.authority_kind, AuthorityKind, "authority_kind")
        )
        object.__setattr__(self, "issuer", _text(self.issuer, "issuer"))
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
            claim_digest=claim.digest,
            obligation_id=result.obligation_id,
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            result_digest=result.digest,
            authority_kind=result.authority.kind,
            issuer=issuer,
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_digest": self.attempt_digest,
            "authority_kind": self.authority_kind.value,
            "claim_digest": self.claim_digest,
            "claim_id": self.claim_id,
            "issuer": self.issuer,
            "obligation_id": self.obligation_id,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProofReceipt:
    """Receipt that can be issued only for an affirmative theorem proof."""

    receipt_id: str
    claim_id: str
    claim_digest: str
    obligation_id: str
    request_digest: str
    attempt_digest: str
    result_digest: str
    proof_authority: AuthorityKind
    verifier: str
    schema_version: str = PROOF_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "claim_digest", _digest(self.claim_digest, "claim_digest"))
        object.__setattr__(self, "obligation_id", _text(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self, "request_digest", _digest(self.request_digest, "request_digest")
        )
        object.__setattr__(
            self, "attempt_digest", _digest(self.attempt_digest, "attempt_digest")
        )
        object.__setattr__(
            self, "result_digest", _digest(self.result_digest, "result_digest")
        )
        object.__setattr__(
            self, "proof_authority", _enum(self.proof_authority, AuthorityKind, "proof_authority")
        )
        if self.proof_authority is not AuthorityKind.THEOREM_PROOF:
            raise AuthorityMismatchError(
                f"{self.proof_authority.value} cannot label a theorem proof receipt"
            )
        object.__setattr__(self, "verifier", _text(self.verifier, "verifier"))
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
        result.require_theorem_proof()
        return cls(
            receipt_id=receipt_id,
            claim_id=claim.claim_id,
            claim_digest=claim.digest,
            obligation_id=result.obligation_id,
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            result_digest=result.digest,
            proof_authority=AuthorityKind.THEOREM_PROOF,
            verifier=verifier,
        )

    from_result = issue

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_digest": self.attempt_digest,
            "claim_digest": self.claim_digest,
            "claim_id": self.claim_id,
            "obligation_id": self.obligation_id,
            "proof_authority": self.proof_authority.value,
            "receipt_id": self.receipt_id,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "verifier": self.verifier,
        }


@runtime_checkable
class ProofBackend(Protocol):
    """Structural interface implemented by side-effect-free backend adapters."""

    @property
    def backend_id(self) -> str:
        """Stable backend adapter identifier."""

    @property
    def backend_version(self) -> str:
        """Backend implementation or protocol version."""

    def supports(self, request: BackendRequest) -> bool:
        """Return whether an already-available backend supports the request."""

    def run(self, request: BackendRequest) -> tuple[BackendAttempt, BoundedResult]:
        """Execute one bounded request and return its attempt and typed result."""


# Terminology aliases used by downstream domain adapters.
BackendResult = BoundedResult
ProofAttempt = BackendAttempt
TheoremProofReceipt = ProofReceipt


__all__ = [
    "AttemptStatus",
    "AuthorityKind",
    "AuthorityMismatchError",
    "BackendAttempt",
    "BackendRequest",
    "BackendResult",
    "BoundedResult",
    "ExecutionBounds",
    "ProofAttempt",
    "ProofBackend",
    "ProofReceipt",
    "ProtocolValidationError",
    "QueryKind",
    "ResourceUsage",
    "ResultAuthority",
    "ResultReceipt",
    "ResultStatus",
    "TheoremProofReceipt",
    "BACKEND_ATTEMPT_SCHEMA_VERSION",
    "BACKEND_REQUEST_SCHEMA_VERSION",
    "BOUNDED_RESULT_SCHEMA_VERSION",
    "PROOF_RECEIPT_SCHEMA_VERSION",
    "RESULT_AUTHORITY_SCHEMA_VERSION",
    "RESULT_RECEIPT_SCHEMA_VERSION",
]
