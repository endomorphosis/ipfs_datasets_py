"""Calibration profiles and empirical counter contracts (SCG-009).

Defines closed, versioned durable models for capsule, analyzer, task-class, and
model-route calibration. Empirical success may change routing and audit
frequency only; it never upgrades formal proof classification to ``exact``.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types (no floats).
* Rates and confidence intervals use integer basis points in ``[0, 10000]``.
* ``classification_source=empirical`` cannot declare ``proof_classification=exact``.
* Private material and model-written authority are rejected.
* Partitions are closed: calibration, development, held_out.
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
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    GovernorArtifactHeader,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

CAPSULE_CALIBRATION_RECORD_INTERFACE: Final[str] = "CapsuleCalibrationRecord@1"
CAPSULE_CALIBRATION_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-capsule-calibration@1"
)
ANALYZER_CALIBRATION_PROFILE_INTERFACE: Final[str] = "AnalyzerCalibrationProfile@1"
ANALYZER_CALIBRATION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-analyzer-calibration@1"
)
TASK_CLASS_CALIBRATION_PROFILE_INTERFACE: Final[str] = (
    "TaskClassCalibrationProfile@1"
)
TASK_CLASS_CALIBRATION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-task-class-calibration@1"
)
MODEL_ROUTE_CALIBRATION_PROFILE_INTERFACE: Final[str] = (
    "ModelRouteCalibrationProfile@1"
)
MODEL_ROUTE_CALIBRATION_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-model-route-calibration@1"
)
EMPIRICAL_RATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-empirical-rate@1"
)

BASIS_POINTS: Final[int] = 10_000
MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_PARTITION_KEYS: Final[int] = 512
MAX_REVISION: Final[int] = 2**63 - 1

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_INTERVAL_METHOD_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]{0,63}$"
)


class CalibrationContractError(SemanticGovernorBaseError):
    """Raised when a calibration contract record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class EvidencePartition(str, Enum):
    """Immutable evidence partitions; held-out is disjoint from calibration."""

    CALIBRATION = "calibration"
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class ProofClassification(str, Enum):
    """Formal/structural proof classification (not empirical success alone)."""

    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"
    UNAVAILABLE = "unavailable"


class ClassificationSource(str, Enum):
    """Authority for a declared proof classification."""

    FORMAL = "formal"
    SCHEMA = "schema"
    DETERMINISTIC = "deterministic"
    OBSERVED_STRUCTURAL = "observed_structural"
    EMPIRICAL = "empirical"


# Sources that may declare proof_classification=exact.
_EXACT_ALLOWED_SOURCES: Final[frozenset[str]] = frozenset(
    {
        ClassificationSource.FORMAL.value,
        ClassificationSource.SCHEMA.value,
        ClassificationSource.DETERMINISTIC.value,
        ClassificationSource.OBSERVED_STRUCTURAL.value,
    }
)

# Empirical-only sources — never upgrade formal exactness.
_EMPIRICAL_SOURCES: Final[frozenset[str]] = frozenset(
    {
        ClassificationSource.EMPIRICAL.value,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise CalibrationContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise CalibrationContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise CalibrationContractError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CalibrationContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise CalibrationContractError(f"{name} must be a valid CID") from exc


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise CalibrationContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise CalibrationContractError(f"{name} must be a nonnegative integer")
    if value > MAX_REVISION:
        raise CalibrationContractError(f"{name} exceeds maximum")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CalibrationContractError(f"{name} must be a boolean")
    return value


def _basis_points(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise CalibrationContractError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
    if value < 0 or value > BASIS_POINTS:
        raise CalibrationContractError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
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
        raise CalibrationContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise CalibrationContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CalibrationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise CalibrationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise CalibrationContractError(f"{name} must not contain duplicates")
    return ordered


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise CalibrationContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CalibrationContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _header(value: Any, name: str = "header") -> GovernorArtifactHeader:
    if isinstance(value, GovernorArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return GovernorArtifactHeader.from_dict(value)
        except SemanticGovernorBaseError as exc:
            raise CalibrationContractError(str(exc)) from exc
    raise CalibrationContractError(f"{name} must be GovernorArtifactHeader or mapping")


def ratio_to_basis_points(numerator: int, denominator: int) -> int | None:
    """Return ``numerator/denominator`` as integer basis points, or null."""

    if type(numerator) is not int or isinstance(numerator, bool) or numerator < 0:
        raise CalibrationContractError("ratio numerator must be a nonnegative integer")
    if type(denominator) is not int or isinstance(denominator, bool):
        raise CalibrationContractError("ratio denominator must be an integer")
    if denominator <= 0:
        return None
    value = (numerator * BASIS_POINTS) // denominator
    if value > BASIS_POINTS:
        return BASIS_POINTS
    return value


def assert_proof_classification_allowed(
    proof_classification: str | ProofClassification,
    classification_source: str | ClassificationSource,
) -> None:
    """Fail closed when empirical results try to declare formal exactness.

    Empirical calibration may only inform routing and audit frequency. It must
    never set ``proof_classification`` to ``exact``.
    """

    classification = (
        proof_classification.value
        if isinstance(proof_classification, ProofClassification)
        else str(proof_classification)
    )
    source = (
        classification_source.value
        if isinstance(classification_source, ClassificationSource)
        else str(classification_source)
    )
    # Validate closed enums first.
    classification = _enum(classification, ProofClassification, "proof_classification")
    source = _enum(source, ClassificationSource, "classification_source")
    if (
        classification == ProofClassification.EXACT.value
        and source in _EMPIRICAL_SOURCES
    ):
        raise CalibrationContractError(
            "empirical results cannot set proof classification to exact"
        )
    if (
        classification == ProofClassification.EXACT.value
        and source not in _EXACT_ALLOWED_SOURCES
    ):
        raise CalibrationContractError(
            "proof classification exact requires non-empirical classification_source"
        )


# ---------------------------------------------------------------------------
# Empirical rate with integer confidence interval
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmpiricalRate:
    """Integer-rate summary with closed confidence-interval bounds.

    All ratios are basis points in ``[0, 10000]``. No floating-point values.
    """

    successes: int
    trials: int
    rate_bp: int
    interval_lower_bp: int
    interval_upper_bp: int
    interval_method: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "successes",
            "trials",
            "rate_bp",
            "interval_lower_bp",
            "interval_upper_bp",
            "interval_method",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "successes", _nonneg_int(self.successes, "successes"))
        object.__setattr__(self, "trials", _nonneg_int(self.trials, "trials"))
        if self.successes > self.trials:
            raise CalibrationContractError("successes must not exceed trials")
        object.__setattr__(self, "rate_bp", _basis_points(self.rate_bp, "rate_bp"))
        object.__setattr__(
            self,
            "interval_lower_bp",
            _basis_points(self.interval_lower_bp, "interval_lower_bp"),
        )
        object.__setattr__(
            self,
            "interval_upper_bp",
            _basis_points(self.interval_upper_bp, "interval_upper_bp"),
        )
        if self.interval_lower_bp > self.interval_upper_bp:
            raise CalibrationContractError(
                "interval_lower_bp must not exceed interval_upper_bp"
            )
        method = _text(self.interval_method, "interval_method")
        if _INTERVAL_METHOD_RE.fullmatch(method) is None:
            raise CalibrationContractError(
                "interval_method must be a lowercase snake-case token"
            )
        object.__setattr__(self, "interval_method", method)
        if self.trials == 0:
            if self.rate_bp != 0:
                raise CalibrationContractError(
                    "rate_bp must be 0 when trials is 0"
                )
        else:
            expected = ratio_to_basis_points(self.successes, self.trials)
            if expected is not None and self.rate_bp != expected:
                raise CalibrationContractError(
                    "rate_bp must equal floor(successes * 10000 / trials)"
                )
        if not (self.interval_lower_bp <= self.rate_bp <= self.interval_upper_bp):
            raise CalibrationContractError(
                "rate_bp must lie within [interval_lower_bp, interval_upper_bp]"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EMPIRICAL_RATE_SCHEMA,
            "successes": self.successes,
            "trials": self.trials,
            "rate_bp": self.rate_bp,
            "interval_lower_bp": self.interval_lower_bp,
            "interval_upper_bp": self.interval_upper_bp,
            "interval_method": self.interval_method,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EmpiricalRate":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != EMPIRICAL_RATE_SCHEMA:
            raise CalibrationContractError("unsupported EmpiricalRate schema version")
        return cls(
            successes=payload["successes"],
            trials=payload["trials"],
            rate_bp=payload["rate_bp"],
            interval_lower_bp=payload["interval_lower_bp"],
            interval_upper_bp=payload["interval_upper_bp"],
            interval_method=payload["interval_method"],
        )

    @classmethod
    def from_counts(
        cls,
        successes: int,
        trials: int,
        *,
        interval_lower_bp: int | None = None,
        interval_upper_bp: int | None = None,
        interval_method: str = "wilson_score_95",
    ) -> "EmpiricalRate":
        """Build a rate from counters; default CI collapses to the point rate."""

        rate = ratio_to_basis_points(successes, trials)
        rate_bp = 0 if rate is None else rate
        lower = rate_bp if interval_lower_bp is None else interval_lower_bp
        upper = rate_bp if interval_upper_bp is None else interval_upper_bp
        return cls(
            successes=successes,
            trials=trials,
            rate_bp=rate_bp,
            interval_lower_bp=lower,
            interval_upper_bp=upper,
            interval_method=interval_method,
        )


def _normalize_empirical_rate(
    value: EmpiricalRate | Mapping[str, Any],
    name: str,
) -> EmpiricalRate:
    if isinstance(value, EmpiricalRate):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return EmpiricalRate.from_dict(value)
        return EmpiricalRate(
            successes=value.get("successes", 0),
            trials=value.get("trials", 0),
            rate_bp=value.get("rate_bp", 0),
            interval_lower_bp=value.get("interval_lower_bp", 0),
            interval_upper_bp=value.get("interval_upper_bp", 0),
            interval_method=value.get("interval_method", "wilson_score_95"),
        )
    raise CalibrationContractError(f"{name} must be EmpiricalRate or mapping")


# ---------------------------------------------------------------------------
# CapsuleCalibrationRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapsuleCalibrationRecord:
    """Per-capsule-class empirical counters bound to formal classification.

    Empirical counters never authorize ``proof_classification=exact``. That
    classification requires a non-empirical ``classification_source``.
    """

    header: GovernorArtifactHeader
    record_id: str
    capsule_class: str
    language: str
    symbol_kind: str
    framework: str
    analyzer_feature: str
    repository_family: str
    task_class: str
    risk_class: str
    route_tier: str
    proof_classification: ProofClassification | str
    classification_source: ClassificationSource | str
    partition: EvidencePartition | str
    revision: int
    use_count: int
    compressed_success_count: int
    expanded_success_count: int
    omission_failure_count: int
    stale_failure_count: int
    false_exact_classification_count: int
    unnecessary_raw_fallback_count: int
    review_disagreement_count: int
    token_savings_total: int
    verification_cost_total: int
    omission_rate: EmpiricalRate
    source_audit_cids: Sequence[str] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "record_id",
            "capsule_class",
            "language",
            "symbol_kind",
            "framework",
            "analyzer_feature",
            "repository_family",
            "task_class",
            "risk_class",
            "route_tier",
            "proof_classification",
            "classification_source",
            "partition",
            "revision",
            "use_count",
            "compressed_success_count",
            "expanded_success_count",
            "omission_failure_count",
            "stale_failure_count",
            "false_exact_classification_count",
            "unnecessary_raw_fallback_count",
            "review_disagreement_count",
            "token_savings_total",
            "verification_cost_total",
            "omission_rate",
            "source_audit_cids",
            "metadata",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "capsule_calibration_record":
            raise CalibrationContractError(
                "header.artifact_kind must be capsule_calibration_record"
            )
        object.__setattr__(self, "record_id", _token(self.record_id, "record_id"))
        for name in (
            "capsule_class",
            "language",
            "symbol_kind",
            "framework",
            "analyzer_feature",
            "repository_family",
            "task_class",
            "risk_class",
            "route_tier",
        ):
            object.__setattr__(self, name, _token(getattr(self, name), name))
        classification = _enum(
            self.proof_classification, ProofClassification, "proof_classification"
        )
        source = _enum(
            self.classification_source, ClassificationSource, "classification_source"
        )
        assert_proof_classification_allowed(classification, source)
        object.__setattr__(self, "proof_classification", classification)
        object.__setattr__(self, "classification_source", source)
        object.__setattr__(
            self, "partition", _enum(self.partition, EvidencePartition, "partition")
        )
        object.__setattr__(self, "revision", _nonneg_int(self.revision, "revision"))
        for name in (
            "use_count",
            "compressed_success_count",
            "expanded_success_count",
            "omission_failure_count",
            "stale_failure_count",
            "false_exact_classification_count",
            "unnecessary_raw_fallback_count",
            "review_disagreement_count",
            "token_savings_total",
            "verification_cost_total",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        if self.compressed_success_count > self.use_count:
            raise CalibrationContractError(
                "compressed_success_count must not exceed use_count"
            )
        object.__setattr__(
            self, "omission_rate", _normalize_empirical_rate(self.omission_rate, "omission_rate")
        )
        object.__setattr__(
            self,
            "source_audit_cids",
            _unique_sorted_cids(list(self.source_audit_cids), "source_audit_cids"),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CAPSULE_CALIBRATION_RECORD_SCHEMA,
            "interface_id": CAPSULE_CALIBRATION_RECORD_INTERFACE,
            "header": self.header.identity_payload(),
            "record_id": self.record_id,
            "capsule_class": self.capsule_class,
            "language": self.language,
            "symbol_kind": self.symbol_kind,
            "framework": self.framework,
            "analyzer_feature": self.analyzer_feature,
            "repository_family": self.repository_family,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "route_tier": self.route_tier,
            "proof_classification": self.proof_classification,
            "classification_source": self.classification_source,
            "partition": self.partition,
            "revision": self.revision,
            "use_count": self.use_count,
            "compressed_success_count": self.compressed_success_count,
            "expanded_success_count": self.expanded_success_count,
            "omission_failure_count": self.omission_failure_count,
            "stale_failure_count": self.stale_failure_count,
            "false_exact_classification_count": self.false_exact_classification_count,
            "unnecessary_raw_fallback_count": self.unnecessary_raw_fallback_count,
            "review_disagreement_count": self.review_disagreement_count,
            "token_savings_total": self.token_savings_total,
            "verification_cost_total": self.verification_cost_total,
            "omission_rate": self.omission_rate.identity_payload(),
            "source_audit_cids": list(self.source_audit_cids),
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CAPSULE_CALIBRATION_RECORD_SCHEMA,
            "interface_id": CAPSULE_CALIBRATION_RECORD_INTERFACE,
            "header": self.header.to_dict(),
            "record_id": self.record_id,
            "capsule_class": self.capsule_class,
            "language": self.language,
            "symbol_kind": self.symbol_kind,
            "framework": self.framework,
            "analyzer_feature": self.analyzer_feature,
            "repository_family": self.repository_family,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "route_tier": self.route_tier,
            "proof_classification": self.proof_classification,
            "classification_source": self.classification_source,
            "partition": self.partition,
            "revision": self.revision,
            "use_count": self.use_count,
            "compressed_success_count": self.compressed_success_count,
            "expanded_success_count": self.expanded_success_count,
            "omission_failure_count": self.omission_failure_count,
            "stale_failure_count": self.stale_failure_count,
            "false_exact_classification_count": self.false_exact_classification_count,
            "unnecessary_raw_fallback_count": self.unnecessary_raw_fallback_count,
            "review_disagreement_count": self.review_disagreement_count,
            "token_savings_total": self.token_savings_total,
            "verification_cost_total": self.verification_cost_total,
            "omission_rate": self.omission_rate.to_dict(),
            "source_audit_cids": list(self.source_audit_cids),
            "metadata": _thaw_structured(self.metadata),
            "record_cid": self.record_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapsuleCalibrationRecord":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != CAPSULE_CALIBRATION_RECORD_SCHEMA:
            raise CalibrationContractError(
                "unsupported CapsuleCalibrationRecord schema version"
            )
        if payload.pop("interface_id") != CAPSULE_CALIBRATION_RECORD_INTERFACE:
            raise CalibrationContractError(
                "unsupported CapsuleCalibrationRecord interface_id"
            )
        result = cls(
            header=payload["header"],
            record_id=payload["record_id"],
            capsule_class=payload["capsule_class"],
            language=payload["language"],
            symbol_kind=payload["symbol_kind"],
            framework=payload["framework"],
            analyzer_feature=payload["analyzer_feature"],
            repository_family=payload["repository_family"],
            task_class=payload["task_class"],
            risk_class=payload["risk_class"],
            route_tier=payload["route_tier"],
            proof_classification=payload["proof_classification"],
            classification_source=payload["classification_source"],
            partition=payload["partition"],
            revision=payload["revision"],
            use_count=payload["use_count"],
            compressed_success_count=payload["compressed_success_count"],
            expanded_success_count=payload["expanded_success_count"],
            omission_failure_count=payload["omission_failure_count"],
            stale_failure_count=payload["stale_failure_count"],
            false_exact_classification_count=payload[
                "false_exact_classification_count"
            ],
            unnecessary_raw_fallback_count=payload["unnecessary_raw_fallback_count"],
            review_disagreement_count=payload["review_disagreement_count"],
            token_savings_total=payload["token_savings_total"],
            verification_cost_total=payload["verification_cost_total"],
            omission_rate=payload["omission_rate"],
            source_audit_cids=payload["source_audit_cids"],
            metadata=payload["metadata"],
        )
        if claimed != result.record_cid:
            raise CalibrationContractError(
                "CapsuleCalibrationRecord record_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Shared profile body helpers
# ---------------------------------------------------------------------------


def _normalize_record_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    return _unique_sorted_cids(values, name)


# ---------------------------------------------------------------------------
# AnalyzerCalibrationProfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalyzerCalibrationProfile:
    """Aggregate empirical profile for one analyzer feature family."""

    header: GovernorArtifactHeader
    profile_id: str
    analyzer_id: str
    analyzer_version: str
    partition: EvidencePartition | str
    revision: int
    total_uses: int
    false_exact_classification_count: int
    stale_failure_count: int
    omission_rate: EmpiricalRate
    record_cids: Sequence[str] = ()
    language_keys: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "analyzer_id",
            "analyzer_version",
            "partition",
            "revision",
            "total_uses",
            "false_exact_classification_count",
            "stale_failure_count",
            "omission_rate",
            "record_cids",
            "language_keys",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "analyzer_calibration_profile":
            raise CalibrationContractError(
                "header.artifact_kind must be analyzer_calibration_profile"
            )
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "analyzer_id", _token(self.analyzer_id, "analyzer_id"))
        object.__setattr__(
            self, "analyzer_version", _text(self.analyzer_version, "analyzer_version")
        )
        object.__setattr__(
            self, "partition", _enum(self.partition, EvidencePartition, "partition")
        )
        object.__setattr__(self, "revision", _nonneg_int(self.revision, "revision"))
        object.__setattr__(self, "total_uses", _nonneg_int(self.total_uses, "total_uses"))
        object.__setattr__(
            self,
            "false_exact_classification_count",
            _nonneg_int(
                self.false_exact_classification_count,
                "false_exact_classification_count",
            ),
        )
        object.__setattr__(
            self,
            "stale_failure_count",
            _nonneg_int(self.stale_failure_count, "stale_failure_count"),
        )
        object.__setattr__(
            self, "omission_rate", _normalize_empirical_rate(self.omission_rate, "omission_rate")
        )
        object.__setattr__(
            self, "record_cids", _normalize_record_cids(list(self.record_cids), "record_cids")
        )
        if not isinstance(self.language_keys, (list, tuple)):
            raise CalibrationContractError("language_keys must be a list")
        languages = tuple(sorted(_token(item, "language_keys") for item in self.language_keys))
        if len(languages) != len(set(languages)):
            raise CalibrationContractError("language_keys must not contain duplicates")
        if len(languages) > MAX_PARTITION_KEYS:
            raise CalibrationContractError("language_keys exceeds maximum length")
        object.__setattr__(self, "language_keys", languages)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ANALYZER_CALIBRATION_PROFILE_SCHEMA,
            "interface_id": ANALYZER_CALIBRATION_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "analyzer_id": self.analyzer_id,
            "analyzer_version": self.analyzer_version,
            "partition": self.partition,
            "revision": self.revision,
            "total_uses": self.total_uses,
            "false_exact_classification_count": self.false_exact_classification_count,
            "stale_failure_count": self.stale_failure_count,
            "omission_rate": self.omission_rate.identity_payload(),
            "record_cids": list(self.record_cids),
            "language_keys": list(self.language_keys),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema": ANALYZER_CALIBRATION_PROFILE_SCHEMA,
            "interface_id": ANALYZER_CALIBRATION_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "analyzer_id": self.analyzer_id,
            "analyzer_version": self.analyzer_version,
            "partition": self.partition,
            "revision": self.revision,
            "total_uses": self.total_uses,
            "false_exact_classification_count": self.false_exact_classification_count,
            "stale_failure_count": self.stale_failure_count,
            "omission_rate": self.omission_rate.to_dict(),
            "record_cids": list(self.record_cids),
            "language_keys": list(self.language_keys),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalyzerCalibrationProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != ANALYZER_CALIBRATION_PROFILE_SCHEMA:
            raise CalibrationContractError(
                "unsupported AnalyzerCalibrationProfile schema version"
            )
        if payload.pop("interface_id") != ANALYZER_CALIBRATION_PROFILE_INTERFACE:
            raise CalibrationContractError(
                "unsupported AnalyzerCalibrationProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            analyzer_id=payload["analyzer_id"],
            analyzer_version=payload["analyzer_version"],
            partition=payload["partition"],
            revision=payload["revision"],
            total_uses=payload["total_uses"],
            false_exact_classification_count=payload[
                "false_exact_classification_count"
            ],
            stale_failure_count=payload["stale_failure_count"],
            omission_rate=payload["omission_rate"],
            record_cids=payload["record_cids"],
            language_keys=payload["language_keys"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise CalibrationContractError(
                "AnalyzerCalibrationProfile profile_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# TaskClassCalibrationProfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskClassCalibrationProfile:
    """Aggregate empirical profile for one task/risk class."""

    header: GovernorArtifactHeader
    profile_id: str
    task_class: str
    risk_class: str
    partition: EvidencePartition | str
    revision: int
    total_uses: int
    compressed_success_count: int
    expanded_success_count: int
    review_disagreement_count: int
    omission_rate: EmpiricalRate
    # Formal required proof posture for this task class — not empirical.
    required_proof_classification: ProofClassification | str
    classification_source: ClassificationSource | str
    record_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "task_class",
            "risk_class",
            "partition",
            "revision",
            "total_uses",
            "compressed_success_count",
            "expanded_success_count",
            "review_disagreement_count",
            "omission_rate",
            "required_proof_classification",
            "classification_source",
            "record_cids",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "task_class_calibration_profile":
            raise CalibrationContractError(
                "header.artifact_kind must be task_class_calibration_profile"
            )
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "task_class", _token(self.task_class, "task_class"))
        object.__setattr__(self, "risk_class", _token(self.risk_class, "risk_class"))
        object.__setattr__(
            self, "partition", _enum(self.partition, EvidencePartition, "partition")
        )
        object.__setattr__(self, "revision", _nonneg_int(self.revision, "revision"))
        for name in (
            "total_uses",
            "compressed_success_count",
            "expanded_success_count",
            "review_disagreement_count",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        if self.compressed_success_count > self.total_uses:
            raise CalibrationContractError(
                "compressed_success_count must not exceed total_uses"
            )
        object.__setattr__(
            self, "omission_rate", _normalize_empirical_rate(self.omission_rate, "omission_rate")
        )
        classification = _enum(
            self.required_proof_classification,
            ProofClassification,
            "required_proof_classification",
        )
        source = _enum(
            self.classification_source, ClassificationSource, "classification_source"
        )
        assert_proof_classification_allowed(classification, source)
        object.__setattr__(self, "required_proof_classification", classification)
        object.__setattr__(self, "classification_source", source)
        object.__setattr__(
            self, "record_cids", _normalize_record_cids(list(self.record_cids), "record_cids")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TASK_CLASS_CALIBRATION_PROFILE_SCHEMA,
            "interface_id": TASK_CLASS_CALIBRATION_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "partition": self.partition,
            "revision": self.revision,
            "total_uses": self.total_uses,
            "compressed_success_count": self.compressed_success_count,
            "expanded_success_count": self.expanded_success_count,
            "review_disagreement_count": self.review_disagreement_count,
            "omission_rate": self.omission_rate.identity_payload(),
            "required_proof_classification": self.required_proof_classification,
            "classification_source": self.classification_source,
            "record_cids": list(self.record_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TASK_CLASS_CALIBRATION_PROFILE_SCHEMA,
            "interface_id": TASK_CLASS_CALIBRATION_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "partition": self.partition,
            "revision": self.revision,
            "total_uses": self.total_uses,
            "compressed_success_count": self.compressed_success_count,
            "expanded_success_count": self.expanded_success_count,
            "review_disagreement_count": self.review_disagreement_count,
            "omission_rate": self.omission_rate.to_dict(),
            "required_proof_classification": self.required_proof_classification,
            "classification_source": self.classification_source,
            "record_cids": list(self.record_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaskClassCalibrationProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != TASK_CLASS_CALIBRATION_PROFILE_SCHEMA:
            raise CalibrationContractError(
                "unsupported TaskClassCalibrationProfile schema version"
            )
        if payload.pop("interface_id") != TASK_CLASS_CALIBRATION_PROFILE_INTERFACE:
            raise CalibrationContractError(
                "unsupported TaskClassCalibrationProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            task_class=payload["task_class"],
            risk_class=payload["risk_class"],
            partition=payload["partition"],
            revision=payload["revision"],
            total_uses=payload["total_uses"],
            compressed_success_count=payload["compressed_success_count"],
            expanded_success_count=payload["expanded_success_count"],
            review_disagreement_count=payload["review_disagreement_count"],
            omission_rate=payload["omission_rate"],
            required_proof_classification=payload["required_proof_classification"],
            classification_source=payload["classification_source"],
            record_cids=payload["record_cids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise CalibrationContractError(
                "TaskClassCalibrationProfile profile_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# ModelRouteCalibrationProfile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelRouteCalibrationProfile:
    """Route-tier empirical metrics (audit frequency / escalation only)."""

    header: GovernorArtifactHeader
    profile_id: str
    route_id: str
    route_tier: str
    partition: EvidencePartition | str
    revision: int
    total_uses: int
    escalation_count: int
    retry_count: int
    shadow_sample_count: int
    success_rate: EmpiricalRate
    escalation_rate_bp: int
    retry_rate_bp: int
    shadow_sample_rate_bp: int
    # Empirical routing must never claim formal exact proof authority.
    allows_empirical_exact_upgrade: bool
    record_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "route_id",
            "route_tier",
            "partition",
            "revision",
            "total_uses",
            "escalation_count",
            "retry_count",
            "shadow_sample_count",
            "success_rate",
            "escalation_rate_bp",
            "retry_rate_bp",
            "shadow_sample_rate_bp",
            "allows_empirical_exact_upgrade",
            "record_cids",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "model_route_calibration_profile":
            raise CalibrationContractError(
                "header.artifact_kind must be model_route_calibration_profile"
            )
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "route_id", _token(self.route_id, "route_id"))
        object.__setattr__(self, "route_tier", _token(self.route_tier, "route_tier"))
        object.__setattr__(
            self, "partition", _enum(self.partition, EvidencePartition, "partition")
        )
        object.__setattr__(self, "revision", _nonneg_int(self.revision, "revision"))
        for name in (
            "total_uses",
            "escalation_count",
            "retry_count",
            "shadow_sample_count",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        object.__setattr__(
            self, "success_rate", _normalize_empirical_rate(self.success_rate, "success_rate")
        )
        object.__setattr__(
            self,
            "escalation_rate_bp",
            _basis_points(self.escalation_rate_bp, "escalation_rate_bp"),
        )
        object.__setattr__(
            self, "retry_rate_bp", _basis_points(self.retry_rate_bp, "retry_rate_bp")
        )
        object.__setattr__(
            self,
            "shadow_sample_rate_bp",
            _basis_points(self.shadow_sample_rate_bp, "shadow_sample_rate_bp"),
        )
        allows = _bool(
            self.allows_empirical_exact_upgrade, "allows_empirical_exact_upgrade"
        )
        # Hard invariant: empirical route success never upgrades formal exactness.
        if allows:
            raise CalibrationContractError(
                "empirical results cannot set proof classification to exact; "
                "allows_empirical_exact_upgrade must be false"
            )
        object.__setattr__(self, "allows_empirical_exact_upgrade", allows)
        object.__setattr__(
            self, "record_cids", _normalize_record_cids(list(self.record_cids), "record_cids")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MODEL_ROUTE_CALIBRATION_PROFILE_SCHEMA,
            "interface_id": MODEL_ROUTE_CALIBRATION_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "route_id": self.route_id,
            "route_tier": self.route_tier,
            "partition": self.partition,
            "revision": self.revision,
            "total_uses": self.total_uses,
            "escalation_count": self.escalation_count,
            "retry_count": self.retry_count,
            "shadow_sample_count": self.shadow_sample_count,
            "success_rate": self.success_rate.identity_payload(),
            "escalation_rate_bp": self.escalation_rate_bp,
            "retry_rate_bp": self.retry_rate_bp,
            "shadow_sample_rate_bp": self.shadow_sample_rate_bp,
            "allows_empirical_exact_upgrade": self.allows_empirical_exact_upgrade,
            "record_cids": list(self.record_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MODEL_ROUTE_CALIBRATION_PROFILE_SCHEMA,
            "interface_id": MODEL_ROUTE_CALIBRATION_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "route_id": self.route_id,
            "route_tier": self.route_tier,
            "partition": self.partition,
            "revision": self.revision,
            "total_uses": self.total_uses,
            "escalation_count": self.escalation_count,
            "retry_count": self.retry_count,
            "shadow_sample_count": self.shadow_sample_count,
            "success_rate": self.success_rate.to_dict(),
            "escalation_rate_bp": self.escalation_rate_bp,
            "retry_rate_bp": self.retry_rate_bp,
            "shadow_sample_rate_bp": self.shadow_sample_rate_bp,
            "allows_empirical_exact_upgrade": self.allows_empirical_exact_upgrade,
            "record_cids": list(self.record_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelRouteCalibrationProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != MODEL_ROUTE_CALIBRATION_PROFILE_SCHEMA:
            raise CalibrationContractError(
                "unsupported ModelRouteCalibrationProfile schema version"
            )
        if payload.pop("interface_id") != MODEL_ROUTE_CALIBRATION_PROFILE_INTERFACE:
            raise CalibrationContractError(
                "unsupported ModelRouteCalibrationProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            route_id=payload["route_id"],
            route_tier=payload["route_tier"],
            partition=payload["partition"],
            revision=payload["revision"],
            total_uses=payload["total_uses"],
            escalation_count=payload["escalation_count"],
            retry_count=payload["retry_count"],
            shadow_sample_count=payload["shadow_sample_count"],
            success_rate=payload["success_rate"],
            escalation_rate_bp=payload["escalation_rate_bp"],
            retry_rate_bp=payload["retry_rate_bp"],
            shadow_sample_rate_bp=payload["shadow_sample_rate_bp"],
            allows_empirical_exact_upgrade=payload["allows_empirical_exact_upgrade"],
            record_cids=payload["record_cids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise CalibrationContractError(
                "ModelRouteCalibrationProfile profile_cid does not verify"
            )
        return result


def evidence_partitions() -> tuple[str, ...]:
    """Return the closed evidence-partition vocabulary."""

    return tuple(item.value for item in EvidencePartition)


def proof_classifications() -> tuple[str, ...]:
    """Return the closed proof-classification vocabulary."""

    return tuple(item.value for item in ProofClassification)


def classification_sources() -> tuple[str, ...]:
    """Return the closed classification-source vocabulary."""

    return tuple(item.value for item in ClassificationSource)


__all__ = [
    "ANALYZER_CALIBRATION_PROFILE_INTERFACE",
    "ANALYZER_CALIBRATION_PROFILE_SCHEMA",
    "BASIS_POINTS",
    "CAPSULE_CALIBRATION_RECORD_INTERFACE",
    "CAPSULE_CALIBRATION_RECORD_SCHEMA",
    "EMPIRICAL_RATE_SCHEMA",
    "MODEL_ROUTE_CALIBRATION_PROFILE_INTERFACE",
    "MODEL_ROUTE_CALIBRATION_PROFILE_SCHEMA",
    "TASK_CLASS_CALIBRATION_PROFILE_INTERFACE",
    "TASK_CLASS_CALIBRATION_PROFILE_SCHEMA",
    "AnalyzerCalibrationProfile",
    "CalibrationContractError",
    "CapsuleCalibrationRecord",
    "ClassificationSource",
    "EmpiricalRate",
    "EvidencePartition",
    "ModelRouteCalibrationProfile",
    "ProofClassification",
    "TaskClassCalibrationProfile",
    "assert_proof_classification_allowed",
    "classification_sources",
    "evidence_partitions",
    "proof_classifications",
    "ratio_to_basis_points",
]
