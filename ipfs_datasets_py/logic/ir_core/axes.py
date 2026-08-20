"""Orthogonal canonical axes for logic-platform status and evidence (LPC-030).

These seven closed enums answer different questions and must never be reused as
substitutes for one another:

* :class:`LogicOperationStatus` — did the attempt finish, and how?
* :class:`LogicSemanticVerdict` — what semantic conclusion (if any) was reached?
* :class:`LogicAvailability` — can the provider/feature be used at all?
* :class:`LogicEvidenceKind` — what *format/category* of evidence was emitted?
* :class:`LogicEvidenceAuthority` — what *trust ceiling* does that evidence carry?
* :class:`LogicBoundedness` — what semantic scope bounds the conclusion?
* :class:`LogicTranslationPreservation` — what guarantee does a translation claim?

A succeeded operation may still carry an unknown verdict and advisory authority.
No helper in this module promotes operation success into proof authority.
Legacy overlapping enums remain until LPC-031 supplies explicit adapters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Type, TypeAlias


LOGIC_AXIS_SCHEMA_VERSION: Final = "logic-axis/v1"
LOGIC_OPERATION_STATUS_GENERATION: Final = "LogicOperationStatus@1"
LOGIC_SEMANTIC_VERDICT_GENERATION: Final = "LogicSemanticVerdict@1"
LOGIC_AVAILABILITY_GENERATION: Final = "LogicAvailability@1"
LOGIC_EVIDENCE_KIND_GENERATION: Final = "LogicEvidenceKind@1"
LOGIC_EVIDENCE_AUTHORITY_GENERATION: Final = "LogicEvidenceAuthority@1"
LOGIC_BOUNDEDNESS_GENERATION: Final = "LogicBoundedness@1"
LOGIC_TRANSLATION_PRESERVATION_GENERATION: Final = "LogicTranslationPreservation@1"


class AxisValidationError(ValueError):
    """Raised when an axis value, label, or coordinate bundle is invalid."""


class LogicOperationStatus(str, Enum):
    """Lifecycle of one provider or operation attempt.

    Distinct from semantic verdict: ``SUCCEEDED`` means the attempt completed
    without a transport/runtime failure, not that anything was proved.
    """

    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    INVALID = "invalid"
    ERROR = "error"

    @property
    def terminal(self) -> bool:
        return self not in {
            LogicOperationStatus.PLANNED,
            LogicOperationStatus.RUNNING,
        }

    @property
    def completed_without_crash(self) -> bool:
        """Whether dependants may read produced artifacts (not proof claims)."""

        return self in {
            LogicOperationStatus.SUCCEEDED,
            LogicOperationStatus.PARTIAL,
        }


class LogicSemanticVerdict(str, Enum):
    """Semantic conclusion about an obligation or query.

    Distinct from operation lifecycle: a succeeded attempt may still report
    ``UNKNOWN`` or ``INCONCLUSIVE``.
    """

    PROVED = "proved"
    DISPROVED = "disproved"
    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    SECURE = "secure"
    ATTACK_FOUND = "attack_found"
    UNKNOWN = "unknown"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    CANCELLED = "cancelled"
    NOT_APPLICABLE = "not_applicable"

    @property
    def conclusive(self) -> bool:
        return self in {
            LogicSemanticVerdict.PROVED,
            LogicSemanticVerdict.DISPROVED,
            LogicSemanticVerdict.SATISFIABLE,
            LogicSemanticVerdict.UNSATISFIABLE,
            LogicSemanticVerdict.SATISFIED,
            LogicSemanticVerdict.VIOLATED,
            LogicSemanticVerdict.AUTHORIZED,
            LogicSemanticVerdict.DENIED,
            LogicSemanticVerdict.SECURE,
            LogicSemanticVerdict.ATTACK_FOUND,
        }


class LogicAvailability(str, Enum):
    """Whether a provider, feature, or toolchain can be used.

    Distinct from operation status: availability is a capability posture, not
    the outcome of a particular attempt.
    """

    DECLARED = "declared"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    NOT_PROBED = "not_probed"
    ABSENT = "absent"
    OPT_IN = "opt_in"
    SOURCE_MISSING = "source_missing"
    UNKNOWN = "unknown"


class LogicEvidenceKind(str, Enum):
    """Format or category of emitted evidence.

    Kind never conveys trust.  A ``KERNEL_CHECKED_PROOF`` kind still requires an
    explicit :class:`LogicEvidenceAuthority` and independent bindings.
    """

    UNKNOWN = "unknown"
    KERNEL_CHECKED_PROOF = "kernel_checked_proof"
    CHECKED_PROOF = "checked_proof"
    PROOF_CERTIFICATE = "proof_certificate"
    UNSAT_CORE = "unsat_core"
    MODEL = "model"
    COUNTEREXAMPLE = "counterexample"
    TRACE = "trace"
    MONITOR_VERDICT = "monitor_verdict"
    POLICY_DECISION = "policy_decision"
    ATTESTATION = "attestation"
    CANDIDATE = "candidate"
    DECLARATION = "declaration"
    LLM_OUTPUT = "llm_output"
    ATP_CANDIDATE = "atp_candidate"
    SMT_CANDIDATE = "smt_candidate"
    SOLVER_RESULT = "solver_result"
    TEST_RESULT = "test_result"
    STATIC_ANALYSIS = "static_analysis"
    CACHE_ENTRY = "cache_entry"
    SOURCE = "source"
    ARTIFACT = "artifact"
    RUNTIME_OBSERVATION = "runtime_observation"
    REVIEW = "review"
    MODEL_OUTPUT = "model_output"
    OTHER = "other"


class LogicEvidenceAuthority(str, Enum):
    """Trust ceiling conveyed by evidence, kept separate from its kind.

    Operation success never upgrades this axis.  ``ADVISORY`` remains valid on
    a fully succeeded provider response.
    """

    AUTHORITATIVE = "authoritative"
    INDEPENDENTLY_CHECKABLE = "independently_checkable"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    NONE = "none"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        """Total order for ceiling comparisons only; not an inference source."""

        return {
            LogicEvidenceAuthority.UNKNOWN: 0,
            LogicEvidenceAuthority.NONE: 1,
            LogicEvidenceAuthority.ADVISORY: 2,
            LogicEvidenceAuthority.BOUNDED: 3,
            LogicEvidenceAuthority.INDEPENDENTLY_CHECKABLE: 4,
            LogicEvidenceAuthority.AUTHORITATIVE: 5,
        }[self]


class LogicBoundedness(str, Enum):
    """Semantic scope of a result.

    Distinct from operational resource budgets (wall time, memory).  A resource
    limit may *cause* a bounded search, but boundedness is the claim about the
    conclusion's domain of validity.
    """

    UNBOUNDED = "unbounded"
    FINITE_DOMAIN = "finite_domain"
    FINITE_TRACE = "finite_trace"
    STEP_BOUNDED = "step_bounded"
    RESOURCE_BOUNDED = "resource_bounded"
    APPROXIMATE = "approximate"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class LogicTranslationPreservation(str, Enum):
    """Semantic guarantee claimed by a translation between representations.

    Distinct from evidence authority and boundedness: a lossless translation of
    advisory evidence remains advisory.
    """

    LOSSLESS = "lossless"
    EXACT = "exact"
    EQUISATISFIABLE = "equisatisfiable"
    SOUND_OVER_APPROXIMATION = "sound_over_approximation"
    SOUND_UNDER_APPROXIMATION = "sound_under_approximation"
    BOUNDED_ABSTRACTION = "bounded_abstraction"
    CONSERVATIVE_APPROXIMATION = "conservative_approximation"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


AxisEnum: TypeAlias = type[Enum]

CANONICAL_AXIS_TYPES: Final[tuple[AxisEnum, ...]] = (
    LogicOperationStatus,
    LogicSemanticVerdict,
    LogicAvailability,
    LogicEvidenceKind,
    LogicEvidenceAuthority,
    LogicBoundedness,
    LogicTranslationPreservation,
)

CANONICAL_AXIS_NAMES: Final[tuple[str, ...]] = (
    "operation_status",
    "semantic_verdict",
    "availability",
    "evidence_kind",
    "evidence_authority",
    "boundedness",
    "translation_preservation",
)

CANONICAL_AXIS_GENERATIONS: Final[Mapping[str, str]] = {
    "operation_status": LOGIC_OPERATION_STATUS_GENERATION,
    "semantic_verdict": LOGIC_SEMANTIC_VERDICT_GENERATION,
    "availability": LOGIC_AVAILABILITY_GENERATION,
    "evidence_kind": LOGIC_EVIDENCE_KIND_GENERATION,
    "evidence_authority": LOGIC_EVIDENCE_AUTHORITY_GENERATION,
    "boundedness": LOGIC_BOUNDEDNESS_GENERATION,
    "translation_preservation": LOGIC_TRANSLATION_PRESERVATION_GENERATION,
}

CANONICAL_AXIS_BY_NAME: Final[Mapping[str, AxisEnum]] = {
    name: axis_type
    for name, axis_type in zip(CANONICAL_AXIS_NAMES, CANONICAL_AXIS_TYPES)
}


def _enum_value(enum_type: Type[Enum], value: object, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(repr(member.value) for member in enum_type)
        raise AxisValidationError(
            f"{field_name} must be one of {allowed}; got {value!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class LogicAxisCoordinate:
    """One independent value on each of the seven orthogonal axes.

    Fields are independent by construction: no field is derived from another
    inside this type.  Callers must supply each axis explicitly.
    """

    operation_status: LogicOperationStatus
    semantic_verdict: LogicSemanticVerdict
    availability: LogicAvailability
    evidence_kind: LogicEvidenceKind
    evidence_authority: LogicEvidenceAuthority
    boundedness: LogicBoundedness
    translation_preservation: LogicTranslationPreservation

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_status",
            _enum_value(
                LogicOperationStatus,
                self.operation_status,
                "operation_status",
            ),
        )
        object.__setattr__(
            self,
            "semantic_verdict",
            _enum_value(
                LogicSemanticVerdict,
                self.semantic_verdict,
                "semantic_verdict",
            ),
        )
        object.__setattr__(
            self,
            "availability",
            _enum_value(LogicAvailability, self.availability, "availability"),
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _enum_value(LogicEvidenceKind, self.evidence_kind, "evidence_kind"),
        )
        object.__setattr__(
            self,
            "evidence_authority",
            _enum_value(
                LogicEvidenceAuthority,
                self.evidence_authority,
                "evidence_authority",
            ),
        )
        object.__setattr__(
            self,
            "boundedness",
            _enum_value(LogicBoundedness, self.boundedness, "boundedness"),
        )
        object.__setattr__(
            self,
            "translation_preservation",
            _enum_value(
                LogicTranslationPreservation,
                self.translation_preservation,
                "translation_preservation",
            ),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "availability": self.availability.value,
            "boundedness": self.boundedness.value,
            "evidence_authority": self.evidence_authority.value,
            "evidence_kind": self.evidence_kind.value,
            "operation_status": self.operation_status.value,
            "schema_version": LOGIC_AXIS_SCHEMA_VERSION,
            "semantic_verdict": self.semantic_verdict.value,
            "translation_preservation": self.translation_preservation.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicAxisCoordinate":
        if not isinstance(data, Mapping):
            raise AxisValidationError("LogicAxisCoordinate payload must be a mapping")
        return cls(
            operation_status=data.get(  # type: ignore[arg-type]
                "operation_status", LogicOperationStatus.ERROR
            ),
            semantic_verdict=data.get(  # type: ignore[arg-type]
                "semantic_verdict", LogicSemanticVerdict.UNKNOWN
            ),
            availability=data.get(  # type: ignore[arg-type]
                "availability", LogicAvailability.UNKNOWN
            ),
            evidence_kind=data.get(  # type: ignore[arg-type]
                "evidence_kind", LogicEvidenceKind.UNKNOWN
            ),
            evidence_authority=data.get(  # type: ignore[arg-type]
                "evidence_authority", LogicEvidenceAuthority.UNKNOWN
            ),
            boundedness=data.get(  # type: ignore[arg-type]
                "boundedness", LogicBoundedness.UNKNOWN
            ),
            translation_preservation=data.get(  # type: ignore[arg-type]
                "translation_preservation",
                LogicTranslationPreservation.UNKNOWN,
            ),
        )


def succeeded_unknown_advisory_coordinate() -> LogicAxisCoordinate:
    """Canonical counterexample: success does not imply proof or authority."""

    return LogicAxisCoordinate(
        operation_status=LogicOperationStatus.SUCCEEDED,
        semantic_verdict=LogicSemanticVerdict.UNKNOWN,
        availability=LogicAvailability.AVAILABLE,
        evidence_kind=LogicEvidenceKind.CANDIDATE,
        evidence_authority=LogicEvidenceAuthority.ADVISORY,
        boundedness=LogicBoundedness.UNKNOWN,
        translation_preservation=LogicTranslationPreservation.NOT_APPLICABLE,
    )


def evidence_authority_from_operation_status(
    status: LogicOperationStatus | str,
) -> LogicEvidenceAuthority:
    """Refuse to infer evidence authority from operation lifecycle.

    Always returns :attr:`LogicEvidenceAuthority.UNKNOWN`.  Callers that need
    authority must obtain it from explicit evidence bindings, never from status.
    """

    _enum_value(LogicOperationStatus, status, "operation_status")
    return LogicEvidenceAuthority.UNKNOWN


def semantic_verdict_from_operation_status(
    status: LogicOperationStatus | str,
) -> LogicSemanticVerdict:
    """Refuse to infer a semantic verdict from operation lifecycle."""

    _enum_value(LogicOperationStatus, status, "operation_status")
    return LogicSemanticVerdict.UNKNOWN


def assert_distinct_axis_types(
    axis_types: Sequence[AxisEnum] | None = None,
) -> None:
    """Fail closed if any two axis types are the same object or share identity."""

    types = tuple(axis_types) if axis_types is not None else CANONICAL_AXIS_TYPES
    if len(types) != len(CANONICAL_AXIS_NAMES):
        raise AxisValidationError(
            f"expected {len(CANONICAL_AXIS_NAMES)} orthogonal axes; got {len(types)}"
        )
    if len(set(types)) != len(types):
        raise AxisValidationError("canonical axis types must be pairwise distinct")
    names = [axis_type.__name__ for axis_type in types]
    if len(set(names)) != len(names):
        raise AxisValidationError("canonical axis type names must be pairwise distinct")
    for axis_type in types:
        if not issubclass(axis_type, Enum):
            raise AxisValidationError(
                f"{axis_type!r} is not an Enum axis type"
            )
        if not issubclass(axis_type, str):
            raise AxisValidationError(
                f"{axis_type.__name__} must be a str Enum for stable wire values"
            )


def axes_are_orthogonal() -> bool:
    """Return True when the seven canonical axes remain distinct types."""

    try:
        assert_distinct_axis_types()
    except AxisValidationError:
        return False
    return True


__all__ = [
    "CANONICAL_AXIS_BY_NAME",
    "CANONICAL_AXIS_GENERATIONS",
    "CANONICAL_AXIS_NAMES",
    "CANONICAL_AXIS_TYPES",
    "LOGIC_AVAILABILITY_GENERATION",
    "LOGIC_AXIS_SCHEMA_VERSION",
    "LOGIC_BOUNDEDNESS_GENERATION",
    "LOGIC_EVIDENCE_AUTHORITY_GENERATION",
    "LOGIC_EVIDENCE_KIND_GENERATION",
    "LOGIC_OPERATION_STATUS_GENERATION",
    "LOGIC_SEMANTIC_VERDICT_GENERATION",
    "LOGIC_TRANSLATION_PRESERVATION_GENERATION",
    "AxisValidationError",
    "LogicAvailability",
    "LogicAxisCoordinate",
    "LogicBoundedness",
    "LogicEvidenceAuthority",
    "LogicEvidenceKind",
    "LogicOperationStatus",
    "LogicSemanticVerdict",
    "LogicTranslationPreservation",
    "assert_distinct_axis_types",
    "axes_are_orthogonal",
    "evidence_authority_from_operation_status",
    "semantic_verdict_from_operation_status",
    "succeeded_unknown_advisory_coordinate",
]
