"""Deterministic property-specific prover portfolio planning.

``VerificationPortfolio@1`` plans staged solver, ATP, model-checker, monitor,
policy, protocol, hyperproperty, and kernel attempts by property kind and the
required assurance ceiling.  Planning is pure data transformation: importing
or calling this module never registers a provider, launches a tool, probes
the environment, or mutates shared state.

Authority invariants
--------------------
* Final authority is derived from retained attempt outcomes and is independent
  of attempt order.
* Candidate outcomes never become theorem (or other conclusive) authority
  without a successful reconstruction attempt.
* Conflicting conclusive authorities quarantine rather than pick a winner.
* Capability gaps are recorded explicitly and never silently skipped into
  success.
* Every plan is bounded by a resource policy and a required assurance ceiling.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.properties import PropertyKind

VERIFICATION_PORTFOLIO_INTERFACE: Final = "VerificationPortfolio@1"
VERIFICATION_PORTFOLIO_SCHEMA_VERSION: Final = "verification-portfolio/v1"
PORTFOLIO_OBLIGATION_SCHEMA_VERSION: Final = "verification-portfolio-obligation/v1"
PORTFOLIO_PLAN_SCHEMA_VERSION: Final = "verification-portfolio-plan/v1"
PORTFOLIO_ATTEMPT_SPEC_SCHEMA_VERSION: Final = "verification-portfolio-attempt-spec/v1"
PORTFOLIO_ATTEMPT_OUTCOME_SCHEMA_VERSION: Final = (
    "verification-portfolio-attempt-outcome/v1"
)
PORTFOLIO_SELECTION_SCHEMA_VERSION: Final = "verification-portfolio-selection/v1"
PORTFOLIO_CAPABILITY_SCHEMA_VERSION: Final = "verification-portfolio-capability/v1"
PORTFOLIO_RESOURCE_POLICY_SCHEMA_VERSION: Final = (
    "verification-portfolio-resource-policy/v1"
)
PORTFOLIO_POLICY_SCHEMA_VERSION: Final = "verification-portfolio-property-policy/v1"

DEFAULT_TIMEOUT_MS: Final = 60_000
DEFAULT_MAX_STEPS: Final = 100_000
DEFAULT_MAX_MEMORY_BYTES: Final = 512 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES: Final = 1024 * 1024
DEFAULT_MAX_PARALLEL: Final = 4
DEFAULT_MAX_ATTEMPTS: Final = 32


class PortfolioError(ValueError):
    """Raised when portfolio planning or selection fails closed."""


class AttemptFamily(StrEnum):
    """Closed vocabulary of portfolio attempt families (goal LFV-G043)."""

    SOLVER = "solver"
    ATP = "atp"
    MODEL_CHECKER = "model_checker"
    MONITOR = "monitor"
    POLICY = "policy"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    KERNEL = "kernel"
    ORCHESTRATOR = "orchestrator"
    ADVISOR = "advisor"


class PortfolioRole(StrEnum):
    """How an attempt contributes evidence; only some roles may be authoritative."""

    ADVISOR = "advisor"
    CANDIDATE = "candidate"
    AUTHORITY = "authority"
    RECONSTRUCTION = "reconstruction"
    ORCHESTRATOR = "orchestrator"

    @property
    def may_be_authoritative(self) -> bool:
        return self in (PortfolioRole.AUTHORITY, PortfolioRole.RECONSTRUCTION)


class CapabilityStatus(StrEnum):
    """Declared capability without installation or process probes."""

    DECLARED = "declared"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"


class AttemptDisposition(StrEnum):
    """Normalized attempt contribution after portfolio selection rules."""

    CONCLUSIVE_AUTHORITY = "conclusive_authority"
    CANDIDATE = "candidate"
    RECONSTRUCTED = "reconstructed"
    COUNTEREXAMPLE = "counterexample"
    GAP = "gap"
    QUARANTINED = "quarantined"
    NON_CONCLUSIVE = "non_conclusive"
    BLOCKED = "blocked"


class PortfolioVerdict(StrEnum):
    """Fail-closed portfolio disposition independent of attempt presentation order."""

    PROVED = "proved"
    DISPROVED = "disproved"
    INCONCLUSIVE = "inconclusive"
    QUARANTINED = "quarantined"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


# Property kinds that require kernel reconstruction for authoritative theorem claims.
_THEOREM_LIKE: Final[frozenset[PropertyKind]] = frozenset(
    {
        PropertyKind.THEOREM,
        PropertyKind.VALIDITY,
        PropertyKind.INVARIANT,
        PropertyKind.CONTRACT,
        PropertyKind.REFINEMENT,
        PropertyKind.TERMINATION,
    }
)

_ASSURANCE_RANK: Final[Mapping[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.AUTHORITATIVE: 4,
}

_FAMILY_DEFAULT_AUTHORITY: Final[Mapping[AttemptFamily, ResultAuthority]] = {
    AttemptFamily.SOLVER: ResultAuthority.SATISFIABILITY,
    AttemptFamily.ATP: ResultAuthority.CANDIDATE,
    AttemptFamily.MODEL_CHECKER: ResultAuthority.MODEL_CHECK,
    AttemptFamily.MONITOR: ResultAuthority.MONITOR,
    AttemptFamily.POLICY: ResultAuthority.AUTHORIZATION,
    AttemptFamily.PROTOCOL: ResultAuthority.PROTOCOL,
    AttemptFamily.HYPERPROPERTY: ResultAuthority.HYPERPROPERTY,
    AttemptFamily.KERNEL: ResultAuthority.RECONSTRUCTION,
    AttemptFamily.ORCHESTRATOR: ResultAuthority.CANDIDATE,
    AttemptFamily.ADVISOR: ResultAuthority.CANDIDATE,
}

_CONCLUSIVE_POSITIVE: Final[frozenset[ResultStatus]] = frozenset(
    {
        ResultStatus.PROVED,
        ResultStatus.UNSATISFIABLE,
        ResultStatus.SATISFIED,
        ResultStatus.AUTHORIZED,
        ResultStatus.SECURE,
        ResultStatus.RECONSTRUCTED,
        ResultStatus.ATTESTED,
    }
)

_CONCLUSIVE_NEGATIVE: Final[frozenset[ResultStatus]] = frozenset(
    {
        ResultStatus.DISPROVED,
        ResultStatus.SATISFIABLE,
        ResultStatus.VIOLATED,
        ResultStatus.DENIED,
        ResultStatus.ATTACK_FOUND,
        ResultStatus.RECONSTRUCTION_FAILED,
        ResultStatus.ATTESTATION_INVALID,
    }
)

_NON_CONCLUSIVE: Final[frozenset[ResultStatus]] = frozenset(
    {
        ResultStatus.UNKNOWN,
        ResultStatus.TIMEOUT,
        ResultStatus.UNAVAILABLE,
        ResultStatus.UNSUPPORTED,
        ResultStatus.MALFORMED,
        ResultStatus.ERROR,
        ResultStatus.CANDIDATE,
    }
)


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise PortfolioError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _enum(value: object, enum_type: type[StrEnum] | type, field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise PortfolioError(f"{field_name} must be one of {choices}") from error


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioError(f"{field_name} must be a mapping")
    return dict(value)


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PortfolioError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PortfolioError(f"{field_name} must be a non-negative integer")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PortfolioError(f"{field_name} must be a positive integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise PortfolioError(f"{field_name} must be a boolean")
    return value


def _unique_text(values: Sequence[str] | object, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise PortfolioError(f"{field_name} must be a sequence of strings")
    result = tuple(_text(item, f"{field_name} item") for item in values)
    if len(result) != len(set(result)):
        raise PortfolioError(f"{field_name} must not contain duplicates")
    return result


def assurance_satisfies(
    achieved: EvidenceAuthority | str, required: EvidenceAuthority | str
) -> bool:
    """Return whether ``achieved`` meets or exceeds ``required`` (rank order)."""

    left = _enum(achieved, EvidenceAuthority, "achieved assurance")
    right = _enum(required, EvidenceAuthority, "required assurance")
    return _ASSURANCE_RANK[left] >= _ASSURANCE_RANK[right]


def family_default_authority(family: AttemptFamily | str) -> ResultAuthority:
    """Return the default result authority for an attempt family."""

    return _FAMILY_DEFAULT_AUTHORITY[
        _enum(family, AttemptFamily, "attempt family")
    ]


# ---------------------------------------------------------------------------
# Resource and capability declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioResourcePolicy:
    """Resource and concurrency bounds attached to every portfolio plan."""

    bounds: ExecutionBounds = field(
        default_factory=lambda: ExecutionBounds(
            timeout_ms=DEFAULT_TIMEOUT_MS,
            max_steps=DEFAULT_MAX_STEPS,
            max_memory_bytes=DEFAULT_MAX_MEMORY_BYTES,
            max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
        )
    )
    max_parallel: int = DEFAULT_MAX_PARALLEL
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    cancel_on_counterexample: bool = True
    schema_version: str = PORTFOLIO_RESOURCE_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.bounds, ExecutionBounds):
            raise PortfolioError("bounds must be an ExecutionBounds value")
        object.__setattr__(
            self, "max_parallel", _positive_int(self.max_parallel, "max_parallel")
        )
        if self.max_parallel > 64:
            raise PortfolioError("max_parallel must be at most 64")
        object.__setattr__(
            self, "max_attempts", _positive_int(self.max_attempts, "max_attempts")
        )
        object.__setattr__(
            self,
            "cancel_on_counterexample",
            _boolean(self.cancel_on_counterexample, "cancel_on_counterexample"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_RESOURCE_POLICY_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported resource policy schema: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": self.bounds.to_dict(),
            "cancel_on_counterexample": self.cancel_on_counterexample,
            "max_attempts": self.max_attempts,
            "max_parallel": self.max_parallel,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioResourcePolicy":
        payload = _mapping(value, "resource policy")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "bounds",
                    "cancel_on_counterexample",
                    "max_attempts",
                    "max_parallel",
                    "schema_version",
                }
            ),
            "resource policy",
        )
        return cls(
            bounds=ExecutionBounds.from_dict(payload.get("bounds", {})),
            max_parallel=payload.get("max_parallel", DEFAULT_MAX_PARALLEL),
            max_attempts=payload.get("max_attempts", DEFAULT_MAX_ATTEMPTS),
            cancel_on_counterexample=payload.get("cancel_on_counterexample", True),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_RESOURCE_POLICY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioCapability:
    """Side-effect-free capability declaration for one backend/prover lane."""

    backend_id: str
    family: AttemptFamily
    status: CapabilityStatus = CapabilityStatus.DECLARED
    result_authority: ResultAuthority | None = None
    authority_capabilities: tuple[str, ...] = ()
    reconstruction_capable: bool = False
    version: str = ""
    diagnostics: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PORTFOLIO_CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "family", _enum(self.family, AttemptFamily, "family")
        )
        object.__setattr__(
            self, "status", _enum(self.status, CapabilityStatus, "status")
        )
        authority = (
            family_default_authority(self.family)
            if self.result_authority is None
            else _enum(self.result_authority, ResultAuthority, "result_authority")
        )
        object.__setattr__(self, "result_authority", authority)
        object.__setattr__(
            self,
            "authority_capabilities",
            _unique_text(self.authority_capabilities, "authority_capabilities"),
        )
        object.__setattr__(
            self,
            "reconstruction_capable",
            _boolean(self.reconstruction_capable, "reconstruction_capable"),
        )
        object.__setattr__(
            self, "version", _text(self.version, "version", optional=True)
        )
        object.__setattr__(
            self, "diagnostics", _unique_text(self.diagnostics, "diagnostics")
        )
        try:
            object.__setattr__(
                self,
                "metadata",
                self.metadata
                if isinstance(self.metadata, FrozenMap)
                else FrozenMap(self.metadata),
            )
        except (TypeError, ValueError) as error:
            raise PortfolioError(
                "metadata must be an immutable JSON mapping"
            ) from error
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_CAPABILITY_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported capability schema: {self.schema_version}"
            )
        if (
            self.family is AttemptFamily.KERNEL
            and self.reconstruction_capable is False
            and self.status is CapabilityStatus.AVAILABLE
        ):
            # Kernels that are available but not reconstruction-capable cannot
            # grant theorem authority; callers must still declare that fact.
            pass

    @property
    def runnable(self) -> bool:
        return self.status is CapabilityStatus.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_capabilities": list(self.authority_capabilities),
            "backend_id": self.backend_id,
            "diagnostics": list(self.diagnostics),
            "family": self.family.value,
            "metadata": self.metadata.to_dict(),
            "reconstruction_capable": self.reconstruction_capable,
            "result_authority": self.result_authority.value,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioCapability":
        payload = _mapping(value, "capability")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "authority_capabilities",
                    "backend_id",
                    "diagnostics",
                    "family",
                    "metadata",
                    "reconstruction_capable",
                    "result_authority",
                    "schema_version",
                    "status",
                    "version",
                }
            ),
            "capability",
        )
        return cls(
            backend_id=payload.get("backend_id", ""),
            family=payload.get("family", ""),
            status=payload.get("status", CapabilityStatus.DECLARED),
            result_authority=payload.get("result_authority"),
            authority_capabilities=tuple(
                payload.get("authority_capabilities") or ()
            ),
            reconstruction_capable=payload.get("reconstruction_capable", False),
            version=payload.get("version", ""),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            metadata=FrozenMap(payload.get("metadata") or {}),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_CAPABILITY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class CapabilityGap:
    """Explicit missing or blocked capability for a planned attempt."""

    backend_id: str
    family: AttemptFamily
    reason: str
    status: CapabilityStatus = CapabilityStatus.UNAVAILABLE
    required_for_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "family", _enum(self.family, AttemptFamily, "family")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self, "status", _enum(self.status, CapabilityStatus, "status")
        )
        object.__setattr__(
            self,
            "required_for_authority",
            _boolean(self.required_for_authority, "required_for_authority"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "family": self.family.value,
            "reason": self.reason,
            "required_for_authority": self.required_for_authority,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityGap":
        payload = _mapping(value, "capability gap")
        return cls(
            backend_id=payload.get("backend_id", ""),
            family=payload.get("family", ""),
            reason=payload.get("reason", ""),
            status=payload.get("status", CapabilityStatus.UNAVAILABLE),
            required_for_authority=payload.get("required_for_authority", False),
        )


# ---------------------------------------------------------------------------
# Obligation, attempt specs, policies, plans
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioObligation:
    """Property obligation independent of prover input languages."""

    obligation_id: str
    property_kind: PropertyKind
    statement: str
    required_assurance: EvidenceAuthority = EvidenceAuthority.BOUNDED
    required_authority: ResultAuthority | None = None
    assumption_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PORTFOLIO_OBLIGATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "property_kind",
            _enum(self.property_kind, PropertyKind, "property_kind"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "required_assurance",
            _enum(self.required_assurance, EvidenceAuthority, "required_assurance"),
        )
        if self.required_authority is None:
            object.__setattr__(
                self,
                "required_authority",
                default_required_authority(self.property_kind),
            )
        else:
            object.__setattr__(
                self,
                "required_authority",
                _enum(
                    self.required_authority, ResultAuthority, "required_authority"
                ),
            )
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_text(self.assumption_ids, "assumption_ids"),
        )
        try:
            object.__setattr__(
                self,
                "metadata",
                self.metadata
                if isinstance(self.metadata, FrozenMap)
                else FrozenMap(self.metadata),
            )
        except (TypeError, ValueError) as error:
            raise PortfolioError(
                "metadata must be an immutable JSON mapping"
            ) from error
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_OBLIGATION_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported obligation schema: {self.schema_version}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "metadata": self.metadata.to_dict(),
            "obligation_id": self.obligation_id,
            "property_kind": self.property_kind.value,
            "required_assurance": self.required_assurance.value,
            "required_authority": self.required_authority.value,
            "schema_version": self.schema_version,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioObligation":
        payload = _mapping(value, "obligation")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "assumption_ids",
                    "metadata",
                    "obligation_id",
                    "property_kind",
                    "required_assurance",
                    "required_authority",
                    "schema_version",
                    "statement",
                }
            ),
            "obligation",
        )
        return cls(
            obligation_id=payload.get("obligation_id", ""),
            property_kind=payload.get("property_kind", ""),
            statement=payload.get("statement", ""),
            required_assurance=payload.get(
                "required_assurance", EvidenceAuthority.BOUNDED
            ),
            required_authority=payload.get("required_authority"),
            assumption_ids=tuple(payload.get("assumption_ids") or ()),
            metadata=FrozenMap(payload.get("metadata") or {}),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_OBLIGATION_SCHEMA_VERSION
            ),
        )


def default_required_authority(property_kind: PropertyKind | str) -> ResultAuthority:
    """Map a property kind onto the default conclusive result authority."""

    kind = _enum(property_kind, PropertyKind, "property_kind")
    mapping: dict[PropertyKind, ResultAuthority] = {
        PropertyKind.SATISFIABILITY: ResultAuthority.SATISFIABILITY,
        PropertyKind.VALIDITY: ResultAuthority.THEOREM,
        PropertyKind.THEOREM: ResultAuthority.THEOREM,
        PropertyKind.INVARIANT: ResultAuthority.THEOREM,
        PropertyKind.CONTRACT: ResultAuthority.THEOREM,
        PropertyKind.REFINEMENT: ResultAuthority.THEOREM,
        PropertyKind.TERMINATION: ResultAuthority.THEOREM,
        PropertyKind.SAFETY: ResultAuthority.MODEL_CHECK,
        PropertyKind.LIVENESS: ResultAuthority.MODEL_CHECK,
        PropertyKind.REACHABILITY: ResultAuthority.MODEL_CHECK,
        PropertyKind.TRACE_CONFORMANCE: ResultAuthority.MONITOR,
        PropertyKind.AUTHORIZATION: ResultAuthority.AUTHORIZATION,
        PropertyKind.AUTHENTICATION: ResultAuthority.AUTHORIZATION,
        PropertyKind.SECRECY: ResultAuthority.PROTOCOL,
        PropertyKind.HYPERPROPERTY: ResultAuthority.HYPERPROPERTY,
        PropertyKind.NONINTERFERENCE: ResultAuthority.HYPERPROPERTY,
        PropertyKind.HEAP_SAFETY: ResultAuthority.THEOREM,
        PropertyKind.DATA_RACE_FREEDOM: ResultAuthority.MODEL_CHECK,
    }
    return mapping.get(kind, ResultAuthority.THEOREM)


@dataclass(frozen=True, slots=True)
class PortfolioAttemptSpec:
    """One planned attempt inside a staged portfolio."""

    attempt_id: str
    backend_id: str
    family: AttemptFamily
    role: PortfolioRole
    stage: int = 0
    result_authority: ResultAuthority | None = None
    requires_candidate: bool = False
    authority_capability: str = ""
    runnable: bool = True
    gap_reason: str = ""
    schema_version: str = PORTFOLIO_ATTEMPT_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "family", _enum(self.family, AttemptFamily, "family")
        )
        object.__setattr__(self, "role", _enum(self.role, PortfolioRole, "role"))
        object.__setattr__(self, "stage", _non_negative_int(self.stage, "stage"))
        authority = (
            family_default_authority(self.family)
            if self.result_authority is None
            else _enum(self.result_authority, ResultAuthority, "result_authority")
        )
        object.__setattr__(self, "result_authority", authority)
        object.__setattr__(
            self,
            "requires_candidate",
            _boolean(self.requires_candidate, "requires_candidate"),
        )
        object.__setattr__(
            self,
            "authority_capability",
            _text(self.authority_capability, "authority_capability", optional=True),
        )
        object.__setattr__(self, "runnable", _boolean(self.runnable, "runnable"))
        object.__setattr__(
            self, "gap_reason", _text(self.gap_reason, "gap_reason", optional=True)
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_ATTEMPT_SPEC_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported attempt spec schema: {self.schema_version}"
            )
        if self.role is PortfolioRole.ADVISOR and self.authority_capability:
            raise PortfolioError("advisor attempts cannot declare authority capability")
        if (
            self.role is PortfolioRole.CANDIDATE
            and self.result_authority
            not in (ResultAuthority.CANDIDATE, ResultAuthority.SATISFIABILITY)
        ):
            # Candidates may still emit sat/unsat raw solver status; selection
            # demotes them unless reconstruction succeeds.
            pass
        if self.requires_candidate and self.role is PortfolioRole.ADVISOR:
            raise PortfolioError("advisor attempts cannot require a candidate")
        if (
            self.role is PortfolioRole.RECONSTRUCTION
            and self.family is not AttemptFamily.KERNEL
        ):
            raise PortfolioError("reconstruction role requires the kernel family")
        if not self.runnable and not self.gap_reason:
            raise PortfolioError("non-runnable attempts require a gap_reason")

    @property
    def authoritative_when_conclusive(self) -> bool:
        return self.role.may_be_authoritative and bool(self.authority_capability)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "authority_capability": self.authority_capability,
            "backend_id": self.backend_id,
            "family": self.family.value,
            "gap_reason": self.gap_reason,
            "requires_candidate": self.requires_candidate,
            "result_authority": self.result_authority.value,
            "role": self.role.value,
            "runnable": self.runnable,
            "schema_version": self.schema_version,
            "stage": self.stage,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioAttemptSpec":
        payload = _mapping(value, "attempt spec")
        return cls(
            attempt_id=payload.get("attempt_id", ""),
            backend_id=payload.get("backend_id", ""),
            family=payload.get("family", ""),
            role=payload.get("role", ""),
            stage=payload.get("stage", 0),
            result_authority=payload.get("result_authority"),
            requires_candidate=payload.get("requires_candidate", False),
            authority_capability=payload.get("authority_capability", ""),
            runnable=payload.get("runnable", True),
            gap_reason=payload.get("gap_reason", ""),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_ATTEMPT_SPEC_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PropertyPortfolioPolicy:
    """Reviewed staged routing for one property kind."""

    property_kind: PropertyKind
    attempts: tuple[PortfolioAttemptSpec, ...]
    policy_id: str = ""
    resource_policy: PortfolioResourcePolicy = field(
        default_factory=PortfolioResourcePolicy
    )
    fail_on_disagreement: bool = True
    require_reconstruction_for_candidates: bool = True
    minimum_assurance: EvidenceAuthority = EvidenceAuthority.BOUNDED
    schema_version: str = PORTFOLIO_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = _enum(self.property_kind, PropertyKind, "property_kind")
        object.__setattr__(self, "property_kind", kind)
        attempts = tuple(self.attempts)
        if not attempts or any(
            not isinstance(item, PortfolioAttemptSpec) for item in attempts
        ):
            raise PortfolioError("policy attempts must contain PortfolioAttemptSpec values")
        ids = [item.attempt_id for item in attempts]
        if len(ids) != len(set(ids)):
            raise PortfolioError("policy attempt_id values must be unique")
        backends = [item.backend_id for item in attempts]
        if len(backends) != len(set(backends)):
            raise PortfolioError("a policy cannot route a backend twice")
        object.__setattr__(self, "attempts", attempts)
        policy_id = self.policy_id or f"verification-portfolio:{kind.value}@1"
        object.__setattr__(self, "policy_id", _text(policy_id, "policy_id"))
        if not isinstance(self.resource_policy, PortfolioResourcePolicy):
            raise PortfolioError("resource_policy must be a PortfolioResourcePolicy")
        object.__setattr__(
            self,
            "fail_on_disagreement",
            _boolean(self.fail_on_disagreement, "fail_on_disagreement"),
        )
        object.__setattr__(
            self,
            "require_reconstruction_for_candidates",
            _boolean(
                self.require_reconstruction_for_candidates,
                "require_reconstruction_for_candidates",
            ),
        )
        object.__setattr__(
            self,
            "minimum_assurance",
            _enum(self.minimum_assurance, EvidenceAuthority, "minimum_assurance"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_POLICY_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported property policy schema: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": [item.to_dict() for item in self.attempts],
            "fail_on_disagreement": self.fail_on_disagreement,
            "minimum_assurance": self.minimum_assurance.value,
            "policy_id": self.policy_id,
            "property_kind": self.property_kind.value,
            "require_reconstruction_for_candidates": (
                self.require_reconstruction_for_candidates
            ),
            "resource_policy": self.resource_policy.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PropertyPortfolioPolicy":
        payload = _mapping(value, "property policy")
        attempts = payload.get("attempts") or ()
        if isinstance(attempts, (str, bytes, bytearray)) or not isinstance(
            attempts, Sequence
        ):
            raise PortfolioError("attempts must be a sequence")
        return cls(
            property_kind=payload.get("property_kind", ""),
            attempts=tuple(PortfolioAttemptSpec.from_dict(item) for item in attempts),
            policy_id=payload.get("policy_id", ""),
            resource_policy=PortfolioResourcePolicy.from_dict(
                payload.get("resource_policy") or {}
            ),
            fail_on_disagreement=payload.get("fail_on_disagreement", True),
            require_reconstruction_for_candidates=payload.get(
                "require_reconstruction_for_candidates", True
            ),
            minimum_assurance=payload.get(
                "minimum_assurance", EvidenceAuthority.BOUNDED
            ),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_POLICY_SCHEMA_VERSION
            ),
        )


def _spec(
    backend_id: str,
    family: AttemptFamily,
    role: PortfolioRole,
    *,
    stage: int = 0,
    result_authority: ResultAuthority | None = None,
    requires_candidate: bool = False,
    authority_capability: str = "",
) -> PortfolioAttemptSpec:
    return PortfolioAttemptSpec(
        attempt_id=f"attempt:{backend_id}",
        backend_id=backend_id,
        family=family,
        role=role,
        stage=stage,
        result_authority=result_authority,
        requires_candidate=requires_candidate,
        authority_capability=authority_capability,
    )


def _kernel_reconstruction_specs(stage: int = 2) -> tuple[PortfolioAttemptSpec, ...]:
    return (
        _spec(
            "lean",
            AttemptFamily.KERNEL,
            PortfolioRole.RECONSTRUCTION,
            stage=stage,
            result_authority=ResultAuthority.RECONSTRUCTION,
            requires_candidate=True,
            authority_capability="lean_kernel_check",
        ),
        _spec(
            "rocq",
            AttemptFamily.KERNEL,
            PortfolioRole.RECONSTRUCTION,
            stage=stage,
            result_authority=ResultAuthority.RECONSTRUCTION,
            requires_candidate=True,
            authority_capability="rocq_kernel_check",
        ),
        _spec(
            "isabelle",
            AttemptFamily.KERNEL,
            PortfolioRole.RECONSTRUCTION,
            stage=stage,
            result_authority=ResultAuthority.RECONSTRUCTION,
            requires_candidate=True,
            authority_capability="isabelle_kernel_check",
        ),
    )


def _policy(
    kind: PropertyKind,
    attempts: Sequence[PortfolioAttemptSpec],
    *,
    minimum_assurance: EvidenceAuthority = EvidenceAuthority.BOUNDED,
) -> PropertyPortfolioPolicy:
    return PropertyPortfolioPolicy(
        property_kind=kind,
        attempts=tuple(attempts),
        minimum_assurance=minimum_assurance,
    )


DEFAULT_PROPERTY_POLICIES: Mapping[PropertyKind, PropertyPortfolioPolicy] = {
    PropertyKind.SATISFIABILITY: _policy(
        PropertyKind.SATISFIABILITY,
        (
            _spec(
                "z3",
                AttemptFamily.SOLVER,
                PortfolioRole.AUTHORITY,
                authority_capability="finite_constraint_satisfiability",
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
            _spec(
                "cvc5",
                AttemptFamily.SOLVER,
                PortfolioRole.AUTHORITY,
                authority_capability="finite_constraint_satisfiability",
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
        ),
    ),
    PropertyKind.VALIDITY: _policy(
        PropertyKind.VALIDITY,
        (
            _spec(
                "z3",
                AttemptFamily.SOLVER,
                PortfolioRole.CANDIDATE,
                stage=0,
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
            _spec(
                "cvc5",
                AttemptFamily.SOLVER,
                PortfolioRole.CANDIDATE,
                stage=0,
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
            *_kernel_reconstruction_specs(stage=1),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
    PropertyKind.THEOREM: _policy(
        PropertyKind.THEOREM,
        (
            _spec(
                "hammer",
                AttemptFamily.ORCHESTRATOR,
                PortfolioRole.ORCHESTRATOR,
                stage=0,
            ),
            _spec(
                "vampire",
                AttemptFamily.ATP,
                PortfolioRole.CANDIDATE,
                stage=1,
            ),
            _spec(
                "eprover",
                AttemptFamily.ATP,
                PortfolioRole.CANDIDATE,
                stage=1,
            ),
            _spec(
                "z3",
                AttemptFamily.SOLVER,
                PortfolioRole.CANDIDATE,
                stage=1,
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
            *_kernel_reconstruction_specs(stage=2),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
    PropertyKind.INVARIANT: _policy(
        PropertyKind.INVARIANT,
        (
            _spec(
                "hammer",
                AttemptFamily.ORCHESTRATOR,
                PortfolioRole.ORCHESTRATOR,
                stage=0,
            ),
            _spec(
                "vampire",
                AttemptFamily.ATP,
                PortfolioRole.CANDIDATE,
                stage=1,
            ),
            *_kernel_reconstruction_specs(stage=2),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
    PropertyKind.CONTRACT: _policy(
        PropertyKind.CONTRACT,
        (
            _spec(
                "z3",
                AttemptFamily.SOLVER,
                PortfolioRole.CANDIDATE,
                stage=0,
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
            _spec(
                "cvc5",
                AttemptFamily.SOLVER,
                PortfolioRole.CANDIDATE,
                stage=0,
                result_authority=ResultAuthority.SATISFIABILITY,
            ),
            *_kernel_reconstruction_specs(stage=1),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
    PropertyKind.SAFETY: _policy(
        PropertyKind.SAFETY,
        (
            _spec(
                "tla_tlc",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
            _spec(
                "apalache",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
        ),
    ),
    PropertyKind.LIVENESS: _policy(
        PropertyKind.LIVENESS,
        (
            _spec(
                "tla_tlc",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
            _spec(
                "apalache",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
        ),
    ),
    PropertyKind.REACHABILITY: _policy(
        PropertyKind.REACHABILITY,
        (
            _spec(
                "tla_tlc",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
            _spec(
                "apalache",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
        ),
    ),
    PropertyKind.DATA_RACE_FREEDOM: _policy(
        PropertyKind.DATA_RACE_FREEDOM,
        (
            _spec(
                "tla_tlc",
                AttemptFamily.MODEL_CHECKER,
                PortfolioRole.AUTHORITY,
                authority_capability="bounded_state_machine",
                result_authority=ResultAuthority.MODEL_CHECK,
            ),
        ),
    ),
    PropertyKind.TRACE_CONFORMANCE: _policy(
        PropertyKind.TRACE_CONFORMANCE,
        (
            _spec(
                "runtime_mtl",
                AttemptFamily.MONITOR,
                PortfolioRole.AUTHORITY,
                authority_capability="runtime_trace_monitoring",
                result_authority=ResultAuthority.MONITOR,
            ),
        ),
    ),
    PropertyKind.AUTHORIZATION: _policy(
        PropertyKind.AUTHORIZATION,
        (
            _spec(
                "datalog_secpal",
                AttemptFamily.POLICY,
                PortfolioRole.AUTHORITY,
                authority_capability="authorization_policy",
                result_authority=ResultAuthority.AUTHORIZATION,
            ),
        ),
    ),
    PropertyKind.AUTHENTICATION: _policy(
        PropertyKind.AUTHENTICATION,
        (
            _spec(
                "datalog_secpal",
                AttemptFamily.POLICY,
                PortfolioRole.AUTHORITY,
                authority_capability="authorization_policy",
                result_authority=ResultAuthority.AUTHORIZATION,
            ),
        ),
    ),
    PropertyKind.SECRECY: _policy(
        PropertyKind.SECRECY,
        (
            _spec(
                "tamarin",
                AttemptFamily.PROTOCOL,
                PortfolioRole.AUTHORITY,
                authority_capability="protocol_trace_property",
                result_authority=ResultAuthority.PROTOCOL,
            ),
            _spec(
                "proverif",
                AttemptFamily.PROTOCOL,
                PortfolioRole.AUTHORITY,
                authority_capability="protocol_reachability",
                result_authority=ResultAuthority.PROTOCOL,
            ),
        ),
    ),
    PropertyKind.HYPERPROPERTY: _policy(
        PropertyKind.HYPERPROPERTY,
        (
            _spec(
                "hyperltl_autohyper_mchyper",
                AttemptFamily.HYPERPROPERTY,
                PortfolioRole.AUTHORITY,
                authority_capability="hyperproperty_model_check",
                result_authority=ResultAuthority.HYPERPROPERTY,
            ),
        ),
    ),
    PropertyKind.NONINTERFERENCE: _policy(
        PropertyKind.NONINTERFERENCE,
        (
            _spec(
                "hyperltl_autohyper_mchyper",
                AttemptFamily.HYPERPROPERTY,
                PortfolioRole.AUTHORITY,
                authority_capability="hyperproperty_model_check",
                result_authority=ResultAuthority.HYPERPROPERTY,
            ),
        ),
    ),
    PropertyKind.HEAP_SAFETY: _policy(
        PropertyKind.HEAP_SAFETY,
        (
            _spec(
                "leanstral",
                AttemptFamily.ADVISOR,
                PortfolioRole.ADVISOR,
                stage=0,
            ),
            _spec(
                "vampire",
                AttemptFamily.ATP,
                PortfolioRole.CANDIDATE,
                stage=1,
            ),
            *_kernel_reconstruction_specs(stage=2),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
    PropertyKind.REFINEMENT: _policy(
        PropertyKind.REFINEMENT,
        (
            _spec(
                "hammer",
                AttemptFamily.ORCHESTRATOR,
                PortfolioRole.ORCHESTRATOR,
                stage=0,
            ),
            _spec(
                "vampire",
                AttemptFamily.ATP,
                PortfolioRole.CANDIDATE,
                stage=1,
            ),
            *_kernel_reconstruction_specs(stage=2),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
    PropertyKind.TERMINATION: _policy(
        PropertyKind.TERMINATION,
        (
            _spec(
                "hammer",
                AttemptFamily.ORCHESTRATOR,
                PortfolioRole.ORCHESTRATOR,
                stage=0,
            ),
            _spec(
                "vampire",
                AttemptFamily.ATP,
                PortfolioRole.CANDIDATE,
                stage=1,
            ),
            *_kernel_reconstruction_specs(stage=2),
        ),
        minimum_assurance=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    ),
}


@dataclass(frozen=True, slots=True)
class PortfolioPlan:
    """Deterministic staged plan for one obligation."""

    obligation: PortfolioObligation
    policy_id: str
    attempts: tuple[PortfolioAttemptSpec, ...]
    resource_policy: PortfolioResourcePolicy
    required_assurance: EvidenceAuthority
    required_authority: ResultAuthority
    capability_gaps: tuple[CapabilityGap, ...] = ()
    stages: tuple[int, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PORTFOLIO_PLAN_SCHEMA_VERSION
    interface: ClassVar[str] = VERIFICATION_PORTFOLIO_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.obligation, PortfolioObligation):
            raise PortfolioError("obligation must be a PortfolioObligation")
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        attempts = tuple(self.attempts)
        if not attempts or any(
            not isinstance(item, PortfolioAttemptSpec) for item in attempts
        ):
            raise PortfolioError("plan attempts must contain PortfolioAttemptSpec values")
        object.__setattr__(self, "attempts", attempts)
        if not isinstance(self.resource_policy, PortfolioResourcePolicy):
            raise PortfolioError("resource_policy must be a PortfolioResourcePolicy")
        if len(attempts) > self.resource_policy.max_attempts:
            raise PortfolioError(
                f"plan has {len(attempts)} attempts but resource policy allows "
                f"at most {self.resource_policy.max_attempts}"
            )
        object.__setattr__(
            self,
            "required_assurance",
            _enum(self.required_assurance, EvidenceAuthority, "required_assurance"),
        )
        object.__setattr__(
            self,
            "required_authority",
            _enum(self.required_authority, ResultAuthority, "required_authority"),
        )
        gaps = tuple(self.capability_gaps)
        if any(not isinstance(item, CapabilityGap) for item in gaps):
            raise PortfolioError("capability_gaps must contain CapabilityGap values")
        # Deterministic gap order by (backend_id, family, reason).
        object.__setattr__(
            self,
            "capability_gaps",
            tuple(
                sorted(
                    gaps,
                    key=lambda item: (
                        item.backend_id,
                        item.family.value,
                        item.reason,
                    ),
                )
            ),
        )
        stages = tuple(sorted({item.stage for item in attempts}))
        object.__setattr__(self, "stages", stages)
        try:
            object.__setattr__(
                self,
                "metadata",
                self.metadata
                if isinstance(self.metadata, FrozenMap)
                else FrozenMap(self.metadata),
            )
        except (TypeError, ValueError) as error:
            raise PortfolioError(
                "metadata must be an immutable JSON mapping"
            ) from error
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_PLAN_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported plan schema: {self.schema_version}"
            )

    @property
    def plan_id(self) -> str:
        return self.digest

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    @property
    def backend_ids(self) -> tuple[str, ...]:
        return tuple(item.backend_id for item in self.attempts)

    @property
    def runnable_attempts(self) -> tuple[PortfolioAttemptSpec, ...]:
        return tuple(item for item in self.attempts if item.runnable)

    @property
    def reconstruction_attempts(self) -> tuple[PortfolioAttemptSpec, ...]:
        return tuple(
            item
            for item in self.attempts
            if item.role is PortfolioRole.RECONSTRUCTION
        )

    @property
    def candidate_attempts(self) -> tuple[PortfolioAttemptSpec, ...]:
        return tuple(
            item for item in self.attempts if item.role is PortfolioRole.CANDIDATE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": [item.to_dict() for item in self.attempts],
            "capability_gaps": [item.to_dict() for item in self.capability_gaps],
            "interface": self.interface,
            "metadata": self.metadata.to_dict(),
            "obligation": self.obligation.to_dict(),
            "policy_id": self.policy_id,
            "required_assurance": self.required_assurance.value,
            "required_authority": self.required_authority.value,
            "resource_policy": self.resource_policy.to_dict(),
            "schema_version": self.schema_version,
            "stages": list(self.stages),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioPlan":
        payload = _mapping(value, "portfolio plan")
        attempts = payload.get("attempts") or ()
        gaps = payload.get("capability_gaps") or ()
        if isinstance(attempts, (str, bytes, bytearray)) or not isinstance(
            attempts, Sequence
        ):
            raise PortfolioError("attempts must be a sequence")
        if isinstance(gaps, (str, bytes, bytearray)) or not isinstance(gaps, Sequence):
            raise PortfolioError("capability_gaps must be a sequence")
        obligation = payload.get("obligation")
        if not isinstance(obligation, Mapping):
            raise PortfolioError("obligation must be a mapping")
        return cls(
            obligation=PortfolioObligation.from_dict(obligation),
            policy_id=payload.get("policy_id", ""),
            attempts=tuple(PortfolioAttemptSpec.from_dict(item) for item in attempts),
            resource_policy=PortfolioResourcePolicy.from_dict(
                payload.get("resource_policy") or {}
            ),
            required_assurance=payload.get(
                "required_assurance", EvidenceAuthority.BOUNDED
            ),
            required_authority=payload.get(
                "required_authority", ResultAuthority.THEOREM
            ),
            capability_gaps=tuple(CapabilityGap.from_dict(item) for item in gaps),
            metadata=FrozenMap(payload.get("metadata") or {}),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_PLAN_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Outcome recording and order-independent selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioAttemptOutcome:
    """Recorded outcome of one planned attempt (no process execution here)."""

    attempt_id: str
    backend_id: str
    status: ResultStatus
    authority: ResultAuthority
    role: PortfolioRole
    stage: int = 0
    conclusive_counterexample: bool = False
    achieved_assurance: EvidenceAuthority = EvidenceAuthority.NONE
    detail: str = ""
    witness: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PORTFOLIO_ATTEMPT_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self, "status", _enum(self.status, ResultStatus, "status")
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, ResultAuthority, "authority")
        )
        object.__setattr__(self, "role", _enum(self.role, PortfolioRole, "role"))
        object.__setattr__(self, "stage", _non_negative_int(self.stage, "stage"))
        object.__setattr__(
            self,
            "conclusive_counterexample",
            _boolean(self.conclusive_counterexample, "conclusive_counterexample"),
        )
        object.__setattr__(
            self,
            "achieved_assurance",
            _enum(
                self.achieved_assurance, EvidenceAuthority, "achieved_assurance"
            ),
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "detail", optional=True)
        )
        try:
            object.__setattr__(
                self,
                "witness",
                self.witness
                if isinstance(self.witness, FrozenMap)
                else FrozenMap(self.witness),
            )
        except (TypeError, ValueError) as error:
            raise PortfolioError(
                "witness must be an immutable JSON mapping"
            ) from error
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_ATTEMPT_OUTCOME_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported attempt outcome schema: {self.schema_version}"
            )
        if self.conclusive_counterexample and self.status not in _CONCLUSIVE_NEGATIVE:
            raise PortfolioError(
                "conclusive_counterexample requires a negative conclusive status"
            )

    @property
    def is_positive(self) -> bool:
        return self.status in _CONCLUSIVE_POSITIVE

    @property
    def is_negative(self) -> bool:
        return self.status in _CONCLUSIVE_NEGATIVE

    @property
    def is_non_conclusive(self) -> bool:
        return self.status in _NON_CONCLUSIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "achieved_assurance": self.achieved_assurance.value,
            "attempt_id": self.attempt_id,
            "authority": self.authority.value,
            "backend_id": self.backend_id,
            "conclusive_counterexample": self.conclusive_counterexample,
            "detail": self.detail,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "stage": self.stage,
            "status": self.status.value,
            "witness": self.witness.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioAttemptOutcome":
        payload = _mapping(value, "attempt outcome")
        return cls(
            attempt_id=payload.get("attempt_id", ""),
            backend_id=payload.get("backend_id", ""),
            status=payload.get("status", ""),
            authority=payload.get("authority", ""),
            role=payload.get("role", ""),
            stage=payload.get("stage", 0),
            conclusive_counterexample=payload.get("conclusive_counterexample", False),
            achieved_assurance=payload.get(
                "achieved_assurance", EvidenceAuthority.NONE
            ),
            detail=payload.get("detail", ""),
            witness=FrozenMap(payload.get("witness") or {}),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_ATTEMPT_OUTCOME_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioSelection:
    """Order-independent final disposition over retained attempt outcomes."""

    plan_id: str
    verdict: PortfolioVerdict
    achieved_assurance: EvidenceAuthority
    authority_attempt_ids: tuple[str, ...] = ()
    candidate_attempt_ids: tuple[str, ...] = ()
    reconstruction_attempt_ids: tuple[str, ...] = ()
    counterexample_attempt_id: str = ""
    quarantined_attempt_ids: tuple[str, ...] = ()
    dispositions: tuple[tuple[str, AttemptDisposition], ...] = ()
    disagreement: bool = False
    reason: str = ""
    schema_version: str = PORTFOLIO_SELECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _text(self.plan_id, "plan_id"))
        object.__setattr__(
            self, "verdict", _enum(self.verdict, PortfolioVerdict, "verdict")
        )
        object.__setattr__(
            self,
            "achieved_assurance",
            _enum(
                self.achieved_assurance, EvidenceAuthority, "achieved_assurance"
            ),
        )
        object.__setattr__(
            self,
            "authority_attempt_ids",
            tuple(sorted(_unique_text(self.authority_attempt_ids, "authority_attempt_ids"))),
        )
        object.__setattr__(
            self,
            "candidate_attempt_ids",
            tuple(sorted(_unique_text(self.candidate_attempt_ids, "candidate_attempt_ids"))),
        )
        object.__setattr__(
            self,
            "reconstruction_attempt_ids",
            tuple(
                sorted(
                    _unique_text(
                        self.reconstruction_attempt_ids, "reconstruction_attempt_ids"
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "counterexample_attempt_id",
            _text(
                self.counterexample_attempt_id,
                "counterexample_attempt_id",
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "quarantined_attempt_ids",
            tuple(
                sorted(
                    _unique_text(
                        self.quarantined_attempt_ids, "quarantined_attempt_ids"
                    )
                )
            ),
        )
        dispositions = tuple(self.dispositions)
        normalized: list[tuple[str, AttemptDisposition]] = []
        for item in dispositions:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise PortfolioError(
                    "dispositions must be (attempt_id, AttemptDisposition) pairs"
                )
            attempt_id = _text(item[0], "disposition attempt_id")
            disposition = _enum(item[1], AttemptDisposition, "disposition")
            normalized.append((attempt_id, disposition))
        object.__setattr__(
            self,
            "dispositions",
            tuple(sorted(normalized, key=lambda pair: pair[0])),
        )
        object.__setattr__(
            self, "disagreement", _boolean(self.disagreement, "disagreement")
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PORTFOLIO_SELECTION_SCHEMA_VERSION:
            raise PortfolioError(
                f"unsupported selection schema: {self.schema_version}"
            )
        if self.verdict is PortfolioVerdict.PROVED and not self.authority_attempt_ids:
            raise PortfolioError("proved selection requires authority_attempt_ids")
        if (
            self.verdict is PortfolioVerdict.DISPROVED
            and not self.counterexample_attempt_id
        ):
            raise PortfolioError(
                "disproved selection requires counterexample_attempt_id"
            )
        if self.disagreement and self.verdict is not PortfolioVerdict.QUARANTINED:
            raise PortfolioError("disagreement must quarantine")

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "achieved_assurance": self.achieved_assurance.value,
            "authority_attempt_ids": list(self.authority_attempt_ids),
            "candidate_attempt_ids": list(self.candidate_attempt_ids),
            "counterexample_attempt_id": self.counterexample_attempt_id,
            "disagreement": self.disagreement,
            "dispositions": [
                {"attempt_id": attempt_id, "disposition": disposition.value}
                for attempt_id, disposition in self.dispositions
            ],
            "plan_id": self.plan_id,
            "quarantined_attempt_ids": list(self.quarantined_attempt_ids),
            "reason": self.reason,
            "reconstruction_attempt_ids": list(self.reconstruction_attempt_ids),
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PortfolioSelection":
        payload = _mapping(value, "portfolio selection")
        raw_dispositions = payload.get("dispositions") or ()
        dispositions: list[tuple[str, AttemptDisposition]] = []
        if isinstance(raw_dispositions, (str, bytes, bytearray)) or not isinstance(
            raw_dispositions, Sequence
        ):
            raise PortfolioError("dispositions must be a sequence")
        for item in raw_dispositions:
            if isinstance(item, Mapping):
                dispositions.append(
                    (
                        item.get("attempt_id", ""),
                        item.get("disposition", ""),
                    )
                )
            elif (
                isinstance(item, Sequence)
                and not isinstance(item, (str, bytes, bytearray))
                and len(item) == 2
            ):
                dispositions.append((item[0], item[1]))
            else:
                raise PortfolioError("invalid disposition entry")
        return cls(
            plan_id=payload.get("plan_id", ""),
            verdict=payload.get("verdict", ""),
            achieved_assurance=payload.get(
                "achieved_assurance", EvidenceAuthority.NONE
            ),
            authority_attempt_ids=tuple(payload.get("authority_attempt_ids") or ()),
            candidate_attempt_ids=tuple(payload.get("candidate_attempt_ids") or ()),
            reconstruction_attempt_ids=tuple(
                payload.get("reconstruction_attempt_ids") or ()
            ),
            counterexample_attempt_id=payload.get("counterexample_attempt_id", ""),
            quarantined_attempt_ids=tuple(
                payload.get("quarantined_attempt_ids") or ()
            ),
            dispositions=tuple(dispositions),
            disagreement=payload.get("disagreement", False),
            reason=payload.get("reason", ""),
            schema_version=payload.get(
                "schema_version", PORTFOLIO_SELECTION_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class VerificationPortfolio:
    """Side-effect-free planner and order-independent authority selector.

    Interface: :data:`VERIFICATION_PORTFOLIO_INTERFACE` (``VerificationPortfolio@1``).
    """

    interface: ClassVar[str] = VERIFICATION_PORTFOLIO_INTERFACE
    schema_version: ClassVar[str] = VERIFICATION_PORTFOLIO_SCHEMA_VERSION

    def __init__(
        self,
        policies: Mapping[PropertyKind | str, PropertyPortfolioPolicy] | None = None,
        *,
        default_resource_policy: PortfolioResourcePolicy | None = None,
    ) -> None:
        source = policies if policies is not None else DEFAULT_PROPERTY_POLICIES
        normalized: dict[PropertyKind, PropertyPortfolioPolicy] = {}
        for key, policy in source.items():
            kind = _enum(key, PropertyKind, "policy key")
            if (
                not isinstance(policy, PropertyPortfolioPolicy)
                or policy.property_kind is not kind
            ):
                raise PortfolioError("policy key and property_kind must agree")
            normalized[kind] = policy
        if policies is None:
            missing = set(PropertyKind) - set(normalized)
            if missing:  # pragma: no cover - constant invariant
                raise RuntimeError(
                    "default policies missing "
                    f"{sorted(item.value for item in missing)}"
                )
        self._policies = normalized
        self._default_resource_policy = (
            default_resource_policy or PortfolioResourcePolicy()
        )
        if not isinstance(self._default_resource_policy, PortfolioResourcePolicy):
            raise PortfolioError(
                "default_resource_policy must be a PortfolioResourcePolicy"
            )

    @property
    def policies(self) -> Mapping[PropertyKind, PropertyPortfolioPolicy]:
        return dict(self._policies)

    def policy_for(self, property_kind: PropertyKind | str) -> PropertyPortfolioPolicy:
        kind = _enum(property_kind, PropertyKind, "property_kind")
        try:
            return self._policies[kind]
        except KeyError as error:
            raise PortfolioError(
                f"no portfolio policy for property kind {kind.value}"
            ) from error

    def plan(
        self,
        obligation: PortfolioObligation | Mapping[str, Any],
        *,
        capabilities: Sequence[PortfolioCapability] | Mapping[str, PortfolioCapability] | None = None,
        resource_policy: PortfolioResourcePolicy | None = None,
    ) -> PortfolioPlan:
        """Build a deterministic staged plan; never launches tools."""

        normalized = self._obligation(obligation)
        policy = self.policy_for(normalized.property_kind)
        capability_index = self._capability_index(capabilities)
        resource = resource_policy or policy.resource_policy or self._default_resource_policy
        if not isinstance(resource, PortfolioResourcePolicy):
            raise PortfolioError("resource_policy must be a PortfolioResourcePolicy")

        required_assurance = (
            normalized.required_assurance
            if assurance_satisfies(
                normalized.required_assurance, policy.minimum_assurance
            )
            else policy.minimum_assurance
            if assurance_satisfies(
                policy.minimum_assurance, normalized.required_assurance
            )
            else normalized.required_assurance
        )
        # Take the max of obligation and policy minimums.
        if _ASSURANCE_RANK[policy.minimum_assurance] > _ASSURANCE_RANK[
            normalized.required_assurance
        ]:
            required_assurance = policy.minimum_assurance
        else:
            required_assurance = normalized.required_assurance

        base_attempts = list(policy.attempts)
        # High assurance on theorem-like properties forces reconstruction lanes.
        if (
            normalized.property_kind in _THEOREM_LIKE
            and assurance_satisfies(
                required_assurance, EvidenceAuthority.INDEPENDENTLY_CHECKABLE
            )
            and not any(
                item.role is PortfolioRole.RECONSTRUCTION for item in base_attempts
            )
        ):
            stage = max((item.stage for item in base_attempts), default=-1) + 1
            base_attempts.extend(_kernel_reconstruction_specs(stage=stage))

        planned: list[PortfolioAttemptSpec] = []
        gaps: list[CapabilityGap] = []
        for spec in base_attempts:
            capability = capability_index.get(spec.backend_id)
            if capability is None:
                # Without an explicit capability map every declared backend is
                # treated as declared-runnable so planning stays pure and useful
                # offline.  Callers that want gap reporting supply capabilities.
                planned.append(spec)
                continue
            if capability.family is not spec.family and capability.family not in (
                AttemptFamily.ORCHESTRATOR,
                AttemptFamily.ADVISOR,
            ):
                gap = CapabilityGap(
                    backend_id=spec.backend_id,
                    family=spec.family,
                    reason=(
                        f"capability family {capability.family.value} does not match "
                        f"planned family {spec.family.value}"
                    ),
                    status=CapabilityStatus.UNSUPPORTED,
                    required_for_authority=spec.authoritative_when_conclusive,
                )
                gaps.append(gap)
                planned.append(
                    PortfolioAttemptSpec(
                        attempt_id=spec.attempt_id,
                        backend_id=spec.backend_id,
                        family=spec.family,
                        role=spec.role,
                        stage=spec.stage,
                        result_authority=spec.result_authority,
                        requires_candidate=spec.requires_candidate,
                        authority_capability=spec.authority_capability,
                        runnable=False,
                        gap_reason=gap.reason,
                    )
                )
                continue
            if capability.status in (
                CapabilityStatus.UNAVAILABLE,
                CapabilityStatus.UNSUPPORTED,
                CapabilityStatus.QUARANTINED,
            ):
                gap = CapabilityGap(
                    backend_id=spec.backend_id,
                    family=spec.family,
                    reason=(
                        f"backend is {capability.status.value}"
                        + (
                            f": {'; '.join(capability.diagnostics)}"
                            if capability.diagnostics
                            else ""
                        )
                    ),
                    status=capability.status,
                    required_for_authority=spec.authoritative_when_conclusive,
                )
                gaps.append(gap)
                planned.append(
                    PortfolioAttemptSpec(
                        attempt_id=spec.attempt_id,
                        backend_id=spec.backend_id,
                        family=spec.family,
                        role=spec.role,
                        stage=spec.stage,
                        result_authority=spec.result_authority,
                        requires_candidate=spec.requires_candidate,
                        authority_capability=spec.authority_capability,
                        runnable=False,
                        gap_reason=gap.reason,
                    )
                )
                continue
            if (
                spec.role is PortfolioRole.RECONSTRUCTION
                and not capability.reconstruction_capable
                and capability.status is CapabilityStatus.AVAILABLE
            ):
                gap = CapabilityGap(
                    backend_id=spec.backend_id,
                    family=spec.family,
                    reason="kernel is not reconstruction-capable",
                    status=CapabilityStatus.UNSUPPORTED,
                    required_for_authority=True,
                )
                gaps.append(gap)
                planned.append(
                    PortfolioAttemptSpec(
                        attempt_id=spec.attempt_id,
                        backend_id=spec.backend_id,
                        family=spec.family,
                        role=spec.role,
                        stage=spec.stage,
                        result_authority=spec.result_authority,
                        requires_candidate=spec.requires_candidate,
                        authority_capability=spec.authority_capability,
                        runnable=False,
                        gap_reason=gap.reason,
                    )
                )
                continue
            planned.append(spec)

        # Stable stage-major, backend-id-minor ordering for determinism.
        planned_sorted = tuple(
            sorted(planned, key=lambda item: (item.stage, item.backend_id, item.attempt_id))
        )
        return PortfolioPlan(
            obligation=normalized,
            policy_id=policy.policy_id,
            attempts=planned_sorted,
            resource_policy=resource,
            required_assurance=required_assurance,
            required_authority=normalized.required_authority,
            capability_gaps=tuple(gaps),
            metadata={
                "planner": self.interface,
                "schema_version": self.schema_version,
                "require_reconstruction_for_candidates": (
                    policy.require_reconstruction_for_candidates
                ),
                "fail_on_disagreement": policy.fail_on_disagreement,
            },
        )

    # Natural read-only alias used by supervisors.
    route = plan

    def select(
        self,
        plan: PortfolioPlan,
        outcomes: Sequence[PortfolioAttemptOutcome] | Mapping[str, Any],
        *,
        fail_on_disagreement: bool | None = None,
    ) -> PortfolioSelection:
        """Derive a fail-closed disposition independent of outcome order."""

        if not isinstance(plan, PortfolioPlan):
            raise PortfolioError("plan must be a PortfolioPlan")
        policy = self.policy_for(plan.obligation.property_kind)
        fail_closed_disagreement = (
            policy.fail_on_disagreement
            if fail_on_disagreement is None
            else _boolean(fail_on_disagreement, "fail_on_disagreement")
        )
        recorded = self._normalize_outcomes(plan, outcomes)
        specs = {item.attempt_id: item for item in plan.attempts}

        dispositions: dict[str, AttemptDisposition] = {}
        candidate_ids: list[str] = []
        reconstruction_ids: list[str] = []
        authority_positive: list[PortfolioAttemptOutcome] = []
        counterexamples: list[PortfolioAttemptOutcome] = []

        for outcome in recorded:
            spec = specs[outcome.attempt_id]
            if not spec.runnable:
                dispositions[outcome.attempt_id] = AttemptDisposition.GAP
                continue
            if outcome.role is PortfolioRole.ADVISOR:
                dispositions[outcome.attempt_id] = AttemptDisposition.NON_CONCLUSIVE
                continue
            if outcome.conclusive_counterexample or (
                outcome.is_negative and outcome.role.may_be_authoritative
            ):
                counterexamples.append(outcome)
                dispositions[outcome.attempt_id] = AttemptDisposition.COUNTEREXAMPLE
                continue
            if outcome.role is PortfolioRole.CANDIDATE:
                if outcome.is_positive or outcome.status is ResultStatus.CANDIDATE:
                    candidate_ids.append(outcome.attempt_id)
                    dispositions[outcome.attempt_id] = AttemptDisposition.CANDIDATE
                else:
                    dispositions[outcome.attempt_id] = AttemptDisposition.NON_CONCLUSIVE
                continue
            if outcome.role is PortfolioRole.RECONSTRUCTION:
                if outcome.status is ResultStatus.RECONSTRUCTED and outcome.is_positive:
                    reconstruction_ids.append(outcome.attempt_id)
                    dispositions[outcome.attempt_id] = AttemptDisposition.RECONSTRUCTED
                    # Reconstruction success is the authority path for candidates.
                    authority_positive.append(outcome)
                elif spec.requires_candidate and not any(
                    item.role is PortfolioRole.CANDIDATE
                    and (
                        item.is_positive or item.status is ResultStatus.CANDIDATE
                    )
                    for item in recorded
                ):
                    dispositions[outcome.attempt_id] = AttemptDisposition.BLOCKED
                else:
                    dispositions[outcome.attempt_id] = AttemptDisposition.NON_CONCLUSIVE
                continue
            if outcome.role is PortfolioRole.AUTHORITY and outcome.is_positive:
                if not spec.authority_capability:
                    # Authority role without capability never grants authority.
                    dispositions[outcome.attempt_id] = AttemptDisposition.NON_CONCLUSIVE
                else:
                    authority_positive.append(outcome)
                    dispositions[outcome.attempt_id] = (
                        AttemptDisposition.CONCLUSIVE_AUTHORITY
                    )
                continue
            if outcome.role is PortfolioRole.ORCHESTRATOR:
                dispositions[outcome.attempt_id] = AttemptDisposition.NON_CONCLUSIVE
                continue
            dispositions[outcome.attempt_id] = AttemptDisposition.NON_CONCLUSIVE

        # Candidates route to reconstruction: positive candidates alone never prove.
        if (
            policy.require_reconstruction_for_candidates
            and candidate_ids
            and not reconstruction_ids
            and plan.obligation.required_authority is ResultAuthority.THEOREM
        ):
            for attempt_id in candidate_ids:
                dispositions[attempt_id] = AttemptDisposition.CANDIDATE

        # Drop authority_positive entries that are mere candidates without reconstruction
        # when theorem authority is required.
        if plan.required_authority is ResultAuthority.THEOREM:
            authority_positive = [
                item
                for item in authority_positive
                if item.role is PortfolioRole.RECONSTRUCTION
                or (
                    item.role is PortfolioRole.AUTHORITY
                    and item.authority is ResultAuthority.THEOREM
                )
            ]

        # Stable sorting so order of ``outcomes`` cannot change selection.
        authority_positive = sorted(
            authority_positive,
            key=lambda item: (item.attempt_id, item.backend_id),
        )
        counterexamples = sorted(
            counterexamples,
            key=lambda item: (item.attempt_id, item.backend_id),
        )
        candidate_ids = sorted(set(candidate_ids))
        reconstruction_ids = sorted(set(reconstruction_ids))

        positive_ids = tuple(item.attempt_id for item in authority_positive)
        counterexample_id = (
            counterexamples[0].attempt_id if counterexamples else ""
        )

        disagreement = bool(positive_ids and counterexamples)
        if disagreement and fail_closed_disagreement:
            quarantined = tuple(
                sorted({*positive_ids, *(item.attempt_id for item in counterexamples)})
            )
            for attempt_id in quarantined:
                dispositions[attempt_id] = AttemptDisposition.QUARANTINED
            return PortfolioSelection(
                plan_id=plan.plan_id,
                verdict=PortfolioVerdict.QUARANTINED,
                achieved_assurance=EvidenceAuthority.NONE,
                authority_attempt_ids=(),
                candidate_attempt_ids=tuple(candidate_ids),
                reconstruction_attempt_ids=tuple(reconstruction_ids),
                counterexample_attempt_id="",
                quarantined_attempt_ids=quarantined,
                dispositions=tuple(dispositions.items()),
                disagreement=True,
                reason=(
                    "conflicting conclusive authority and counterexample; "
                    "portfolio quarantined"
                ),
            )

        if counterexample_id:
            return PortfolioSelection(
                plan_id=plan.plan_id,
                verdict=PortfolioVerdict.DISPROVED,
                achieved_assurance=EvidenceAuthority.NONE,
                authority_attempt_ids=(),
                candidate_attempt_ids=tuple(candidate_ids),
                reconstruction_attempt_ids=tuple(reconstruction_ids),
                counterexample_attempt_id=counterexample_id,
                quarantined_attempt_ids=(),
                dispositions=tuple(dispositions.items()),
                disagreement=False,
                reason="conclusive counterexample retained",
            )

        if positive_ids:
            # Achieved assurance is the min of authority outcomes that contribute.
            achieved = min(
                (item.achieved_assurance for item in authority_positive),
                key=lambda value: _ASSURANCE_RANK[value],
            )
            if not assurance_satisfies(achieved, plan.required_assurance):
                return PortfolioSelection(
                    plan_id=plan.plan_id,
                    verdict=PortfolioVerdict.INCONCLUSIVE,
                    achieved_assurance=achieved,
                    authority_attempt_ids=(),
                    candidate_attempt_ids=tuple(candidate_ids),
                    reconstruction_attempt_ids=tuple(reconstruction_ids),
                    counterexample_attempt_id="",
                    quarantined_attempt_ids=(),
                    dispositions=tuple(dispositions.items()),
                    disagreement=False,
                    reason=(
                        f"authority outcomes only achieve {achieved.value}, "
                        f"required {plan.required_assurance.value}"
                    ),
                )
            return PortfolioSelection(
                plan_id=plan.plan_id,
                verdict=PortfolioVerdict.PROVED,
                achieved_assurance=achieved,
                authority_attempt_ids=positive_ids,
                candidate_attempt_ids=tuple(candidate_ids),
                reconstruction_attempt_ids=tuple(reconstruction_ids),
                counterexample_attempt_id="",
                quarantined_attempt_ids=(),
                dispositions=tuple(dispositions.items()),
                disagreement=False,
                reason="order-independent authority selection",
            )

        # Gap-only or non-conclusive portfolios.
        if plan.capability_gaps and not any(
            not item.is_non_conclusive for item in recorded if specs[item.attempt_id].runnable
        ):
            if all(
                gap.status is CapabilityStatus.UNSUPPORTED
                for gap in plan.capability_gaps
            ):
                verdict = PortfolioVerdict.UNSUPPORTED
            else:
                verdict = PortfolioVerdict.UNAVAILABLE
            return PortfolioSelection(
                plan_id=plan.plan_id,
                verdict=verdict,
                achieved_assurance=EvidenceAuthority.NONE,
                authority_attempt_ids=(),
                candidate_attempt_ids=tuple(candidate_ids),
                reconstruction_attempt_ids=tuple(reconstruction_ids),
                counterexample_attempt_id="",
                quarantined_attempt_ids=(),
                dispositions=tuple(dispositions.items()),
                disagreement=False,
                reason="capability gaps prevent conclusive authority",
            )

        if candidate_ids and not reconstruction_ids:
            return PortfolioSelection(
                plan_id=plan.plan_id,
                verdict=PortfolioVerdict.INCONCLUSIVE,
                achieved_assurance=EvidenceAuthority.ADVISORY,
                authority_attempt_ids=(),
                candidate_attempt_ids=tuple(candidate_ids),
                reconstruction_attempt_ids=(),
                counterexample_attempt_id="",
                quarantined_attempt_ids=(),
                dispositions=tuple(dispositions.items()),
                disagreement=False,
                reason=(
                    "candidates require reconstruction before authority; "
                    "no reconstruction succeeded"
                ),
            )

        return PortfolioSelection(
            plan_id=plan.plan_id,
            verdict=PortfolioVerdict.INCONCLUSIVE,
            achieved_assurance=EvidenceAuthority.NONE,
            authority_attempt_ids=(),
            candidate_attempt_ids=tuple(candidate_ids),
            reconstruction_attempt_ids=tuple(reconstruction_ids),
            counterexample_attempt_id="",
            quarantined_attempt_ids=(),
            dispositions=tuple(dispositions.items()),
            disagreement=False,
            reason="no conclusive authority retained",
        )

    def plan_and_select(
        self,
        obligation: PortfolioObligation | Mapping[str, Any],
        outcomes: Sequence[PortfolioAttemptOutcome] | Mapping[str, Any],
        *,
        capabilities: Sequence[PortfolioCapability] | Mapping[str, PortfolioCapability] | None = None,
        resource_policy: PortfolioResourcePolicy | None = None,
        fail_on_disagreement: bool | None = None,
    ) -> tuple[PortfolioPlan, PortfolioSelection]:
        """Plan then select; pure composition of :meth:`plan` and :meth:`select`."""

        plan = self.plan(
            obligation,
            capabilities=capabilities,
            resource_policy=resource_policy,
        )
        return plan, self.select(
            plan, outcomes, fail_on_disagreement=fail_on_disagreement
        )

    def _obligation(
        self, obligation: PortfolioObligation | Mapping[str, Any]
    ) -> PortfolioObligation:
        if isinstance(obligation, PortfolioObligation):
            return obligation
        if isinstance(obligation, Mapping):
            return PortfolioObligation.from_dict(obligation)
        raise PortfolioError("obligation must be a PortfolioObligation or mapping")

    def _capability_index(
        self,
        capabilities: Sequence[PortfolioCapability]
        | Mapping[str, PortfolioCapability]
        | None,
    ) -> dict[str, PortfolioCapability]:
        if capabilities is None:
            return {}
        if isinstance(capabilities, Mapping):
            items = list(capabilities.values())
        else:
            if isinstance(capabilities, (str, bytes, bytearray)):
                raise PortfolioError("capabilities must be a sequence or mapping")
            items = list(capabilities)
        index: dict[str, PortfolioCapability] = {}
        for item in items:
            if not isinstance(item, PortfolioCapability):
                raise PortfolioError(
                    "capabilities must contain PortfolioCapability values"
                )
            if item.backend_id in index:
                raise PortfolioError(
                    f"duplicate capability for backend {item.backend_id!r}"
                )
            index[item.backend_id] = item
        return index

    def _normalize_outcomes(
        self,
        plan: PortfolioPlan,
        outcomes: Sequence[PortfolioAttemptOutcome] | Mapping[str, Any],
    ) -> tuple[PortfolioAttemptOutcome, ...]:
        if isinstance(outcomes, Mapping):
            raw_items = outcomes.get("outcomes") or outcomes.get("attempts") or ()
            if isinstance(raw_items, (str, bytes, bytearray)) or not isinstance(
                raw_items, Sequence
            ):
                raise PortfolioError("outcomes mapping must contain a sequence")
            items: list[Any] = list(raw_items)
        else:
            if isinstance(outcomes, (str, bytes, bytearray)):
                raise PortfolioError("outcomes must be a sequence")
            items = list(outcomes)

        normalized: list[PortfolioAttemptOutcome] = []
        for item in items:
            if isinstance(item, PortfolioAttemptOutcome):
                normalized.append(item)
            elif isinstance(item, Mapping):
                normalized.append(PortfolioAttemptOutcome.from_dict(item))
            else:
                raise PortfolioError(
                    "outcomes must contain PortfolioAttemptOutcome values or mappings"
                )

        planned_ids = {item.attempt_id for item in plan.attempts}
        seen: set[str] = set()
        for item in normalized:
            if item.attempt_id not in planned_ids:
                raise PortfolioError(
                    f"outcome attempt_id {item.attempt_id!r} is not in the plan"
                )
            if item.attempt_id in seen:
                raise PortfolioError(
                    f"duplicate outcome for attempt {item.attempt_id!r}"
                )
            seen.add(item.attempt_id)
            spec = next(
                attempt
                for attempt in plan.attempts
                if attempt.attempt_id == item.attempt_id
            )
            if item.backend_id != spec.backend_id:
                raise PortfolioError(
                    f"outcome backend_id {item.backend_id!r} does not match "
                    f"plan backend_id {spec.backend_id!r}"
                )
            if item.role is not spec.role:
                raise PortfolioError(
                    f"outcome role {item.role.value} does not match "
                    f"plan role {spec.role.value}"
                )

        # Fill missing planned attempts as non-conclusive gaps so selection
        # always considers the full plan (order-independent completeness).
        by_id = {item.attempt_id: item for item in normalized}
        complete: list[PortfolioAttemptOutcome] = []
        for spec in plan.attempts:
            if spec.attempt_id in by_id:
                complete.append(by_id[spec.attempt_id])
                continue
            status = (
                ResultStatus.UNAVAILABLE
                if not spec.runnable
                else ResultStatus.UNKNOWN
            )
            complete.append(
                PortfolioAttemptOutcome(
                    attempt_id=spec.attempt_id,
                    backend_id=spec.backend_id,
                    status=status,
                    authority=spec.result_authority,
                    role=spec.role,
                    stage=spec.stage,
                    detail=spec.gap_reason or "no outcome recorded",
                )
            )
        # Sort by attempt_id so caller order cannot affect selection.
        return tuple(sorted(complete, key=lambda item: item.attempt_id))


def plan_portfolio(
    obligation: PortfolioObligation | Mapping[str, Any],
    *,
    capabilities: Sequence[PortfolioCapability] | Mapping[str, PortfolioCapability] | None = None,
    resource_policy: PortfolioResourcePolicy | None = None,
    policies: Mapping[PropertyKind | str, PropertyPortfolioPolicy] | None = None,
) -> PortfolioPlan:
    """Module-level facade for :meth:`VerificationPortfolio.plan`."""

    return VerificationPortfolio(policies=policies).plan(
        obligation,
        capabilities=capabilities,
        resource_policy=resource_policy,
    )


def select_portfolio(
    plan: PortfolioPlan,
    outcomes: Sequence[PortfolioAttemptOutcome] | Mapping[str, Any],
    *,
    fail_on_disagreement: bool | None = None,
    policies: Mapping[PropertyKind | str, PropertyPortfolioPolicy] | None = None,
) -> PortfolioSelection:
    """Module-level facade for :meth:`VerificationPortfolio.select`."""

    return VerificationPortfolio(policies=policies).select(
        plan, outcomes, fail_on_disagreement=fail_on_disagreement
    )


__all__ = [
    "AttemptDisposition",
    "AttemptFamily",
    "CapabilityGap",
    "CapabilityStatus",
    "DEFAULT_PROPERTY_POLICIES",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_PARALLEL",
    "DEFAULT_MAX_MEMORY_BYTES",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_TIMEOUT_MS",
    "PortfolioAttemptOutcome",
    "PortfolioAttemptSpec",
    "PortfolioCapability",
    "PortfolioError",
    "PortfolioObligation",
    "PortfolioPlan",
    "PortfolioResourcePolicy",
    "PortfolioRole",
    "PortfolioSelection",
    "PortfolioVerdict",
    "PropertyPortfolioPolicy",
    "VERIFICATION_PORTFOLIO_INTERFACE",
    "VERIFICATION_PORTFOLIO_SCHEMA_VERSION",
    "VerificationPortfolio",
    "assurance_satisfies",
    "default_required_authority",
    "family_default_authority",
    "plan_portfolio",
    "select_portfolio",
]
