"""Typed, authority-preserving results for logic backend adapters.

``ir_core.protocols`` provides the original bounded theorem, satisfiability,
runtime-monitor, evidence-gate, and policy result contracts.  This module is a
leaf normalization layer for the wider software-verification backend surface.
It composes the existing immutable :class:`ExecutionBounds` and
:class:`ResourceUsage` records, but deliberately does not change or extend the
legacy enums in place.

Result authorities are closed and non-hierarchical.  In particular, a model
check, monitor verdict, authorization decision, protocol analysis,
hyperproperty check, candidate, reconstruction, or attestation cannot be
relabeled as theorem proof.  Operational states such as ``timeout`` and
``unavailable`` are shared, but remain scoped by the concrete result type.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, ClassVar, Final

from ..families.models import EvidenceAuthority
from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import (
    BoundedResult as CoreBoundedResult,
)
from ..ir_core.protocols import (
    EvidenceGateResult as CoreEvidenceGateResult,
)
from ..ir_core.protocols import (
    ExecutionBounds,
    ResourceUsage,
)
from ..ir_core.protocols import (
    MonitorResult as CoreMonitorResult,
)
from ..ir_core.protocols import (
    PolicyDecision as CorePolicyDecision,
)
from ..ir_core.protocols import (
    ProofResult as CoreProofResult,
)
from ..ir_core.protocols import (
    ResultStatus as CoreResultStatus,
)
from ..ir_core.protocols import (
    SatisfiabilityResult as CoreSatisfiabilityResult,
)

TYPED_BACKEND_RESULT_SCHEMA_VERSION: Final = "typed-backend-result/v1"
RESULT_AUTHORITY_NORMALIZATION_VERSION: Final = "result-authority-normalization/v1"


class ResultNormalizationError(ValueError):
    """Raised when a backend outcome cannot be normalized without semantic loss."""


class AuthoritySubstitutionError(ResultNormalizationError):
    """Raised when one result authority is presented as another."""


class ResultAuthority(StrEnum):
    """Closed, intentionally non-interchangeable backend-result authorities."""

    THEOREM = "theorem"
    SATISFIABILITY = "satisfiability"
    MODEL_CHECK = "model_check"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    CANDIDATE = "candidate"
    RECONSTRUCTION = "reconstruction"
    ATTESTATION = "attestation"

    # Descriptive aliases do not create additional wire values.
    THEOREM_PROOF = "theorem"
    MODEL_CHECKING = "model_check"
    RUNTIME_MONITOR = "monitor"
    PROTOCOL_ANALYSIS = "protocol"
    HYPERPROPERTY_CHECK = "hyperproperty"
    PROOF_CANDIDATE = "candidate"
    PROOF_RECONSTRUCTION = "reconstruction"
    RECEIPT_ATTESTATION = "attestation"


class ResultStatus(StrEnum):
    """Semantic conclusions and explicit non-success states.

    Reused conclusion words such as ``satisfied`` gain meaning only from the
    concrete result class and its exact :class:`ResultAuthority`.
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
    CANDIDATE = "candidate"
    RECONSTRUCTED = "reconstructed"
    RECONSTRUCTION_FAILED = "reconstruction_failed"
    ATTESTED = "attested"
    ATTESTATION_INVALID = "attestation_invalid"

    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"
    ERROR = "error"


_NON_CONCLUSIVE_STATUSES: Final = frozenset(
    {
        ResultStatus.UNKNOWN,
        ResultStatus.TIMEOUT,
        ResultStatus.UNAVAILABLE,
        ResultStatus.UNSUPPORTED,
        ResultStatus.MALFORMED,
        ResultStatus.ERROR,
    }
)

_AUTHORITY_CONCLUSIONS: Final[dict[ResultAuthority, frozenset[ResultStatus]]] = {
    ResultAuthority.THEOREM: frozenset(
        {ResultStatus.PROVED, ResultStatus.DISPROVED}
    ),
    ResultAuthority.SATISFIABILITY: frozenset(
        {ResultStatus.SATISFIABLE, ResultStatus.UNSATISFIABLE}
    ),
    ResultAuthority.MODEL_CHECK: frozenset(
        {ResultStatus.SATISFIED, ResultStatus.VIOLATED}
    ),
    ResultAuthority.MONITOR: frozenset(
        {ResultStatus.SATISFIED, ResultStatus.VIOLATED}
    ),
    ResultAuthority.AUTHORIZATION: frozenset(
        {ResultStatus.AUTHORIZED, ResultStatus.DENIED}
    ),
    ResultAuthority.PROTOCOL: frozenset(
        {ResultStatus.SECURE, ResultStatus.ATTACK_FOUND}
    ),
    ResultAuthority.HYPERPROPERTY: frozenset(
        {ResultStatus.SATISFIED, ResultStatus.VIOLATED}
    ),
    ResultAuthority.CANDIDATE: frozenset({ResultStatus.CANDIDATE}),
    ResultAuthority.RECONSTRUCTION: frozenset(
        {ResultStatus.RECONSTRUCTED, ResultStatus.RECONSTRUCTION_FAILED}
    ),
    ResultAuthority.ATTESTATION: frozenset(
        {ResultStatus.ATTESTED, ResultStatus.ATTESTATION_INVALID}
    ),
}


def _enum(value: object, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise ResultNormalizationError(
            f"{field_name} must be one of {choices}"
        ) from error


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
        raise ResultNormalizationError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _unique_text(
    values: Sequence[str] | object, field_name: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ResultNormalizationError(
            f"{field_name} must be a sequence of strings"
        )
    result = tuple(_text(item, f"{field_name} item") for item in values)
    if len(result) != len(set(result)):
        raise ResultNormalizationError(f"{field_name} must not contain duplicates")
    return result


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ResultNormalizationError(f"{field_name} must be a mapping")
    return dict(value)


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ResultNormalizationError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class TypedBackendResult:
    """Immutable normalized result with one exact semantic authority.

    Construct a concrete subclass, or use
    :meth:`ResultAuthorityNormalization.build`.  The base class is an
    interface/decoder and cannot be instantiated directly, preventing callers
    from bypassing the class-to-authority invariant.
    """

    result_type: ClassVar[str] = "typed_backend_result"
    expected_authority: ClassVar[ResultAuthority | None] = None

    result_id: str
    backend_id: str
    backend_version: str
    authority: ResultAuthority
    status: ResultStatus
    assumptions: tuple[str, ...] = ()
    bounds: ExecutionBounds = field(default_factory=ExecutionBounds)
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.NONE
    usage: ResourceUsage = field(default_factory=ResourceUsage)
    witness: FrozenMap = field(default_factory=FrozenMap)
    diagnostics: tuple[str, ...] = ()
    reason: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TYPED_BACKEND_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self) is TypedBackendResult:
            raise ResultNormalizationError(
                "TypedBackendResult must be represented by a concrete authority type"
            )
        object.__setattr__(self, "result_id", _text(self.result_id, "result_id"))
        object.__setattr__(self, "backend_id", _text(self.backend_id, "backend_id"))
        object.__setattr__(
            self,
            "backend_version",
            _text(self.backend_version, "backend_version"),
        )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, ResultAuthority, "authority"),
        )
        expected = type(self).expected_authority
        if expected is None or self.authority is not expected:
            expected_text = expected.value if expected is not None else "a concrete type"
            raise AuthoritySubstitutionError(
                f"{type(self).__name__} requires {expected_text} authority, "
                f"not {self.authority.value}"
            )
        object.__setattr__(
            self, "status", _enum(self.status, ResultStatus, "status")
        )
        allowed = _AUTHORITY_CONCLUSIONS[self.authority] | _NON_CONCLUSIVE_STATUSES
        if self.status not in allowed:
            raise AuthoritySubstitutionError(
                f"{self.status.value} is not a valid {self.authority.value} outcome"
            )
        object.__setattr__(
            self,
            "assumptions",
            _unique_text(self.assumptions, "assumptions"),
        )
        if not isinstance(self.bounds, ExecutionBounds):
            raise ResultNormalizationError(
                "bounds must be an ir_core.protocols.ExecutionBounds value"
            )
        object.__setattr__(
            self,
            "translation_ceiling",
            _enum(
                self.translation_ceiling,
                EvidenceAuthority,
                "translation_ceiling",
            ),
        )
        if not isinstance(self.usage, ResourceUsage):
            raise ResultNormalizationError(
                "usage must be an ir_core.protocols.ResourceUsage value"
            )
        try:
            object.__setattr__(
                self,
                "witness",
                (
                    self.witness
                    if isinstance(self.witness, FrozenMap)
                    else FrozenMap(self.witness)
                ),
            )
            object.__setattr__(
                self,
                "metadata",
                (
                    self.metadata
                    if isinstance(self.metadata, FrozenMap)
                    else FrozenMap(self.metadata)
                ),
            )
        except (TypeError, ValueError) as error:
            raise ResultNormalizationError(
                "witness and metadata must be immutable JSON mappings"
            ) from error
        object.__setattr__(
            self,
            "diagnostics",
            _unique_text(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", optional=True)
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TYPED_BACKEND_RESULT_SCHEMA_VERSION:
            raise ResultNormalizationError(
                f"unsupported typed backend result schema version: {self.schema_version}"
            )

    @property
    def digest(self) -> str:
        """Stable identity covering authority, evidence, and operational facts."""

        return stable_digest(self.to_dict())

    @property
    def is_conclusive(self) -> bool:
        return self.status not in _NON_CONCLUSIVE_STATUSES

    @property
    def exceeded_bounds(self) -> tuple[str, ...]:
        """Observed bound overruns without discarding timeout/resource evidence."""

        return self.usage.exceeds(self.bounds)

    def require_authority(
        self, required: ResultAuthority | str
    ) -> TypedBackendResult:
        required_authority = _enum(required, ResultAuthority, "required authority")
        if self.authority is not required_authority:
            raise AuthoritySubstitutionError(
                f"{self.authority.value} result cannot be used as "
                f"{required_authority.value}"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "authority": self.authority.value,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "bounds": self.bounds.to_dict(),
            "diagnostics": list(self.diagnostics),
            "metadata": self.metadata.to_dict(),
            "reason": self.reason,
            "result_id": self.result_id,
            "result_type": type(self).result_type,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "translation_ceiling": self.translation_ceiling.value,
            "usage": self.usage.to_dict(),
            "witness": self.witness.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TypedBackendResult:
        """Strictly restore a result and revalidate its type/authority pairing."""

        payload = _mapping(value, "typed backend result")
        _reject_unknown(payload, _RESULT_FIELDS, "typed backend result")

        result_type = payload.get("result_type", "")
        if cls is TypedBackendResult:
            result_class = _RESULT_CLASSES_BY_TYPE.get(result_type)
            if result_class is None:
                raise ResultNormalizationError(
                    f"unsupported result_type: {result_type!r}"
                )
        else:
            result_class = cls
            if result_type and result_type != cls.result_type:
                raise AuthoritySubstitutionError(
                    f"{cls.__name__} cannot decode result_type {result_type!r}"
                )

        authority = _enum(payload.get("authority", ""), ResultAuthority, "authority")
        if result_class.expected_authority is not authority:
            raise AuthoritySubstitutionError(
                f"{result_class.__name__} requires "
                f"{result_class.expected_authority.value} authority, "
                f"not {authority.value}"
            )
        return result_class(
            result_id=payload.get("result_id", ""),
            backend_id=payload.get("backend_id", ""),
            backend_version=payload.get("backend_version", ""),
            authority=authority,
            status=payload.get("status", ""),
            assumptions=tuple(payload.get("assumptions", ())),
            bounds=ExecutionBounds.from_dict(payload.get("bounds", {})),
            translation_ceiling=payload.get(
                "translation_ceiling", EvidenceAuthority.NONE.value
            ),
            usage=ResourceUsage.from_dict(payload.get("usage", {})),
            witness=FrozenMap(payload.get("witness", {})),
            diagnostics=tuple(payload.get("diagnostics", ())),
            reason=payload.get("reason", ""),
            metadata=FrozenMap(payload.get("metadata", {})),
            schema_version=payload.get(
                "schema_version", TYPED_BACKEND_RESULT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class TheoremResult(TypedBackendResult):
    result_type: ClassVar[str] = "theorem"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.THEOREM


@dataclass(frozen=True, slots=True)
class SatisfiabilityResult(TypedBackendResult):
    result_type: ClassVar[str] = "satisfiability"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.SATISFIABILITY


@dataclass(frozen=True, slots=True)
class ModelCheckResult(TypedBackendResult):
    result_type: ClassVar[str] = "model_check"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.MODEL_CHECK


@dataclass(frozen=True, slots=True)
class MonitorResult(TypedBackendResult):
    result_type: ClassVar[str] = "monitor"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.MONITOR


@dataclass(frozen=True, slots=True)
class AuthorizationResult(TypedBackendResult):
    result_type: ClassVar[str] = "authorization"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.AUTHORIZATION


@dataclass(frozen=True, slots=True)
class ProtocolResult(TypedBackendResult):
    result_type: ClassVar[str] = "protocol"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.PROTOCOL


@dataclass(frozen=True, slots=True)
class HyperpropertyResult(TypedBackendResult):
    result_type: ClassVar[str] = "hyperproperty"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.HYPERPROPERTY


@dataclass(frozen=True, slots=True)
class CandidateResult(TypedBackendResult):
    result_type: ClassVar[str] = "candidate"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.CANDIDATE


@dataclass(frozen=True, slots=True)
class ReconstructionResult(TypedBackendResult):
    result_type: ClassVar[str] = "reconstruction"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.RECONSTRUCTION


@dataclass(frozen=True, slots=True)
class AttestationResult(TypedBackendResult):
    result_type: ClassVar[str] = "attestation"
    expected_authority: ClassVar[ResultAuthority] = ResultAuthority.ATTESTATION


_RESULT_CLASSES_BY_AUTHORITY: Final[
    dict[ResultAuthority, type[TypedBackendResult]]
] = {
    ResultAuthority.THEOREM: TheoremResult,
    ResultAuthority.SATISFIABILITY: SatisfiabilityResult,
    ResultAuthority.MODEL_CHECK: ModelCheckResult,
    ResultAuthority.MONITOR: MonitorResult,
    ResultAuthority.AUTHORIZATION: AuthorizationResult,
    ResultAuthority.PROTOCOL: ProtocolResult,
    ResultAuthority.HYPERPROPERTY: HyperpropertyResult,
    ResultAuthority.CANDIDATE: CandidateResult,
    ResultAuthority.RECONSTRUCTION: ReconstructionResult,
    ResultAuthority.ATTESTATION: AttestationResult,
}
_RESULT_CLASSES_BY_TYPE: Final = {
    result_class.result_type: result_class
    for result_class in _RESULT_CLASSES_BY_AUTHORITY.values()
}
_RESULT_FIELDS: Final = frozenset(
    {
        "result_id",
        "result_type",
        "backend_id",
        "backend_version",
        "authority",
        "status",
        "assumptions",
        "bounds",
        "translation_ceiling",
        "usage",
        "witness",
        "diagnostics",
        "reason",
        "metadata",
        "schema_version",
    }
)


class ResultAuthorityNormalization:
    """Fail-closed constructors and decoders for typed backend results."""

    schema_version: ClassVar[str] = RESULT_AUTHORITY_NORMALIZATION_VERSION

    @classmethod
    def build(
        cls,
        authority: ResultAuthority | str,
        **fields: Any,
    ) -> TypedBackendResult:
        """Build the concrete class fixed by ``authority``.

        A redundant authority or result type in ``fields`` must agree exactly;
        it is never allowed to override the trusted argument.
        """

        expected = _enum(authority, ResultAuthority, "authority")
        supplied_authority = fields.pop("authority", expected)
        if _enum(supplied_authority, ResultAuthority, "authority") is not expected:
            raise AuthoritySubstitutionError(
                f"supplied authority does not match trusted {expected.value} authority"
            )
        supplied_type = fields.pop("result_type", "")
        result_class = _RESULT_CLASSES_BY_AUTHORITY[expected]
        if supplied_type and supplied_type != result_class.result_type:
            raise AuthoritySubstitutionError(
                f"result_type {supplied_type!r} does not match {expected.value} authority"
            )
        return result_class(authority=expected, **fields)

    @classmethod
    def normalize(
        cls,
        value: TypedBackendResult | Mapping[str, Any],
        *,
        expected_authority: ResultAuthority | str | None = None,
    ) -> TypedBackendResult:
        """Normalize a typed object or wire mapping under an optional trust anchor."""

        expected = (
            _enum(expected_authority, ResultAuthority, "expected_authority")
            if expected_authority is not None
            else None
        )
        if isinstance(value, TypedBackendResult):
            if expected is not None:
                value.require_authority(expected)
            return value

        payload = _mapping(value, "typed backend result")
        if expected is not None:
            supplied = payload.get("authority", expected.value)
            if _enum(supplied, ResultAuthority, "authority") is not expected:
                raise AuthoritySubstitutionError(
                    f"payload authority does not match trusted {expected.value} authority"
                )
            payload["authority"] = expected.value
            expected_type = _RESULT_CLASSES_BY_AUTHORITY[expected].result_type
            supplied_type = payload.get("result_type", expected_type)
            if supplied_type != expected_type:
                raise AuthoritySubstitutionError(
                    f"payload result_type {supplied_type!r} does not match "
                    f"trusted {expected.value} authority"
                )
            payload["result_type"] = expected_type
        return TypedBackendResult.from_dict(payload)

    @classmethod
    def from_core(
        cls,
        result: CoreBoundedResult,
        *,
        translation_ceiling: EvidenceAuthority | str = EvidenceAuthority.NONE,
    ) -> TypedBackendResult:
        """Compose an exact legacy theorem/sat/monitor result into this contract.

        Legacy evidence-gate and policy decisions are intentionally rejected:
        neither is semantically identical to authorization or any other new
        authority.  Concrete adapters must emit an explicit new typed result.
        """

        if not isinstance(result, CoreBoundedResult):
            raise ResultNormalizationError(
                "result must be an ir_core.protocols.BoundedResult value"
            )
        if isinstance(result, CoreProofResult):
            authority = ResultAuthority.THEOREM
            statuses = {
                CoreResultStatus.PROVED: ResultStatus.PROVED,
                CoreResultStatus.DISPROVED: ResultStatus.DISPROVED,
            }
        elif isinstance(result, CoreSatisfiabilityResult):
            authority = ResultAuthority.SATISFIABILITY
            statuses = {
                CoreResultStatus.SATISFIABLE: ResultStatus.SATISFIABLE,
                CoreResultStatus.UNSATISFIABLE: ResultStatus.UNSATISFIABLE,
            }
        elif isinstance(result, CoreMonitorResult):
            authority = ResultAuthority.MONITOR
            statuses = {
                CoreResultStatus.MONITOR_SATISFIED: ResultStatus.SATISFIED,
                CoreResultStatus.MONITOR_VIOLATED: ResultStatus.VIOLATED,
            }
        elif isinstance(result, (CoreEvidenceGateResult, CorePolicyDecision)):
            raise AuthoritySubstitutionError(
                f"legacy {type(result).__name__} has no semantically identical "
                "generalized authority"
            )
        else:
            raise ResultNormalizationError(
                f"unsupported legacy result type: {type(result).__name__}"
            )

        normalized_status = statuses.get(result.status)
        if normalized_status is None:
            normalized_status = {
                CoreResultStatus.UNKNOWN: ResultStatus.UNKNOWN,
                CoreResultStatus.ERROR: ResultStatus.ERROR,
            }.get(result.status)
        if normalized_status is None:
            raise AuthoritySubstitutionError(
                f"{result.status.value} cannot be normalized as {authority.value}"
            )

        return cls.build(
            authority,
            result_id=result.result_id,
            backend_id=result.backend_id,
            backend_version=result.backend_version,
            status=normalized_status,
            assumptions=result.assumption_ids,
            bounds=result.bounds,
            translation_ceiling=translation_ceiling,
            usage=result.usage,
            witness=result.payload,
            diagnostics=result.diagnostics,
            reason=(
                "; ".join(result.diagnostics)
                if normalized_status in _NON_CONCLUSIVE_STATUSES
                else ""
            ),
            metadata={
                "core_result": {
                    "attempt_digest": result.attempt_digest,
                    "authority": result.authority.to_dict(),
                    "claim_digest": result.claim_digest,
                    "declaration_id": result.declaration_id,
                    "obligation_digest": result.obligation_digest,
                    "obligation_id": result.obligation_id,
                    "output_digest": result.output_digest,
                    "request_digest": result.request_digest,
                    "result_digest": result.digest,
                    "result_type": type(result).result_type,
                    "schema_version": result.schema_version,
                }
            },
        )


def normalize_result(
    value: TypedBackendResult | Mapping[str, Any],
    *,
    expected_authority: ResultAuthority | str | None = None,
) -> TypedBackendResult:
    """Convenience facade for :meth:`ResultAuthorityNormalization.normalize`."""

    return ResultAuthorityNormalization.normalize(
        value, expected_authority=expected_authority
    )


# Readability aliases; aliases share the same exact class and wire authority.
ModelCheckingResult = ModelCheckResult
RuntimeMonitorResult = MonitorResult
ProtocolAnalysisResult = ProtocolResult
HyperpropertyCheckResult = HyperpropertyResult
ProofCandidateResult = CandidateResult
ProofReconstructionResult = ReconstructionResult
ReceiptAttestationResult = AttestationResult


__all__ = [
    "AttestationResult",
    "AuthoritySubstitutionError",
    "AuthorizationResult",
    "CandidateResult",
    "HyperpropertyCheckResult",
    "HyperpropertyResult",
    "ModelCheckResult",
    "ModelCheckingResult",
    "MonitorResult",
    "ProofCandidateResult",
    "ProofReconstructionResult",
    "ProtocolAnalysisResult",
    "ProtocolResult",
    "ReceiptAttestationResult",
    "ReconstructionResult",
    "ResultAuthority",
    "ResultAuthorityNormalization",
    "ResultNormalizationError",
    "ResultStatus",
    "RuntimeMonitorResult",
    "SatisfiabilityResult",
    "TheoremResult",
    "TypedBackendResult",
    "normalize_result",
    "RESULT_AUTHORITY_NORMALIZATION_VERSION",
    "TYPED_BACKEND_RESULT_SCHEMA_VERSION",
]
