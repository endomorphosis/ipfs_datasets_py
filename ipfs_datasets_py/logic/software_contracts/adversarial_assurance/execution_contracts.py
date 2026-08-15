"""Expected-detection, execution, receipt, outcome, and equivalence models (AAE-009).

Defines closed, versioned durable models for expected detection sets, mutation
execution plans, execution receipts, mutation outcomes, and equivalence
assessments.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types admitted by content identity (no floats, no host
  objects, no repr fallbacks).
* Stored CIDs are verified by decode-and-recompute, never trusted alone.
* Classification distinguishes predicted, selected, executed, and observed
  detectors separately (missed and unexpected are derived).
* Invalid, uncompilable, infrastructure-failed, timeout, inconclusive, or
  equivalent mutants are never counted as killed.
* Unknown enums / statuses fail closed.
* Private material, model-written authority, and host fallbacks are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    AssuranceTerminalStatus,
    reject_private_model_authority_and_host_fallbacks,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

EXPECTED_DETECTION_SET_INTERFACE: Final[str] = "ExpectedDetectionSet@1"
EXPECTED_DETECTION_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-expected-detection-set@1"
)
MUTATION_EXECUTION_PLAN_INTERFACE: Final[str] = "MutationExecutionPlan@1"
MUTATION_EXECUTION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-execution-plan@1"
)
MUTATION_EXECUTION_RECEIPT_INTERFACE: Final[str] = "MutationExecutionReceipt@1"
MUTATION_EXECUTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-execution-receipt@1"
)
MUTATION_OUTCOME_INTERFACE: Final[str] = "MutationOutcome@1"
MUTATION_OUTCOME_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-outcome@1"
)
MUTATION_EQUIVALENCE_ASSESSMENT_INTERFACE: Final[str] = (
    "MutationEquivalenceAssessment@1"
)
MUTATION_EQUIVALENCE_ASSESSMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutation-equivalence-assessment@1"
)
DETECTOR_PREDICTION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detector-prediction@1"
)
DETECTOR_CLASSIFICATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detector-classification@1"
)
COST_MEASUREMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-cost-measurement@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOKEN_LIST: Final[int] = 256
MAX_DETECTORS: Final[int] = 1_024
MAX_DEPENDENCY_PATH: Final[int] = 64
MAX_EXECUTION_SECONDS: Final[int] = 7 * 24 * 3_600
MAX_REVISION: Final[int] = 2**63 - 1
MAX_COST_UNITS: Final[int] = 2**63 - 1

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)


class ExecutionContractError(AssuranceBaseError):
    """Raised when an execution contract record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class DetectorKind(str, Enum):
    """Closed kinds of detectors that may appear in expected detection sets."""

    STATIC_RULE = "static_rule"
    TYPE_CHECK = "type_check"
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    PROPERTY_TEST = "property_test"
    FORMAL_OBLIGATION = "formal_obligation"
    POLICY_RULE = "policy_rule"
    RUNTIME_INVARIANT = "runtime_invariant"
    FULL_SUITE = "full_suite"
    INCREMENTAL_SEAL = "incremental_seal"
    HUMAN_REVIEW = "human_review"


class DetectorStrength(str, Enum):
    """Whether a predicted detector is required or optional strength."""

    REQUIRED = "required"
    OPTIONAL = "optional"


class DetectorRole(str, Enum):
    """Lifecycle roles used when classifying detectors for one mutant."""

    PREDICTED = "predicted"
    SELECTED = "selected"
    EXECUTED = "executed"
    OBSERVED = "observed"
    MISSED = "missed"
    UNEXPECTED = "unexpected"


class MutationOutcomeStatus(str, Enum):
    """Closed mutation outcome vocabulary (plan §5)."""

    KILLED_BY_STATIC_ANALYSIS = "killed_by_static_analysis"
    KILLED_BY_TYPE_CHECK = "killed_by_type_check"
    KILLED_BY_TEST = "killed_by_test"
    KILLED_BY_FORMAL_PROOF = "killed_by_formal_proof"
    KILLED_BY_POLICY = "killed_by_policy"
    KILLED_BY_RUNTIME_INVARIANT = "killed_by_runtime_invariant"
    KILLED_BY_FULL_SUITE = "killed_by_full_suite"
    SURVIVED_SELECTED_VERIFICATION = "survived_selected_verification"
    SURVIVED_FULL_VERIFICATION = "survived_full_verification"
    EQUIVALENT = "equivalent"
    PROBABLY_EQUIVALENT = "probably_equivalent"
    INVALID_MUTANT = "invalid_mutant"
    UNCOMPILABLE = "uncompilable"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    TIMEOUT = "timeout"
    INCONCLUSIVE = "inconclusive"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class EquivalenceAssessmentStatus(str, Enum):
    """Closed equivalence assessment vocabulary."""

    EQUIVALENT = "equivalent"
    PROBABLY_EQUIVALENT = "probably_equivalent"
    NOT_EQUIVALENT = "not_equivalent"
    UNKNOWN = "unknown"


class EquivalenceMethod(str, Enum):
    """Bounded methods admitted for equivalence assessment evidence."""

    AST_COMPARISON = "ast_comparison"
    NORMALIZED_IR = "normalized_ir"
    CONSTANT_PROPAGATION = "constant_propagation"
    SYMBOLIC_EXECUTION = "symbolic_execution"
    RESTRICTED_SMT = "restricted_smt"
    REACHABILITY = "reachability"
    BOUNDED_PUBLIC_BEHAVIOR = "bounded_public_behavior"
    HUMAN_REVIEW = "human_review"


# Statuses that count as a true kill for mutation scoring.
_KILLED_OUTCOME_STATUSES: Final[frozenset[str]] = frozenset(
    {
        MutationOutcomeStatus.KILLED_BY_STATIC_ANALYSIS.value,
        MutationOutcomeStatus.KILLED_BY_TYPE_CHECK.value,
        MutationOutcomeStatus.KILLED_BY_TEST.value,
        MutationOutcomeStatus.KILLED_BY_FORMAL_PROOF.value,
        MutationOutcomeStatus.KILLED_BY_POLICY.value,
        MutationOutcomeStatus.KILLED_BY_RUNTIME_INVARIANT.value,
        MutationOutcomeStatus.KILLED_BY_FULL_SUITE.value,
    }
)

# Explicitly never counted as killed (plan §5 / AAE-009 acceptance).
_NEVER_COUNTED_AS_KILLED: Final[frozenset[str]] = frozenset(
    {
        MutationOutcomeStatus.INVALID_MUTANT.value,
        MutationOutcomeStatus.UNCOMPILABLE.value,
        MutationOutcomeStatus.INFRASTRUCTURE_FAILURE.value,
        MutationOutcomeStatus.TIMEOUT.value,
        MutationOutcomeStatus.INCONCLUSIVE.value,
        MutationOutcomeStatus.EQUIVALENT.value,
        MutationOutcomeStatus.PROBABLY_EQUIVALENT.value,
        MutationOutcomeStatus.SURVIVED_SELECTED_VERIFICATION.value,
        MutationOutcomeStatus.SURVIVED_FULL_VERIFICATION.value,
        MutationOutcomeStatus.HUMAN_REVIEW_REQUIRED.value,
    }
)

# Map kill status -> expected detector kind that produced the kill.
_KILL_STATUS_TO_DETECTOR_KIND: Final[Mapping[str, frozenset[str]]] = {
    MutationOutcomeStatus.KILLED_BY_STATIC_ANALYSIS.value: frozenset(
        {DetectorKind.STATIC_RULE.value}
    ),
    MutationOutcomeStatus.KILLED_BY_TYPE_CHECK.value: frozenset(
        {DetectorKind.TYPE_CHECK.value}
    ),
    MutationOutcomeStatus.KILLED_BY_TEST.value: frozenset(
        {
            DetectorKind.UNIT_TEST.value,
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
        }
    ),
    MutationOutcomeStatus.KILLED_BY_FORMAL_PROOF.value: frozenset(
        {DetectorKind.FORMAL_OBLIGATION.value, DetectorKind.INCREMENTAL_SEAL.value}
    ),
    MutationOutcomeStatus.KILLED_BY_POLICY.value: frozenset(
        {DetectorKind.POLICY_RULE.value}
    ),
    MutationOutcomeStatus.KILLED_BY_RUNTIME_INVARIANT.value: frozenset(
        {DetectorKind.RUNTIME_INVARIANT.value}
    ),
    MutationOutcomeStatus.KILLED_BY_FULL_SUITE.value: frozenset(
        {DetectorKind.FULL_SUITE.value}
    ),
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ExecutionContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ExecutionContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ExecutionContractError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ExecutionContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ExecutionContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise ExecutionContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise ExecutionContractError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise ExecutionContractError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise ExecutionContractError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _nonneg_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ExecutionContractError(f"{name} must be a nonnegative integer")
    if value > maximum:
        raise ExecutionContractError(f"{name} exceeds maximum")
    return value


def _pos_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise ExecutionContractError(f"{name} must be a positive integer")
    if value > maximum:
        raise ExecutionContractError(f"{name} exceeds maximum")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ExecutionContractError(f"{name} must be a boolean")
    return value


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
        raise ExecutionContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise ExecutionContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise ExecutionContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise ExecutionContractError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ExecutionContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise ExecutionContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ExecutionContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ExecutionContractError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > maximum:
        raise ExecutionContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ExecutionContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ExecutionContractError(f"{name} must be a list")
    ordered = tuple(sorted(_enum(value, enum_type, name) for value in values))
    if len(ordered) > maximum:
        raise ExecutionContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ExecutionContractError(f"{name} must not contain duplicates")
    return ordered


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise ExecutionContractError(str(exc)) from exc
    raise ExecutionContractError(f"{name} must be AssuranceArtifactHeader or mapping")


def _require_subset(
    subset: Sequence[str],
    superset: Sequence[str],
    *,
    subset_name: str,
    superset_name: str,
) -> None:
    missing = set(subset) - set(superset)
    if missing:
        raise ExecutionContractError(
            f"{subset_name} must be a subset of {superset_name}; "
            f"extra={sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# DetectorPrediction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectorPrediction:
    """One predicted detector with claim, rationale, dependency, and strength.

    Every prediction binds the violated claim, why the detector should observe
    it, the connecting source/proof dependency, required versus optional
    strength, and expected terminal status.
    """

    detector_id: str
    detector_kind: DetectorKind | str
    violated_claim: str
    observation_rationale: str
    dependency_path: Sequence[str]
    strength: DetectorStrength | str
    expected_terminal_status: AssuranceTerminalStatus | str
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "detector_id",
            "detector_kind",
            "violated_claim",
            "observation_rationale",
            "dependency_path",
            "strength",
            "expected_terminal_status",
            "notes",
            "metadata",
            "prediction_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "detector_id", _token(self.detector_id, "detector_id")
        )
        object.__setattr__(
            self,
            "detector_kind",
            _enum(self.detector_kind, DetectorKind, "detector_kind"),
        )
        object.__setattr__(
            self, "violated_claim", _text(self.violated_claim, "violated_claim")
        )
        object.__setattr__(
            self,
            "observation_rationale",
            _text(self.observation_rationale, "observation_rationale"),
        )
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise ExecutionContractError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self, "strength", _enum(self.strength, DetectorStrength, "strength")
        )
        object.__setattr__(
            self,
            "expected_terminal_status",
            _enum(
                self.expected_terminal_status,
                AssuranceTerminalStatus,
                "expected_terminal_status",
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTOR_PREDICTION_SCHEMA,
            "detector_id": self.detector_id,
            "detector_kind": self.detector_kind,
            "violated_claim": self.violated_claim,
            "observation_rationale": self.observation_rationale,
            "dependency_path": list(self.dependency_path),
            "strength": self.strength,
            "expected_terminal_status": self.expected_terminal_status,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def prediction_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["prediction_cid"] = self.prediction_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectorPrediction":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("prediction_cid")
        if payload.pop("schema") != DETECTOR_PREDICTION_SCHEMA:
            raise ExecutionContractError(
                "unsupported DetectorPrediction schema version"
            )
        result = cls(
            detector_id=payload["detector_id"],
            detector_kind=payload["detector_kind"],
            violated_claim=payload["violated_claim"],
            observation_rationale=payload["observation_rationale"],
            dependency_path=payload["dependency_path"],
            strength=payload["strength"],
            expected_terminal_status=payload["expected_terminal_status"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.prediction_cid:
            raise ExecutionContractError(
                "DetectorPrediction prediction_cid identity mismatch"
            )
        return result


def _normalize_detector_prediction(
    value: DetectorPrediction | Mapping[str, Any],
    name: str = "detector",
) -> DetectorPrediction:
    if isinstance(value, DetectorPrediction):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "prediction_cid" in value:
            return DetectorPrediction.from_dict(value)
        return DetectorPrediction(
            detector_id=value["detector_id"],
            detector_kind=value["detector_kind"],
            violated_claim=value["violated_claim"],
            observation_rationale=value["observation_rationale"],
            dependency_path=value["dependency_path"],
            strength=value["strength"],
            expected_terminal_status=value["expected_terminal_status"],
            notes=value.get("notes"),
            metadata=value.get("metadata", {}),
        )
    raise ExecutionContractError(f"{name} must be DetectorPrediction or mapping")


def _normalize_detector_predictions(
    values: Sequence[DetectorPrediction | Mapping[str, Any]],
    name: str = "predicted_detectors",
) -> tuple[DetectorPrediction, ...]:
    if not isinstance(values, (list, tuple)):
        raise ExecutionContractError(f"{name} must be a list")
    if len(values) > MAX_DETECTORS:
        raise ExecutionContractError(f"{name} exceeds maximum length")
    detectors = tuple(
        _normalize_detector_prediction(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )
    ids = [detector.detector_id for detector in detectors]
    if len(ids) != len(set(ids)):
        raise ExecutionContractError(f"{name} detector_id values must be unique")
    # Stable order by detector_id for identity determinism.
    return tuple(sorted(detectors, key=lambda item: item.detector_id))


# ---------------------------------------------------------------------------
# DetectorClassification (predicted / selected / executed / observed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectorClassification:
    """Separates predicted, selected, executed, and observed detector IDs.

    Missed detectors are predicted but not observed. Unexpected detectors are
    observed but not predicted. Role lists are closed and fail when nesting
    invariants are violated (executed ⊆ selected, observed ⊆ executed).
    """

    predicted_detector_ids: Sequence[str]
    selected_detector_ids: Sequence[str]
    executed_detector_ids: Sequence[str]
    observed_detector_ids: Sequence[str]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "predicted_detector_ids",
            "selected_detector_ids",
            "executed_detector_ids",
            "observed_detector_ids",
            "missed_detector_ids",
            "unexpected_detector_ids",
            "classification_cid",
        }
    )

    def __post_init__(self) -> None:
        predicted = _unique_sorted_tokens(
            list(self.predicted_detector_ids),
            "predicted_detector_ids",
            maximum=MAX_DETECTORS,
        )
        selected = _unique_sorted_tokens(
            list(self.selected_detector_ids),
            "selected_detector_ids",
            maximum=MAX_DETECTORS,
        )
        executed = _unique_sorted_tokens(
            list(self.executed_detector_ids),
            "executed_detector_ids",
            maximum=MAX_DETECTORS,
        )
        observed = _unique_sorted_tokens(
            list(self.observed_detector_ids),
            "observed_detector_ids",
            maximum=MAX_DETECTORS,
        )
        _require_subset(
            executed,
            selected,
            subset_name="executed_detector_ids",
            superset_name="selected_detector_ids",
        )
        _require_subset(
            observed,
            executed,
            subset_name="observed_detector_ids",
            superset_name="executed_detector_ids",
        )
        object.__setattr__(self, "predicted_detector_ids", predicted)
        object.__setattr__(self, "selected_detector_ids", selected)
        object.__setattr__(self, "executed_detector_ids", executed)
        object.__setattr__(self, "observed_detector_ids", observed)

    @property
    def missed_detector_ids(self) -> tuple[str, ...]:
        """Predicted detectors that were not observed (detection gaps)."""

        return tuple(
            detector_id
            for detector_id in self.predicted_detector_ids
            if detector_id not in set(self.observed_detector_ids)
        )

    @property
    def unexpected_detector_ids(self) -> tuple[str, ...]:
        """Observed detectors that were not predicted."""

        predicted = set(self.predicted_detector_ids)
        return tuple(
            detector_id
            for detector_id in self.observed_detector_ids
            if detector_id not in predicted
        )

    def role_for(self, detector_id: str) -> tuple[str, ...]:
        """Return every role the detector currently occupies (closed set)."""

        token = _token(detector_id, "detector_id")
        roles: list[str] = []
        if token in self.predicted_detector_ids:
            roles.append(DetectorRole.PREDICTED.value)
        if token in self.selected_detector_ids:
            roles.append(DetectorRole.SELECTED.value)
        if token in self.executed_detector_ids:
            roles.append(DetectorRole.EXECUTED.value)
        if token in self.observed_detector_ids:
            roles.append(DetectorRole.OBSERVED.value)
        if token in self.missed_detector_ids:
            roles.append(DetectorRole.MISSED.value)
        if token in self.unexpected_detector_ids:
            roles.append(DetectorRole.UNEXPECTED.value)
        return tuple(roles)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTOR_CLASSIFICATION_SCHEMA,
            "predicted_detector_ids": list(self.predicted_detector_ids),
            "selected_detector_ids": list(self.selected_detector_ids),
            "executed_detector_ids": list(self.executed_detector_ids),
            "observed_detector_ids": list(self.observed_detector_ids),
            "missed_detector_ids": list(self.missed_detector_ids),
            "unexpected_detector_ids": list(self.unexpected_detector_ids),
        }

    @property
    def classification_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["classification_cid"] = self.classification_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectorClassification":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("classification_cid")
        if payload.pop("schema") != DETECTOR_CLASSIFICATION_SCHEMA:
            raise ExecutionContractError(
                "unsupported DetectorClassification schema version"
            )
        claimed_missed = payload.pop("missed_detector_ids")
        claimed_unexpected = payload.pop("unexpected_detector_ids")
        result = cls(
            predicted_detector_ids=payload["predicted_detector_ids"],
            selected_detector_ids=payload["selected_detector_ids"],
            executed_detector_ids=payload["executed_detector_ids"],
            observed_detector_ids=payload["observed_detector_ids"],
        )
        if list(claimed_missed) != list(result.missed_detector_ids):
            raise ExecutionContractError(
                "missed_detector_ids must match derived predicted-not-observed set"
            )
        if list(claimed_unexpected) != list(result.unexpected_detector_ids):
            raise ExecutionContractError(
                "unexpected_detector_ids must match derived observed-not-predicted set"
            )
        if claimed != result.classification_cid:
            raise ExecutionContractError(
                "DetectorClassification classification_cid identity mismatch"
            )
        return result


def _normalize_detector_classification(
    value: DetectorClassification | Mapping[str, Any],
    name: str = "detector_classification",
) -> DetectorClassification:
    if isinstance(value, DetectorClassification):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "classification_cid" in value:
            return DetectorClassification.from_dict(value)
        return DetectorClassification(
            predicted_detector_ids=value.get("predicted_detector_ids", ()),
            selected_detector_ids=value.get("selected_detector_ids", ()),
            executed_detector_ids=value.get("executed_detector_ids", ()),
            observed_detector_ids=value.get("observed_detector_ids", ()),
        )
    raise ExecutionContractError(
        f"{name} must be DetectorClassification or mapping"
    )


# ---------------------------------------------------------------------------
# CostMeasurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostMeasurement:
    """Incremental and counterfactual full-suite cost for one mutant execution."""

    incremental_cost_units: int
    full_suite_counterfactual_cost_units: int
    execution_seconds: int
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "incremental_cost_units",
            "full_suite_counterfactual_cost_units",
            "execution_seconds",
            "notes",
            "cost_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "incremental_cost_units",
            _nonneg_int(
                self.incremental_cost_units,
                "incremental_cost_units",
                maximum=MAX_COST_UNITS,
            ),
        )
        object.__setattr__(
            self,
            "full_suite_counterfactual_cost_units",
            _nonneg_int(
                self.full_suite_counterfactual_cost_units,
                "full_suite_counterfactual_cost_units",
                maximum=MAX_COST_UNITS,
            ),
        )
        object.__setattr__(
            self,
            "execution_seconds",
            _nonneg_int(
                self.execution_seconds,
                "execution_seconds",
                maximum=MAX_EXECUTION_SECONDS,
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COST_MEASUREMENT_SCHEMA,
            "incremental_cost_units": self.incremental_cost_units,
            "full_suite_counterfactual_cost_units": (
                self.full_suite_counterfactual_cost_units
            ),
            "execution_seconds": self.execution_seconds,
            "notes": self.notes,
        }

    @property
    def cost_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["cost_cid"] = self.cost_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CostMeasurement":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("cost_cid")
        if payload.pop("schema") != COST_MEASUREMENT_SCHEMA:
            raise ExecutionContractError(
                "unsupported CostMeasurement schema version"
            )
        result = cls(
            incremental_cost_units=payload["incremental_cost_units"],
            full_suite_counterfactual_cost_units=payload[
                "full_suite_counterfactual_cost_units"
            ],
            execution_seconds=payload["execution_seconds"],
            notes=payload["notes"],
        )
        if claimed != result.cost_cid:
            raise ExecutionContractError(
                "CostMeasurement cost_cid identity mismatch"
            )
        return result


def _normalize_cost(
    value: CostMeasurement | Mapping[str, Any],
    name: str = "cost",
) -> CostMeasurement:
    if isinstance(value, CostMeasurement):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "cost_cid" in value:
            return CostMeasurement.from_dict(value)
        return CostMeasurement(
            incremental_cost_units=value["incremental_cost_units"],
            full_suite_counterfactual_cost_units=value[
                "full_suite_counterfactual_cost_units"
            ],
            execution_seconds=value["execution_seconds"],
            notes=value.get("notes"),
        )
    raise ExecutionContractError(f"{name} must be CostMeasurement or mapping")


# ---------------------------------------------------------------------------
# ExpectedDetectionSet
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpectedDetectionSet:
    """Predicted detectors for one admitted mutant candidate.

    Interface: ``ExpectedDetectionSet@1``

    May name static rules, type checks, selected unit and integration tests,
    property tests, formal obligations, policy rules, runtime invariants,
    full-suite fallback, incremental seal verification, and human review.
    """

    header: AssuranceArtifactHeader
    detection_set_id: str
    candidate_id: str
    candidate_cid: str
    predicted_detectors: Sequence[DetectorPrediction | Mapping[str, Any]]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "detection_set_id",
            "candidate_id",
            "candidate_cid",
            "predicted_detectors",
            "notes",
            "metadata",
            "detection_set_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "expected_detection_set":
            raise ExecutionContractError(
                "header.artifact_kind must be expected_detection_set"
            )
        object.__setattr__(
            self,
            "detection_set_id",
            _token(self.detection_set_id, "detection_set_id"),
        )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        detectors = _normalize_detector_predictions(
            list(self.predicted_detectors), "predicted_detectors"
        )
        if not detectors:
            raise ExecutionContractError("predicted_detectors must not be empty")
        object.__setattr__(self, "predicted_detectors", detectors)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def predicted_detector_ids(self) -> tuple[str, ...]:
        return tuple(detector.detector_id for detector in self.predicted_detectors)

    def detector_by_id(self, detector_id: str) -> DetectorPrediction:
        token = _token(detector_id, "detector_id")
        for detector in self.predicted_detectors:
            if detector.detector_id == token:
                return detector
        raise ExecutionContractError(f"unknown detector_id {token!r}")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EXPECTED_DETECTION_SET_SCHEMA,
            "interface_id": EXPECTED_DETECTION_SET_INTERFACE,
            "header": self.header.identity_payload(),
            "detection_set_id": self.detection_set_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "predicted_detectors": [
                detector.identity_payload() for detector in self.predicted_detectors
            ],
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def detection_set_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPECTED_DETECTION_SET_SCHEMA,
            "interface_id": EXPECTED_DETECTION_SET_INTERFACE,
            "header": self.header.to_dict(),
            "detection_set_id": self.detection_set_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "predicted_detectors": [
                detector.to_dict() for detector in self.predicted_detectors
            ],
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "detection_set_cid": self.detection_set_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExpectedDetectionSet":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("detection_set_cid")
        if payload.pop("schema") != EXPECTED_DETECTION_SET_SCHEMA:
            raise ExecutionContractError(
                "unsupported ExpectedDetectionSet schema version"
            )
        if payload.pop("interface_id") != EXPECTED_DETECTION_SET_INTERFACE:
            raise ExecutionContractError(
                "unsupported ExpectedDetectionSet interface_id"
            )
        result = cls(
            header=payload["header"],
            detection_set_id=payload["detection_set_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            predicted_detectors=payload["predicted_detectors"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.detection_set_cid:
            raise ExecutionContractError(
                "ExpectedDetectionSet detection_set_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# MutationExecutionPlan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationExecutionPlan:
    """Bounded plan for executing verification against one mutant.

    Interface: ``MutationExecutionPlan@1``

    Selects predicted detectors for incremental execution, optionally enables
    full-suite fallback, and binds disposable-worktree safety flags.
    """

    header: AssuranceArtifactHeader
    execution_plan_id: str
    candidate_id: str
    candidate_cid: str
    expected_detection_set_cid: str
    selected_detector_ids: Sequence[str]
    predicted_detector_ids: Sequence[str]
    require_disposable_worktree: bool = True
    require_network_disabled: bool = True
    full_suite_fallback_enabled: bool = False
    timeout_seconds: int = 3_600
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "execution_plan_id",
            "candidate_id",
            "candidate_cid",
            "expected_detection_set_cid",
            "selected_detector_ids",
            "predicted_detector_ids",
            "require_disposable_worktree",
            "require_network_disabled",
            "full_suite_fallback_enabled",
            "timeout_seconds",
            "notes",
            "metadata",
            "execution_plan_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_execution_plan":
            raise ExecutionContractError(
                "header.artifact_kind must be mutation_execution_plan"
            )
        object.__setattr__(
            self,
            "execution_plan_id",
            _token(self.execution_plan_id, "execution_plan_id"),
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
        predicted = _unique_sorted_tokens(
            list(self.predicted_detector_ids),
            "predicted_detector_ids",
            maximum=MAX_DETECTORS,
        )
        if not predicted:
            raise ExecutionContractError("predicted_detector_ids must not be empty")
        selected = _unique_sorted_tokens(
            list(self.selected_detector_ids),
            "selected_detector_ids",
            maximum=MAX_DETECTORS,
        )
        if not selected:
            raise ExecutionContractError("selected_detector_ids must not be empty")
        # Selected detectors must be predicted unless full-suite fallback expands
        # with an explicit full_suite detector id already present in predicted.
        # Selection may be a subset of predicted; expansion beyond predicted is
        # only allowed when full_suite_fallback_enabled and the extra ids are
        # the closed full-suite marker.
        fallback = _bool(
            self.full_suite_fallback_enabled, "full_suite_fallback_enabled"
        )
        extra = set(selected) - set(predicted)
        if extra and not fallback:
            raise ExecutionContractError(
                "selected_detector_ids must be a subset of predicted_detector_ids "
                "unless full_suite_fallback_enabled is true"
            )
        if extra and any(
            detector_id != "full_suite" and not detector_id.startswith("full_suite.")
            for detector_id in extra
        ):
            raise ExecutionContractError(
                "full-suite expansion may only add full_suite detector ids"
            )
        object.__setattr__(self, "predicted_detector_ids", predicted)
        object.__setattr__(self, "selected_detector_ids", selected)
        for flag_name in ("require_disposable_worktree", "require_network_disabled"):
            flag = _bool(getattr(self, flag_name), flag_name)
            if not flag:
                raise ExecutionContractError(f"{flag_name} must be true")
            object.__setattr__(self, flag_name, flag)
        object.__setattr__(self, "full_suite_fallback_enabled", fallback)
        object.__setattr__(
            self,
            "timeout_seconds",
            _pos_int(
                self.timeout_seconds,
                "timeout_seconds",
                maximum=MAX_EXECUTION_SECONDS,
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_EXECUTION_PLAN_SCHEMA,
            "interface_id": MUTATION_EXECUTION_PLAN_INTERFACE,
            "header": self.header.identity_payload(),
            "execution_plan_id": self.execution_plan_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "selected_detector_ids": list(self.selected_detector_ids),
            "predicted_detector_ids": list(self.predicted_detector_ids),
            "require_disposable_worktree": self.require_disposable_worktree,
            "require_network_disabled": self.require_network_disabled,
            "full_suite_fallback_enabled": self.full_suite_fallback_enabled,
            "timeout_seconds": self.timeout_seconds,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def execution_plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_EXECUTION_PLAN_SCHEMA,
            "interface_id": MUTATION_EXECUTION_PLAN_INTERFACE,
            "header": self.header.to_dict(),
            "execution_plan_id": self.execution_plan_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "selected_detector_ids": list(self.selected_detector_ids),
            "predicted_detector_ids": list(self.predicted_detector_ids),
            "require_disposable_worktree": self.require_disposable_worktree,
            "require_network_disabled": self.require_network_disabled,
            "full_suite_fallback_enabled": self.full_suite_fallback_enabled,
            "timeout_seconds": self.timeout_seconds,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "execution_plan_cid": self.execution_plan_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationExecutionPlan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("execution_plan_cid")
        if payload.pop("schema") != MUTATION_EXECUTION_PLAN_SCHEMA:
            raise ExecutionContractError(
                "unsupported MutationExecutionPlan schema version"
            )
        if payload.pop("interface_id") != MUTATION_EXECUTION_PLAN_INTERFACE:
            raise ExecutionContractError(
                "unsupported MutationExecutionPlan interface_id"
            )
        result = cls(
            header=payload["header"],
            execution_plan_id=payload["execution_plan_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            expected_detection_set_cid=payload["expected_detection_set_cid"],
            selected_detector_ids=payload["selected_detector_ids"],
            predicted_detector_ids=payload["predicted_detector_ids"],
            require_disposable_worktree=payload["require_disposable_worktree"],
            require_network_disabled=payload["require_network_disabled"],
            full_suite_fallback_enabled=payload["full_suite_fallback_enabled"],
            timeout_seconds=payload["timeout_seconds"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.execution_plan_cid:
            raise ExecutionContractError(
                "MutationExecutionPlan execution_plan_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# MutationExecutionReceipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationExecutionReceipt:
    """Observed execution receipt with detector role classification and cost.

    Interface: ``MutationExecutionReceipt@1``

    Records predicted, selected, executed, and observed detectors separately.
    Missed and unexpected sets are derived and sealed into identity.
    """

    header: AssuranceArtifactHeader
    receipt_id: str
    candidate_id: str
    candidate_cid: str
    execution_plan_cid: str
    expected_detection_set_cid: str
    detector_classification: DetectorClassification
    cost: CostMeasurement
    mutant_identity_cid: str
    infrastructure_ok: bool = True
    timed_out: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "receipt_id",
            "candidate_id",
            "candidate_cid",
            "execution_plan_cid",
            "expected_detection_set_cid",
            "detector_classification",
            "cost",
            "mutant_identity_cid",
            "infrastructure_ok",
            "timed_out",
            "notes",
            "metadata",
            "receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_execution_receipt":
            raise ExecutionContractError(
                "header.artifact_kind must be mutation_execution_receipt"
            )
        object.__setattr__(self, "receipt_id", _token(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self,
            "execution_plan_cid",
            _cid(self.execution_plan_cid, "execution_plan_cid"),
        )
        object.__setattr__(
            self,
            "expected_detection_set_cid",
            _cid(self.expected_detection_set_cid, "expected_detection_set_cid"),
        )
        classification = _normalize_detector_classification(
            self.detector_classification
        )
        object.__setattr__(self, "detector_classification", classification)
        object.__setattr__(self, "cost", _normalize_cost(self.cost))
        object.__setattr__(
            self,
            "mutant_identity_cid",
            _cid(self.mutant_identity_cid, "mutant_identity_cid"),
        )
        infrastructure_ok = _bool(self.infrastructure_ok, "infrastructure_ok")
        timed_out = _bool(self.timed_out, "timed_out")
        if timed_out and infrastructure_ok is False:
            # Both may be true independently; no conflict. Keep as stated.
            pass
        object.__setattr__(self, "infrastructure_ok", infrastructure_ok)
        object.__setattr__(self, "timed_out", timed_out)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def predicted_detector_ids(self) -> tuple[str, ...]:
        return tuple(self.detector_classification.predicted_detector_ids)

    @property
    def selected_detector_ids(self) -> tuple[str, ...]:
        return tuple(self.detector_classification.selected_detector_ids)

    @property
    def executed_detector_ids(self) -> tuple[str, ...]:
        return tuple(self.detector_classification.executed_detector_ids)

    @property
    def observed_detector_ids(self) -> tuple[str, ...]:
        return tuple(self.detector_classification.observed_detector_ids)

    @property
    def missed_detector_ids(self) -> tuple[str, ...]:
        return self.detector_classification.missed_detector_ids

    @property
    def unexpected_detector_ids(self) -> tuple[str, ...]:
        return self.detector_classification.unexpected_detector_ids

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_EXECUTION_RECEIPT_SCHEMA,
            "interface_id": MUTATION_EXECUTION_RECEIPT_INTERFACE,
            "header": self.header.identity_payload(),
            "receipt_id": self.receipt_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "execution_plan_cid": self.execution_plan_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "detector_classification": (
                self.detector_classification.identity_payload()
            ),
            "cost": self.cost.identity_payload(),
            "mutant_identity_cid": self.mutant_identity_cid,
            "infrastructure_ok": self.infrastructure_ok,
            "timed_out": self.timed_out,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_EXECUTION_RECEIPT_SCHEMA,
            "interface_id": MUTATION_EXECUTION_RECEIPT_INTERFACE,
            "header": self.header.to_dict(),
            "receipt_id": self.receipt_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "execution_plan_cid": self.execution_plan_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "detector_classification": self.detector_classification.to_dict(),
            "cost": self.cost.to_dict(),
            "mutant_identity_cid": self.mutant_identity_cid,
            "infrastructure_ok": self.infrastructure_ok,
            "timed_out": self.timed_out,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationExecutionReceipt":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("receipt_cid")
        if payload.pop("schema") != MUTATION_EXECUTION_RECEIPT_SCHEMA:
            raise ExecutionContractError(
                "unsupported MutationExecutionReceipt schema version"
            )
        if payload.pop("interface_id") != MUTATION_EXECUTION_RECEIPT_INTERFACE:
            raise ExecutionContractError(
                "unsupported MutationExecutionReceipt interface_id"
            )
        result = cls(
            header=payload["header"],
            receipt_id=payload["receipt_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            execution_plan_cid=payload["execution_plan_cid"],
            expected_detection_set_cid=payload["expected_detection_set_cid"],
            detector_classification=payload["detector_classification"],
            cost=payload["cost"],
            mutant_identity_cid=payload["mutant_identity_cid"],
            infrastructure_ok=payload["infrastructure_ok"],
            timed_out=payload["timed_out"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.receipt_cid:
            raise ExecutionContractError(
                "MutationExecutionReceipt receipt_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# MutationOutcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationOutcome:
    """Closed outcome classification for one mutant execution.

    Interface: ``MutationOutcome@1``

    ``counts_as_killed`` is a derived property and is never true for invalid,
    uncompilable, infrastructure, timeout, inconclusive, or equivalent cases.
    """

    header: AssuranceArtifactHeader
    outcome_id: str
    candidate_id: str
    candidate_cid: str
    receipt_cid: str
    expected_detection_set_cid: str
    outcome_status: MutationOutcomeStatus | str
    detector_classification: DetectorClassification
    killing_detector_id: str | None = None
    killing_detector_kind: DetectorKind | str | None = None
    equivalence_assessment_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "outcome_id",
            "candidate_id",
            "candidate_cid",
            "receipt_cid",
            "expected_detection_set_cid",
            "outcome_status",
            "detector_classification",
            "killing_detector_id",
            "killing_detector_kind",
            "equivalence_assessment_cid",
            "counts_as_killed",
            "notes",
            "metadata",
            "outcome_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_outcome":
            raise ExecutionContractError(
                "header.artifact_kind must be mutation_outcome"
            )
        object.__setattr__(self, "outcome_id", _token(self.outcome_id, "outcome_id"))
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(self, "receipt_cid", _cid(self.receipt_cid, "receipt_cid"))
        object.__setattr__(
            self,
            "expected_detection_set_cid",
            _cid(self.expected_detection_set_cid, "expected_detection_set_cid"),
        )
        status = _enum(self.outcome_status, MutationOutcomeStatus, "outcome_status")
        object.__setattr__(self, "outcome_status", status)
        classification = _normalize_detector_classification(
            self.detector_classification
        )
        object.__setattr__(self, "detector_classification", classification)

        killing_id = self.killing_detector_id
        if killing_id is not None:
            killing_id = _token(killing_id, "killing_detector_id")
        object.__setattr__(self, "killing_detector_id", killing_id)

        killing_kind = self.killing_detector_kind
        if killing_kind is not None:
            killing_kind = _enum(
                killing_kind, DetectorKind, "killing_detector_kind"
            )
        object.__setattr__(self, "killing_detector_kind", killing_kind)

        object.__setattr__(
            self,
            "equivalence_assessment_cid",
            _optional_cid(
                self.equivalence_assessment_cid, "equivalence_assessment_cid"
            ),
        )

        # Fail-closed kill bookkeeping.
        killed = status in _KILLED_OUTCOME_STATUSES
        if killed:
            if killing_id is None:
                raise ExecutionContractError(
                    "killed outcomes require killing_detector_id"
                )
            if killing_id not in classification.observed_detector_ids:
                raise ExecutionContractError(
                    "killing_detector_id must be among observed_detector_ids"
                )
            if killing_kind is None:
                raise ExecutionContractError(
                    "killed outcomes require killing_detector_kind"
                )
            allowed_kinds = _KILL_STATUS_TO_DETECTOR_KIND[status]
            if killing_kind not in allowed_kinds:
                raise ExecutionContractError(
                    f"killing_detector_kind {killing_kind!r} is inconsistent with "
                    f"outcome_status {status!r}"
                )
        else:
            if killing_id is not None or killing_kind is not None:
                raise ExecutionContractError(
                    "non-killed outcomes must not set killing_detector_id/kind"
                )

        if status in {
            MutationOutcomeStatus.EQUIVALENT.value,
            MutationOutcomeStatus.PROBABLY_EQUIVALENT.value,
        }:
            if self.equivalence_assessment_cid is None:
                raise ExecutionContractError(
                    "equivalent outcomes require equivalence_assessment_cid"
                )

        # Hard acceptance: never count these as killed.
        if status in _NEVER_COUNTED_AS_KILLED and killed:
            raise ExecutionContractError(
                f"outcome_status {status!r} must never count as killed"
            )
        if status in _NEVER_COUNTED_AS_KILLED and status in _KILLED_OUTCOME_STATUSES:
            raise ExecutionContractError(
                f"internal inconsistency: {status!r} in both kill and never-kill sets"
            )

        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def counts_as_killed(self) -> bool:
        """True only for genuine kill statuses; never for invalid/equivalent/etc."""

        return counts_as_killed(self.outcome_status)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_OUTCOME_SCHEMA,
            "interface_id": MUTATION_OUTCOME_INTERFACE,
            "header": self.header.identity_payload(),
            "outcome_id": self.outcome_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "receipt_cid": self.receipt_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "outcome_status": self.outcome_status,
            "detector_classification": (
                self.detector_classification.identity_payload()
            ),
            "killing_detector_id": self.killing_detector_id,
            "killing_detector_kind": self.killing_detector_kind,
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "counts_as_killed": self.counts_as_killed,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def outcome_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_OUTCOME_SCHEMA,
            "interface_id": MUTATION_OUTCOME_INTERFACE,
            "header": self.header.to_dict(),
            "outcome_id": self.outcome_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "receipt_cid": self.receipt_cid,
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "outcome_status": self.outcome_status,
            "detector_classification": self.detector_classification.to_dict(),
            "killing_detector_id": self.killing_detector_id,
            "killing_detector_kind": self.killing_detector_kind,
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "counts_as_killed": self.counts_as_killed,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "outcome_cid": self.outcome_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationOutcome":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("outcome_cid")
        claimed_counts = payload.pop("counts_as_killed")
        if payload.pop("schema") != MUTATION_OUTCOME_SCHEMA:
            raise ExecutionContractError(
                "unsupported MutationOutcome schema version"
            )
        if payload.pop("interface_id") != MUTATION_OUTCOME_INTERFACE:
            raise ExecutionContractError(
                "unsupported MutationOutcome interface_id"
            )
        result = cls(
            header=payload["header"],
            outcome_id=payload["outcome_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            receipt_cid=payload["receipt_cid"],
            expected_detection_set_cid=payload["expected_detection_set_cid"],
            outcome_status=payload["outcome_status"],
            detector_classification=payload["detector_classification"],
            killing_detector_id=payload["killing_detector_id"],
            killing_detector_kind=payload["killing_detector_kind"],
            equivalence_assessment_cid=payload["equivalence_assessment_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if type(claimed_counts) is not bool:
            raise ExecutionContractError("counts_as_killed must be a boolean")
        if claimed_counts != result.counts_as_killed:
            raise ExecutionContractError(
                "counts_as_killed must match derived kill classification; "
                "invalid/uncompilable/infrastructure/timeout/inconclusive/"
                "equivalent cases never count as killed"
            )
        if claimed != result.outcome_cid:
            raise ExecutionContractError(
                "MutationOutcome outcome_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# MutationEquivalenceAssessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationEquivalenceAssessment:
    """Bounded equivalence judgment for one mutant.

    Interface: ``MutationEquivalenceAssessment@1``

    Uses only ``equivalent``, ``probably_equivalent``, ``not_equivalent``, and
    ``unknown``. Difficulty to kill never implies equivalence.
    """

    header: AssuranceArtifactHeader
    assessment_id: str
    candidate_id: str
    candidate_cid: str
    assessment_status: EquivalenceAssessmentStatus | str
    methods: Sequence[EquivalenceMethod | str]
    evidence_cids: Sequence[str] = ()
    difficulty_to_kill_not_evidence: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "assessment_id",
            "candidate_id",
            "candidate_cid",
            "assessment_status",
            "methods",
            "evidence_cids",
            "difficulty_to_kill_not_evidence",
            "notes",
            "metadata",
            "assessment_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutation_equivalence_assessment":
            raise ExecutionContractError(
                "header.artifact_kind must be mutation_equivalence_assessment"
            )
        object.__setattr__(
            self, "assessment_id", _token(self.assessment_id, "assessment_id")
        )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self,
            "assessment_status",
            _enum(
                self.assessment_status,
                EquivalenceAssessmentStatus,
                "assessment_status",
            ),
        )
        methods = _unique_sorted_enums(
            list(self.methods),
            EquivalenceMethod,
            "methods",
            maximum=len(EquivalenceMethod),
        )
        if not methods:
            raise ExecutionContractError("methods must not be empty")
        object.__setattr__(self, "methods", methods)
        object.__setattr__(
            self,
            "evidence_cids",
            _unique_sorted_cids(list(self.evidence_cids), "evidence_cids"),
        )
        flag = _bool(
            self.difficulty_to_kill_not_evidence,
            "difficulty_to_kill_not_evidence",
        )
        if not flag:
            raise ExecutionContractError(
                "difficulty_to_kill_not_evidence must be true; difficulty to "
                "kill never implies equivalence"
            )
        object.__setattr__(self, "difficulty_to_kill_not_evidence", flag)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_EQUIVALENCE_ASSESSMENT_SCHEMA,
            "interface_id": MUTATION_EQUIVALENCE_ASSESSMENT_INTERFACE,
            "header": self.header.identity_payload(),
            "assessment_id": self.assessment_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "assessment_status": self.assessment_status,
            "methods": list(self.methods),
            "evidence_cids": list(self.evidence_cids),
            "difficulty_to_kill_not_evidence": self.difficulty_to_kill_not_evidence,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def assessment_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTATION_EQUIVALENCE_ASSESSMENT_SCHEMA,
            "interface_id": MUTATION_EQUIVALENCE_ASSESSMENT_INTERFACE,
            "header": self.header.to_dict(),
            "assessment_id": self.assessment_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "assessment_status": self.assessment_status,
            "methods": list(self.methods),
            "evidence_cids": list(self.evidence_cids),
            "difficulty_to_kill_not_evidence": self.difficulty_to_kill_not_evidence,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "assessment_cid": self.assessment_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationEquivalenceAssessment":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("assessment_cid")
        if payload.pop("schema") != MUTATION_EQUIVALENCE_ASSESSMENT_SCHEMA:
            raise ExecutionContractError(
                "unsupported MutationEquivalenceAssessment schema version"
            )
        if payload.pop("interface_id") != MUTATION_EQUIVALENCE_ASSESSMENT_INTERFACE:
            raise ExecutionContractError(
                "unsupported MutationEquivalenceAssessment interface_id"
            )
        result = cls(
            header=payload["header"],
            assessment_id=payload["assessment_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            assessment_status=payload["assessment_status"],
            methods=payload["methods"],
            evidence_cids=payload["evidence_cids"],
            difficulty_to_kill_not_evidence=payload[
                "difficulty_to_kill_not_evidence"
            ],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.assessment_cid:
            raise ExecutionContractError(
                "MutationEquivalenceAssessment assessment_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Vocabulary / kill-counting helpers
# ---------------------------------------------------------------------------


def detector_kinds() -> tuple[str, ...]:
    """Return the closed detector-kind vocabulary in declaration order."""

    return tuple(item.value for item in DetectorKind)


def detector_strengths() -> tuple[str, ...]:
    """Return the closed detector-strength vocabulary in declaration order."""

    return tuple(item.value for item in DetectorStrength)


def detector_roles() -> tuple[str, ...]:
    """Return the closed detector-role vocabulary in declaration order."""

    return tuple(item.value for item in DetectorRole)


def mutation_outcome_statuses() -> tuple[str, ...]:
    """Return the closed mutation-outcome vocabulary in declaration order."""

    return tuple(item.value for item in MutationOutcomeStatus)


def equivalence_assessment_statuses() -> tuple[str, ...]:
    """Return the closed equivalence-assessment vocabulary in declaration order."""

    return tuple(item.value for item in EquivalenceAssessmentStatus)


def equivalence_methods() -> tuple[str, ...]:
    """Return the closed equivalence-method vocabulary in declaration order."""

    return tuple(item.value for item in EquivalenceMethod)


def killed_outcome_statuses() -> tuple[str, ...]:
    """Return outcome statuses that count as a genuine kill."""

    return tuple(
        status
        for status in mutation_outcome_statuses()
        if status in _KILLED_OUTCOME_STATUSES
    )


def never_counted_as_killed_statuses() -> tuple[str, ...]:
    """Return outcome statuses that must never count as killed."""

    return tuple(
        status
        for status in mutation_outcome_statuses()
        if status in _NEVER_COUNTED_AS_KILLED
    )


def counts_as_killed(status: MutationOutcomeStatus | str) -> bool:
    """Return True only for genuine kill statuses.

    Invalid, uncompilable, infrastructure, timeout, inconclusive, equivalent,
    probably_equivalent, survival, and human-review statuses return False.
    Unknown statuses fail closed.
    """

    normalized = _enum(status, MutationOutcomeStatus, "outcome_status")
    if normalized in _NEVER_COUNTED_AS_KILLED:
        return False
    return normalized in _KILLED_OUTCOME_STATUSES


def assert_outcome_never_false_kill(outcome: MutationOutcome) -> None:
    """Fail closed when a non-kill status claims kill credit."""

    if not isinstance(outcome, MutationOutcome):
        raise ExecutionContractError("outcome must be MutationOutcome")
    if outcome.counts_as_killed and outcome.outcome_status in _NEVER_COUNTED_AS_KILLED:
        raise ExecutionContractError(
            f"outcome_status {outcome.outcome_status!r} must never count as killed"
        )
    if outcome.counts_as_killed != counts_as_killed(outcome.outcome_status):
        raise ExecutionContractError(
            "counts_as_killed disagrees with outcome_status classification"
        )


def verify_detection_set_identity(
    detection_set: ExpectedDetectionSet | Mapping[str, Any],
) -> str:
    """Recompute and return the detection-set CID; raise on forged input."""

    if isinstance(detection_set, ExpectedDetectionSet):
        sealed = detection_set
    elif isinstance(detection_set, Mapping):
        sealed = ExpectedDetectionSet.from_dict(detection_set)
    else:
        raise ExecutionContractError(
            "detection_set must be ExpectedDetectionSet or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.detection_set_cid:
        raise ExecutionContractError(
            "detection_set_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_outcome_identity(
    outcome: MutationOutcome | Mapping[str, Any],
) -> str:
    """Recompute and return the outcome CID; raise on forged input."""

    if isinstance(outcome, MutationOutcome):
        sealed = outcome
    elif isinstance(outcome, Mapping):
        sealed = MutationOutcome.from_dict(outcome)
    else:
        raise ExecutionContractError("outcome must be MutationOutcome or mapping")
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.outcome_cid:
        raise ExecutionContractError(
            "outcome_cid identity mismatch with recomputed identity"
        )
    assert_outcome_never_false_kill(sealed)
    return recomputed


__all__ = [
    "COST_MEASUREMENT_SCHEMA",
    "DETECTOR_CLASSIFICATION_SCHEMA",
    "DETECTOR_PREDICTION_SCHEMA",
    "EXPECTED_DETECTION_SET_INTERFACE",
    "EXPECTED_DETECTION_SET_SCHEMA",
    "MUTATION_EQUIVALENCE_ASSESSMENT_INTERFACE",
    "MUTATION_EQUIVALENCE_ASSESSMENT_SCHEMA",
    "MUTATION_EXECUTION_PLAN_INTERFACE",
    "MUTATION_EXECUTION_PLAN_SCHEMA",
    "MUTATION_EXECUTION_RECEIPT_INTERFACE",
    "MUTATION_EXECUTION_RECEIPT_SCHEMA",
    "MUTATION_OUTCOME_INTERFACE",
    "MUTATION_OUTCOME_SCHEMA",
    "CostMeasurement",
    "DetectorClassification",
    "DetectorKind",
    "DetectorPrediction",
    "DetectorRole",
    "DetectorStrength",
    "EquivalenceAssessmentStatus",
    "EquivalenceMethod",
    "ExecutionContractError",
    "ExpectedDetectionSet",
    "MutationEquivalenceAssessment",
    "MutationExecutionPlan",
    "MutationExecutionReceipt",
    "MutationOutcome",
    "MutationOutcomeStatus",
    "assert_outcome_never_false_kill",
    "counts_as_killed",
    "detector_kinds",
    "detector_roles",
    "detector_strengths",
    "equivalence_assessment_statuses",
    "equivalence_methods",
    "killed_outcome_statuses",
    "mutation_outcome_statuses",
    "never_counted_as_killed_statuses",
    "verify_detection_set_identity",
    "verify_outcome_identity",
]
