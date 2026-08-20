"""Compare predicted versus observed detectors and classify assurance gaps (AAE-028).

Interface surface:

* ``compare_detection_sets@1`` — separate predicted detectors into not-selected,
  not-executed, path-unobserved, weak-property, dependency/capsule omission,
  and unexpected-observed roles; emit sealed ``DetectionFailure@1`` records.
* ``classify_assurance_gap@1`` — map comparison causes plus equivalence /
  intentional / unspecified signals onto the closed plan §5
  ``AssuranceGapClass`` taxonomy and seal an ``AssuranceGap@1``.

Authority rules (normative):

* Pure and deterministic: no store, worktree, or production-policy mutation.
* Canonical identity comes only from ``software_contracts.content``.
* Closed cause taxonomy and closed gap taxonomy fail closed on unknowns.
* Unknown causes always require human review rather than silent omission.
* Difficulty-to-kill never implies equivalence (equivalence is an explicit
  assessment input, never inferred from missed detectors alone).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AnalysisContractError,
    AssuranceGap,
    AssuranceGapClass,
    DetectionFailure,
    DetectionFailureKind,
    GapSeverity,
    MinimizedEvidenceBinding,
    SourceSpan,
    SurvivorRiskClass,
    verify_detection_failure_identity,
    verify_gap_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    MAX_DETECTORS,
    MAX_DEPENDENCY_PATH,
    DetectorClassification,
    DetectorKind,
    DetectorPrediction,
    EquivalenceAssessmentStatus,
    ExpectedDetectionSet,
    ExecutionContractError,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

COMPARE_DETECTION_SETS_INTERFACE: Final[str] = "compare_detection_sets@1"
CLASSIFY_ASSURANCE_GAP_INTERFACE: Final[str] = "classify_assurance_gap@1"

DETECTOR_OBSERVATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detector-observation@1"
)
DETECTION_COMPARISON_ENTRY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detection-comparison-entry@1"
)
DETECTION_COMPARISON_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detection-comparison-result@1"
)
DETECTION_COMPARISON_RESULT_INTERFACE: Final[str] = "DetectionComparisonResult@1"
GAP_CLASSIFICATION_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-gap-classification-subject@1"
)

GENERATOR_ID: Final[str] = "gap_classification"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_LIST: Final[int] = 1_024
MAX_FAILURES: Final[int] = 1_024
MAX_ENTRIES: Final[int] = 1_024

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)

# Test-like detector kinds map not-executed / path misses onto missing_test.
_TEST_LIKE_KINDS: Final[frozenset[str]] = frozenset(
    {
        DetectorKind.UNIT_TEST.value,
        DetectorKind.INTEGRATION_TEST.value,
        DetectorKind.PROPERTY_TEST.value,
        DetectorKind.FULL_SUITE.value,
    }
)
_PROOF_LIKE_KINDS: Final[frozenset[str]] = frozenset(
    {
        DetectorKind.FORMAL_OBLIGATION.value,
        DetectorKind.INCREMENTAL_SEAL.value,
    }
)
_POLICY_LIKE_KINDS: Final[frozenset[str]] = frozenset(
    {DetectorKind.POLICY_RULE.value}
)

# Overall gap-cause priority (first match wins when multiple signals apply).
_CAUSE_PRIORITY: Final[tuple[str, ...]] = (
    "equivalence",
    "intentional",
    "unspecified",
    "dependency_omission",
    "capsule_omission",
    "not_selected",
    "not_executed",
    "path_unobserved",
    "weak_property",
    "unknown",
)

# Severity defaults by survivor risk class.
_RISK_TO_SEVERITY: Final[Mapping[str, str]] = MappingProxyType(
    {
        SurvivorRiskClass.CRITICAL_SECURITY.value: GapSeverity.CRITICAL.value,
        SurvivorRiskClass.AUTHORIZATION.value: GapSeverity.CRITICAL.value,
        SurvivorRiskClass.FINANCIAL_LEGAL.value: GapSeverity.CRITICAL.value,
        SurvivorRiskClass.DURABILITY.value: GapSeverity.HIGH.value,
        SurvivorRiskClass.DISTRIBUTED_TRANSITION.value: GapSeverity.HIGH.value,
        SurvivorRiskClass.PROOF_RECEIPT_TRUST.value: GapSeverity.HIGH.value,
        SurvivorRiskClass.CRITICAL_INVARIANT.value: GapSeverity.HIGH.value,
        SurvivorRiskClass.HIGH.value: GapSeverity.HIGH.value,
        SurvivorRiskClass.MEDIUM.value: GapSeverity.MEDIUM.value,
        SurvivorRiskClass.LOCAL_BUG.value: GapSeverity.MEDIUM.value,
        SurvivorRiskClass.LOW.value: GapSeverity.LOW.value,
    }
)

# Causes that always require human review.
_HUMAN_REVIEW_CAUSES: Final[frozenset[str]] = frozenset(
    {
        "unknown",
        "equivalence",
        "intentional",
        "unspecified",
    }
)


class GapClassificationError(AssuranceBaseError):
    """Raised when detection comparison or gap classification fails closed."""


class AssuranceGapCause(str, Enum):
    """Closed intermediate causes for predicted-versus-observed detection gaps.

    Acceptance (AAE-028) requires separation of not-selected, not-executed,
    path-unobserved, weak-property, dependency/capsule omission, unspecified,
    intentional, equivalence, and unknown causes. Dependency and capsule
    omissions are distinct members of the closed set.
    """

    NOT_SELECTED = "not_selected"
    NOT_EXECUTED = "not_executed"
    PATH_UNOBSERVED = "path_unobserved"
    WEAK_PROPERTY = "weak_property"
    DEPENDENCY_OMISSION = "dependency_omission"
    CAPSULE_OMISSION = "capsule_omission"
    UNSPECIFIED = "unspecified"
    INTENTIONAL = "intentional"
    EQUIVALENCE = "equivalence"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise GapClassificationError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise GapClassificationError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise GapClassificationError(f"{name} exceeds maximum length")
    if any(not char.isprintable() for char in value):
        raise GapClassificationError(f"{name} contains non-printable characters")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise GapClassificationError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise GapClassificationError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise GapClassificationError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:
        raise GapClassificationError(f"{name} must be a valid CIDv1") from exc
    return text


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    if type(value) is str:
        try:
            return enum_type(value).value
        except ValueError as exc:
            raise GapClassificationError(
                f"{name}={value!r} is not an admitted {enum_type.__name__}"
            ) from exc
    raise GapClassificationError(f"{name} must be {enum_type.__name__} or string")


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise GapClassificationError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise GapClassificationError(
            f"{name} field set mismatch; missing={missing}; extra={extra}"
        )
    return dict(data)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GapClassificationError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(value, path=name)
    validate_structured_value(value)
    return MappingProxyType(_thaw_structured(value))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
    symbol: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise GapClassificationError(f"{name} must be a list")
    if len(values) > maximum:
        raise GapClassificationError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = (
            _symbol_id(raw, f"{name}[{index}]")
            if symbol
            else _token(raw, f"{name}[{index}]")
        )
        if item in seen:
            raise GapClassificationError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise GapClassificationError(str(exc)) from exc
    raise GapClassificationError(f"{name} must be AssuranceArtifactHeader or mapping")


def _normalize_source_span(
    value: SourceSpan | Mapping[str, Any],
    name: str = "source_span",
) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "span_cid" in value:
                return SourceSpan.from_dict(value)
            return SourceSpan(
                path=value["path"],
                start_line=value["start_line"],
                end_line=value["end_line"],
                start_col=value.get("start_col"),
                end_col=value.get("end_col"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise GapClassificationError(f"{name} is malformed: {exc}") from exc
    raise GapClassificationError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]],
    name: str = "source_spans",
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise GapClassificationError(f"{name} must be a list")
    if not values:
        raise GapClassificationError(f"{name} must not be empty")
    if len(values) > MAX_LIST:
        raise GapClassificationError(f"{name} exceeds maximum length")
    spans = tuple(
        _normalize_source_span(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )
    return tuple(
        sorted(
            spans,
            key=lambda item: (item.path, item.start_line, item.end_line, item.span_cid),
        )
    )


def _normalize_evidence(
    value: MinimizedEvidenceBinding | Mapping[str, Any],
    name: str = "minimized_evidence",
) -> MinimizedEvidenceBinding:
    if isinstance(value, MinimizedEvidenceBinding):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "binding_cid" in value:
                return MinimizedEvidenceBinding.from_dict(value)
            return MinimizedEvidenceBinding(
                evidence_cids=value["evidence_cids"],
                minimized=value.get("minimized", True),
                minimization_failed=value.get("minimization_failed", False),
                reproduction_input_cid=value.get("reproduction_input_cid"),
                notes=value.get("notes"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise GapClassificationError(f"{name} is malformed: {exc}") from exc
    raise GapClassificationError(
        f"{name} must be MinimizedEvidenceBinding or mapping"
    )


def _normalize_expected(
    value: ExpectedDetectionSet | Mapping[str, Any],
    name: str = "expected",
) -> ExpectedDetectionSet:
    if isinstance(value, ExpectedDetectionSet):
        return value
    if isinstance(value, Mapping):
        try:
            return ExpectedDetectionSet.from_dict(value)
        except ExecutionContractError as exc:
            raise GapClassificationError(str(exc)) from exc
    raise GapClassificationError(f"{name} must be ExpectedDetectionSet or mapping")


def _normalize_classification(
    value: DetectorClassification | Mapping[str, Any],
    name: str = "classification",
) -> DetectorClassification:
    if isinstance(value, DetectorClassification):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "classification_cid" in value:
                return DetectorClassification.from_dict(value)
            return DetectorClassification(
                predicted_detector_ids=value.get("predicted_detector_ids", ()),
                selected_detector_ids=value.get("selected_detector_ids", ()),
                executed_detector_ids=value.get("executed_detector_ids", ()),
                observed_detector_ids=value.get("observed_detector_ids", ()),
            )
        except (ExecutionContractError, KeyError, TypeError) as exc:
            raise GapClassificationError(f"{name} is malformed: {exc}") from exc
    raise GapClassificationError(
        f"{name} must be DetectorClassification or mapping"
    )


def _artifact_header(
    base: AssuranceArtifactHeader,
    *,
    artifact_kind: str,
    interface_id: str,
    symbol_ids: Sequence[str] | None = None,
) -> AssuranceArtifactHeader:
    """Clone a header for a derived artifact with a new kind and generator pin."""

    versions = base.versions
    generator = versions.generator
    new_generator = type(generator)(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    new_versions = type(versions)(
        operator_id=versions.operator_id,
        operator_version=versions.operator_version,
        campaign_policy_id=versions.campaign_policy_id,
        campaign_policy_version=versions.campaign_policy_version,
        generator=new_generator,
    )
    symbols = (
        tuple(symbol_ids)
        if symbol_ids is not None
        else tuple(base.target_symbol_ids)
    )
    return AssuranceArtifactHeader(
        artifact_kind=artifact_kind,
        repository_id=base.repository_id,
        repository_state_cid=base.repository_state_cid,
        target_symbol_ids=symbols,
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=new_versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


# ---------------------------------------------------------------------------
# DetectorObservation — per-detector observation annotations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectorObservation:
    """Optional observation annotations for one detector after execution.

    When a predicted detector is executed but not observed, these flags decide
    among path-unobserved, weak-property, dependency omission, and capsule
    omission causes. Defaults assume the path was exercised and assertions /
    capsule edges are intact so the residual miss is an observation miss.
    """

    detector_id: str
    path_observed: bool = True
    assertion_strength_adequate: bool = True
    dependency_edge_present: bool = True
    capsule_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "detector_id",
            "path_observed",
            "assertion_strength_adequate",
            "dependency_edge_present",
            "capsule_complete",
            "notes",
            "metadata",
            "observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "detector_id", _token(self.detector_id, "detector_id")
        )
        object.__setattr__(
            self, "path_observed", _bool(self.path_observed, "path_observed")
        )
        object.__setattr__(
            self,
            "assertion_strength_adequate",
            _bool(self.assertion_strength_adequate, "assertion_strength_adequate"),
        )
        object.__setattr__(
            self,
            "dependency_edge_present",
            _bool(self.dependency_edge_present, "dependency_edge_present"),
        )
        object.__setattr__(
            self, "capsule_complete", _bool(self.capsule_complete, "capsule_complete")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTOR_OBSERVATION_SCHEMA,
            "detector_id": self.detector_id,
            "path_observed": self.path_observed,
            "assertion_strength_adequate": self.assertion_strength_adequate,
            "dependency_edge_present": self.dependency_edge_present,
            "capsule_complete": self.capsule_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["observation_cid"] = self.observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectorObservation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("observation_cid")
        if payload.pop("schema") != DETECTOR_OBSERVATION_SCHEMA:
            raise GapClassificationError(
                "unsupported DetectorObservation schema version"
            )
        result = cls(
            detector_id=payload["detector_id"],
            path_observed=payload["path_observed"],
            assertion_strength_adequate=payload["assertion_strength_adequate"],
            dependency_edge_present=payload["dependency_edge_present"],
            capsule_complete=payload["capsule_complete"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.observation_cid:
            raise GapClassificationError(
                "DetectorObservation observation_cid identity mismatch"
            )
        return result


def _normalize_observation(
    value: DetectorObservation | Mapping[str, Any],
    name: str = "observation",
) -> DetectorObservation:
    if isinstance(value, DetectorObservation):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "observation_cid" in value:
            return DetectorObservation.from_dict(value)
        return DetectorObservation(
            detector_id=value["detector_id"],
            path_observed=value.get("path_observed", True),
            assertion_strength_adequate=value.get(
                "assertion_strength_adequate", True
            ),
            dependency_edge_present=value.get("dependency_edge_present", True),
            capsule_complete=value.get("capsule_complete", True),
            notes=value.get("notes"),
            metadata=value.get("metadata", {}),
        )
    raise GapClassificationError(f"{name} must be DetectorObservation or mapping")


def _normalize_observations(
    values: Sequence[DetectorObservation | Mapping[str, Any]] | None,
    name: str = "detector_observations",
) -> tuple[DetectorObservation, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise GapClassificationError(f"{name} must be a list")
    if len(values) > MAX_DETECTORS:
        raise GapClassificationError(f"{name} exceeds maximum length")
    items = tuple(
        _normalize_observation(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )
    ids = [item.detector_id for item in items]
    if len(ids) != len(set(ids)):
        raise GapClassificationError(f"{name} detector_id values must be unique")
    return tuple(sorted(items, key=lambda item: item.detector_id))


# ---------------------------------------------------------------------------
# DetectionComparisonEntry — one detector's predicted-vs-observed role
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectionComparisonEntry:
    """One detector's role after comparing predicted and observed sets."""

    detector_id: str
    cause: AssuranceGapCause | str
    predicted: bool
    selected: bool
    executed: bool
    observed: bool
    failure_kind: DetectionFailureKind | str | None
    dependency_path: Sequence[str]
    summary: str
    detector_kind: DetectorKind | str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "detector_id",
            "cause",
            "predicted",
            "selected",
            "executed",
            "observed",
            "failure_kind",
            "dependency_path",
            "summary",
            "detector_kind",
            "notes",
            "metadata",
            "entry_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "detector_id", _token(self.detector_id, "detector_id")
        )
        cause = _enum(self.cause, AssuranceGapCause, "cause")
        object.__setattr__(self, "cause", cause)
        predicted = _bool(self.predicted, "predicted")
        selected = _bool(self.selected, "selected")
        executed = _bool(self.executed, "executed")
        observed = _bool(self.observed, "observed")
        if executed and not selected:
            raise GapClassificationError(
                "executed detectors must also be selected"
            )
        if observed and not executed:
            raise GapClassificationError(
                "observed detectors must also be executed"
            )
        object.__setattr__(self, "predicted", predicted)
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "executed", executed)
        object.__setattr__(self, "observed", observed)

        failure_kind = self.failure_kind
        if failure_kind is not None:
            failure_kind = _enum(
                failure_kind, DetectionFailureKind, "failure_kind"
            )
        object.__setattr__(self, "failure_kind", failure_kind)

        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise GapClassificationError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(self, "summary", _text(self.summary, "summary"))

        detector_kind = self.detector_kind
        if detector_kind is not None:
            detector_kind = _enum(detector_kind, DetectorKind, "detector_kind")
        object.__setattr__(self, "detector_kind", detector_kind)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Cause-specific role invariants (fail closed).
        if cause == AssuranceGapCause.NOT_SELECTED.value:
            if not predicted or selected:
                raise GapClassificationError(
                    "not_selected requires predicted=true and selected=false"
                )
            if failure_kind != DetectionFailureKind.SELECTION_MISS.value:
                raise GapClassificationError(
                    "not_selected requires failure_kind=selection_miss"
                )
        elif cause == AssuranceGapCause.NOT_EXECUTED.value:
            if not selected or executed:
                raise GapClassificationError(
                    "not_executed requires selected=true and executed=false"
                )
            if failure_kind != DetectionFailureKind.EXECUTION_MISS.value:
                raise GapClassificationError(
                    "not_executed requires failure_kind=execution_miss"
                )
        elif cause in {
            AssuranceGapCause.PATH_UNOBSERVED.value,
            AssuranceGapCause.WEAK_PROPERTY.value,
            AssuranceGapCause.DEPENDENCY_OMISSION.value,
            AssuranceGapCause.CAPSULE_OMISSION.value,
        }:
            if not executed or observed:
                raise GapClassificationError(
                    f"{cause} requires executed=true and observed=false"
                )
            if failure_kind is None:
                raise GapClassificationError(
                    f"{cause} requires a detection failure_kind"
                )
        elif cause == AssuranceGapCause.UNKNOWN.value and predicted and not observed:
            if failure_kind is None:
                raise GapClassificationError(
                    "unknown predicted-miss requires a detection failure_kind"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTION_COMPARISON_ENTRY_SCHEMA,
            "detector_id": self.detector_id,
            "cause": self.cause,
            "predicted": self.predicted,
            "selected": self.selected,
            "executed": self.executed,
            "observed": self.observed,
            "failure_kind": self.failure_kind,
            "dependency_path": list(self.dependency_path),
            "summary": self.summary,
            "detector_kind": self.detector_kind,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def entry_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["entry_cid"] = self.entry_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectionComparisonEntry":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("entry_cid")
        if payload.pop("schema") != DETECTION_COMPARISON_ENTRY_SCHEMA:
            raise GapClassificationError(
                "unsupported DetectionComparisonEntry schema version"
            )
        result = cls(
            detector_id=payload["detector_id"],
            cause=payload["cause"],
            predicted=payload["predicted"],
            selected=payload["selected"],
            executed=payload["executed"],
            observed=payload["observed"],
            failure_kind=payload["failure_kind"],
            dependency_path=payload["dependency_path"],
            summary=payload["summary"],
            detector_kind=payload["detector_kind"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.entry_cid:
            raise GapClassificationError(
                "DetectionComparisonEntry entry_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# DetectionComparisonResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectionComparisonResult:
    """Sealed result of comparing predicted and observed detector sets.

    Interface: ``DetectionComparisonResult@1``

    Separates detectors by closed cause and binds sealed DetectionFailure
    records for every predicted miss and unexpected observation.
    """

    interface_id: str
    candidate_id: str
    candidate_cid: str
    expected_detection_set_cid: str
    classification_cid: str
    entries: Sequence[DetectionComparisonEntry | Mapping[str, Any]]
    failures: Sequence[DetectionFailure | Mapping[str, Any]]
    not_selected_detector_ids: Sequence[str]
    not_executed_detector_ids: Sequence[str]
    path_unobserved_detector_ids: Sequence[str]
    weak_property_detector_ids: Sequence[str]
    dependency_omission_detector_ids: Sequence[str]
    capsule_omission_detector_ids: Sequence[str]
    unexpected_detector_ids: Sequence[str]
    observed_as_predicted_detector_ids: Sequence[str]
    primary_cause: AssuranceGapCause | str
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "candidate_id",
            "candidate_cid",
            "expected_detection_set_cid",
            "classification_cid",
            "entries",
            "failures",
            "not_selected_detector_ids",
            "not_executed_detector_ids",
            "path_unobserved_detector_ids",
            "weak_property_detector_ids",
            "dependency_omission_detector_ids",
            "capsule_omission_detector_ids",
            "unexpected_detector_ids",
            "observed_as_predicted_detector_ids",
            "primary_cause",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "interface_id", _text(self.interface_id, "interface_id")
        )
        if self.interface_id != COMPARE_DETECTION_SETS_INTERFACE:
            raise GapClassificationError(
                "interface_id must be compare_detection_sets@1"
            )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self,
            "expected_detection_set_cid",
            _cid(self.expected_detection_set_cid, "expected_detection_set_cid"),
        )
        object.__setattr__(
            self,
            "classification_cid",
            _cid(self.classification_cid, "classification_cid"),
        )

        entries = _normalize_entries(list(self.entries))
        failures = _normalize_failures(list(self.failures))
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "failures", failures)

        not_selected = _unique_sorted_tokens(
            list(self.not_selected_detector_ids),
            "not_selected_detector_ids",
            maximum=MAX_DETECTORS,
        )
        not_executed = _unique_sorted_tokens(
            list(self.not_executed_detector_ids),
            "not_executed_detector_ids",
            maximum=MAX_DETECTORS,
        )
        path_unobserved = _unique_sorted_tokens(
            list(self.path_unobserved_detector_ids),
            "path_unobserved_detector_ids",
            maximum=MAX_DETECTORS,
        )
        weak_property = _unique_sorted_tokens(
            list(self.weak_property_detector_ids),
            "weak_property_detector_ids",
            maximum=MAX_DETECTORS,
        )
        dependency_omission = _unique_sorted_tokens(
            list(self.dependency_omission_detector_ids),
            "dependency_omission_detector_ids",
            maximum=MAX_DETECTORS,
        )
        capsule_omission = _unique_sorted_tokens(
            list(self.capsule_omission_detector_ids),
            "capsule_omission_detector_ids",
            maximum=MAX_DETECTORS,
        )
        unexpected = _unique_sorted_tokens(
            list(self.unexpected_detector_ids),
            "unexpected_detector_ids",
            maximum=MAX_DETECTORS,
        )
        observed_ok = _unique_sorted_tokens(
            list(self.observed_as_predicted_detector_ids),
            "observed_as_predicted_detector_ids",
            maximum=MAX_DETECTORS,
        )

        # Cross-check lists against entries.
        by_cause = _entries_by_cause(entries)
        if not_selected != by_cause[AssuranceGapCause.NOT_SELECTED.value]:
            raise GapClassificationError(
                "not_selected_detector_ids must match entry causes"
            )
        if not_executed != by_cause[AssuranceGapCause.NOT_EXECUTED.value]:
            raise GapClassificationError(
                "not_executed_detector_ids must match entry causes"
            )
        if path_unobserved != by_cause[AssuranceGapCause.PATH_UNOBSERVED.value]:
            raise GapClassificationError(
                "path_unobserved_detector_ids must match entry causes"
            )
        if weak_property != by_cause[AssuranceGapCause.WEAK_PROPERTY.value]:
            raise GapClassificationError(
                "weak_property_detector_ids must match entry causes"
            )
        if dependency_omission != by_cause[
            AssuranceGapCause.DEPENDENCY_OMISSION.value
        ]:
            raise GapClassificationError(
                "dependency_omission_detector_ids must match entry causes"
            )
        if capsule_omission != by_cause[AssuranceGapCause.CAPSULE_OMISSION.value]:
            raise GapClassificationError(
                "capsule_omission_detector_ids must match entry causes"
            )

        entry_unexpected = tuple(
            sorted(
                item.detector_id
                for item in entries
                if item.failure_kind
                == DetectionFailureKind.UNEXPECTED_OBSERVED.value
            )
        )
        if unexpected != entry_unexpected:
            raise GapClassificationError(
                "unexpected_detector_ids must match unexpected_observed entries"
            )

        predicted_observed = tuple(
            sorted(
                item.detector_id
                for item in entries
                if item.predicted and item.observed and item.failure_kind is None
            )
        )
        if observed_ok != predicted_observed:
            raise GapClassificationError(
                "observed_as_predicted_detector_ids must match predicted+observed "
                "entries without failure"
            )

        object.__setattr__(self, "not_selected_detector_ids", not_selected)
        object.__setattr__(self, "not_executed_detector_ids", not_executed)
        object.__setattr__(self, "path_unobserved_detector_ids", path_unobserved)
        object.__setattr__(self, "weak_property_detector_ids", weak_property)
        object.__setattr__(
            self, "dependency_omission_detector_ids", dependency_omission
        )
        object.__setattr__(self, "capsule_omission_detector_ids", capsule_omission)
        object.__setattr__(self, "unexpected_detector_ids", unexpected)
        object.__setattr__(
            self, "observed_as_predicted_detector_ids", observed_ok
        )

        primary = _enum(self.primary_cause, AssuranceGapCause, "primary_cause")
        derived_primary = _derive_primary_cause(
            not_selected=not_selected,
            not_executed=not_executed,
            path_unobserved=path_unobserved,
            weak_property=weak_property,
            dependency_omission=dependency_omission,
            capsule_omission=capsule_omission,
            unexpected=unexpected,
            observed_ok=observed_ok,
            entries=entries,
        )
        if primary != derived_primary:
            raise GapClassificationError(
                f"primary_cause {primary!r} must match derived {derived_primary!r}"
            )
        object.__setattr__(self, "primary_cause", primary)

        failure_cids = {item.failure_cid for item in failures}
        entry_failure_kinds = {
            item.detector_id: item.failure_kind
            for item in entries
            if item.failure_kind is not None
        }
        if len(failures) != len(entry_failure_kinds):
            raise GapClassificationError(
                "failures must cover every entry that declares a failure_kind"
            )
        for failure in failures:
            if failure.detector_id not in entry_failure_kinds:
                raise GapClassificationError(
                    f"failure for detector {failure.detector_id!r} has no entry"
                )
            if failure.failure_kind != entry_failure_kinds[failure.detector_id]:
                raise GapClassificationError(
                    f"failure_kind mismatch for detector {failure.detector_id!r}"
                )
        if len(failure_cids) != len(failures):
            raise GapClassificationError("failure_cid values must be unique")

        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def failure_cids(self) -> tuple[str, ...]:
        return tuple(sorted(item.failure_cid for item in self.failures))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTION_COMPARISON_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "classification_cid": self.classification_cid,
            "entries": [item.identity_payload() for item in self.entries],
            "failures": [item.identity_payload() for item in self.failures],
            "not_selected_detector_ids": list(self.not_selected_detector_ids),
            "not_executed_detector_ids": list(self.not_executed_detector_ids),
            "path_unobserved_detector_ids": list(self.path_unobserved_detector_ids),
            "weak_property_detector_ids": list(self.weak_property_detector_ids),
            "dependency_omission_detector_ids": list(
                self.dependency_omission_detector_ids
            ),
            "capsule_omission_detector_ids": list(
                self.capsule_omission_detector_ids
            ),
            "unexpected_detector_ids": list(self.unexpected_detector_ids),
            "observed_as_predicted_detector_ids": list(
                self.observed_as_predicted_detector_ids
            ),
            "primary_cause": self.primary_cause,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DETECTION_COMPARISON_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "classification_cid": self.classification_cid,
            "entries": [item.to_dict() for item in self.entries],
            "failures": [item.to_dict() for item in self.failures],
            "not_selected_detector_ids": list(self.not_selected_detector_ids),
            "not_executed_detector_ids": list(self.not_executed_detector_ids),
            "path_unobserved_detector_ids": list(self.path_unobserved_detector_ids),
            "weak_property_detector_ids": list(self.weak_property_detector_ids),
            "dependency_omission_detector_ids": list(
                self.dependency_omission_detector_ids
            ),
            "capsule_omission_detector_ids": list(
                self.capsule_omission_detector_ids
            ),
            "unexpected_detector_ids": list(self.unexpected_detector_ids),
            "observed_as_predicted_detector_ids": list(
                self.observed_as_predicted_detector_ids
            ),
            "primary_cause": self.primary_cause,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectionComparisonResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid")
        if payload.pop("schema") != DETECTION_COMPARISON_RESULT_SCHEMA:
            raise GapClassificationError(
                "unsupported DetectionComparisonResult schema version"
            )
        result = cls(
            interface_id=payload["interface_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            expected_detection_set_cid=payload["expected_detection_set_cid"],
            classification_cid=payload["classification_cid"],
            entries=payload["entries"],
            failures=payload["failures"],
            not_selected_detector_ids=payload["not_selected_detector_ids"],
            not_executed_detector_ids=payload["not_executed_detector_ids"],
            path_unobserved_detector_ids=payload["path_unobserved_detector_ids"],
            weak_property_detector_ids=payload["weak_property_detector_ids"],
            dependency_omission_detector_ids=payload[
                "dependency_omission_detector_ids"
            ],
            capsule_omission_detector_ids=payload[
                "capsule_omission_detector_ids"
            ],
            unexpected_detector_ids=payload["unexpected_detector_ids"],
            observed_as_predicted_detector_ids=payload[
                "observed_as_predicted_detector_ids"
            ],
            primary_cause=payload["primary_cause"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.result_cid:
            raise GapClassificationError(
                "DetectionComparisonResult result_cid identity mismatch"
            )
        return result


def _normalize_entries(
    values: Sequence[DetectionComparisonEntry | Mapping[str, Any]],
) -> tuple[DetectionComparisonEntry, ...]:
    if not isinstance(values, (list, tuple)):
        raise GapClassificationError("entries must be a list")
    if len(values) > MAX_ENTRIES:
        raise GapClassificationError("entries exceeds maximum length")
    items: list[DetectionComparisonEntry] = []
    for index, raw in enumerate(values):
        if isinstance(raw, DetectionComparisonEntry):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "entry_cid" in raw:
                items.append(DetectionComparisonEntry.from_dict(raw))
            else:
                items.append(
                    DetectionComparisonEntry(
                        detector_id=raw["detector_id"],
                        cause=raw["cause"],
                        predicted=raw["predicted"],
                        selected=raw["selected"],
                        executed=raw["executed"],
                        observed=raw["observed"],
                        failure_kind=raw.get("failure_kind"),
                        dependency_path=raw["dependency_path"],
                        summary=raw["summary"],
                        detector_kind=raw.get("detector_kind"),
                        notes=raw.get("notes"),
                        metadata=raw.get("metadata", {}),
                    )
                )
        else:
            raise GapClassificationError(
                f"entries[{index}] must be DetectionComparisonEntry or mapping"
            )
    ids = [item.detector_id for item in items]
    if len(ids) != len(set(ids)):
        raise GapClassificationError("entries detector_id values must be unique")
    return tuple(sorted(items, key=lambda item: item.detector_id))


def _normalize_failures(
    values: Sequence[DetectionFailure | Mapping[str, Any]],
) -> tuple[DetectionFailure, ...]:
    if not isinstance(values, (list, tuple)):
        raise GapClassificationError("failures must be a list")
    if len(values) > MAX_FAILURES:
        raise GapClassificationError("failures exceeds maximum length")
    items: list[DetectionFailure] = []
    for index, raw in enumerate(values):
        if isinstance(raw, DetectionFailure):
            items.append(raw)
        elif isinstance(raw, Mapping):
            try:
                if "schema" in raw or "failure_cid" in raw:
                    items.append(DetectionFailure.from_dict(raw))
                else:
                    items.append(DetectionFailure(**dict(raw)))  # type: ignore[arg-type]
            except (AnalysisContractError, TypeError, KeyError) as exc:
                raise GapClassificationError(
                    f"failures[{index}] is malformed: {exc}"
                ) from exc
        else:
            raise GapClassificationError(
                f"failures[{index}] must be DetectionFailure or mapping"
            )
    return tuple(sorted(items, key=lambda item: item.detector_id))


def _entries_by_cause(
    entries: Sequence[DetectionComparisonEntry],
) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {
        cause.value: [] for cause in AssuranceGapCause
    }
    for item in entries:
        if item.cause in buckets:
            buckets[item.cause].append(item.detector_id)
    return {key: tuple(sorted(value)) for key, value in buckets.items()}


def _derive_primary_cause(
    *,
    not_selected: Sequence[str],
    not_executed: Sequence[str],
    path_unobserved: Sequence[str],
    weak_property: Sequence[str],
    dependency_omission: Sequence[str],
    capsule_omission: Sequence[str],
    unexpected: Sequence[str],
    observed_ok: Sequence[str],
    entries: Sequence[DetectionComparisonEntry],
) -> str:
    """Derive the dominant comparison cause from partitioned detector IDs."""

    present: dict[str, bool] = {
        AssuranceGapCause.DEPENDENCY_OMISSION.value: bool(dependency_omission),
        AssuranceGapCause.CAPSULE_OMISSION.value: bool(capsule_omission),
        AssuranceGapCause.NOT_SELECTED.value: bool(not_selected),
        AssuranceGapCause.NOT_EXECUTED.value: bool(not_executed),
        AssuranceGapCause.PATH_UNOBSERVED.value: bool(path_unobserved),
        AssuranceGapCause.WEAK_PROPERTY.value: bool(weak_property),
    }
    # Equivalence / intentional / unspecified never arise from detector roles
    # alone; they are overall subject signals applied by classify_assurance_gap.
    for cause in (
        AssuranceGapCause.DEPENDENCY_OMISSION.value,
        AssuranceGapCause.CAPSULE_OMISSION.value,
        AssuranceGapCause.NOT_SELECTED.value,
        AssuranceGapCause.NOT_EXECUTED.value,
        AssuranceGapCause.PATH_UNOBSERVED.value,
        AssuranceGapCause.WEAK_PROPERTY.value,
    ):
        if present.get(cause):
            return cause
    # Unexpected observations without predicted misses → unknown (needs review).
    if unexpected and not observed_ok:
        return AssuranceGapCause.UNKNOWN.value
    if unexpected:
        return AssuranceGapCause.UNKNOWN.value
    # All predicted detectors observed, no residual miss.
    if observed_ok and not any(present.values()):
        # Perfect match still gets a neutral primary of unknown only if entries
        # exist with explicit unknown; otherwise treat as no gap signal and keep
        # primary as unknown for roll-up (classify may override).
        unknown_entries = [
            item
            for item in entries
            if item.cause == AssuranceGapCause.UNKNOWN.value
        ]
        if unknown_entries:
            return AssuranceGapCause.UNKNOWN.value
        # No miss: primary_cause is unknown only as "no detection-gap cause";
        # classify_assurance_gap elevates intentional/equivalence/etc.
        return AssuranceGapCause.UNKNOWN.value
    return AssuranceGapCause.UNKNOWN.value


# ---------------------------------------------------------------------------
# GapClassificationSubject — inputs for classify_assurance_gap
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GapClassificationSubject:
    """Bound inputs for rolling a comparison into one AssuranceGap.

    Carries survivor context plus optional equivalence / intentional /
    unspecified signals that cannot be derived from detector roles alone.
    """

    candidate_id: str
    candidate_cid: str
    risk_class: SurvivorRiskClass | str
    violated_or_missing_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    header: AssuranceArtifactHeader | Mapping[str, Any]
    gap_id: str
    survivor_report_cid: str | None = None
    equivalence_status: EquivalenceAssessmentStatus | str | None = None
    intentionally_unconstrained: bool = False
    specification_ambiguous: bool = False
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "candidate_id",
            "candidate_cid",
            "risk_class",
            "violated_or_missing_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "header",
            "gap_id",
            "survivor_report_cid",
            "equivalence_status",
            "intentionally_unconstrained",
            "specification_ambiguous",
            "observation_complete",
            "notes",
            "metadata",
            "subject_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, SurvivorRiskClass, "risk_class"),
        )
        object.__setattr__(
            self,
            "violated_or_missing_property",
            _text(
                self.violated_or_missing_property,
                "violated_or_missing_property",
            ),
        )
        symbols = _unique_sorted_tokens(
            list(self.symbol_ids), "symbol_ids", symbol=True
        )
        if not symbols:
            raise GapClassificationError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(
            self, "source_spans", _normalize_source_spans(list(self.source_spans))
        )
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise GapClassificationError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        object.__setattr__(self, "header", _header(self.header))
        object.__setattr__(self, "gap_id", _token(self.gap_id, "gap_id"))
        object.__setattr__(
            self,
            "survivor_report_cid",
            _optional_cid(self.survivor_report_cid, "survivor_report_cid"),
        )
        status = self.equivalence_status
        if status is not None:
            status = _enum(
                status, EquivalenceAssessmentStatus, "equivalence_status"
            )
        object.__setattr__(self, "equivalence_status", status)
        object.__setattr__(
            self,
            "intentionally_unconstrained",
            _bool(self.intentionally_unconstrained, "intentionally_unconstrained"),
        )
        object.__setattr__(
            self,
            "specification_ambiguous",
            _bool(self.specification_ambiguous, "specification_ambiguous"),
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GAP_CLASSIFICATION_SUBJECT_SCHEMA,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "risk_class": self.risk_class,
            "violated_or_missing_property": self.violated_or_missing_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "header": self.header.identity_payload(),
            "gap_id": self.gap_id,
            "survivor_report_cid": self.survivor_report_cid,
            "equivalence_status": self.equivalence_status,
            "intentionally_unconstrained": self.intentionally_unconstrained,
            "specification_ambiguous": self.specification_ambiguous,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GAP_CLASSIFICATION_SUBJECT_SCHEMA,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "risk_class": self.risk_class,
            "violated_or_missing_property": self.violated_or_missing_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.to_dict() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "header": self.header.to_dict(),
            "gap_id": self.gap_id,
            "survivor_report_cid": self.survivor_report_cid,
            "equivalence_status": self.equivalence_status,
            "intentionally_unconstrained": self.intentionally_unconstrained,
            "specification_ambiguous": self.specification_ambiguous,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "subject_cid": self.subject_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GapClassificationSubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_cid")
        if payload.pop("schema") != GAP_CLASSIFICATION_SUBJECT_SCHEMA:
            raise GapClassificationError(
                "unsupported GapClassificationSubject schema version"
            )
        result = cls(
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            risk_class=payload["risk_class"],
            violated_or_missing_property=payload["violated_or_missing_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            header=payload["header"],
            gap_id=payload["gap_id"],
            survivor_report_cid=payload["survivor_report_cid"],
            equivalence_status=payload["equivalence_status"],
            intentionally_unconstrained=payload["intentionally_unconstrained"],
            specification_ambiguous=payload["specification_ambiguous"],
            observation_complete=payload["observation_complete"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.subject_cid:
            raise GapClassificationError(
                "GapClassificationSubject subject_cid identity mismatch"
            )
        return result


def _normalize_subject(
    value: GapClassificationSubject | Mapping[str, Any],
    name: str = "subject",
) -> GapClassificationSubject:
    if isinstance(value, GapClassificationSubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_cid" in value:
            return GapClassificationSubject.from_dict(value)
        return GapClassificationSubject(
            candidate_id=value["candidate_id"],
            candidate_cid=value["candidate_cid"],
            risk_class=value["risk_class"],
            violated_or_missing_property=value["violated_or_missing_property"],
            symbol_ids=value["symbol_ids"],
            source_spans=value["source_spans"],
            dependency_path=value["dependency_path"],
            minimized_evidence=value["minimized_evidence"],
            header=value["header"],
            gap_id=value["gap_id"],
            survivor_report_cid=value.get("survivor_report_cid"),
            equivalence_status=value.get("equivalence_status"),
            intentionally_unconstrained=value.get(
                "intentionally_unconstrained", False
            ),
            specification_ambiguous=value.get("specification_ambiguous", False),
            observation_complete=value.get("observation_complete", True),
            notes=value.get("notes"),
            metadata=value.get("metadata", {}),
        )
    raise GapClassificationError(
        f"{name} must be GapClassificationSubject or mapping"
    )


def _normalize_comparison(
    value: DetectionComparisonResult | Mapping[str, Any],
    name: str = "comparison",
) -> DetectionComparisonResult:
    if isinstance(value, DetectionComparisonResult):
        return value
    if isinstance(value, Mapping):
        return DetectionComparisonResult.from_dict(value)
    raise GapClassificationError(
        f"{name} must be DetectionComparisonResult or mapping"
    )


# ---------------------------------------------------------------------------
# Cause → failure_kind / gap_class mapping
# ---------------------------------------------------------------------------


def _executed_miss_cause(
    observation: DetectorObservation | None,
) -> tuple[str, str]:
    """Choose cause + DetectionFailureKind for an executed-but-not-observed detector."""

    if observation is not None and not observation.dependency_edge_present:
        return (
            AssuranceGapCause.DEPENDENCY_OMISSION.value,
            DetectionFailureKind.PATH_MISS.value,
        )
    if observation is not None and not observation.capsule_complete:
        return (
            AssuranceGapCause.CAPSULE_OMISSION.value,
            DetectionFailureKind.PATH_MISS.value,
        )
    if observation is not None and not observation.assertion_strength_adequate:
        return (
            AssuranceGapCause.WEAK_PROPERTY.value,
            DetectionFailureKind.ASSERTION_STRENGTH_FAILURE.value,
        )
    if observation is not None and not observation.path_observed:
        return (
            AssuranceGapCause.PATH_UNOBSERVED.value,
            DetectionFailureKind.PATH_MISS.value,
        )
    # Default residual executed miss: path/observation miss.
    return (
        AssuranceGapCause.PATH_UNOBSERVED.value,
        DetectionFailureKind.OBSERVATION_MISS.value,
    )


def cause_to_gap_class(
    cause: AssuranceGapCause | str,
    *,
    detector_kind: DetectorKind | str | None = None,
) -> str:
    """Map a closed intermediate cause onto the plan §5 AssuranceGapClass."""

    normalized = _enum(cause, AssuranceGapCause, "cause")
    kind: str | None = None
    if detector_kind is not None:
        kind = _enum(detector_kind, DetectorKind, "detector_kind")

    if normalized == AssuranceGapCause.NOT_SELECTED.value:
        return AssuranceGapClass.TEST_SELECTION_FAILURE.value
    if normalized == AssuranceGapCause.NOT_EXECUTED.value:
        if kind in _PROOF_LIKE_KINDS:
            return AssuranceGapClass.MISSING_PROOF_OBLIGATION.value
        if kind in _POLICY_LIKE_KINDS:
            return AssuranceGapClass.MISSING_POLICY_CONSTRAINT.value
        return AssuranceGapClass.MISSING_TEST.value
    if normalized == AssuranceGapCause.PATH_UNOBSERVED.value:
        if kind in _PROOF_LIKE_KINDS:
            return AssuranceGapClass.MISSING_PROOF_OBLIGATION.value
        if kind in _POLICY_LIKE_KINDS:
            return AssuranceGapClass.MISSING_POLICY_CONSTRAINT.value
        if kind in _TEST_LIKE_KINDS or kind is None:
            return AssuranceGapClass.MISSING_TEST.value
        return AssuranceGapClass.UNMODELED_SIDE_EFFECT.value
    if normalized == AssuranceGapCause.WEAK_PROPERTY.value:
        return AssuranceGapClass.WEAK_ASSERTION.value
    if normalized == AssuranceGapCause.DEPENDENCY_OMISSION.value:
        return AssuranceGapClass.STALE_OR_INCOMPLETE_DEPENDENCY_EDGE.value
    if normalized == AssuranceGapCause.CAPSULE_OMISSION.value:
        return AssuranceGapClass.CAPSULE_COMPLETENESS_FAILURE.value
    if normalized == AssuranceGapCause.UNSPECIFIED.value:
        return AssuranceGapClass.SPECIFICATION_AMBIGUITY.value
    if normalized == AssuranceGapCause.INTENTIONAL.value:
        return AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value
    if normalized == AssuranceGapCause.EQUIVALENCE.value:
        return AssuranceGapClass.PROBABLY_EQUIVALENT.value
    return AssuranceGapClass.UNKNOWN.value


def _severity_for_risk(risk_class: str, cause: str) -> str:
    base = _RISK_TO_SEVERITY.get(risk_class, GapSeverity.MEDIUM.value)
    if cause in {
        AssuranceGapCause.EQUIVALENCE.value,
        AssuranceGapCause.INTENTIONAL.value,
    }:
        return GapSeverity.INFORMATIONAL.value
    if cause == AssuranceGapCause.UNSPECIFIED.value:
        return GapSeverity.MEDIUM.value
    if cause == AssuranceGapCause.UNKNOWN.value:
        # Preserve risk-driven severity but force review.
        return base
    return base


def _summary_for_cause(
    cause: str,
    *,
    candidate_id: str,
    property_text: str,
    detector_ids: Sequence[str],
) -> str:
    detectors = ", ".join(detector_ids) if detector_ids else "(none)"
    templates = {
        AssuranceGapCause.NOT_SELECTED.value: (
            f"predicted detectors were not selected for {candidate_id}: "
            f"{detectors}; property: {property_text}"
        ),
        AssuranceGapCause.NOT_EXECUTED.value: (
            f"selected detectors were not executed for {candidate_id}: "
            f"{detectors}; property: {property_text}"
        ),
        AssuranceGapCause.PATH_UNOBSERVED.value: (
            f"executed detectors did not observe the mutated path for "
            f"{candidate_id}: {detectors}; property: {property_text}"
        ),
        AssuranceGapCause.WEAK_PROPERTY.value: (
            f"detectors observed with inadequate assertion strength for "
            f"{candidate_id}: {detectors}; property: {property_text}"
        ),
        AssuranceGapCause.DEPENDENCY_OMISSION.value: (
            f"dependency edge omission prevented observation for "
            f"{candidate_id}: {detectors}; property: {property_text}"
        ),
        AssuranceGapCause.CAPSULE_OMISSION.value: (
            f"capsule completeness failure prevented observation for "
            f"{candidate_id}: {detectors}; property: {property_text}"
        ),
        AssuranceGapCause.UNSPECIFIED.value: (
            f"specification ambiguity leaves property unconstrained for "
            f"{candidate_id}: {property_text}"
        ),
        AssuranceGapCause.INTENTIONAL.value: (
            f"behavior is intentionally unconstrained for {candidate_id}: "
            f"{property_text}"
        ),
        AssuranceGapCause.EQUIVALENCE.value: (
            f"mutant assessed equivalent/probably_equivalent for "
            f"{candidate_id}; property: {property_text}"
        ),
        AssuranceGapCause.UNKNOWN.value: (
            f"unknown assurance gap for {candidate_id}; property: "
            f"{property_text}; detectors: {detectors}"
        ),
    }
    return templates[cause]


# ---------------------------------------------------------------------------
# compare_detection_sets
# ---------------------------------------------------------------------------


def compare_detection_sets(
    expected: ExpectedDetectionSet | Mapping[str, Any],
    classification: DetectorClassification | Mapping[str, Any],
    *,
    header: AssuranceArtifactHeader | Mapping[str, Any],
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any],
    detector_observations: Sequence[DetectorObservation | Mapping[str, Any]]
    | None = None,
    outcome_cid: str | None = None,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DetectionComparisonResult:
    """Compare predicted detectors against selected/executed/observed roles.

    Interface: ``compare_detection_sets@1``

    For every predicted detector, classifies the residual miss (if any) into
    the closed cause taxonomy:

    * ``not_selected`` — predicted but not selected
    * ``not_executed`` — selected but not executed
    * ``path_unobserved`` — executed but path/observation miss
    * ``weak_property`` — executed with inadequate assertion strength
    * ``dependency_omission`` / ``capsule_omission`` — structural omission
      annotations on the observation

    Unexpected observed detectors are recorded separately. Fail-closed when
    classification nesting invariants or identity mismatches are violated.
    """

    sealed_expected = _normalize_expected(expected)
    sealed_class = _normalize_classification(classification)
    base_header = _header(header)
    evidence = _normalize_evidence(minimized_evidence)
    observations = _normalize_observations(detector_observations)
    observation_by_id = {item.detector_id: item for item in observations}
    outcome = _optional_cid(outcome_cid, "outcome_cid")

    predicted_ids = set(sealed_expected.predicted_detector_ids)
    class_predicted = set(sealed_class.predicted_detector_ids)
    if predicted_ids != class_predicted:
        raise GapClassificationError(
            "classification.predicted_detector_ids must equal "
            "expected.predicted_detector_ids"
        )

    selected = set(sealed_class.selected_detector_ids)
    executed = set(sealed_class.executed_detector_ids)
    observed = set(sealed_class.observed_detector_ids)

    # Fail closed if classification claims selected/executed/observed detectors
    # that violate nesting (DetectorClassification already enforces this, but
    # re-check after set construction).
    if not executed.issubset(selected):
        raise GapClassificationError("executed must be a subset of selected")
    if not observed.issubset(executed):
        raise GapClassificationError("observed must be a subset of executed")

    failure_header = _artifact_header(
        base_header,
        artifact_kind="detection_failure",
        interface_id=COMPARE_DETECTION_SETS_INTERFACE,
        symbol_ids=base_header.target_symbol_ids,
    )

    entries: list[DetectionComparisonEntry] = []
    failures: list[DetectionFailure] = []

    prediction_by_id: dict[str, DetectorPrediction] = {
        item.detector_id: item for item in sealed_expected.predicted_detectors
    }

    # --- predicted detectors ---
    for detector_id in sorted(predicted_ids):
        prediction = prediction_by_id[detector_id]
        is_selected = detector_id in selected
        is_executed = detector_id in executed
        is_observed = detector_id in observed
        path = tuple(prediction.dependency_path)
        kind = prediction.detector_kind

        if not is_selected:
            cause = AssuranceGapCause.NOT_SELECTED.value
            failure_kind = DetectionFailureKind.SELECTION_MISS.value
            summary = (
                f"predicted detector {detector_id} was not selected for "
                f"candidate {sealed_expected.candidate_id}"
            )
        elif not is_executed:
            cause = AssuranceGapCause.NOT_EXECUTED.value
            failure_kind = DetectionFailureKind.EXECUTION_MISS.value
            summary = (
                f"selected detector {detector_id} was not executed for "
                f"candidate {sealed_expected.candidate_id}"
            )
        elif not is_observed:
            obs = observation_by_id.get(detector_id)
            cause, failure_kind = _executed_miss_cause(obs)
            if cause == AssuranceGapCause.WEAK_PROPERTY.value:
                summary = (
                    f"detector {detector_id} executed with weak property "
                    f"assertion for candidate {sealed_expected.candidate_id}"
                )
            elif cause == AssuranceGapCause.DEPENDENCY_OMISSION.value:
                summary = (
                    f"detector {detector_id} missed due to dependency omission "
                    f"for candidate {sealed_expected.candidate_id}"
                )
            elif cause == AssuranceGapCause.CAPSULE_OMISSION.value:
                summary = (
                    f"detector {detector_id} missed due to capsule omission "
                    f"for candidate {sealed_expected.candidate_id}"
                )
            else:
                summary = (
                    f"detector {detector_id} executed but path was unobserved "
                    f"for candidate {sealed_expected.candidate_id}"
                )
        else:
            # Predicted and observed — no failure.
            entries.append(
                DetectionComparisonEntry(
                    detector_id=detector_id,
                    cause=AssuranceGapCause.UNKNOWN.value,
                    predicted=True,
                    selected=is_selected,
                    executed=is_executed,
                    observed=True,
                    failure_kind=None,
                    dependency_path=path,
                    summary=(
                        f"detector {detector_id} predicted and observed for "
                        f"candidate {sealed_expected.candidate_id}"
                    ),
                    detector_kind=kind,
                    notes=None,
                    metadata={"role": "observed_as_predicted"},
                )
            )
            continue

        entry = DetectionComparisonEntry(
            detector_id=detector_id,
            cause=cause,
            predicted=True,
            selected=is_selected,
            executed=is_executed,
            observed=is_observed,
            failure_kind=failure_kind,
            dependency_path=path,
            summary=summary,
            detector_kind=kind,
            notes=None,
            metadata={"role": "predicted_miss"},
        )
        entries.append(entry)

        failure_id = f"detfail.{cause}.{detector_id}"
        # failure_id must match token regex (already lowercase with dots).
        failures.append(
            DetectionFailure(
                header=failure_header,
                failure_id=failure_id,
                failure_kind=failure_kind,
                candidate_id=sealed_expected.candidate_id,
                candidate_cid=sealed_expected.candidate_cid,
                detector_id=detector_id,
                predicted=True,
                selected=is_selected,
                executed=is_executed,
                observed=is_observed,
                summary=summary,
                dependency_path=path,
                minimized_evidence=evidence,
                expected_detection_set_cid=sealed_expected.detection_set_cid,
                outcome_cid=outcome,
                notes=None,
                metadata={
                    "cause": cause,
                    "detector_kind": kind,
                },
            )
        )

    # --- unexpected observed detectors ---
    for detector_id in sorted(observed - predicted_ids):
        summary = (
            f"detector {detector_id} was observed but not predicted for "
            f"candidate {sealed_expected.candidate_id}"
        )
        path = (detector_id,)
        entries.append(
            DetectionComparisonEntry(
                detector_id=detector_id,
                cause=AssuranceGapCause.UNKNOWN.value,
                predicted=False,
                selected=detector_id in selected,
                executed=detector_id in executed,
                observed=True,
                failure_kind=DetectionFailureKind.UNEXPECTED_OBSERVED.value,
                dependency_path=path,
                summary=summary,
                detector_kind=None,
                notes=None,
                metadata={"role": "unexpected_observed"},
            )
        )
        failures.append(
            DetectionFailure(
                header=failure_header,
                failure_id=f"detfail.unexpected.{detector_id}",
                failure_kind=DetectionFailureKind.UNEXPECTED_OBSERVED.value,
                candidate_id=sealed_expected.candidate_id,
                candidate_cid=sealed_expected.candidate_cid,
                detector_id=detector_id,
                predicted=False,
                selected=detector_id in selected,
                executed=detector_id in executed,
                observed=True,
                summary=summary,
                dependency_path=path,
                minimized_evidence=evidence,
                expected_detection_set_cid=sealed_expected.detection_set_cid,
                outcome_cid=outcome,
                notes=None,
                metadata={"cause": AssuranceGapCause.UNKNOWN.value},
            )
        )

    entries_sorted = tuple(sorted(entries, key=lambda item: item.detector_id))
    failures_sorted = tuple(sorted(failures, key=lambda item: item.detector_id))
    by_cause = _entries_by_cause(entries_sorted)

    not_selected = by_cause[AssuranceGapCause.NOT_SELECTED.value]
    not_executed = by_cause[AssuranceGapCause.NOT_EXECUTED.value]
    path_unobserved = by_cause[AssuranceGapCause.PATH_UNOBSERVED.value]
    weak_property = by_cause[AssuranceGapCause.WEAK_PROPERTY.value]
    dependency_omission = by_cause[AssuranceGapCause.DEPENDENCY_OMISSION.value]
    capsule_omission = by_cause[AssuranceGapCause.CAPSULE_OMISSION.value]
    unexpected_ids = tuple(
        sorted(
            item.detector_id
            for item in entries_sorted
            if item.failure_kind
            == DetectionFailureKind.UNEXPECTED_OBSERVED.value
        )
    )
    observed_ok = tuple(
        sorted(
            item.detector_id
            for item in entries_sorted
            if item.predicted and item.observed and item.failure_kind is None
        )
    )
    primary = _derive_primary_cause(
        not_selected=not_selected,
        not_executed=not_executed,
        path_unobserved=path_unobserved,
        weak_property=weak_property,
        dependency_omission=dependency_omission,
        capsule_omission=capsule_omission,
        unexpected=unexpected_ids,
        observed_ok=observed_ok,
        entries=entries_sorted,
    )

    result_metadata = dict(metadata or {})
    result_metadata.setdefault(
        "expected_detection_set_id", sealed_expected.detection_set_id
    )
    result_metadata.setdefault("generator_id", GENERATOR_ID)
    result_metadata.setdefault("generator_version", GENERATOR_VERSION)

    return DetectionComparisonResult(
        interface_id=COMPARE_DETECTION_SETS_INTERFACE,
        candidate_id=sealed_expected.candidate_id,
        candidate_cid=sealed_expected.candidate_cid,
        expected_detection_set_cid=sealed_expected.detection_set_cid,
        classification_cid=sealed_class.classification_cid,
        entries=entries_sorted,
        failures=failures_sorted,
        not_selected_detector_ids=not_selected,
        not_executed_detector_ids=not_executed,
        path_unobserved_detector_ids=path_unobserved,
        weak_property_detector_ids=weak_property,
        dependency_omission_detector_ids=dependency_omission,
        capsule_omission_detector_ids=capsule_omission,
        unexpected_detector_ids=unexpected_ids,
        observed_as_predicted_detector_ids=observed_ok,
        primary_cause=primary,
        notes=_optional_text(notes, "notes") if notes is not None else None,
        metadata=result_metadata,
    )


# ---------------------------------------------------------------------------
# classify_assurance_gap
# ---------------------------------------------------------------------------


def classify_assurance_gap(
    subject: GapClassificationSubject | Mapping[str, Any],
    comparison: DetectionComparisonResult | Mapping[str, Any] | None = None,
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssuranceGap:
    """Classify one assurance gap from comparison causes and subject signals.

    Interface: ``classify_assurance_gap@1``

    Decision priority (first match wins):

    1. equivalence assessment (``equivalent`` / ``probably_equivalent``)
    2. intentionally unconstrained
    3. specification ambiguity (unspecified)
    4. dependency omission
    5. capsule omission
    6. not-selected
    7. not-executed
    8. path-unobserved
    9. weak-property
    10. unknown (always requires human review)

    Incomplete observation fails closed. Unknown never silently drops review.
    """

    sealed_subject = _normalize_subject(subject)
    if not sealed_subject.observation_complete:
        raise GapClassificationError(
            "classify_assurance_gap fails closed when observation_complete is false"
        )

    sealed_comparison: DetectionComparisonResult | None = None
    if comparison is not None:
        sealed_comparison = _normalize_comparison(comparison)
        if sealed_comparison.candidate_id != sealed_subject.candidate_id:
            raise GapClassificationError(
                "comparison.candidate_id must match subject.candidate_id"
            )
        if sealed_comparison.candidate_cid != sealed_subject.candidate_cid:
            raise GapClassificationError(
                "comparison.candidate_cid must match subject.candidate_cid"
            )

    cause = _resolve_overall_cause(sealed_subject, sealed_comparison)
    detector_kind = _primary_detector_kind(sealed_comparison, cause)
    gap_class = cause_to_gap_class(cause, detector_kind=detector_kind)
    severity = _severity_for_risk(sealed_subject.risk_class, cause)
    requires_review = cause in _HUMAN_REVIEW_CAUSES or gap_class == (
        AssuranceGapClass.UNKNOWN.value
    )

    detector_ids = _detectors_for_cause(sealed_comparison, cause)
    summary = _summary_for_cause(
        cause,
        candidate_id=sealed_subject.candidate_id,
        property_text=sealed_subject.violated_or_missing_property,
        detector_ids=detector_ids,
    )
    if notes is not None:
        note_text = _optional_text(notes, "notes")
    else:
        note_text = sealed_subject.notes

    gap_header = _artifact_header(
        sealed_subject.header,
        artifact_kind="assurance_gap",
        interface_id=CLASSIFY_ASSURANCE_GAP_INTERFACE,
        symbol_ids=sealed_subject.symbol_ids,
    )

    failure_cids: tuple[str, ...] = ()
    if sealed_comparison is not None:
        # Bind failures that share the selected cause (or all when unknown).
        if cause == AssuranceGapCause.UNKNOWN.value:
            failure_cids = sealed_comparison.failure_cids
        else:
            matching = [
                item.failure_cid
                for item in sealed_comparison.failures
                if item.metadata.get("cause") == cause
                or _failure_matches_cause(item, cause)
            ]
            failure_cids = tuple(sorted(set(matching)))

    gap_metadata = dict(sealed_subject.metadata)
    if metadata:
        gap_metadata.update(dict(metadata))
    gap_metadata["cause"] = cause
    gap_metadata["gap_class"] = gap_class
    if sealed_comparison is not None:
        gap_metadata["comparison_result_cid"] = sealed_comparison.result_cid
        gap_metadata["comparison_primary_cause"] = sealed_comparison.primary_cause
    if sealed_subject.equivalence_status is not None:
        gap_metadata["equivalence_status"] = sealed_subject.equivalence_status
    gap_metadata["generator_id"] = GENERATOR_ID
    gap_metadata["generator_version"] = GENERATOR_VERSION

    gap = AssuranceGap(
        header=gap_header,
        gap_id=sealed_subject.gap_id,
        gap_class=gap_class,
        severity=severity,
        risk_class=sealed_subject.risk_class,
        summary=summary,
        candidate_id=sealed_subject.candidate_id,
        candidate_cid=sealed_subject.candidate_cid,
        survivor_report_cid=sealed_subject.survivor_report_cid,
        violated_or_missing_property=sealed_subject.violated_or_missing_property,
        symbol_ids=sealed_subject.symbol_ids,
        source_spans=sealed_subject.source_spans,
        dependency_path=sealed_subject.dependency_path,
        minimized_evidence=sealed_subject.minimized_evidence,
        requires_human_review=requires_review,
        detection_failure_cids=failure_cids,
        vacuity_finding_cids=(),
        notes=note_text,
        metadata=gap_metadata,
    )
    verify_gap_identity(gap)
    return gap


def _resolve_overall_cause(
    subject: GapClassificationSubject,
    comparison: DetectionComparisonResult | None,
) -> str:
    """Apply the closed priority order across subject signals and comparison."""

    # 1. Equivalence
    if subject.equivalence_status in {
        EquivalenceAssessmentStatus.EQUIVALENT.value,
        EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
    }:
        return AssuranceGapCause.EQUIVALENCE.value

    # 2. Intentional
    if subject.intentionally_unconstrained:
        return AssuranceGapCause.INTENTIONAL.value

    # 3. Unspecified / specification ambiguity
    if subject.specification_ambiguous:
        return AssuranceGapCause.UNSPECIFIED.value

    if comparison is None:
        return AssuranceGapCause.UNKNOWN.value

    # 4–9. Comparison-derived causes in priority order.
    present = {
        AssuranceGapCause.DEPENDENCY_OMISSION.value: bool(
            comparison.dependency_omission_detector_ids
        ),
        AssuranceGapCause.CAPSULE_OMISSION.value: bool(
            comparison.capsule_omission_detector_ids
        ),
        AssuranceGapCause.NOT_SELECTED.value: bool(
            comparison.not_selected_detector_ids
        ),
        AssuranceGapCause.NOT_EXECUTED.value: bool(
            comparison.not_executed_detector_ids
        ),
        AssuranceGapCause.PATH_UNOBSERVED.value: bool(
            comparison.path_unobserved_detector_ids
        ),
        AssuranceGapCause.WEAK_PROPERTY.value: bool(
            comparison.weak_property_detector_ids
        ),
    }
    for cause in _CAUSE_PRIORITY:
        if cause in present and present[cause]:
            return cause

    # Unexpected-only or fully-observed residual.
    if comparison.unexpected_detector_ids:
        return AssuranceGapCause.UNKNOWN.value
    return AssuranceGapCause.UNKNOWN.value


def _detectors_for_cause(
    comparison: DetectionComparisonResult | None,
    cause: str,
) -> tuple[str, ...]:
    if comparison is None:
        return ()
    mapping = {
        AssuranceGapCause.NOT_SELECTED.value: comparison.not_selected_detector_ids,
        AssuranceGapCause.NOT_EXECUTED.value: comparison.not_executed_detector_ids,
        AssuranceGapCause.PATH_UNOBSERVED.value: comparison.path_unobserved_detector_ids,
        AssuranceGapCause.WEAK_PROPERTY.value: comparison.weak_property_detector_ids,
        AssuranceGapCause.DEPENDENCY_OMISSION.value: (
            comparison.dependency_omission_detector_ids
        ),
        AssuranceGapCause.CAPSULE_OMISSION.value: (
            comparison.capsule_omission_detector_ids
        ),
    }
    if cause in mapping:
        return tuple(mapping[cause])
    if cause == AssuranceGapCause.UNKNOWN.value:
        return tuple(
            sorted(
                set(comparison.unexpected_detector_ids)
                | {
                    item.detector_id
                    for item in comparison.entries
                    if item.failure_kind is not None
                }
            )
        )
    return ()


def _primary_detector_kind(
    comparison: DetectionComparisonResult | None,
    cause: str,
) -> str | None:
    if comparison is None:
        return None
    target_ids = set(_detectors_for_cause(comparison, cause))
    if not target_ids:
        return None
    for item in comparison.entries:
        if item.detector_id in target_ids and item.detector_kind is not None:
            return item.detector_kind
    return None


def _failure_matches_cause(failure: DetectionFailure, cause: str) -> bool:
    kind = failure.failure_kind
    if cause == AssuranceGapCause.NOT_SELECTED.value:
        return kind == DetectionFailureKind.SELECTION_MISS.value
    if cause == AssuranceGapCause.NOT_EXECUTED.value:
        return kind == DetectionFailureKind.EXECUTION_MISS.value
    if cause == AssuranceGapCause.PATH_UNOBSERVED.value:
        return kind in {
            DetectionFailureKind.PATH_MISS.value,
            DetectionFailureKind.OBSERVATION_MISS.value,
            DetectionFailureKind.EXPECTED_NOT_OBSERVED.value,
        }
    if cause == AssuranceGapCause.WEAK_PROPERTY.value:
        return kind == DetectionFailureKind.ASSERTION_STRENGTH_FAILURE.value
    if cause in {
        AssuranceGapCause.DEPENDENCY_OMISSION.value,
        AssuranceGapCause.CAPSULE_OMISSION.value,
    }:
        return kind == DetectionFailureKind.PATH_MISS.value
    return False


# ---------------------------------------------------------------------------
# Vocabulary / identity helpers
# ---------------------------------------------------------------------------


def assurance_gap_causes() -> tuple[str, ...]:
    """Return the closed intermediate gap-cause vocabulary in declaration order."""

    return tuple(item.value for item in AssuranceGapCause)


def verify_detection_comparison_result_identity(
    result: DetectionComparisonResult | Mapping[str, Any],
) -> str:
    """Recompute and return the comparison result CID; raise on forged input."""

    if isinstance(result, DetectionComparisonResult):
        sealed = result
    elif isinstance(result, Mapping):
        sealed = DetectionComparisonResult.from_dict(result)
    else:
        raise GapClassificationError(
            "result must be DetectionComparisonResult or mapping"
        )
    for failure in sealed.failures:
        verify_detection_failure_identity(failure)
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.result_cid:
        raise GapClassificationError(
            "result_cid identity mismatch with recomputed identity"
        )
    return recomputed


__all__ = [
    "CLASSIFY_ASSURANCE_GAP_INTERFACE",
    "COMPARE_DETECTION_SETS_INTERFACE",
    "DETECTION_COMPARISON_ENTRY_SCHEMA",
    "DETECTION_COMPARISON_RESULT_INTERFACE",
    "DETECTION_COMPARISON_RESULT_SCHEMA",
    "DETECTOR_OBSERVATION_SCHEMA",
    "GAP_CLASSIFICATION_SUBJECT_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "AssuranceGapCause",
    "DetectionComparisonEntry",
    "DetectionComparisonResult",
    "DetectorObservation",
    "GapClassificationError",
    "GapClassificationSubject",
    "assurance_gap_causes",
    "cause_to_gap_class",
    "classify_assurance_gap",
    "compare_detection_sets",
    "verify_detection_comparison_result_identity",
]
