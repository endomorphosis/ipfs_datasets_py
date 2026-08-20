"""Diagnose surviving mutants with product versus assurance distinctions (AAE-030).

Interface surface:

* ``diagnose_surviving_mutant@1`` — walk the required nine-step decision path
  for one surviving mutant and seal a ``SurvivorDiagnosis@1`` that separates
  product defects from assurance gaps.

Nine-step decision path (plan §9; fixed order, always recorded):

1. equivalence
2. detector selection
3. detector execution
4. path observation
5. assertion strength
6. dependency omission
7. capsule omission
8. unspecified or intentionally unconstrained behavior
9. need for human judgment

Authority rules (normative):

* Pure and deterministic: no store, worktree, or production-policy mutation.
* Canonical identity comes only from ``software_contracts.content``.
* Survival is an assurance-gap *candidate*, never automatically a product defect.
* Difficulty to kill never implies equivalence and is never treated as evidence.
* Incomplete observation fails closed.
* Closed taxonomies fail closed on unknowns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence
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
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AnalysisContractError,
    AssuranceGapClass,
    GapSeverity,
    MinimizedEvidenceBinding,
    SourceSpan,
    SurvivorRiskClass,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    EquivalenceAssessmentStatus,
    MutationOutcomeStatus,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.gaps import (
    AssuranceGapCause,
    DetectionComparisonResult,
    GapClassificationError,
    cause_to_gap_class,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

DIAGNOSE_SURVIVING_MUTANT_INTERFACE: Final[str] = "diagnose_surviving_mutant@1"

DIAGNOSIS_MUTATION_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-diagnosis-mutation-binding@1"
)
DIAGNOSIS_OUTCOME_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-diagnosis-outcome-binding@1"
)
DIAGNOSIS_SIGNALS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-diagnosis-signals@1"
)
DIAGNOSIS_STEP_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-diagnosis-step-result@1"
)
SURVIVOR_DIAGNOSIS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-survivor-diagnosis@1"
)
SURVIVOR_DIAGNOSIS_INTERFACE: Final[str] = "SurvivorDiagnosis@1"

GENERATOR_ID: Final[str] = "survivor_diagnosis"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_LIST: Final[int] = 1_024
MAX_SPANS: Final[int] = 256
MAX_DEPENDENCY_PATH: Final[int] = 256
MAX_DETECTORS: Final[int] = 1_024

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)

# Outcome statuses that count as survival for diagnosis admission.
_SURVIVOR_OUTCOME_STATUSES: Final[frozenset[str]] = frozenset(
    {
        MutationOutcomeStatus.SURVIVED_SELECTED_VERIFICATION.value,
        MutationOutcomeStatus.SURVIVED_FULL_VERIFICATION.value,
        MutationOutcomeStatus.HUMAN_REVIEW_REQUIRED.value,
        # Equivalent outcomes may still be "diagnosed" as non-defects.
        MutationOutcomeStatus.EQUIVALENT.value,
        MutationOutcomeStatus.PROBABLY_EQUIVALENT.value,
    }
)

# Risk → default severity for assurance-gap dispositions.
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


class DiagnosisError(AssuranceBaseError):
    """Raised when survivor diagnosis fails closed."""


class DiagnosisStepId(str, Enum):
    """Closed nine-step decision path (plan §9)."""

    EQUIVALENCE = "equivalence"
    DETECTOR_SELECTION = "detector_selection"
    DETECTOR_EXECUTION = "detector_execution"
    PATH_OBSERVATION = "path_observation"
    ASSERTION_STRENGTH = "assertion_strength"
    DEPENDENCY_OMISSION = "dependency_omission"
    CAPSULE_OMISSION = "capsule_omission"
    UNSPECIFIED_OR_INTENTIONAL = "unspecified_or_intentional"
    HUMAN_JUDGMENT = "human_judgment"


# Normative ordered path; length is always nine.
DIAGNOSIS_STEP_ORDER: Final[tuple[str, ...]] = tuple(
    item.value for item in DiagnosisStepId
)


class DiagnosisDisposition(str, Enum):
    """Closed product-versus-assurance disposition for one survivor.

    Acceptance (AAE-030): diagnosis never labels every survivor a product
    defect and never labels every difficult case equivalent.
    """

    EQUIVALENT = "equivalent"
    PROBABLY_EQUIVALENT = "probably_equivalent"
    ASSURANCE_GAP = "assurance_gap"
    PRODUCT_DEFECT = "product_defect"
    INTENTIONALLY_UNCONSTRAINED = "intentionally_unconstrained"
    SPECIFICATION_AMBIGUITY = "specification_ambiguity"
    UNKNOWN = "unknown"
    NON_SURVIVOR = "non_survivor"


class DiagnosisStepVerdict(str, Enum):
    """Closed per-step verdict recorded on the nine-step path."""

    NOT_TRIGGERED = "not_triggered"
    TRIGGERED = "triggered"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise DiagnosisError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise DiagnosisError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise DiagnosisError(f"{name} exceeds maximum length")
    if any(not char.isprintable() for char in value):
        raise DiagnosisError(f"{name} contains non-printable characters")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise DiagnosisError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise DiagnosisError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise DiagnosisError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ValueError
        raise DiagnosisError(f"{name} must be a valid CIDv1") from exc
    return text


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    if type(value) is not str:
        raise DiagnosisError(f"{name} must be a string or {enum_type.__name__}")
    allowed = {item.value for item in enum_type}
    if value not in allowed:
        raise DiagnosisError(
            f"{name}={value!r} is not in closed set {sorted(allowed)}"
        )
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise DiagnosisError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise DiagnosisError(
            f"{name} contains unknown fields: {sorted(unknown)}"
        )
    missing = fields - set(data)
    # Callers may omit optional keys that have defaults; only require that no
    # unknown keys appear. Required-field checks live in constructors.
    _ = missing
    return dict(data)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise DiagnosisError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(dict(value), path=name)
    try:
        validate_structured_value(dict(value))
    except Exception as exc:
        raise DiagnosisError(f"{name} is not a DAG-JSON structured value") from exc
    return MappingProxyType(_thaw_structured(dict(value)))


def _unique_sorted_tokens(
    values: Sequence[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DiagnosisError(f"{name} must be a list")
    if len(values) > maximum:
        raise DiagnosisError(f"{name} exceeds maximum length")
    items = [_token(item, f"{name}[{index}]") for index, item in enumerate(values)]
    if len(items) != len(set(items)):
        raise DiagnosisError(f"{name} values must be unique")
    ordered = tuple(sorted(items))
    if not ordered and not allow_empty:
        raise DiagnosisError(f"{name} must not be empty")
    return ordered


def _unique_sorted_symbol_ids(
    values: Sequence[Any], name: str, *, maximum: int = MAX_LIST
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DiagnosisError(f"{name} must be a list")
    if len(values) > maximum:
        raise DiagnosisError(f"{name} exceeds maximum length")
    items = [
        _symbol_id(item, f"{name}[{index}]") for index, item in enumerate(values)
    ]
    if len(items) != len(set(items)):
        raise DiagnosisError(f"{name} values must be unique")
    return tuple(sorted(items))


def _unique_sorted_cids(
    values: Sequence[Any], name: str, *, maximum: int = MAX_LIST
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DiagnosisError(f"{name} must be a list")
    if len(values) > maximum:
        raise DiagnosisError(f"{name} exceeds maximum length")
    items = [_cid(item, f"{name}[{index}]") for index, item in enumerate(values)]
    if len(items) != len(set(items)):
        raise DiagnosisError(f"{name} values must be unique")
    return tuple(sorted(items))


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except Exception as exc:
            raise DiagnosisError(f"{name} is malformed: {exc}") from exc
    raise DiagnosisError(f"{name} must be AssuranceArtifactHeader or mapping")


def _normalize_source_span(
    value: SourceSpan | Mapping[str, Any], name: str
) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "span_cid" in value:
                return SourceSpan.from_dict(value)
            return SourceSpan(**dict(value))  # type: ignore[arg-type]
        except (AnalysisContractError, TypeError, KeyError) as exc:
            raise DiagnosisError(f"{name} is malformed: {exc}") from exc
    raise DiagnosisError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]], name: str
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise DiagnosisError(f"{name} must be a list")
    if len(values) > MAX_SPANS:
        raise DiagnosisError(f"{name} exceeds maximum length")
    return tuple(
        _normalize_source_span(item, f"{name}[{index}]")
        for index, item in enumerate(values)
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
            return MinimizedEvidenceBinding(**dict(value))  # type: ignore[arg-type]
        except (AnalysisContractError, TypeError, KeyError) as exc:
            raise DiagnosisError(f"{name} is malformed: {exc}") from exc
    raise DiagnosisError(f"{name} must be MinimizedEvidenceBinding or mapping")


def _normalize_comparison(
    value: DetectionComparisonResult | Mapping[str, Any] | None,
    name: str = "comparison",
) -> DetectionComparisonResult | None:
    if value is None:
        return None
    if isinstance(value, DetectionComparisonResult):
        return value
    if isinstance(value, Mapping):
        try:
            return DetectionComparisonResult.from_dict(value)
        except (GapClassificationError, TypeError, KeyError, ValueError) as exc:
            raise DiagnosisError(f"{name} is malformed: {exc}") from exc
    raise DiagnosisError(f"{name} must be DetectionComparisonResult or mapping")


def _artifact_header(
    base: AssuranceArtifactHeader,
    *,
    artifact_kind: str,
    interface_id: str,
    symbol_ids: Sequence[str] | None = None,
    repository_state_cid: str | None = None,
) -> AssuranceArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    versions = VersionBinding(
        operator_id=base.versions.operator_id,
        operator_version=base.versions.operator_version,
        campaign_policy_id=base.versions.campaign_policy_id,
        campaign_policy_version=base.versions.campaign_policy_version,
        generator=generator,
    )
    return AssuranceArtifactHeader(
        artifact_kind=artifact_kind,
        repository_id=base.repository_id,
        repository_state_cid=repository_state_cid or base.repository_state_cid,
        target_symbol_ids=(
            tuple(symbol_ids)
            if symbol_ids is not None
            else tuple(base.target_symbol_ids)
        ),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


# ---------------------------------------------------------------------------
# Lightweight mutation / outcome / signals bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiagnosisMutationBinding:
    """Bounded mutation identity inputs for ``diagnose_surviving_mutant@1``."""

    candidate_id: str
    candidate_cid: str
    risk_class: SurvivorRiskClass | str
    symbol_ids: Sequence[str]
    violated_or_missing_property: str
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    header: AssuranceArtifactHeader | Mapping[str, Any]
    transformation_summary: str | None = None
    likely_equivalent: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "candidate_id",
            "candidate_cid",
            "risk_class",
            "symbol_ids",
            "violated_or_missing_property",
            "source_spans",
            "dependency_path",
            "header",
            "transformation_summary",
            "likely_equivalent",
            "notes",
            "metadata",
            "binding_cid",
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
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise DiagnosisError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(
            self,
            "violated_or_missing_property",
            _text(self.violated_or_missing_property, "violated_or_missing_property"),
        )
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        if not spans:
            raise DiagnosisError("source_spans must not be empty")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
            allow_empty=False,
        )
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(self, "header", _header(self.header))
        object.__setattr__(
            self,
            "transformation_summary",
            _optional_text(self.transformation_summary, "transformation_summary"),
        )
        object.__setattr__(
            self,
            "likely_equivalent",
            _bool(self.likely_equivalent, "likely_equivalent"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DIAGNOSIS_MUTATION_BINDING_SCHEMA,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "risk_class": self.risk_class,
            "symbol_ids": list(self.symbol_ids),
            "violated_or_missing_property": self.violated_or_missing_property,
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "header": self.header.identity_payload(),
            "transformation_summary": self.transformation_summary,
            "likely_equivalent": self.likely_equivalent,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "source_spans": [span.to_dict() for span in self.source_spans],
            "header": self.header.to_dict(),
            "binding_cid": self.binding_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosisMutationBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid", None)
        if payload.pop("schema", DIAGNOSIS_MUTATION_BINDING_SCHEMA) != (
            DIAGNOSIS_MUTATION_BINDING_SCHEMA
        ):
            raise DiagnosisError(
                "unsupported DiagnosisMutationBinding schema version"
            )
        result = cls(
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            risk_class=payload["risk_class"],
            symbol_ids=payload["symbol_ids"],
            violated_or_missing_property=payload["violated_or_missing_property"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            header=payload["header"],
            transformation_summary=payload.get("transformation_summary"),
            likely_equivalent=payload.get("likely_equivalent", False),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.binding_cid:
            raise DiagnosisError(
                "DiagnosisMutationBinding binding_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class DiagnosisOutcomeBinding:
    """Bounded outcome identity inputs for ``diagnose_surviving_mutant@1``."""

    outcome_id: str
    outcome_cid: str
    outcome_status: MutationOutcomeStatus | str
    candidate_id: str
    candidate_cid: str
    expected_detection_set_cid: str | None = None
    equivalence_assessment_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "outcome_id",
            "outcome_cid",
            "outcome_status",
            "candidate_id",
            "candidate_cid",
            "expected_detection_set_cid",
            "equivalence_assessment_cid",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_id", _token(self.outcome_id, "outcome_id"))
        object.__setattr__(self, "outcome_cid", _cid(self.outcome_cid, "outcome_cid"))
        object.__setattr__(
            self,
            "outcome_status",
            _enum(self.outcome_status, MutationOutcomeStatus, "outcome_status"),
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
            _optional_cid(
                self.expected_detection_set_cid, "expected_detection_set_cid"
            ),
        )
        object.__setattr__(
            self,
            "equivalence_assessment_cid",
            _optional_cid(
                self.equivalence_assessment_cid, "equivalence_assessment_cid"
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DIAGNOSIS_OUTCOME_BINDING_SCHEMA,
            "outcome_id": self.outcome_id,
            "outcome_cid": self.outcome_cid,
            "outcome_status": self.outcome_status,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "binding_cid": self.binding_cid}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosisOutcomeBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid", None)
        if payload.pop("schema", DIAGNOSIS_OUTCOME_BINDING_SCHEMA) != (
            DIAGNOSIS_OUTCOME_BINDING_SCHEMA
        ):
            raise DiagnosisError(
                "unsupported DiagnosisOutcomeBinding schema version"
            )
        result = cls(
            outcome_id=payload["outcome_id"],
            outcome_cid=payload["outcome_cid"],
            outcome_status=payload["outcome_status"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            expected_detection_set_cid=payload.get("expected_detection_set_cid"),
            equivalence_assessment_cid=payload.get("equivalence_assessment_cid"),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.binding_cid:
            raise DiagnosisError(
                "DiagnosisOutcomeBinding binding_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class DiagnosisSignals:
    """Optional diagnosis signals that cannot be derived from mutation/outcome alone.

    Product-defect labeling is *opt-in* via ``product_defect_evidence`` and
    never inferred from survival alone. ``difficulty_to_kill`` is accepted so
    it can be explicitly ignored as equivalence evidence.
    """

    equivalence_status: EquivalenceAssessmentStatus | str | None = None
    intentionally_unconstrained: bool = False
    specification_ambiguous: bool = False
    product_defect_evidence: bool = False
    original_behavior_violates_required_property: bool = False
    product_defect_evidence_cids: Sequence[str] = ()
    difficulty_to_kill: bool = False
    observation_complete: bool = True
    survivor_report_cid: str | None = None
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any] | None = None
    not_selected_detector_ids: Sequence[str] = ()
    not_executed_detector_ids: Sequence[str] = ()
    path_unobserved_detector_ids: Sequence[str] = ()
    weak_property_detector_ids: Sequence[str] = ()
    dependency_omission_detector_ids: Sequence[str] = ()
    capsule_omission_detector_ids: Sequence[str] = ()
    comparison_result_cid: str | None = None
    primary_detector_kind: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "equivalence_status",
            "intentionally_unconstrained",
            "specification_ambiguous",
            "product_defect_evidence",
            "original_behavior_violates_required_property",
            "product_defect_evidence_cids",
            "difficulty_to_kill",
            "observation_complete",
            "survivor_report_cid",
            "minimized_evidence",
            "not_selected_detector_ids",
            "not_executed_detector_ids",
            "path_unobserved_detector_ids",
            "weak_property_detector_ids",
            "dependency_omission_detector_ids",
            "capsule_omission_detector_ids",
            "comparison_result_cid",
            "primary_detector_kind",
            "notes",
            "metadata",
            "signals_cid",
        }
    )

    def __post_init__(self) -> None:
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
            "product_defect_evidence",
            _bool(self.product_defect_evidence, "product_defect_evidence"),
        )
        object.__setattr__(
            self,
            "original_behavior_violates_required_property",
            _bool(
                self.original_behavior_violates_required_property,
                "original_behavior_violates_required_property",
            ),
        )
        object.__setattr__(
            self,
            "product_defect_evidence_cids",
            _unique_sorted_cids(
                list(self.product_defect_evidence_cids),
                "product_defect_evidence_cids",
            ),
        )
        object.__setattr__(
            self,
            "difficulty_to_kill",
            _bool(self.difficulty_to_kill, "difficulty_to_kill"),
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(
            self,
            "survivor_report_cid",
            _optional_cid(self.survivor_report_cid, "survivor_report_cid"),
        )
        evidence = self.minimized_evidence
        if evidence is not None:
            evidence = _normalize_evidence(evidence)
        object.__setattr__(self, "minimized_evidence", evidence)
        object.__setattr__(
            self,
            "not_selected_detector_ids",
            _unique_sorted_tokens(
                list(self.not_selected_detector_ids),
                "not_selected_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        object.__setattr__(
            self,
            "not_executed_detector_ids",
            _unique_sorted_tokens(
                list(self.not_executed_detector_ids),
                "not_executed_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        object.__setattr__(
            self,
            "path_unobserved_detector_ids",
            _unique_sorted_tokens(
                list(self.path_unobserved_detector_ids),
                "path_unobserved_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        object.__setattr__(
            self,
            "weak_property_detector_ids",
            _unique_sorted_tokens(
                list(self.weak_property_detector_ids),
                "weak_property_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        object.__setattr__(
            self,
            "dependency_omission_detector_ids",
            _unique_sorted_tokens(
                list(self.dependency_omission_detector_ids),
                "dependency_omission_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        object.__setattr__(
            self,
            "capsule_omission_detector_ids",
            _unique_sorted_tokens(
                list(self.capsule_omission_detector_ids),
                "capsule_omission_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        object.__setattr__(
            self,
            "comparison_result_cid",
            _optional_cid(self.comparison_result_cid, "comparison_result_cid"),
        )
        kind = self.primary_detector_kind
        if kind is not None:
            kind = _token(kind, "primary_detector_kind")
        object.__setattr__(self, "primary_detector_kind", kind)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        # Product-defect flags require explicit evidence CIDs when asserted.
        if self.product_defect_evidence and not self.product_defect_evidence_cids:
            raise DiagnosisError(
                "product_defect_evidence requires product_defect_evidence_cids"
            )
        if (
            self.product_defect_evidence
            and not self.original_behavior_violates_required_property
        ):
            raise DiagnosisError(
                "product_defect_evidence requires "
                "original_behavior_violates_required_property=true"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DIAGNOSIS_SIGNALS_SCHEMA,
            "equivalence_status": self.equivalence_status,
            "intentionally_unconstrained": self.intentionally_unconstrained,
            "specification_ambiguous": self.specification_ambiguous,
            "product_defect_evidence": self.product_defect_evidence,
            "original_behavior_violates_required_property": (
                self.original_behavior_violates_required_property
            ),
            "product_defect_evidence_cids": list(self.product_defect_evidence_cids),
            "difficulty_to_kill": self.difficulty_to_kill,
            "observation_complete": self.observation_complete,
            "survivor_report_cid": self.survivor_report_cid,
            "minimized_evidence": (
                None
                if self.minimized_evidence is None
                else self.minimized_evidence.identity_payload()
            ),
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
            "comparison_result_cid": self.comparison_result_cid,
            "primary_detector_kind": self.primary_detector_kind,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def signals_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        if self.minimized_evidence is not None:
            payload["minimized_evidence"] = self.minimized_evidence.to_dict()
        payload["signals_cid"] = self.signals_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosisSignals":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("signals_cid", None)
        if payload.pop("schema", DIAGNOSIS_SIGNALS_SCHEMA) != DIAGNOSIS_SIGNALS_SCHEMA:
            raise DiagnosisError("unsupported DiagnosisSignals schema version")
        result = cls(
            equivalence_status=payload.get("equivalence_status"),
            intentionally_unconstrained=payload.get(
                "intentionally_unconstrained", False
            ),
            specification_ambiguous=payload.get("specification_ambiguous", False),
            product_defect_evidence=payload.get("product_defect_evidence", False),
            original_behavior_violates_required_property=payload.get(
                "original_behavior_violates_required_property", False
            ),
            product_defect_evidence_cids=payload.get(
                "product_defect_evidence_cids", ()
            ),
            difficulty_to_kill=payload.get("difficulty_to_kill", False),
            observation_complete=payload.get("observation_complete", True),
            survivor_report_cid=payload.get("survivor_report_cid"),
            minimized_evidence=payload.get("minimized_evidence"),
            not_selected_detector_ids=payload.get("not_selected_detector_ids", ()),
            not_executed_detector_ids=payload.get("not_executed_detector_ids", ()),
            path_unobserved_detector_ids=payload.get(
                "path_unobserved_detector_ids", ()
            ),
            weak_property_detector_ids=payload.get(
                "weak_property_detector_ids", ()
            ),
            dependency_omission_detector_ids=payload.get(
                "dependency_omission_detector_ids", ()
            ),
            capsule_omission_detector_ids=payload.get(
                "capsule_omission_detector_ids", ()
            ),
            comparison_result_cid=payload.get("comparison_result_cid"),
            primary_detector_kind=payload.get("primary_detector_kind"),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.signals_cid:
            raise DiagnosisError("DiagnosisSignals signals_cid identity mismatch")
        return result


@dataclass(frozen=True, slots=True)
class DiagnosisStepResult:
    """One recorded step on the nine-step decision path."""

    step_id: DiagnosisStepId | str
    step_index: int
    verdict: DiagnosisStepVerdict | str
    triggered: bool
    finding: str
    disposition_hint: DiagnosisDisposition | str | None = None
    related_detector_ids: Sequence[str] = ()
    gap_cause: AssuranceGapCause | str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "step_id",
            "step_index",
            "verdict",
            "triggered",
            "finding",
            "disposition_hint",
            "related_detector_ids",
            "gap_cause",
            "notes",
            "metadata",
            "step_cid",
        }
    )

    def __post_init__(self) -> None:
        step_id = _enum(self.step_id, DiagnosisStepId, "step_id")
        object.__setattr__(self, "step_id", step_id)
        if type(self.step_index) is not int or isinstance(self.step_index, bool):
            raise DiagnosisError("step_index must be an integer")
        if not 1 <= self.step_index <= 9:
            raise DiagnosisError("step_index must be in 1..9")
        expected_index = DIAGNOSIS_STEP_ORDER.index(step_id) + 1
        if self.step_index != expected_index:
            raise DiagnosisError(
                f"step_index {self.step_index} does not match step_id {step_id!r} "
                f"(expected {expected_index})"
            )
        object.__setattr__(
            self, "verdict", _enum(self.verdict, DiagnosisStepVerdict, "verdict")
        )
        object.__setattr__(self, "triggered", _bool(self.triggered, "triggered"))
        if self.triggered and self.verdict != DiagnosisStepVerdict.TRIGGERED.value:
            raise DiagnosisError(
                "triggered=true requires verdict=triggered"
            )
        if (
            not self.triggered
            and self.verdict == DiagnosisStepVerdict.TRIGGERED.value
        ):
            raise DiagnosisError(
                "verdict=triggered requires triggered=true"
            )
        object.__setattr__(self, "finding", _text(self.finding, "finding"))
        hint = self.disposition_hint
        if hint is not None:
            hint = _enum(hint, DiagnosisDisposition, "disposition_hint")
        object.__setattr__(self, "disposition_hint", hint)
        object.__setattr__(
            self,
            "related_detector_ids",
            _unique_sorted_tokens(
                list(self.related_detector_ids),
                "related_detector_ids",
                maximum=MAX_DETECTORS,
            ),
        )
        cause = self.gap_cause
        if cause is not None:
            cause = _enum(cause, AssuranceGapCause, "gap_cause")
        object.__setattr__(self, "gap_cause", cause)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DIAGNOSIS_STEP_RESULT_SCHEMA,
            "step_id": self.step_id,
            "step_index": self.step_index,
            "verdict": self.verdict,
            "triggered": self.triggered,
            "finding": self.finding,
            "disposition_hint": self.disposition_hint,
            "related_detector_ids": list(self.related_detector_ids),
            "gap_cause": self.gap_cause,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def step_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "step_cid": self.step_cid}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosisStepResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("step_cid", None)
        if payload.pop("schema", DIAGNOSIS_STEP_RESULT_SCHEMA) != (
            DIAGNOSIS_STEP_RESULT_SCHEMA
        ):
            raise DiagnosisError("unsupported DiagnosisStepResult schema version")
        result = cls(
            step_id=payload["step_id"],
            step_index=payload["step_index"],
            verdict=payload["verdict"],
            triggered=payload["triggered"],
            finding=payload["finding"],
            disposition_hint=payload.get("disposition_hint"),
            related_detector_ids=payload.get("related_detector_ids", ()),
            gap_cause=payload.get("gap_cause"),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.step_cid:
            raise DiagnosisError("DiagnosisStepResult step_cid identity mismatch")
        return result


# ---------------------------------------------------------------------------
# SurvivorDiagnosis sealed result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurvivorDiagnosis:
    """Sealed diagnosis for one surviving mutant.

    Interface: ``SurvivorDiagnosis@1``

    Always records the full nine-step path. Product defects require explicit
    evidence and are never the default disposition for survivors.
    """

    header: AssuranceArtifactHeader
    diagnosis_id: str
    candidate_id: str
    candidate_cid: str
    outcome_cid: str
    outcome_status: MutationOutcomeStatus | str
    repository_state_cid: str
    risk_class: SurvivorRiskClass | str
    disposition: DiagnosisDisposition | str
    deciding_step_id: DiagnosisStepId | str
    steps: Sequence[DiagnosisStepResult | Mapping[str, Any]]
    summary: str
    violated_or_missing_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    gap_class: AssuranceGapClass | str | None = None
    gap_cause: AssuranceGapCause | str | None = None
    severity: GapSeverity | str | None = None
    requires_human_review: bool = False
    survivor_report_cid: str | None = None
    comparison_result_cid: str | None = None
    equivalence_assessment_cid: str | None = None
    product_defect_evidence_cids: Sequence[str] = ()
    difficulty_to_kill_not_evidence: bool = True
    survivor_not_automatically_product_defect: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "diagnosis_id",
            "candidate_id",
            "candidate_cid",
            "outcome_cid",
            "outcome_status",
            "repository_state_cid",
            "risk_class",
            "disposition",
            "deciding_step_id",
            "steps",
            "summary",
            "violated_or_missing_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "gap_class",
            "gap_cause",
            "severity",
            "requires_human_review",
            "survivor_report_cid",
            "comparison_result_cid",
            "equivalence_assessment_cid",
            "product_defect_evidence_cids",
            "difficulty_to_kill_not_evidence",
            "survivor_not_automatically_product_defect",
            "notes",
            "metadata",
            "diagnosis_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "survivor_diagnosis":
            raise DiagnosisError(
                "header.artifact_kind must be survivor_diagnosis"
            )
        object.__setattr__(
            self, "diagnosis_id", _token(self.diagnosis_id, "diagnosis_id")
        )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(self, "outcome_cid", _cid(self.outcome_cid, "outcome_cid"))
        object.__setattr__(
            self,
            "outcome_status",
            _enum(self.outcome_status, MutationOutcomeStatus, "outcome_status"),
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, SurvivorRiskClass, "risk_class"),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, DiagnosisDisposition, "disposition"),
        )
        object.__setattr__(
            self,
            "deciding_step_id",
            _enum(self.deciding_step_id, DiagnosisStepId, "deciding_step_id"),
        )
        steps = _normalize_steps(list(self.steps))
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        object.__setattr__(
            self,
            "violated_or_missing_property",
            _text(self.violated_or_missing_property, "violated_or_missing_property"),
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise DiagnosisError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        if not spans:
            raise DiagnosisError("source_spans must not be empty")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
            allow_empty=False,
        )
        object.__setattr__(self, "dependency_path", path)

        gap_class = self.gap_class
        if gap_class is not None:
            gap_class = _enum(gap_class, AssuranceGapClass, "gap_class")
        object.__setattr__(self, "gap_class", gap_class)
        gap_cause = self.gap_cause
        if gap_cause is not None:
            gap_cause = _enum(gap_cause, AssuranceGapCause, "gap_cause")
        object.__setattr__(self, "gap_cause", gap_cause)
        severity = self.severity
        if severity is not None:
            severity = _enum(severity, GapSeverity, "severity")
        object.__setattr__(self, "severity", severity)

        object.__setattr__(
            self,
            "requires_human_review",
            _bool(self.requires_human_review, "requires_human_review"),
        )
        object.__setattr__(
            self,
            "survivor_report_cid",
            _optional_cid(self.survivor_report_cid, "survivor_report_cid"),
        )
        object.__setattr__(
            self,
            "comparison_result_cid",
            _optional_cid(self.comparison_result_cid, "comparison_result_cid"),
        )
        object.__setattr__(
            self,
            "equivalence_assessment_cid",
            _optional_cid(
                self.equivalence_assessment_cid, "equivalence_assessment_cid"
            ),
        )
        object.__setattr__(
            self,
            "product_defect_evidence_cids",
            _unique_sorted_cids(
                list(self.product_defect_evidence_cids),
                "product_defect_evidence_cids",
            ),
        )

        flag = _bool(
            self.difficulty_to_kill_not_evidence,
            "difficulty_to_kill_not_evidence",
        )
        if not flag:
            raise DiagnosisError(
                "difficulty_to_kill_not_evidence must be true; difficulty to "
                "kill never implies equivalence"
            )
        object.__setattr__(self, "difficulty_to_kill_not_evidence", flag)

        auto = _bool(
            self.survivor_not_automatically_product_defect,
            "survivor_not_automatically_product_defect",
        )
        if not auto:
            raise DiagnosisError(
                "survivor_not_automatically_product_defect must be true; "
                "survival is never automatically a product defect"
            )
        object.__setattr__(self, "survivor_not_automatically_product_defect", auto)

        # Disposition consistency.
        if self.disposition == DiagnosisDisposition.PRODUCT_DEFECT.value:
            if not self.product_defect_evidence_cids:
                raise DiagnosisError(
                    "product_defect disposition requires product_defect_evidence_cids"
                )
        if self.disposition == DiagnosisDisposition.ASSURANCE_GAP.value:
            if self.gap_class is None or self.gap_cause is None:
                raise DiagnosisError(
                    "assurance_gap disposition requires gap_class and gap_cause"
                )
        if self.disposition in {
            DiagnosisDisposition.UNKNOWN.value,
            DiagnosisDisposition.PROBABLY_EQUIVALENT.value,
            DiagnosisDisposition.SPECIFICATION_AMBIGUITY.value,
            DiagnosisDisposition.INTENTIONALLY_UNCONSTRAINED.value,
        }:
            if not self.requires_human_review:
                raise DiagnosisError(
                    f"disposition {self.disposition!r} requires human review"
                )

        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SURVIVOR_DIAGNOSIS_SCHEMA,
            "interface_id": SURVIVOR_DIAGNOSIS_INTERFACE,
            "header": self.header.identity_payload(),
            "diagnosis_id": self.diagnosis_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "outcome_cid": self.outcome_cid,
            "outcome_status": self.outcome_status,
            "repository_state_cid": self.repository_state_cid,
            "risk_class": self.risk_class,
            "disposition": self.disposition,
            "deciding_step_id": self.deciding_step_id,
            "steps": [step.identity_payload() for step in self.steps],
            "summary": self.summary,
            "violated_or_missing_property": self.violated_or_missing_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "gap_class": self.gap_class,
            "gap_cause": self.gap_cause,
            "severity": self.severity,
            "requires_human_review": self.requires_human_review,
            "survivor_report_cid": self.survivor_report_cid,
            "comparison_result_cid": self.comparison_result_cid,
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "product_defect_evidence_cids": list(self.product_defect_evidence_cids),
            "difficulty_to_kill_not_evidence": self.difficulty_to_kill_not_evidence,
            "survivor_not_automatically_product_defect": (
                self.survivor_not_automatically_product_defect
            ),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def diagnosis_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SURVIVOR_DIAGNOSIS_SCHEMA,
            "interface_id": SURVIVOR_DIAGNOSIS_INTERFACE,
            "header": self.header.to_dict(),
            "diagnosis_id": self.diagnosis_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "outcome_cid": self.outcome_cid,
            "outcome_status": self.outcome_status,
            "repository_state_cid": self.repository_state_cid,
            "risk_class": self.risk_class,
            "disposition": self.disposition,
            "deciding_step_id": self.deciding_step_id,
            "steps": [step.to_dict() for step in self.steps],
            "summary": self.summary,
            "violated_or_missing_property": self.violated_or_missing_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.to_dict() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "gap_class": self.gap_class,
            "gap_cause": self.gap_cause,
            "severity": self.severity,
            "requires_human_review": self.requires_human_review,
            "survivor_report_cid": self.survivor_report_cid,
            "comparison_result_cid": self.comparison_result_cid,
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "product_defect_evidence_cids": list(self.product_defect_evidence_cids),
            "difficulty_to_kill_not_evidence": self.difficulty_to_kill_not_evidence,
            "survivor_not_automatically_product_defect": (
                self.survivor_not_automatically_product_defect
            ),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "diagnosis_cid": self.diagnosis_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SurvivorDiagnosis":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("diagnosis_cid")
        if payload.pop("schema") != SURVIVOR_DIAGNOSIS_SCHEMA:
            raise DiagnosisError("unsupported SurvivorDiagnosis schema version")
        if payload.pop("interface_id") != SURVIVOR_DIAGNOSIS_INTERFACE:
            raise DiagnosisError("unsupported SurvivorDiagnosis interface_id")
        result = cls(
            header=payload["header"],
            diagnosis_id=payload["diagnosis_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            outcome_cid=payload["outcome_cid"],
            outcome_status=payload["outcome_status"],
            repository_state_cid=payload["repository_state_cid"],
            risk_class=payload["risk_class"],
            disposition=payload["disposition"],
            deciding_step_id=payload["deciding_step_id"],
            steps=payload["steps"],
            summary=payload["summary"],
            violated_or_missing_property=payload["violated_or_missing_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            gap_class=payload.get("gap_class"),
            gap_cause=payload.get("gap_cause"),
            severity=payload.get("severity"),
            requires_human_review=payload.get("requires_human_review", False),
            survivor_report_cid=payload.get("survivor_report_cid"),
            comparison_result_cid=payload.get("comparison_result_cid"),
            equivalence_assessment_cid=payload.get("equivalence_assessment_cid"),
            product_defect_evidence_cids=payload.get(
                "product_defect_evidence_cids", ()
            ),
            difficulty_to_kill_not_evidence=payload.get(
                "difficulty_to_kill_not_evidence", True
            ),
            survivor_not_automatically_product_defect=payload.get(
                "survivor_not_automatically_product_defect", True
            ),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed != result.diagnosis_cid:
            raise DiagnosisError(
                "SurvivorDiagnosis diagnosis_cid identity mismatch"
            )
        return result


def _normalize_steps(
    values: Sequence[DiagnosisStepResult | Mapping[str, Any]],
) -> tuple[DiagnosisStepResult, ...]:
    if not isinstance(values, (list, tuple)):
        raise DiagnosisError("steps must be a list")
    if len(values) != 9:
        raise DiagnosisError("steps must contain exactly nine step results")
    items: list[DiagnosisStepResult] = []
    for index, raw in enumerate(values):
        if isinstance(raw, DiagnosisStepResult):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "step_cid" in raw:
                items.append(DiagnosisStepResult.from_dict(raw))
            else:
                items.append(DiagnosisStepResult(**dict(raw)))  # type: ignore[arg-type]
        else:
            raise DiagnosisError(
                f"steps[{index}] must be DiagnosisStepResult or mapping"
            )
    for expected_index, expected_id in enumerate(DIAGNOSIS_STEP_ORDER, start=1):
        step = items[expected_index - 1]
        if step.step_id != expected_id or step.step_index != expected_index:
            raise DiagnosisError(
                "steps must follow the required nine-step decision path order"
            )
    return tuple(items)


# ---------------------------------------------------------------------------
# Normalization of diagnose_surviving_mutant inputs
# ---------------------------------------------------------------------------


def _normalize_mutation(
    value: DiagnosisMutationBinding | Mapping[str, Any],
    name: str = "mutation",
) -> DiagnosisMutationBinding:
    if isinstance(value, DiagnosisMutationBinding):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "binding_cid" in value:
            return DiagnosisMutationBinding.from_dict(value)
        data = dict(value)
        # MutationCandidate-shaped projection onto the diagnosis binding.
        if "scope_symbol_ids" in data and "symbol_ids" not in data:
            data["symbol_ids"] = data["scope_symbol_ids"]
        if "violated_or_missing_property" not in data:
            classes = data.get("expected_violated_property_classes") or ()
            if classes:
                data["violated_or_missing_property"] = ",".join(
                    str(item) for item in classes
                )
            elif data.get("transformation_summary"):
                data["violated_or_missing_property"] = str(
                    data["transformation_summary"]
                )
        if "source_spans" not in data:
            paths = data.get("scope_paths") or ()
            if paths:
                data["source_spans"] = [
                    {
                        "path": str(paths[0]),
                        "start_line": 1,
                        "end_line": 1,
                        "start_col": 0,
                        "end_col": 1,
                    }
                ]
        if "dependency_path" not in data:
            symbols = data.get("symbol_ids") or data.get("scope_symbol_ids") or ()
            if symbols:
                data["dependency_path"] = [str(symbols[0])]
        if "candidate_cid" not in data:
            raise DiagnosisError(f"{name} requires candidate_cid")
        return DiagnosisMutationBinding(
            candidate_id=data["candidate_id"],
            candidate_cid=data["candidate_cid"],
            risk_class=data["risk_class"],
            symbol_ids=data["symbol_ids"],
            violated_or_missing_property=data["violated_or_missing_property"],
            source_spans=data["source_spans"],
            dependency_path=data["dependency_path"],
            header=data["header"],
            transformation_summary=data.get("transformation_summary"),
            likely_equivalent=data.get("likely_equivalent", False),
            notes=data.get("notes"),
            metadata=data.get("metadata", {}),
        )
    raise DiagnosisError(f"{name} must be DiagnosisMutationBinding or mapping")


def _normalize_outcome(
    value: DiagnosisOutcomeBinding | Mapping[str, Any],
    name: str = "outcome",
) -> DiagnosisOutcomeBinding:
    if isinstance(value, DiagnosisOutcomeBinding):
        return value
    if isinstance(value, Mapping):
        if "schema" in value and "binding_cid" in value:
            return DiagnosisOutcomeBinding.from_dict(value)
        data = dict(value)
        # MutationOutcome projection.
        if "outcome_status" in data and "candidate_id" in data:
            outcome_cid = data.get("outcome_cid")
            if outcome_cid is None:
                # Allow callers to pass MutationOutcome-like records without
                # precomputed cid when outcome_id + status are present; require
                # explicit outcome_cid for sealed identity binding.
                raise DiagnosisError(f"{name} requires outcome_cid")
            return DiagnosisOutcomeBinding(
                outcome_id=data.get("outcome_id") or data.get("candidate_id") + ".outcome",
                outcome_cid=outcome_cid,
                outcome_status=data["outcome_status"],
                candidate_id=data["candidate_id"],
                candidate_cid=data["candidate_cid"],
                expected_detection_set_cid=data.get("expected_detection_set_cid"),
                equivalence_assessment_cid=data.get("equivalence_assessment_cid"),
                notes=data.get("notes"),
                metadata=data.get("metadata", {}),
            )
        return DiagnosisOutcomeBinding.from_dict(data)
    raise DiagnosisError(f"{name} must be DiagnosisOutcomeBinding or mapping")


def _normalize_repository_state(
    value: str | Mapping[str, Any],
    name: str = "repository_state",
) -> str:
    if type(value) is str:
        return _cid(value, name)
    if isinstance(value, Mapping):
        if "repository_state_cid" in value:
            return _cid(value["repository_state_cid"], f"{name}.repository_state_cid")
        if "cid" in value:
            return _cid(value["cid"], f"{name}.cid")
        raise DiagnosisError(
            f"{name} mapping must provide repository_state_cid or cid"
        )
    raise DiagnosisError(f"{name} must be a CIDv1 string or mapping")


def _normalize_signals(
    value: DiagnosisSignals | Mapping[str, Any] | None,
    name: str = "signals",
) -> DiagnosisSignals:
    if value is None:
        return DiagnosisSignals()
    if isinstance(value, DiagnosisSignals):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "signals_cid" in value:
            return DiagnosisSignals.from_dict(value)
        return DiagnosisSignals(**dict(value))  # type: ignore[arg-type]
    raise DiagnosisError(f"{name} must be DiagnosisSignals or mapping")


def _merge_signals_from_comparison(
    signals: DiagnosisSignals,
    comparison: DetectionComparisonResult | None,
) -> DiagnosisSignals:
    """Overlay detector-partition signals from a sealed comparison when present."""

    if comparison is None:
        return signals
    return DiagnosisSignals(
        equivalence_status=signals.equivalence_status,
        intentionally_unconstrained=signals.intentionally_unconstrained,
        specification_ambiguous=signals.specification_ambiguous,
        product_defect_evidence=signals.product_defect_evidence,
        original_behavior_violates_required_property=(
            signals.original_behavior_violates_required_property
        ),
        product_defect_evidence_cids=signals.product_defect_evidence_cids,
        difficulty_to_kill=signals.difficulty_to_kill,
        observation_complete=signals.observation_complete,
        survivor_report_cid=signals.survivor_report_cid,
        minimized_evidence=signals.minimized_evidence,
        not_selected_detector_ids=(
            signals.not_selected_detector_ids or comparison.not_selected_detector_ids
        ),
        not_executed_detector_ids=(
            signals.not_executed_detector_ids or comparison.not_executed_detector_ids
        ),
        path_unobserved_detector_ids=(
            signals.path_unobserved_detector_ids
            or comparison.path_unobserved_detector_ids
        ),
        weak_property_detector_ids=(
            signals.weak_property_detector_ids or comparison.weak_property_detector_ids
        ),
        dependency_omission_detector_ids=(
            signals.dependency_omission_detector_ids
            or comparison.dependency_omission_detector_ids
        ),
        capsule_omission_detector_ids=(
            signals.capsule_omission_detector_ids
            or comparison.capsule_omission_detector_ids
        ),
        comparison_result_cid=signals.comparison_result_cid or comparison.result_cid,
        primary_detector_kind=signals.primary_detector_kind,
        notes=signals.notes,
        metadata=dict(signals.metadata),
    )


# ---------------------------------------------------------------------------
# Nine-step evaluation
# ---------------------------------------------------------------------------


def _step(
    step_id: str,
    *,
    triggered: bool,
    finding: str,
    disposition_hint: str | None = None,
    related_detector_ids: Sequence[str] = (),
    gap_cause: str | None = None,
    verdict: str | None = None,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DiagnosisStepResult:
    index = DIAGNOSIS_STEP_ORDER.index(step_id) + 1
    if verdict is None:
        verdict = (
            DiagnosisStepVerdict.TRIGGERED.value
            if triggered
            else DiagnosisStepVerdict.NOT_TRIGGERED.value
        )
    return DiagnosisStepResult(
        step_id=step_id,
        step_index=index,
        verdict=verdict,
        triggered=triggered,
        finding=finding,
        disposition_hint=disposition_hint,
        related_detector_ids=related_detector_ids,
        gap_cause=gap_cause,
        notes=notes,
        metadata=dict(metadata or {}),
    )


def _evaluate_nine_steps(
    *,
    mutation: DiagnosisMutationBinding,
    outcome: DiagnosisOutcomeBinding,
    signals: DiagnosisSignals,
) -> tuple[DiagnosisStepResult, ...]:
    """Walk and record the required nine-step path for one survivor."""

    # Explicitly discard non-evidence flags so they cannot drive step 1.
    _ = mutation.likely_equivalent
    difficulty = signals.difficulty_to_kill

    # --- 1. equivalence -------------------------------------------------
    eq_status = signals.equivalence_status
    if eq_status == EquivalenceAssessmentStatus.EQUIVALENT.value:
        step1 = _step(
            DiagnosisStepId.EQUIVALENCE.value,
            triggered=True,
            finding=(
                f"mutant {mutation.candidate_id} assessed equivalent under "
                "bounded evidence"
            ),
            disposition_hint=DiagnosisDisposition.EQUIVALENT.value,
            gap_cause=AssuranceGapCause.EQUIVALENCE.value,
            notes=(
                "difficulty_to_kill ignored as equivalence evidence"
                if difficulty
                else None
            ),
            metadata={
                "equivalence_status": eq_status,
                "difficulty_to_kill_ignored": True,
                "likely_equivalent_ignored": True,
            },
        )
    elif eq_status == EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value:
        step1 = _step(
            DiagnosisStepId.EQUIVALENCE.value,
            triggered=True,
            finding=(
                f"mutant {mutation.candidate_id} assessed probably_equivalent; "
                "human review required"
            ),
            disposition_hint=DiagnosisDisposition.PROBABLY_EQUIVALENT.value,
            gap_cause=AssuranceGapCause.EQUIVALENCE.value,
            notes=(
                "difficulty_to_kill ignored as equivalence evidence"
                if difficulty
                else None
            ),
            metadata={
                "equivalence_status": eq_status,
                "difficulty_to_kill_ignored": True,
                "likely_equivalent_ignored": True,
            },
        )
    elif eq_status == EquivalenceAssessmentStatus.NOT_EQUIVALENT.value:
        step1 = _step(
            DiagnosisStepId.EQUIVALENCE.value,
            triggered=False,
            finding=(
                f"mutant {mutation.candidate_id} assessed not_equivalent; "
                "continue path"
            ),
            metadata={
                "equivalence_status": eq_status,
                "difficulty_to_kill_ignored": True,
                "likely_equivalent_ignored": True,
            },
        )
    elif eq_status == EquivalenceAssessmentStatus.UNKNOWN.value:
        step1 = _step(
            DiagnosisStepId.EQUIVALENCE.value,
            triggered=False,
            finding=(
                f"equivalence unknown for {mutation.candidate_id}; "
                "unknown never becomes equivalent automatically"
            ),
            verdict=DiagnosisStepVerdict.INCONCLUSIVE.value,
            metadata={
                "equivalence_status": eq_status,
                "difficulty_to_kill_ignored": True,
                "likely_equivalent_ignored": True,
            },
        )
    else:
        # No assessment provided: not triggered; difficulty still ignored.
        step1 = _step(
            DiagnosisStepId.EQUIVALENCE.value,
            triggered=False,
            finding=(
                f"no equivalence assessment bound for {mutation.candidate_id}; "
                "difficulty_to_kill is not evidence of equivalence"
            ),
            metadata={
                "equivalence_status": None,
                "difficulty_to_kill_ignored": True,
                "likely_equivalent_ignored": True,
                "difficulty_to_kill_observed": difficulty,
            },
        )

    # --- 2. detector selection ------------------------------------------
    not_selected = signals.not_selected_detector_ids
    step2 = _step(
        DiagnosisStepId.DETECTOR_SELECTION.value,
        triggered=bool(not_selected),
        finding=(
            f"predicted detectors not selected: {', '.join(not_selected)}"
            if not_selected
            else "no detector selection misses observed"
        ),
        disposition_hint=(
            DiagnosisDisposition.ASSURANCE_GAP.value if not_selected else None
        ),
        related_detector_ids=not_selected,
        gap_cause=(
            AssuranceGapCause.NOT_SELECTED.value if not_selected else None
        ),
    )

    # --- 3. detector execution ------------------------------------------
    not_executed = signals.not_executed_detector_ids
    step3 = _step(
        DiagnosisStepId.DETECTOR_EXECUTION.value,
        triggered=bool(not_executed),
        finding=(
            f"selected detectors not executed: {', '.join(not_executed)}"
            if not_executed
            else "no detector execution misses observed"
        ),
        disposition_hint=(
            DiagnosisDisposition.ASSURANCE_GAP.value if not_executed else None
        ),
        related_detector_ids=not_executed,
        gap_cause=(
            AssuranceGapCause.NOT_EXECUTED.value if not_executed else None
        ),
    )

    # --- 4. path observation --------------------------------------------
    path_unobs = signals.path_unobserved_detector_ids
    step4 = _step(
        DiagnosisStepId.PATH_OBSERVATION.value,
        triggered=bool(path_unobs),
        finding=(
            f"executed detectors missed mutated path: {', '.join(path_unobs)}"
            if path_unobs
            else "no path-observation misses observed"
        ),
        disposition_hint=(
            DiagnosisDisposition.ASSURANCE_GAP.value if path_unobs else None
        ),
        related_detector_ids=path_unobs,
        gap_cause=(
            AssuranceGapCause.PATH_UNOBSERVED.value if path_unobs else None
        ),
    )

    # --- 5. assertion strength ------------------------------------------
    weak = signals.weak_property_detector_ids
    step5 = _step(
        DiagnosisStepId.ASSERTION_STRENGTH.value,
        triggered=bool(weak),
        finding=(
            f"detectors with inadequate assertion strength: {', '.join(weak)}"
            if weak
            else "no assertion-strength failures observed"
        ),
        disposition_hint=(
            DiagnosisDisposition.ASSURANCE_GAP.value if weak else None
        ),
        related_detector_ids=weak,
        gap_cause=AssuranceGapCause.WEAK_PROPERTY.value if weak else None,
    )

    # --- 6. dependency omission -----------------------------------------
    dep = signals.dependency_omission_detector_ids
    step6 = _step(
        DiagnosisStepId.DEPENDENCY_OMISSION.value,
        triggered=bool(dep),
        finding=(
            f"dependency-edge omissions: {', '.join(dep)}"
            if dep
            else "no dependency omissions observed"
        ),
        disposition_hint=DiagnosisDisposition.ASSURANCE_GAP.value if dep else None,
        related_detector_ids=dep,
        gap_cause=(
            AssuranceGapCause.DEPENDENCY_OMISSION.value if dep else None
        ),
    )

    # --- 7. capsule omission --------------------------------------------
    cap = signals.capsule_omission_detector_ids
    step7 = _step(
        DiagnosisStepId.CAPSULE_OMISSION.value,
        triggered=bool(cap),
        finding=(
            f"capsule completeness failures: {', '.join(cap)}"
            if cap
            else "no capsule omissions observed"
        ),
        disposition_hint=DiagnosisDisposition.ASSURANCE_GAP.value if cap else None,
        related_detector_ids=cap,
        gap_cause=AssuranceGapCause.CAPSULE_OMISSION.value if cap else None,
    )

    # --- 8. unspecified or intentionally unconstrained ------------------
    if signals.intentionally_unconstrained:
        step8 = _step(
            DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value,
            triggered=True,
            finding=(
                f"behavior intentionally unconstrained for "
                f"{mutation.candidate_id}"
            ),
            disposition_hint=(
                DiagnosisDisposition.INTENTIONALLY_UNCONSTRAINED.value
            ),
            gap_cause=AssuranceGapCause.INTENTIONAL.value,
        )
    elif signals.specification_ambiguous:
        step8 = _step(
            DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value,
            triggered=True,
            finding=(
                f"specification ambiguity leaves property unconstrained for "
                f"{mutation.candidate_id}"
            ),
            disposition_hint=DiagnosisDisposition.SPECIFICATION_AMBIGUITY.value,
            gap_cause=AssuranceGapCause.UNSPECIFIED.value,
        )
    else:
        step8 = _step(
            DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value,
            triggered=False,
            finding="no intentional/unspecified constraint signal",
        )

    # --- 9. human judgment ----------------------------------------------
    # Product-defect evidence is considered only as an explicit opt-in signal
    # feeding the disposition resolver; step 9 records residual review need.
    needs_review_signals = (
        eq_status
        in {
            EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value,
            EquivalenceAssessmentStatus.UNKNOWN.value,
            None,
        }
        or signals.intentionally_unconstrained
        or signals.specification_ambiguous
        or signals.product_defect_evidence
        or outcome.outcome_status
        == MutationOutcomeStatus.HUMAN_REVIEW_REQUIRED.value
    )
    # Human judgment is always evaluated; triggered when residual uncertainty
    # remains after the prior eight steps.
    residual_uncertainty = needs_review_signals and not (
        eq_status == EquivalenceAssessmentStatus.EQUIVALENT.value
    )
    # Also trigger when no prior assurance/product/equivalence signal fired.
    prior_defect_signal = any(
        step.triggered
        for step in (step1, step2, step3, step4, step5, step6, step7, step8)
    )
    if not prior_defect_signal:
        residual_uncertainty = True
    if residual_uncertainty:
        step9 = _step(
            DiagnosisStepId.HUMAN_JUDGMENT.value,
            triggered=True,
            finding=(
                f"human judgment required for survivor {mutation.candidate_id}"
                if not prior_defect_signal or needs_review_signals
                else f"human judgment residual for {mutation.candidate_id}"
            ),
            disposition_hint=DiagnosisDisposition.UNKNOWN.value,
            gap_cause=AssuranceGapCause.UNKNOWN.value,
            metadata={
                "prior_defect_signal": prior_defect_signal,
                "product_defect_evidence": signals.product_defect_evidence,
            },
        )
    else:
        step9 = _step(
            DiagnosisStepId.HUMAN_JUDGMENT.value,
            triggered=False,
            finding=(
                f"no residual human-judgment requirement after path for "
                f"{mutation.candidate_id}"
            ),
            metadata={"prior_defect_signal": prior_defect_signal},
        )

    return (step1, step2, step3, step4, step5, step6, step7, step8, step9)


def _resolve_disposition(
    steps: Sequence[DiagnosisStepResult],
    *,
    mutation: DiagnosisMutationBinding,
    outcome: DiagnosisOutcomeBinding,
    signals: DiagnosisSignals,
) -> tuple[str, str, str | None, str | None, str | None, bool, str]:
    """Resolve primary disposition from the nine-step path.

    Returns:
        disposition, deciding_step_id, gap_class, gap_cause, severity,
        requires_human_review, summary
    """

    # Non-survivor outcomes are reported explicitly rather than forced into a
    # product/assurance defect bucket.
    if outcome.outcome_status not in _SURVIVOR_OUTCOME_STATUSES:
        return (
            DiagnosisDisposition.NON_SURVIVOR.value,
            DiagnosisStepId.HUMAN_JUDGMENT.value,
            None,
            None,
            GapSeverity.INFORMATIONAL.value,
            True,
            (
                f"outcome {outcome.outcome_status!r} is not a survivor status; "
                f"no product or assurance defect assigned for "
                f"{mutation.candidate_id}"
            ),
        )

    by_id = {step.step_id: step for step in steps}
    eq = by_id[DiagnosisStepId.EQUIVALENCE.value]
    unspec = by_id[DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value]
    human = by_id[DiagnosisStepId.HUMAN_JUDGMENT.value]

    # 1. Equivalence wins (never from difficulty alone — already enforced).
    if (
        eq.triggered
        and eq.disposition_hint == DiagnosisDisposition.EQUIVALENT.value
    ):
        return (
            DiagnosisDisposition.EQUIVALENT.value,
            DiagnosisStepId.EQUIVALENCE.value,
            AssuranceGapClass.PROBABLY_EQUIVALENT.value,
            AssuranceGapCause.EQUIVALENCE.value,
            GapSeverity.INFORMATIONAL.value,
            False,
            eq.finding,
        )
    if (
        eq.triggered
        and eq.disposition_hint == DiagnosisDisposition.PROBABLY_EQUIVALENT.value
    ):
        return (
            DiagnosisDisposition.PROBABLY_EQUIVALENT.value,
            DiagnosisStepId.EQUIVALENCE.value,
            AssuranceGapClass.PROBABLY_EQUIVALENT.value,
            AssuranceGapCause.EQUIVALENCE.value,
            GapSeverity.INFORMATIONAL.value,
            True,
            eq.finding,
        )

    # 2. Intentional / unspecified (step 8).
    if (
        unspec.triggered
        and unspec.disposition_hint
        == DiagnosisDisposition.INTENTIONALLY_UNCONSTRAINED.value
    ):
        return (
            DiagnosisDisposition.INTENTIONALLY_UNCONSTRAINED.value,
            DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value,
            AssuranceGapClass.INTENTIONALLY_UNCONSTRAINED.value,
            AssuranceGapCause.INTENTIONAL.value,
            GapSeverity.INFORMATIONAL.value,
            True,
            unspec.finding,
        )
    if (
        unspec.triggered
        and unspec.disposition_hint
        == DiagnosisDisposition.SPECIFICATION_AMBIGUITY.value
    ):
        return (
            DiagnosisDisposition.SPECIFICATION_AMBIGUITY.value,
            DiagnosisStepId.UNSPECIFIED_OR_INTENTIONAL.value,
            AssuranceGapClass.SPECIFICATION_AMBIGUITY.value,
            AssuranceGapCause.UNSPECIFIED.value,
            GapSeverity.MEDIUM.value,
            True,
            unspec.finding,
        )

    # 3. Product defect — only with explicit evidence and not_equivalent.
    # Never the default; never from survival alone.
    if signals.product_defect_evidence:
        if signals.equivalence_status != (
            EquivalenceAssessmentStatus.NOT_EQUIVALENT.value
        ):
            # Explicit product evidence without not_equivalent cannot become a
            # product-defect disposition; fall through to assurance/unknown.
            pass
        else:
            return (
                DiagnosisDisposition.PRODUCT_DEFECT.value,
                DiagnosisStepId.HUMAN_JUDGMENT.value,
                None,
                None,
                _RISK_TO_SEVERITY.get(
                    mutation.risk_class, GapSeverity.HIGH.value
                ),
                True,
                (
                    f"explicit product-defect evidence for "
                    f"{mutation.candidate_id}; original behavior violates "
                    f"required property; survival is not automatic product defect "
                    f"without this evidence"
                ),
            )

    # 4. Assurance-gap causes in structural-priority order (deps before
    # selection, matching gap classification).
    assurance_order: tuple[tuple[str, str], ...] = (
        (
            DiagnosisStepId.DEPENDENCY_OMISSION.value,
            AssuranceGapCause.DEPENDENCY_OMISSION.value,
        ),
        (
            DiagnosisStepId.CAPSULE_OMISSION.value,
            AssuranceGapCause.CAPSULE_OMISSION.value,
        ),
        (
            DiagnosisStepId.DETECTOR_SELECTION.value,
            AssuranceGapCause.NOT_SELECTED.value,
        ),
        (
            DiagnosisStepId.DETECTOR_EXECUTION.value,
            AssuranceGapCause.NOT_EXECUTED.value,
        ),
        (
            DiagnosisStepId.PATH_OBSERVATION.value,
            AssuranceGapCause.PATH_UNOBSERVED.value,
        ),
        (
            DiagnosisStepId.ASSERTION_STRENGTH.value,
            AssuranceGapCause.WEAK_PROPERTY.value,
        ),
    )
    for step_id, cause in assurance_order:
        step = by_id[step_id]
        if not step.triggered:
            continue
        gap_class = cause_to_gap_class(
            cause, detector_kind=signals.primary_detector_kind
        )
        severity = _RISK_TO_SEVERITY.get(
            mutation.risk_class, GapSeverity.MEDIUM.value
        )
        return (
            DiagnosisDisposition.ASSURANCE_GAP.value,
            step_id,
            gap_class,
            cause,
            severity,
            False,
            (
                f"assurance gap ({cause}) for survivor {mutation.candidate_id}; "
                f"not classified as product defect: {step.finding}"
            ),
        )

    # 5. Residual unknown → human judgment.
    return (
        DiagnosisDisposition.UNKNOWN.value,
        DiagnosisStepId.HUMAN_JUDGMENT.value,
        AssuranceGapClass.UNKNOWN.value,
        AssuranceGapCause.UNKNOWN.value,
        _RISK_TO_SEVERITY.get(mutation.risk_class, GapSeverity.MEDIUM.value),
        True,
        (
            human.finding
            if human.triggered
            else (
                f"unknown residual diagnosis for survivor "
                f"{mutation.candidate_id}; human review required"
            )
        ),
    )


# ---------------------------------------------------------------------------
# diagnose_surviving_mutant
# ---------------------------------------------------------------------------


def diagnose_surviving_mutant(
    mutation: DiagnosisMutationBinding | Mapping[str, Any],
    outcome: DiagnosisOutcomeBinding | Mapping[str, Any],
    repository_state: str | Mapping[str, Any],
    *,
    signals: DiagnosisSignals | Mapping[str, Any] | None = None,
    comparison: DetectionComparisonResult | Mapping[str, Any] | None = None,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SurvivorDiagnosis:
    """Diagnose one surviving mutant via the required nine-step decision path.

    Interface: ``diagnose_surviving_mutant@1``

    Plan signature: ``diagnose_surviving_mutant(mutation, outcome,
    repository_state)``.

    Product-versus-assurance rules:

    * Survival is an assurance-gap *candidate*, never automatically a product
      defect (``survivor_not_automatically_product_defect`` is always true).
    * Product-defect disposition requires explicit
      ``product_defect_evidence`` with evidence CIDs, original-behavior
      violation, and ``not_equivalent`` assessment.
    * Difficulty to kill never implies equivalence
      (``difficulty_to_kill_not_evidence`` is always true).

    Incomplete observation fails closed.
    """

    sealed_mutation = _normalize_mutation(mutation)
    sealed_outcome = _normalize_outcome(outcome)
    repo_state_cid = _normalize_repository_state(repository_state)
    sealed_signals = _normalize_signals(signals)
    sealed_comparison = _normalize_comparison(comparison)

    if not sealed_signals.observation_complete:
        raise DiagnosisError(
            "diagnose_surviving_mutant fails closed when observation_complete is false"
        )

    if sealed_mutation.candidate_id != sealed_outcome.candidate_id:
        raise DiagnosisError(
            "mutation.candidate_id must match outcome.candidate_id"
        )
    if sealed_mutation.candidate_cid != sealed_outcome.candidate_cid:
        raise DiagnosisError(
            "mutation.candidate_cid must match outcome.candidate_cid"
        )

    if sealed_comparison is not None:
        if sealed_comparison.candidate_id != sealed_mutation.candidate_id:
            raise DiagnosisError(
                "comparison.candidate_id must match mutation.candidate_id"
            )
        if sealed_comparison.candidate_cid != sealed_mutation.candidate_cid:
            raise DiagnosisError(
                "comparison.candidate_cid must match mutation.candidate_cid"
            )

    sealed_signals = _merge_signals_from_comparison(
        sealed_signals, sealed_comparison
    )

    # Outcome-declared equivalence statuses seed signals when absent.
    seeded_status: str | None = None
    if sealed_signals.equivalence_status is None:
        if sealed_outcome.outcome_status == MutationOutcomeStatus.EQUIVALENT.value:
            seeded_status = EquivalenceAssessmentStatus.EQUIVALENT.value
        elif (
            sealed_outcome.outcome_status
            == MutationOutcomeStatus.PROBABLY_EQUIVALENT.value
        ):
            seeded_status = EquivalenceAssessmentStatus.PROBABLY_EQUIVALENT.value
    if seeded_status is not None:
        sealed_signals = DiagnosisSignals(
            equivalence_status=seeded_status,
            intentionally_unconstrained=sealed_signals.intentionally_unconstrained,
            specification_ambiguous=sealed_signals.specification_ambiguous,
            product_defect_evidence=sealed_signals.product_defect_evidence,
            original_behavior_violates_required_property=(
                sealed_signals.original_behavior_violates_required_property
            ),
            product_defect_evidence_cids=sealed_signals.product_defect_evidence_cids,
            difficulty_to_kill=sealed_signals.difficulty_to_kill,
            observation_complete=sealed_signals.observation_complete,
            survivor_report_cid=sealed_signals.survivor_report_cid,
            minimized_evidence=sealed_signals.minimized_evidence,
            not_selected_detector_ids=sealed_signals.not_selected_detector_ids,
            not_executed_detector_ids=sealed_signals.not_executed_detector_ids,
            path_unobserved_detector_ids=sealed_signals.path_unobserved_detector_ids,
            weak_property_detector_ids=sealed_signals.weak_property_detector_ids,
            dependency_omission_detector_ids=(
                sealed_signals.dependency_omission_detector_ids
            ),
            capsule_omission_detector_ids=sealed_signals.capsule_omission_detector_ids,
            comparison_result_cid=sealed_signals.comparison_result_cid,
            primary_detector_kind=sealed_signals.primary_detector_kind,
            notes=sealed_signals.notes,
            metadata=dict(sealed_signals.metadata),
        )

    steps = _evaluate_nine_steps(
        mutation=sealed_mutation,
        outcome=sealed_outcome,
        signals=sealed_signals,
    )
    (
        disposition,
        deciding_step_id,
        gap_class,
        gap_cause,
        severity,
        requires_review,
        summary,
    ) = _resolve_disposition(
        steps,
        mutation=sealed_mutation,
        outcome=sealed_outcome,
        signals=sealed_signals,
    )

    if notes is not None:
        note_text = _optional_text(notes, "notes")
    else:
        parts = [
            part
            for part in (
                sealed_mutation.notes,
                sealed_outcome.notes,
                sealed_signals.notes,
            )
            if part
        ]
        note_text = "; ".join(parts) if parts else None

    diagnosis_header = _artifact_header(
        sealed_mutation.header,
        artifact_kind="survivor_diagnosis",
        interface_id=DIAGNOSE_SURVIVING_MUTANT_INTERFACE,
        symbol_ids=sealed_mutation.symbol_ids,
        repository_state_cid=repo_state_cid,
    )

    result_metadata = dict(sealed_mutation.metadata)
    result_metadata.update(dict(sealed_signals.metadata))
    if metadata:
        result_metadata.update(dict(metadata))
    result_metadata["generator_id"] = GENERATOR_ID
    result_metadata["generator_version"] = GENERATOR_VERSION
    result_metadata["diagnosis_step_order"] = list(DIAGNOSIS_STEP_ORDER)
    result_metadata["difficulty_to_kill_ignored"] = True
    result_metadata["likely_equivalent_ignored"] = True
    result_metadata["mutation_binding_cid"] = sealed_mutation.binding_cid
    result_metadata["outcome_binding_cid"] = sealed_outcome.binding_cid
    result_metadata["signals_cid"] = sealed_signals.signals_cid
    if sealed_comparison is not None:
        result_metadata["comparison_primary_cause"] = (
            sealed_comparison.primary_cause
        )

    diagnosis = SurvivorDiagnosis(
        header=diagnosis_header,
        diagnosis_id=f"{sealed_mutation.candidate_id}.diagnosis",
        candidate_id=sealed_mutation.candidate_id,
        candidate_cid=sealed_mutation.candidate_cid,
        outcome_cid=sealed_outcome.outcome_cid,
        outcome_status=sealed_outcome.outcome_status,
        repository_state_cid=repo_state_cid,
        risk_class=sealed_mutation.risk_class,
        disposition=disposition,
        deciding_step_id=deciding_step_id,
        steps=steps,
        summary=summary,
        violated_or_missing_property=sealed_mutation.violated_or_missing_property,
        symbol_ids=sealed_mutation.symbol_ids,
        source_spans=sealed_mutation.source_spans,
        dependency_path=sealed_mutation.dependency_path,
        gap_class=gap_class,
        gap_cause=gap_cause,
        severity=severity,
        requires_human_review=requires_review,
        survivor_report_cid=sealed_signals.survivor_report_cid,
        comparison_result_cid=sealed_signals.comparison_result_cid,
        equivalence_assessment_cid=sealed_outcome.equivalence_assessment_cid,
        product_defect_evidence_cids=sealed_signals.product_defect_evidence_cids,
        difficulty_to_kill_not_evidence=True,
        survivor_not_automatically_product_defect=True,
        notes=note_text,
        metadata=result_metadata,
    )
    verify_survivor_diagnosis_identity(diagnosis)
    return diagnosis


# ---------------------------------------------------------------------------
# Vocabulary / identity helpers
# ---------------------------------------------------------------------------


def diagnosis_step_ids() -> tuple[str, ...]:
    """Return the closed nine-step decision path in order."""

    return DIAGNOSIS_STEP_ORDER


def diagnosis_dispositions() -> tuple[str, ...]:
    """Return the closed product-versus-assurance disposition vocabulary."""

    return tuple(item.value for item in DiagnosisDisposition)


def diagnosis_step_verdicts() -> tuple[str, ...]:
    """Return the closed per-step verdict vocabulary."""

    return tuple(item.value for item in DiagnosisStepVerdict)


def verify_survivor_diagnosis_identity(
    diagnosis: SurvivorDiagnosis | Mapping[str, Any],
) -> str:
    """Recompute and return the diagnosis CID; raise on forged input."""

    if isinstance(diagnosis, SurvivorDiagnosis):
        sealed = diagnosis
    elif isinstance(diagnosis, Mapping):
        sealed = SurvivorDiagnosis.from_dict(diagnosis)
    else:
        raise DiagnosisError("diagnosis must be SurvivorDiagnosis or mapping")
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.diagnosis_cid:
        raise DiagnosisError(
            "diagnosis_cid identity mismatch with recomputed identity"
        )
    return recomputed


__all__ = [
    "DIAGNOSE_SURVIVING_MUTANT_INTERFACE",
    "DIAGNOSIS_MUTATION_BINDING_SCHEMA",
    "DIAGNOSIS_OUTCOME_BINDING_SCHEMA",
    "DIAGNOSIS_SIGNALS_SCHEMA",
    "DIAGNOSIS_STEP_ORDER",
    "DIAGNOSIS_STEP_RESULT_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "SURVIVOR_DIAGNOSIS_INTERFACE",
    "SURVIVOR_DIAGNOSIS_SCHEMA",
    "DiagnosisDisposition",
    "DiagnosisError",
    "DiagnosisMutationBinding",
    "DiagnosisOutcomeBinding",
    "DiagnosisSignals",
    "DiagnosisStepId",
    "DiagnosisStepResult",
    "DiagnosisStepVerdict",
    "SurvivorDiagnosis",
    "diagnose_surviving_mutant",
    "diagnosis_dispositions",
    "diagnosis_step_ids",
    "diagnosis_step_verdicts",
    "verify_survivor_diagnosis_identity",
]
