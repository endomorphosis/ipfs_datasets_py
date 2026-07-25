"""Reproducible paired statistics and non-collapsed Pareto analysis.

The benchmark report modules deliberately keep descriptive capture separate
from inference.  This module is the dependency-free inference boundary:

* case pairs are content-addressed and retain their split, cache mode, stratum,
  and source-result receipts;
* missing pairs remain visible and never become zero-valued observations;
* confidence intervals use seeded, paired resampling within every stratum;
* binary comparisons include an exact two-sided McNemar/binomial test;
* exploratory tests are labelled and Holm adjusted within their named family;
* Pareto dominance respects each metric direction and treats safety as a hard
  feasibility constraint, not as a scalar score; and
* a statistics report is validated by recomputing every aggregate and its
  content digest from the serialized case records.

No optional numerical package or benchmark backend is imported.  The standard
library implementation is intentionally small enough to replay in constrained
supervisor environments.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import random
import re
from types import MappingProxyType
from typing import Callable, Final, Iterable, Mapping, Self, Sequence

from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import (
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    BenchmarkProtocol,
    CacheMode,
    CaseResultRecord,
    MetricCategory,
    MetricDirection,
    OutcomeRecord,
    OutcomeStatus,
    ProtocolContractError,
    Split,
    canonical_json,
    validate_paired_outcomes,
)


STATISTICAL_PLAN_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.statistical-plan.v1"
)
PAIRED_OBSERVATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.paired-observation.v1"
)
COMPARISON_SPEC_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.comparison-spec.v1"
)
PAIRED_ANALYSIS_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.paired-analysis.v1"
)
PARETO_RESULT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.pareto-result.v1"
)
STATISTICS_REPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.statistics-report.v1"
)
CAUSAL_BINOMIAL_RATE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-binomial-rate.v2"
)
CAUSAL_RESCUE_RATE_BUNDLE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-rescue-rate-bundle.v2"
)

DEFAULT_BOOTSTRAP_SAMPLES: Final = 10_000
DEFAULT_BOOTSTRAP_SEED: Final = 17_291
MAX_BOOTSTRAP_SAMPLES: Final = 1_000_000
MAX_REPORT_REQUESTS: Final = 512
MAX_REPORT_OBSERVATIONS: Final = 1_000_000

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_WILSON_95_Z: Final = 1.959963984540054


class StatisticsError(ValueError):
    """Raised when statistical evidence violates the frozen contract."""


def HSSLEV0608F63() -> str:
    """Return AST-verifiable evidence for reproducible paired analysis."""

    return (
        "seeded stratified paired bootstrap, exact binary analysis, explicit "
        "missingness, case-receipt traceability, multiplicity labels, and "
        "direction-aware safety-preserving Pareto frontier"
    )


class MetricKind(str, Enum):
    """Supported paired measurement domains."""

    BINARY = "binary"
    CONTINUOUS = "continuous"


class Estimator(str, Enum):
    """Point statistic resampled by the paired bootstrap."""

    MEAN = "mean"
    MEDIAN = "median"


class AnalysisRole(str, Enum):
    """Whether an analysis was preregistered or is exploratory."""

    PRIMARY = "primary"
    EXPLORATORY = "exploratory"


class AnalysisDomain(str, Enum):
    """Decision dimensions kept distinct instead of collapsed into one score."""

    QUALITY = "quality"
    SAFETY = "safety"
    LATENCY = "latency"
    RESOURCE = "resource"
    ROUTING = "routing"
    RELIABILITY = "reliability"


class StratumDimension(str, Enum):
    """Preregistered case partitions analyzed without pooling identities."""

    LOGIC_FAMILY = "logic_family"
    DIFFICULTY = "difficulty"
    AMBIGUITY = "ambiguity"
    PROOF_ROUTE = "proof_route"
    JOINT = "joint"


class MissingKind(str, Enum):
    """Why a scheduled pair has no numeric measurement."""

    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    FIXTURE_INVALID = "fixture_invalid"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or not _SAFE_ID.fullmatch(value)
    ):
        raise StatisticsError(
            f"{field} must be a safe 1-128 character identifier"
        )
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise StatisticsError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _dag_json_cid(value: object, field: str) -> str:
    try:
        return validate_cid(value, codecs=("dag-json",))
    except ValueError as exc:
        raise StatisticsError(
            f"{field} must be a canonical DAG-JSON CIDv1"
        ) from exc


def _cid_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise StatisticsError(f"{field} must be an array")
    result = tuple(
        _dag_json_cid(item, f"{field}[]") for item in value
    )
    if result != tuple(sorted(result)) or len(result) != len(set(result)):
        raise StatisticsError(
            f"{field} must be unique and in canonical CID order"
        )
    return result


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StatisticsError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise StatisticsError(f"{field} must be a finite number")
    return result


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise StatisticsError(f"{field} must be boolean")
    return value


def _integer(
    value: object, field: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StatisticsError(f"{field} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise StatisticsError(f"{field} must be <= {maximum}")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise StatisticsError(f"{field} must be an object with string keys")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise StatisticsError(f"{field} must be an array")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise StatisticsError(
            f"{field} keys changed; missing={missing}, unknown={unknown}"
        )


def _enum(enum_type: type[Enum], value: object, field: str) -> Enum:
    if not isinstance(value, str):
        raise StatisticsError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise StatisticsError(f"unsupported {field}: {value!r}") from exc


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _quantile(values: Sequence[float], probability: float) -> float:
    """Return the deterministic R-7/linear quantile used by this schema."""

    if not values:
        raise StatisticsError("a quantile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _statistic(values: Sequence[float], estimator: Estimator) -> float:
    if not values:
        raise StatisticsError("an estimator requires at least one value")
    if estimator is Estimator.MEAN:
        return math.fsum(values) / len(values)
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _wilson_interval_95(
    numerator: int,
    denominator: int,
) -> tuple[float | None, float | None]:
    """Return the two-sided 95% Wilson score interval.

    Empty populations stay undefined.  They are never silently converted to a
    zero rate, which is particularly important for rescue and suppression
    populations whose eligibility predicates may legitimately select no
    cases.
    """

    if denominator == 0:
        return None, None
    estimate = numerator / denominator
    z_squared = _WILSON_95_Z * _WILSON_95_Z
    scale = 1.0 + z_squared / denominator
    center = (
        estimate + z_squared / (2.0 * denominator)
    ) / scale
    radius = (
        _WILSON_95_Z
        * math.sqrt(
            estimate * (1.0 - estimate) / denominator
            + z_squared / (4.0 * denominator * denominator)
        )
        / scale
    )
    return max(0.0, center - radius), min(1.0, center + radius)


@dataclass(frozen=True, slots=True)
class CausalBinomialRate:
    """CID-bound numerator and denominator for one G210 causal rate.

    Both populations contain the CIDs of the validated per-case accounting
    receipts that contribute to them.  Consequently a percentage cannot be
    relabelled from "all scheduled cases" to "escalation-eligible cases", or
    vice versa, without changing this receipt's CID.  The event population is
    required to be a subset of the denominator population.
    """

    metric_id: str
    event_label: str
    population_label: str
    event_receipt_cids: tuple[str, ...]
    population_receipt_cids: tuple[str, ...]
    confidence_millionths: int = 950_000
    schema: str = CAUSAL_BINOMIAL_RATE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CAUSAL_BINOMIAL_RATE_SCHEMA:
            raise StatisticsError("unsupported causal-binomial-rate schema")
        _safe_id(self.metric_id, "metric_id")
        _safe_id(self.event_label, "event_label")
        _safe_id(self.population_label, "population_label")
        events = _cid_tuple(
            self.event_receipt_cids, "event_receipt_cids"
        )
        population = _cid_tuple(
            self.population_receipt_cids, "population_receipt_cids"
        )
        if not set(events).issubset(population):
            raise StatisticsError(
                "causal-rate events must be a subset of its population"
            )
        if (
            isinstance(self.confidence_millionths, bool)
            or self.confidence_millionths != 950_000
        ):
            raise StatisticsError(
                "G210 causal rates require the frozen 95% confidence level"
            )
        object.__setattr__(self, "event_receipt_cids", events)
        object.__setattr__(self, "population_receipt_cids", population)

    @property
    def numerator(self) -> int:
        return len(self.event_receipt_cids)

    @property
    def denominator(self) -> int:
        return len(self.population_receipt_cids)

    @property
    def estimate(self) -> float | None:
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    @property
    def interval(self) -> tuple[float | None, float | None]:
        return _wilson_interval_95(self.numerator, self.denominator)

    def _body_dict(self) -> dict[str, object]:
        lower, upper = self.interval
        return {
            "schema": self.schema,
            "metric_id": self.metric_id,
            "event_label": self.event_label,
            "population_label": self.population_label,
            "event_receipt_cids": list(self.event_receipt_cids),
            "population_receipt_cids": list(
                self.population_receipt_cids
            ),
            "numerator": self.numerator,
            "denominator": self.denominator,
            "estimate": self.estimate,
            "confidence_millionths": self.confidence_millionths,
            "wilson_lower": lower,
            "wilson_upper": upper,
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self._body_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._body_dict(), "receipt_cid": self.receipt_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "causal_binomial_rate")
        expected = {
            "schema",
            "metric_id",
            "event_label",
            "population_label",
            "event_receipt_cids",
            "population_receipt_cids",
            "numerator",
            "denominator",
            "estimate",
            "confidence_millionths",
            "wilson_lower",
            "wilson_upper",
            "receipt_cid",
        }
        _exact_keys(data, expected, "causal_binomial_rate")
        events = _array(data["event_receipt_cids"], "event_receipt_cids")
        population = _array(
            data["population_receipt_cids"],
            "population_receipt_cids",
        )
        record = cls(
            schema=str(data["schema"]),
            metric_id=str(data["metric_id"]),
            event_label=str(data["event_label"]),
            population_label=str(data["population_label"]),
            event_receipt_cids=tuple(events),  # type: ignore[arg-type]
            population_receipt_cids=tuple(population),  # type: ignore[arg-type]
            confidence_millionths=_integer(
                data["confidence_millionths"],
                "confidence_millionths",
                maximum=1_000_000,
            ),
        )
        if dict(data) != record.to_dict():
            raise StatisticsError(
                "causal-binomial-rate derived fields or CID changed"
            )
        return record


_CAUSAL_RATE_LABELS: Final = MappingProxyType(
    {
        "escalation": (
            "eligible_and_invoked",
            "escalation_eligible",
        ),
        "suppression": (
            "scheduled_route_suppressed",
            "scheduled_optional_route",
        ),
        "causal_rescue": (
            "distinct_kernel_accepted_rescue",
            "escalation_eligible",
        ),
        "kernel_acceptance": (
            "kernel_accepted",
            "kernel_checked",
        ),
        "overlap": (
            "byte_identical_overlap",
            "component_invoked",
        ),
        "unnecessary_work": (
            "invoked_without_causal_rescue",
            "component_invoked",
        ),
    }
)


def build_causal_rescue_rate_bundle(
    aggregate: object,
) -> dict[str, object]:
    """Build all preregistered rates from one validated G210 aggregate."""

    # Local import preserves the existing metrics -> contracts dependency
    # direction while keeping this statistical analysis replayable.
    from .metrics import validate_causal_rescue_aggregate

    validated = validate_causal_rescue_aggregate(aggregate)
    components = _mapping(validated["components"], "causal components")
    rates: list[CausalBinomialRate] = []
    for component_id in sorted(components):
        component = _mapping(
            components[component_id],
            f"causal component {component_id}",
        )
        populations = _mapping(
            component["rate_populations"],
            f"{component_id} rate_populations",
        )
        if set(populations) != set(_CAUSAL_RATE_LABELS):
            raise StatisticsError(
                f"{component_id} causal rate population set changed"
            )
        for rate_id in sorted(populations):
            population = _mapping(
                populations[rate_id],
                f"{component_id}.{rate_id}",
            )
            _exact_keys(
                population,
                {"event_receipt_cids", "population_receipt_cids"},
                f"{component_id}.{rate_id}",
            )
            event_label, population_label = _CAUSAL_RATE_LABELS[rate_id]
            event_cids = _array(
                population["event_receipt_cids"],
                f"{component_id}.{rate_id}.event_receipt_cids",
            )
            population_cids = _array(
                population["population_receipt_cids"],
                f"{component_id}.{rate_id}.population_receipt_cids",
            )
            rates.append(
                CausalBinomialRate(
                    metric_id=f"{component_id}_{rate_id}_rate",
                    event_label=event_label,
                    population_label=f"{component_id}_{population_label}",
                    event_receipt_cids=tuple(event_cids),  # type: ignore[arg-type]
                    population_receipt_cids=tuple(
                        population_cids
                    ),  # type: ignore[arg-type]
                )
            )
    body = {
        "schema": CAUSAL_RESCUE_RATE_BUNDLE_SCHEMA,
        "aggregate": validated,
        "aggregate_cid": validated["aggregate_cid"],
        "proof_authority": "native_kernel",
        "rates": [item.to_dict() for item in rates],
    }
    return {**body, "bundle_cid": cid_for_dag_json(body)}


def validate_causal_rescue_rate_bundle(
    value: object,
) -> dict[str, object]:
    """Recompute every G210 rate, interval, denominator, and CID."""

    data = _mapping(value, "causal rescue rate bundle")
    expected = {
        "schema",
        "aggregate",
        "aggregate_cid",
        "proof_authority",
        "rates",
        "bundle_cid",
    }
    _exact_keys(data, expected, "causal rescue rate bundle")
    if data.get("schema") != CAUSAL_RESCUE_RATE_BUNDLE_SCHEMA:
        raise StatisticsError(
            "unsupported causal rescue rate-bundle schema"
        )
    try:
        rebuilt = build_causal_rescue_rate_bundle(data["aggregate"])
    except ProtocolContractError as exc:
        raise StatisticsError(
            f"causal rescue aggregate is invalid: {exc}"
        ) from exc
    if dict(data) != rebuilt:
        raise StatisticsError(
            "causal rescue rate bundle fields or CID changed"
        )
    return rebuilt


@dataclass(frozen=True, slots=True)
class StatisticalPlan:
    """Frozen inference settings shared by all comparisons in one report."""

    seed: int = DEFAULT_BOOTSTRAP_SEED
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    confidence_level: float = DEFAULT_PROTOCOL.thresholds.confidence_level
    schema: str = STATISTICAL_PLAN_SCHEMA
    bootstrap_method: str = "paired_stratified_percentile"
    quantile_method: str = "linear_r7"
    binary_test_method: str = "exact_two_sided_mcnemar_binomial"
    multiplicity_method: str = "holm"

    def __post_init__(self) -> None:
        if self.schema != STATISTICAL_PLAN_SCHEMA:
            raise StatisticsError("unsupported statistical-plan schema")
        _integer(self.seed, "seed", maximum=(1 << 63) - 1)
        _integer(
            self.bootstrap_samples,
            "bootstrap_samples",
            minimum=1,
            maximum=MAX_BOOTSTRAP_SAMPLES,
        )
        confidence = _number(self.confidence_level, "confidence_level")
        if not 0 < confidence < 1:
            raise StatisticsError("confidence_level must be strictly between 0 and 1")
        if confidence != DEFAULT_PROTOCOL.thresholds.confidence_level:
            raise StatisticsError(
                "confidence_level differs from the frozen protocol"
            )
        if self.bootstrap_method != "paired_stratified_percentile":
            raise StatisticsError("unsupported bootstrap_method")
        if self.quantile_method != "linear_r7":
            raise StatisticsError("unsupported quantile_method")
        if self.binary_test_method != "exact_two_sided_mcnemar_binomial":
            raise StatisticsError("unsupported binary_test_method")
        if self.multiplicity_method != "holm":
            raise StatisticsError("unsupported multiplicity_method")

    def to_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field) for field in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "statistical_plan")
        _exact_keys(data, set(cls.__dataclass_fields__), "statistical_plan")
        return cls(
            seed=_integer(data["seed"], "seed"),
            bootstrap_samples=_integer(
                data["bootstrap_samples"], "bootstrap_samples"
            ),
            confidence_level=_number(
                data["confidence_level"], "confidence_level"
            ),
            schema=str(data["schema"]),
            bootstrap_method=str(data["bootstrap_method"]),
            quantile_method=str(data["quantile_method"]),
            binary_test_method=str(data["binary_test_method"]),
            multiplicity_method=str(data["multiplicity_method"]),
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ComparisonSpec:
    """Identity and interpretation of one paired metric comparison."""

    comparison_id: str
    metric_id: str
    category: MetricCategory
    direction: MetricDirection
    unit: str
    kind: MetricKind
    estimator: Estimator
    baseline_variant_id: str
    candidate_variant_id: str
    domain: AnalysisDomain = AnalysisDomain.QUALITY
    stratum_dimension: StratumDimension = StratumDimension.LOGIC_FAMILY
    role: AnalysisRole = AnalysisRole.PRIMARY
    multiplicity_family: str | None = None
    schema: str = COMPARISON_SPEC_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != COMPARISON_SPEC_SCHEMA:
            raise StatisticsError("unsupported comparison-spec schema")
        for field in (
            "comparison_id",
            "metric_id",
            "unit",
            "baseline_variant_id",
            "candidate_variant_id",
        ):
            _safe_id(getattr(self, field), field)
        if not isinstance(self.category, MetricCategory):
            raise StatisticsError("category must be MetricCategory")
        if not isinstance(self.direction, MetricDirection):
            raise StatisticsError("direction must be MetricDirection")
        if self.direction is MetricDirection.REPORT:
            raise StatisticsError("report-only metrics cannot support inference")
        if not isinstance(self.kind, MetricKind):
            raise StatisticsError("kind must be MetricKind")
        if not isinstance(self.estimator, Estimator):
            raise StatisticsError("estimator must be Estimator")
        if self.kind is MetricKind.BINARY and self.estimator is not Estimator.MEAN:
            raise StatisticsError("binary comparisons require the mean estimator")
        if self.baseline_variant_id == self.candidate_variant_id:
            raise StatisticsError("comparison variants must be distinct")
        if self.baseline_variant_id != "A0":
            raise StatisticsError("paired inference requires the A0 baseline")
        candidate = DEFAULT_PROTOCOL.variant_map.get(self.candidate_variant_id)
        if (
            candidate is None
            or candidate.paired_against != "A0"
            or candidate.safety_diagnostic_only
        ):
            raise StatisticsError(
                "candidate must be a registered non-diagnostic A0-paired arm"
            )
        metric = next(
            (
                item
                for item in DEFAULT_PROTOCOL.metrics
                if item.metric_id == self.metric_id
            ),
            None,
        )
        if metric is None:
            raise StatisticsError("metric_id is not in the frozen registry")
        if (
            metric.category is not self.category
            or metric.direction is not self.direction
            or metric.unit != self.unit
        ):
            raise StatisticsError(
                "metric category, direction, and unit differ from the frozen registry"
            )
        if not isinstance(self.domain, AnalysisDomain):
            raise StatisticsError("domain must be AnalysisDomain")
        if not isinstance(self.stratum_dimension, StratumDimension):
            raise StatisticsError(
                "stratum_dimension must be StratumDimension"
            )
        if not isinstance(self.role, AnalysisRole):
            raise StatisticsError("role must be AnalysisRole")
        if self.role is AnalysisRole.EXPLORATORY:
            _safe_id(self.multiplicity_family, "multiplicity_family")
        elif self.multiplicity_family is not None:
            raise StatisticsError(
                "primary comparisons cannot declare an exploratory family"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "comparison_id": self.comparison_id,
            "metric_id": self.metric_id,
            "category": self.category.value,
            "direction": self.direction.value,
            "unit": self.unit,
            "kind": self.kind.value,
            "estimator": self.estimator.value,
            "baseline_variant_id": self.baseline_variant_id,
            "candidate_variant_id": self.candidate_variant_id,
            "domain": self.domain.value,
            "stratum_dimension": self.stratum_dimension.value,
            "role": self.role.value,
            "multiplicity_family": self.multiplicity_family,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "comparison_spec")
        _exact_keys(
            data,
            {
                "schema",
                "comparison_id",
                "metric_id",
                "category",
                "direction",
                "unit",
                "kind",
                "estimator",
                "baseline_variant_id",
                "candidate_variant_id",
                "domain",
                "stratum_dimension",
                "role",
                "multiplicity_family",
            },
            "comparison_spec",
        )
        return cls(
            schema=str(data["schema"]),
            comparison_id=str(data["comparison_id"]),
            metric_id=str(data["metric_id"]),
            category=_enum(
                MetricCategory, data["category"], "category"
            ),  # type: ignore[arg-type]
            direction=_enum(
                MetricDirection, data["direction"], "direction"
            ),  # type: ignore[arg-type]
            unit=str(data["unit"]),
            kind=_enum(MetricKind, data["kind"], "kind"),  # type: ignore[arg-type]
            estimator=_enum(
                Estimator, data["estimator"], "estimator"
            ),  # type: ignore[arg-type]
            baseline_variant_id=str(data["baseline_variant_id"]),
            candidate_variant_id=str(data["candidate_variant_id"]),
            domain=_enum(
                AnalysisDomain, data["domain"], "domain"
            ),  # type: ignore[arg-type]
            stratum_dimension=_enum(
                StratumDimension,
                data["stratum_dimension"],
                "stratum_dimension",
            ),  # type: ignore[arg-type]
            role=_enum(
                AnalysisRole, data["role"], "role"
            ),  # type: ignore[arg-type]
            multiplicity_family=(
                None
                if data["multiplicity_family"] is None
                else str(data["multiplicity_family"])
            ),
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class PairedCaseObservation:
    """One scheduled pair with numeric values or explicit missingness."""

    protocol_sha256: str
    run_id: str
    case_id: str
    case_manifest_sha256: str
    split: Split
    cache_mode: CacheMode
    stratum: str
    baseline_variant_id: str
    candidate_variant_id: str
    baseline_result_sha256: str
    candidate_result_sha256: str
    baseline_value: float | None
    candidate_value: float | None
    missing_kind: MissingKind | None = None
    missing_reason: str | None = None
    schema: str = PAIRED_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PAIRED_OBSERVATION_SCHEMA:
            raise StatisticsError("unsupported paired-observation schema")
        for field in (
            "protocol_sha256",
            "case_manifest_sha256",
            "baseline_result_sha256",
            "candidate_result_sha256",
        ):
            _digest(getattr(self, field), field)
        for field in (
            "run_id",
            "case_id",
            "stratum",
            "baseline_variant_id",
            "candidate_variant_id",
        ):
            _safe_id(getattr(self, field), field)
        if not isinstance(self.split, Split) or not isinstance(
            self.cache_mode, CacheMode
        ):
            raise StatisticsError("split and cache_mode must use protocol enums")
        if self.baseline_variant_id == self.candidate_variant_id:
            raise StatisticsError("pair variants must be distinct")
        present = self.baseline_value is not None
        if present != (self.candidate_value is not None):
            raise StatisticsError(
                "paired values must both be numeric or both be missing"
            )
        if present:
            object.__setattr__(
                self,
                "baseline_value",
                _number(self.baseline_value, "baseline_value"),
            )
            object.__setattr__(
                self,
                "candidate_value",
                _number(self.candidate_value, "candidate_value"),
            )
            if self.missing_kind is not None or self.missing_reason is not None:
                raise StatisticsError(
                    "measured pairs cannot carry missingness metadata"
                )
        else:
            if not isinstance(self.missing_kind, MissingKind):
                raise StatisticsError("missing pairs require a MissingKind")
            if not isinstance(self.missing_reason, str) or not self.missing_reason.strip():
                raise StatisticsError("missing pairs require a nonempty reason")

    @property
    def measured(self) -> bool:
        return self.baseline_value is not None

    @property
    def delta(self) -> float | None:
        if not self.measured:
            return None
        return float(self.candidate_value) - float(self.baseline_value)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "stratum": self.stratum,
            "baseline_variant_id": self.baseline_variant_id,
            "candidate_variant_id": self.candidate_variant_id,
            "baseline_result_sha256": self.baseline_result_sha256,
            "candidate_result_sha256": self.candidate_result_sha256,
            "baseline_value": self.baseline_value,
            "candidate_value": self.candidate_value,
            "missing_kind": (
                None if self.missing_kind is None else self.missing_kind.value
            ),
            "missing_reason": self.missing_reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "paired_observation")
        _exact_keys(
            data,
            {
                "schema",
                "protocol_sha256",
                "run_id",
                "case_id",
                "case_manifest_sha256",
                "split",
                "cache_mode",
                "stratum",
                "baseline_variant_id",
                "candidate_variant_id",
                "baseline_result_sha256",
                "candidate_result_sha256",
                "baseline_value",
                "candidate_value",
                "missing_kind",
                "missing_reason",
            },
            "paired_observation",
        )
        return cls(
            schema=str(data["schema"]),
            protocol_sha256=str(data["protocol_sha256"]),
            run_id=str(data["run_id"]),
            case_id=str(data["case_id"]),
            case_manifest_sha256=str(data["case_manifest_sha256"]),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            cache_mode=_enum(
                CacheMode, data["cache_mode"], "cache_mode"
            ),  # type: ignore[arg-type]
            stratum=str(data["stratum"]),
            baseline_variant_id=str(data["baseline_variant_id"]),
            candidate_variant_id=str(data["candidate_variant_id"]),
            baseline_result_sha256=str(data["baseline_result_sha256"]),
            candidate_result_sha256=str(data["candidate_result_sha256"]),
            baseline_value=(
                None
                if data["baseline_value"] is None
                else _number(data["baseline_value"], "baseline_value")
            ),
            candidate_value=(
                None
                if data["candidate_value"] is None
                else _number(data["candidate_value"], "candidate_value")
            ),
            missing_kind=(
                None
                if data["missing_kind"] is None
                else _enum(
                    MissingKind, data["missing_kind"], "missing_kind"
                )  # type: ignore[arg-type]
            ),
            missing_reason=(
                None
                if data["missing_reason"] is None
                else str(data["missing_reason"])
            ),
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


# Short compatibility name for callers using generic statistical vocabulary.
PairedObservation = PairedCaseObservation


def _missing_from_outcomes(
    baseline: OutcomeRecord, candidate: OutcomeRecord
) -> tuple[MissingKind, str]:
    statuses = {baseline.status, candidate.status}
    if OutcomeStatus.INFRASTRUCTURE_FAILURE in statuses:
        kind = MissingKind.INFRASTRUCTURE_FAILURE
    else:
        codes = {item.failure_code for item in (baseline, candidate)}
        if any(code is not None and code.value == "fixture_invalid" for code in codes):
            kind = MissingKind.FIXTURE_INVALID
        else:
            kind = MissingKind.CAPABILITY_UNAVAILABLE
    details = []
    for label, item in (("baseline", baseline), ("candidate", candidate)):
        code = "none" if item.failure_code is None else item.failure_code.value
        detail = "" if item.failure_detail is None else f":{item.failure_detail}"
        details.append(f"{label}={item.status.value}/{code}{detail}")
    return kind, "; ".join(details)


def observation_from_outcomes(
    baseline: OutcomeRecord,
    candidate: OutcomeRecord,
    *,
    stratum: str,
    baseline_result_sha256: str,
    candidate_result_sha256: str,
    baseline_value: float | None = None,
    candidate_value: float | None = None,
    protocol: BenchmarkProtocol = DEFAULT_PROTOCOL,
) -> PairedCaseObservation:
    """Create a traceable pair after applying the frozen outcome boundary.

    When values are omitted for an eligible pair, kernel-verified status is
    projected to a binary 0/1 measurement.  For an ineligible pair both values
    must be omitted and the preregistered missingness reason is retained.
    """

    try:
        validate_paired_outcomes(baseline, candidate, protocol=protocol)
    except ProtocolContractError as exc:
        raise StatisticsError(str(exc)) from exc
    if baseline.eligible_for_paired_statistics:
        if baseline_value is None and candidate_value is None:
            baseline_value = float(baseline.status is OutcomeStatus.VERIFIED)
            candidate_value = float(candidate.status is OutcomeStatus.VERIFIED)
        elif (baseline_value is None) != (candidate_value is None):
            raise StatisticsError("eligible pair values must be supplied together")
        missing_kind = None
        missing_reason = None
    else:
        if baseline_value is not None or candidate_value is not None:
            raise StatisticsError("ineligible pairs cannot carry numeric values")
        missing_kind, missing_reason = _missing_from_outcomes(baseline, candidate)
    return PairedCaseObservation(
        protocol_sha256=baseline.protocol_sha256,
        run_id=baseline.run_id,
        case_id=baseline.case_id,
        case_manifest_sha256=baseline.case_manifest_sha256,
        split=baseline.split,
        cache_mode=baseline.cache_mode,
        stratum=stratum,
        baseline_variant_id=baseline.variant_id,
        candidate_variant_id=candidate.variant_id,
        baseline_result_sha256=baseline_result_sha256,
        candidate_result_sha256=candidate_result_sha256,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        missing_kind=missing_kind,
        missing_reason=missing_reason,
    )


def observation_from_case_results(
    baseline: CaseResultRecord,
    candidate: CaseResultRecord,
    *,
    stratum: str,
    baseline_value: float | None = None,
    candidate_value: float | None = None,
    baseline_invalid_control: bool = False,
    candidate_invalid_control: bool = False,
    protocol: BenchmarkProtocol = DEFAULT_PROTOCOL,
) -> PairedCaseObservation:
    """Build an observation directly from durable case-result receipts."""

    if not isinstance(baseline, CaseResultRecord) or not isinstance(
        candidate, CaseResultRecord
    ):
        raise StatisticsError("pair members must be CaseResultRecord values")
    return observation_from_outcomes(
        baseline.to_outcome(invalid_control=baseline_invalid_control),
        candidate.to_outcome(invalid_control=candidate_invalid_control),
        stratum=stratum,
        baseline_result_sha256=baseline.digest,
        candidate_result_sha256=candidate.digest,
        baseline_value=baseline_value,
        candidate_value=candidate_value,
        protocol=protocol,
    )


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Serializable inputs needed to recompute one aggregate."""

    spec: ComparisonSpec
    observations: tuple[PairedCaseObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, ComparisonSpec):
            raise StatisticsError("request spec must be ComparisonSpec")
        if not isinstance(self.observations, tuple) or not self.observations:
            raise StatisticsError("request requires observations")
        if any(
            not isinstance(item, PairedCaseObservation)
            for item in self.observations
        ):
            raise StatisticsError(
                "request observations must be PairedCaseObservation values"
            )
        canonical = tuple(
            sorted(
                self.observations,
                key=lambda item: (
                    item.stratum,
                    item.case_id,
                    item.baseline_result_sha256,
                    item.candidate_result_sha256,
                ),
            )
        )
        object.__setattr__(self, "observations", canonical)

    def to_dict(self) -> dict[str, object]:
        return {
            "spec": self.spec.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "analysis_request")
        _exact_keys(data, {"spec", "observations"}, "analysis_request")
        observations = tuple(
            PairedCaseObservation.from_dict(item)
            for item in _array(data["observations"], "observations")
        )
        return cls(
            spec=ComparisonSpec.from_dict(data["spec"]),
            observations=observations,
        )

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


def _validate_request(request: AnalysisRequest) -> None:
    spec = request.spec
    identities = {
        (
            row.protocol_sha256,
            row.run_id,
            row.case_manifest_sha256,
            row.split,
            row.cache_mode,
            row.baseline_variant_id,
            row.candidate_variant_id,
        )
        for row in request.observations
    }
    if len(identities) != 1:
        raise StatisticsError(
            "a comparison must preserve protocol, run, manifest, split, cache, "
            "and paired variant identities"
        )
    (
        protocol_sha256,
        _,
        _,
        _,
        _,
        baseline_variant,
        candidate_variant,
    ) = next(iter(identities))
    if protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
        raise StatisticsError("comparison does not bind frozen protocol")
    if (
        baseline_variant != spec.baseline_variant_id
        or candidate_variant != spec.candidate_variant_id
    ):
        raise StatisticsError("observation variants differ from comparison spec")
    case_ids = [row.case_id for row in request.observations]
    if len(case_ids) != len(set(case_ids)):
        raise StatisticsError("comparison contains duplicate case observations")
    receipt_pairs = [
        (row.baseline_result_sha256, row.candidate_result_sha256)
        for row in request.observations
    ]
    if len(receipt_pairs) != len(set(receipt_pairs)):
        raise StatisticsError("comparison reuses a source-result pair")
    if spec.kind is MetricKind.BINARY:
        for row in request.observations:
            if row.measured and (
                row.baseline_value not in {0.0, 1.0}
                or row.candidate_value not in {0.0, 1.0}
            ):
                raise StatisticsError("binary measurements must be exactly 0 or 1")


def _derived_seed(plan: StatisticalPlan, spec: ComparisonSpec, scope: str) -> int:
    payload = {
        "plan_seed": plan.seed,
        "comparison_sha256": spec.digest,
        "scope": scope,
    }
    return int(_sha256_json(payload)[:16], 16)


def _bootstrap_interval(
    rows: Sequence[PairedCaseObservation],
    *,
    plan: StatisticalPlan,
    spec: ComparisonSpec,
    scope: str,
) -> tuple[float, float]:
    groups: dict[str, tuple[float, ...]] = {}
    for stratum in sorted({row.stratum for row in rows}):
        groups[stratum] = tuple(
            float(row.delta) for row in rows if row.stratum == stratum
        )
    rng = random.Random(_derived_seed(plan, spec, scope))
    replicates: list[float] = []
    for _ in range(plan.bootstrap_samples):
        sample: list[float] = []
        for stratum in sorted(groups):
            values = groups[stratum]
            sample.extend(values[rng.randrange(len(values))] for _ in values)
        replicates.append(_statistic(sample, spec.estimator))
    tail = (1.0 - plan.confidence_level) / 2.0
    return (_quantile(replicates, tail), _quantile(replicates, 1.0 - tail))


def _exact_mcnemar(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    extreme = min(left_only, right_only)
    cumulative = math.fsum(
        math.comb(discordant, k) for k in range(extreme + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * cumulative)


def _binary_table(
    rows: Sequence[PairedCaseObservation],
) -> dict[str, object]:
    both = [row.case_id for row in rows if row.baseline_value == row.candidate_value == 1]
    baseline_only = [
        row.case_id
        for row in rows
        if row.baseline_value == 1 and row.candidate_value == 0
    ]
    candidate_only = [
        row.case_id
        for row in rows
        if row.baseline_value == 0 and row.candidate_value == 1
    ]
    neither = [row.case_id for row in rows if row.baseline_value == row.candidate_value == 0]
    p_value = _exact_mcnemar(len(baseline_only), len(candidate_only))
    return {
        "both_success_count": len(both),
        "baseline_only_success_count": len(baseline_only),
        "candidate_only_success_count": len(candidate_only),
        "neither_success_count": len(neither),
        "both_success_case_ids": both,
        "baseline_only_success_case_ids": baseline_only,
        "candidate_only_success_case_ids": candidate_only,
        "neither_success_case_ids": neither,
        "discordant_count": len(baseline_only) + len(candidate_only),
        "test_status": (
            "no_discordant_pairs"
            if not baseline_only and not candidate_only
            else "computed"
        ),
        "p_value_raw": p_value,
    }


def _summary(
    rows: Sequence[PairedCaseObservation],
    *,
    plan: StatisticalPlan,
    spec: ComparisonSpec,
    scope: str,
) -> dict[str, object]:
    if not rows:
        return {
            "measured_count": 0,
            "baseline_estimate": None,
            "candidate_estimate": None,
            "candidate_minus_baseline": None,
            "percentage_point_delta": None,
            "improvement": None,
            "confidence_interval_low": None,
            "confidence_interval_high": None,
            "relative_delta": None,
            "relative_delta_missing_reason": "no_measured_pairs",
            "baseline_distribution": None,
            "candidate_distribution": None,
            "binary": None,
        }
    baseline_values = [float(row.baseline_value) for row in rows]
    candidate_values = [float(row.candidate_value) for row in rows]
    deltas = [float(row.delta) for row in rows]
    baseline_estimate = _statistic(baseline_values, spec.estimator)
    candidate_estimate = _statistic(candidate_values, spec.estimator)
    # The paired effect is the estimator over within-case differences.  This
    # matters for the median, where it is not generally a difference of medians.
    delta = _statistic(deltas, spec.estimator)
    low, high = _bootstrap_interval(
        rows, plan=plan, spec=spec, scope=scope
    )
    relative = None if baseline_estimate == 0 else delta / abs(baseline_estimate)
    distribution = lambda values: {
        "p50": _quantile(values, 0.50),
        "p95": _quantile(values, 0.95),
        "p99": _quantile(values, 0.99),
    }
    return {
        "measured_count": len(rows),
        "baseline_estimate": baseline_estimate,
        "candidate_estimate": candidate_estimate,
        "candidate_minus_baseline": delta,
        "percentage_point_delta": (
            delta * 100.0 if spec.kind is MetricKind.BINARY else None
        ),
        "improvement": (
            delta
            if spec.direction is MetricDirection.MAXIMIZE
            else -delta
        ),
        "confidence_interval_low": low,
        "confidence_interval_high": high,
        "relative_delta": relative,
        "relative_delta_missing_reason": (
            "baseline_estimate_zero" if relative is None else None
        ),
        "baseline_distribution": distribution(baseline_values),
        "candidate_distribution": distribution(candidate_values),
        "binary": (
            _binary_table(rows) if spec.kind is MetricKind.BINARY else None
        ),
    }


@dataclass(frozen=True, slots=True)
class PairedAnalysis:
    """One reproducible aggregate with complete case-level traceability."""

    spec: ComparisonSpec
    plan_sha256: str
    split: Split
    cache_mode: CacheMode
    scheduled_count: int
    measured_count: int
    missing_count: int
    summary: Mapping[str, object]
    strata: tuple[Mapping[str, object], ...]
    missingness: Mapping[str, object]
    case_traces: tuple[Mapping[str, object], ...]
    p_value_raw: float | None
    p_value_adjusted: float | None
    multiplicity: Mapping[str, object]
    schema: str = PAIRED_ANALYSIS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PAIRED_ANALYSIS_SCHEMA:
            raise StatisticsError("unsupported paired-analysis schema")
        if not isinstance(self.spec, ComparisonSpec):
            raise StatisticsError("analysis spec must be ComparisonSpec")
        _digest(self.plan_sha256, "plan_sha256")
        if not isinstance(self.split, Split) or not isinstance(
            self.cache_mode, CacheMode
        ):
            raise StatisticsError("analysis split/cache must use protocol enums")
        for field in ("scheduled_count", "measured_count", "missing_count"):
            _integer(getattr(self, field), field)
        if self.scheduled_count != self.measured_count + self.missing_count:
            raise StatisticsError("analysis coverage counts do not add up")
        object.__setattr__(self, "summary", _freeze_json(self.summary))
        object.__setattr__(
            self,
            "strata",
            tuple(_freeze_json(item) for item in self.strata),
        )
        object.__setattr__(self, "missingness", _freeze_json(self.missingness))
        object.__setattr__(
            self,
            "case_traces",
            tuple(_freeze_json(item) for item in self.case_traces),
        )
        object.__setattr__(self, "multiplicity", _freeze_json(self.multiplicity))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "spec": self.spec.to_dict(),
            "plan_sha256": self.plan_sha256,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "scheduled_count": self.scheduled_count,
            "measured_count": self.measured_count,
            "missing_count": self.missing_count,
            "summary": _thaw_json(self.summary),
            "strata": _thaw_json(self.strata),
            "missingness": _thaw_json(self.missingness),
            "case_traces": _thaw_json(self.case_traces),
            "p_value_raw": self.p_value_raw,
            "p_value_adjusted": self.p_value_adjusted,
            "multiplicity": _thaw_json(self.multiplicity),
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self.to_dict())


def analyze_paired(
    spec: ComparisonSpec,
    observations: Iterable[PairedCaseObservation],
    *,
    plan: StatisticalPlan = StatisticalPlan(),
) -> PairedAnalysis:
    """Analyze one comparison using seeded pair-within-stratum resampling."""

    request = AnalysisRequest(spec=spec, observations=tuple(observations))
    _validate_request(request)
    rows = request.observations
    measured = tuple(row for row in rows if row.measured)
    missing = tuple(row for row in rows if not row.measured)
    split = rows[0].split
    cache_mode = rows[0].cache_mode
    summary = _summary(
        measured, plan=plan, spec=spec, scope="overall"
    )
    strata: list[dict[str, object]] = []
    for stratum in sorted({row.stratum for row in rows}):
        scheduled_rows = tuple(row for row in rows if row.stratum == stratum)
        measured_rows = tuple(row for row in scheduled_rows if row.measured)
        strata.append(
            {
                "stratum": stratum,
                "scheduled_count": len(scheduled_rows),
                "measured_count": len(measured_rows),
                "missing_count": len(scheduled_rows) - len(measured_rows),
                "summary": _summary(
                    measured_rows,
                    plan=plan,
                    spec=spec,
                    scope=f"stratum:{stratum}",
                ),
                "case_ids": [row.case_id for row in scheduled_rows],
            }
        )
    reason_counts: dict[str, int] = {}
    kind_counts = {kind.value: 0 for kind in MissingKind}
    for row in missing:
        kind_counts[row.missing_kind.value] += 1  # type: ignore[union-attr]
        reason_counts[str(row.missing_reason)] = (
            reason_counts.get(str(row.missing_reason), 0) + 1
        )
    binary = summary["binary"]
    p_value = (
        None
        if not isinstance(binary, Mapping)
        else float(binary["p_value_raw"])
    )
    multiplicity = {
        "role": spec.role.value,
        "family": spec.multiplicity_family,
        "method": (
            "none_preregistered_primary"
            if spec.role is AnalysisRole.PRIMARY
            else plan.multiplicity_method
        ),
        "family_size": 1 if spec.role is AnalysisRole.PRIMARY else None,
        "adjustment_status": (
            "not_applicable"
            if spec.role is AnalysisRole.PRIMARY
            else "pending_family_adjustment"
        ),
    }
    case_traces = tuple(
        {
            "case_id": row.case_id,
            "stratum": row.stratum,
            "baseline_result_sha256": row.baseline_result_sha256,
            "candidate_result_sha256": row.candidate_result_sha256,
            "observation_sha256": row.digest,
            "included": row.measured,
            "baseline_value": row.baseline_value,
            "candidate_value": row.candidate_value,
            "candidate_minus_baseline": row.delta,
            "missing_kind": (
                None if row.missing_kind is None else row.missing_kind.value
            ),
            "missing_reason": row.missing_reason,
        }
        for row in rows
    )
    return PairedAnalysis(
        spec=spec,
        plan_sha256=plan.digest,
        split=split,
        cache_mode=cache_mode,
        scheduled_count=len(rows),
        measured_count=len(measured),
        missing_count=len(missing),
        summary=summary,
        strata=tuple(strata),
        missingness={
            "missing_case_ids": [row.case_id for row in missing],
            "kind_counts": kind_counts,
            "reason_counts": dict(sorted(reason_counts.items())),
            "policy": (
                "capability_unavailable, independently established fixture_invalid, "
                "and infrastructure_failure remain null and outside numeric "
                "denominators; evaluated logical failures remain measured"
            ),
        },
        case_traces=case_traces,
        p_value_raw=p_value,
        p_value_adjusted=(
            p_value if spec.role is AnalysisRole.PRIMARY else None
        ),
        multiplicity=multiplicity,
    )


def adjust_exploratory_multiplicity(
    analyses: Iterable[PairedAnalysis],
) -> tuple[PairedAnalysis, ...]:
    """Apply Holm adjustment to each named exploratory binary-test family."""

    records = tuple(analyses)
    if len({item.spec.comparison_id for item in records}) != len(records):
        raise StatisticsError("analysis comparison IDs must be unique")
    result = list(records)
    families = sorted(
        {
            item.spec.multiplicity_family
            for item in records
            if item.spec.role is AnalysisRole.EXPLORATORY
        }
    )
    for family in families:
        indexes = [
            index
            for index, item in enumerate(records)
            if item.spec.role is AnalysisRole.EXPLORATORY
            and item.spec.multiplicity_family == family
        ]
        tested = [
            index for index in indexes if records[index].p_value_raw is not None
        ]
        ordered = sorted(
            tested,
            key=lambda index: (
                float(records[index].p_value_raw),
                records[index].spec.comparison_id,
            ),
        )
        adjusted: dict[int, float] = {}
        running = 0.0
        count = len(ordered)
        for rank, index in enumerate(ordered):
            candidate = min(
                1.0,
                (count - rank) * float(records[index].p_value_raw),
            )
            running = max(running, candidate)
            adjusted[index] = running
        for index in indexes:
            current = records[index]
            multiplicity = {
                "role": AnalysisRole.EXPLORATORY.value,
                "family": family,
                "method": "holm",
                "family_size": len(indexes),
                "tested_hypothesis_count": len(tested),
                "adjustment_status": (
                    "adjusted"
                    if current.p_value_raw is not None
                    else "no_test_statistic"
                ),
            }
            result[index] = replace(
                current,
                p_value_adjusted=adjusted.get(index),
                multiplicity=multiplicity,
            )
    return tuple(result)


def analyze_requests(
    requests: Iterable[AnalysisRequest],
    *,
    plan: StatisticalPlan = StatisticalPlan(),
) -> tuple[PairedAnalysis, ...]:
    """Analyze a canonical request set and finish family-wise adjustment."""

    records = tuple(
        sorted(requests, key=lambda item: item.spec.comparison_id)
    )
    if not records:
        raise StatisticsError("at least one analysis request is required")
    if len(records) > MAX_REPORT_REQUESTS:
        raise StatisticsError("statistics report contains too many requests")
    if len({item.spec.comparison_id for item in records}) != len(records):
        raise StatisticsError("comparison IDs must be unique")
    analyses = tuple(
        analyze_paired(item.spec, item.observations, plan=plan)
        for item in records
    )
    return adjust_exploratory_multiplicity(analyses)


def analyze_paired_results(
    baselines: Iterable[CaseResultRecord],
    candidates: Iterable[CaseResultRecord],
    *,
    spec: ComparisonSpec,
    strata: Mapping[str, str],
    plan: StatisticalPlan = StatisticalPlan(),
    value_getter: Callable[[CaseResultRecord], float] | None = None,
    protocol: BenchmarkProtocol = DEFAULT_PROTOCOL,
) -> PairedAnalysis:
    """Convenience analysis over two case-result collections.

    ``value_getter`` is omitted for the kernel-verified binary outcome.  A
    custom getter can project latency, resource, routing, reliability, or other
    preregistered numeric evidence from each durable result.
    """

    baseline_records = tuple(baselines)
    candidate_records = tuple(candidates)
    if not baseline_records or not candidate_records:
        raise StatisticsError("case-result analysis requires nonempty collections")
    baseline_by_case = {item.case_id: item for item in baseline_records}
    candidate_by_case = {item.case_id: item for item in candidate_records}
    if len(baseline_by_case) != len(baseline_records) or len(candidate_by_case) != len(
        candidate_records
    ):
        raise StatisticsError("case-result collections contain duplicate case IDs")
    if set(baseline_by_case) != set(candidate_by_case):
        raise StatisticsError("baseline and candidate collections are not complete pairs")
    if set(strata) != set(baseline_by_case):
        raise StatisticsError("strata must identify every paired case exactly")
    observations = []
    for case_id in sorted(baseline_by_case):
        baseline = baseline_by_case[case_id]
        candidate = candidate_by_case[case_id]
        if value_getter is None:
            baseline_value = candidate_value = None
        elif (
            baseline.to_outcome().eligible_for_paired_statistics
            and candidate.to_outcome().eligible_for_paired_statistics
        ):
            baseline_value = _number(value_getter(baseline), "baseline_value")
            candidate_value = _number(value_getter(candidate), "candidate_value")
        else:
            baseline_value = candidate_value = None
        observations.append(
            observation_from_case_results(
                baseline,
                candidate,
                stratum=strata[case_id],
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                protocol=protocol,
            )
        )
    return analyze_paired(spec, observations, plan=plan)


@dataclass(frozen=True, slots=True)
class ParetoObjective:
    """One independently interpreted objective in a Pareto comparison."""

    metric_id: str
    direction: MetricDirection

    def __post_init__(self) -> None:
        _safe_id(self.metric_id, "metric_id")
        if not isinstance(self.direction, MetricDirection):
            raise StatisticsError("Pareto direction must be MetricDirection")

    def to_dict(self) -> dict[str, str]:
        return {"metric_id": self.metric_id, "direction": self.direction.value}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "pareto_objective")
        _exact_keys(data, {"metric_id", "direction"}, "pareto_objective")
        return cls(
            metric_id=str(data["metric_id"]),
            direction=_enum(
                MetricDirection, data["direction"], "direction"
            ),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class ParetoCandidate:
    """Candidate metrics plus the aggregate and case receipts behind them."""

    candidate_id: str
    metrics: Mapping[str, float | None]
    analysis_sha256s: tuple[str, ...]
    case_result_sha256s: tuple[str, ...]
    safety_feasible: bool = True
    safety_reason: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.candidate_id, "candidate_id")
        if not isinstance(self.metrics, Mapping) or not self.metrics:
            raise StatisticsError("Pareto candidate metrics must be nonempty")
        normalized: dict[str, float | None] = {}
        for metric_id, value in self.metrics.items():
            _safe_id(metric_id, "metric_id")
            normalized[metric_id] = (
                None if value is None else _number(value, f"metrics.{metric_id}")
            )
        object.__setattr__(
            self, "metrics", MappingProxyType(dict(sorted(normalized.items())))
        )
        if not self.analysis_sha256s or not self.case_result_sha256s:
            raise StatisticsError(
                "Pareto candidates require aggregate and case-result links"
            )
        for field in ("analysis_sha256s", "case_result_sha256s"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise StatisticsError(f"{field} must be unique")
            for value in values:
                _digest(value, f"{field}[]")
            object.__setattr__(self, field, tuple(sorted(values)))
        if not isinstance(self.safety_feasible, bool):
            raise StatisticsError("safety_feasible must be boolean")
        if self.safety_feasible and self.safety_reason is not None:
            raise StatisticsError("safe candidates cannot carry a safety reason")
        if not self.safety_feasible and (
            not isinstance(self.safety_reason, str)
            or not self.safety_reason.strip()
        ):
            raise StatisticsError("unsafe candidates require a safety reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "metrics": dict(self.metrics),
            "analysis_sha256s": list(self.analysis_sha256s),
            "case_result_sha256s": list(self.case_result_sha256s),
            "safety_feasible": self.safety_feasible,
            "safety_reason": self.safety_reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "pareto_candidate")
        _exact_keys(
            data,
            {
                "candidate_id",
                "metrics",
                "analysis_sha256s",
                "case_result_sha256s",
                "safety_feasible",
                "safety_reason",
            },
            "pareto_candidate",
        )
        metrics = _mapping(data["metrics"], "metrics")
        return cls(
            candidate_id=str(data["candidate_id"]),
            metrics={
                key: None if item is None else _number(item, f"metrics.{key}")
                for key, item in metrics.items()
            },
            analysis_sha256s=tuple(
                str(item)
                for item in _array(
                    data["analysis_sha256s"], "analysis_sha256s"
                )
            ),
            case_result_sha256s=tuple(
                str(item)
                for item in _array(
                    data["case_result_sha256s"], "case_result_sha256s"
                )
            ),
            safety_feasible=_boolean(
                data["safety_feasible"], "safety_feasible"
            ),
            safety_reason=(
                None
                if data["safety_reason"] is None
                else str(data["safety_reason"])
            ),
        )


def _dominates(
    left: ParetoCandidate,
    right: ParetoCandidate,
    objectives: Sequence[ParetoObjective],
) -> bool:
    no_worse = True
    strictly_better = False
    for objective in objectives:
        if objective.direction is MetricDirection.REPORT:
            continue
        left_value = left.metrics[objective.metric_id]
        right_value = right.metrics[objective.metric_id]
        if left_value is None or right_value is None:
            return False
        if objective.direction is MetricDirection.MAXIMIZE:
            no_worse &= left_value >= right_value
            strictly_better |= left_value > right_value
        else:
            no_worse &= left_value <= right_value
            strictly_better |= left_value < right_value
    return no_worse and strictly_better


def pareto_frontier(
    candidates: Iterable[ParetoCandidate],
    objectives: Iterable[ParetoObjective],
) -> dict[str, object]:
    """Return deterministic dominance evidence without scalarizing safety."""

    points = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    dimensions = tuple(sorted(objectives, key=lambda item: item.metric_id))
    if not points or not dimensions:
        raise StatisticsError("Pareto analysis requires candidates and objectives")
    if len({item.candidate_id for item in points}) != len(points):
        raise StatisticsError("Pareto candidate IDs must be unique")
    if len({item.metric_id for item in dimensions}) != len(dimensions):
        raise StatisticsError("Pareto objective metric IDs must be unique")
    active = tuple(
        item for item in dimensions if item.direction is not MetricDirection.REPORT
    )
    if not active:
        raise StatisticsError("Pareto analysis requires a directional objective")
    records: list[dict[str, object]] = []
    frontier: list[str] = []
    for candidate in points:
        missing = [
            item.metric_id
            for item in active
            if item.metric_id not in candidate.metrics
            or candidate.metrics[item.metric_id] is None
        ]
        if not candidate.safety_feasible:
            eligible = False
            reason = f"safety_infeasible:{candidate.safety_reason}"
        elif missing:
            eligible = False
            reason = "missing_objectives:" + ",".join(missing)
        else:
            eligible = True
            reason = None
        dominators = []
        if eligible:
            dominators = [
                other.candidate_id
                for other in points
                if other.candidate_id != candidate.candidate_id
                and other.safety_feasible
                and all(
                    objective.metric_id in other.metrics
                    and other.metrics[objective.metric_id] is not None
                    for objective in active
                )
                and _dominates(other, candidate, active)
            ]
            if not dominators:
                frontier.append(candidate.candidate_id)
        records.append(
            {
                "candidate_id": candidate.candidate_id,
                "eligible": eligible,
                "ineligible_reason": reason,
                "on_frontier": eligible and not dominators,
                "dominated_by": sorted(dominators),
                "metrics": dict(candidate.metrics),
                "analysis_sha256s": list(candidate.analysis_sha256s),
                "case_result_sha256s": list(candidate.case_result_sha256s),
                "safety_feasible": candidate.safety_feasible,
                "safety_reason": candidate.safety_reason,
            }
        )
    return {
        "schema": PARETO_RESULT_SCHEMA,
        "objectives": [item.to_dict() for item in dimensions],
        "frontier_candidate_ids": frontier,
        "candidates": records,
        "dominance_rule": (
            "no worse on every maximize/minimize objective and strictly better "
            "on at least one; report-only objectives do not dominate"
        ),
        "safety_policy": (
            "safety is a hard feasibility constraint and is never scalarized"
        ),
    }


def _artifact_digest(value: Mapping[str, object]) -> str:
    return _sha256_json(
        {key: item for key, item in value.items() if key != "artifact_sha256"}
    )


def build_statistics_report(
    plan: StatisticalPlan,
    requests: Iterable[AnalysisRequest],
    *,
    pareto_objectives: Iterable[ParetoObjective] = (),
    pareto_candidates: Iterable[ParetoCandidate] = (),
) -> dict[str, object]:
    """Build and self-validate a reproducible statistics report."""

    request_records = tuple(
        sorted(requests, key=lambda item: item.spec.comparison_id)
    )
    if sum(len(item.observations) for item in request_records) > MAX_REPORT_OBSERVATIONS:
        raise StatisticsError("statistics report contains too many observations")
    analyses = analyze_requests(request_records, plan=plan)
    objectives = tuple(
        sorted(pareto_objectives, key=lambda item: item.metric_id)
    )
    candidates = tuple(
        sorted(pareto_candidates, key=lambda item: item.candidate_id)
    )
    if bool(objectives) != bool(candidates):
        raise StatisticsError(
            "Pareto objectives and candidates must both be supplied or both omitted"
        )
    pareto = (
        None if not objectives else pareto_frontier(candidates, objectives)
    )
    value: dict[str, object] = {
        "schema": STATISTICS_REPORT_SCHEMA,
        "evidence": HSSLEV0608F63(),
        "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
        "plan": plan.to_dict(),
        "requests": [item.to_dict() for item in request_records],
        "analyses": [item.to_dict() for item in analyses],
        "pareto_inputs": (
            None
            if not objectives
            else {
                "objectives": [item.to_dict() for item in objectives],
                "candidates": [item.to_dict() for item in candidates],
            }
        ),
        "pareto": pareto,
        "artifact_sha256": "",
    }
    value["artifact_sha256"] = _artifact_digest(value)
    return validate_statistics_report(value)


def validate_statistics_report(value: object) -> dict[str, object]:
    """Recompute all report aggregates and reject stale or tampered evidence."""

    data = _mapping(value, "statistics_report")
    _exact_keys(
        data,
        {
            "schema",
            "evidence",
            "protocol_sha256",
            "plan",
            "requests",
            "analyses",
            "pareto_inputs",
            "pareto",
            "artifact_sha256",
        },
        "statistics_report",
    )
    if data["schema"] != STATISTICS_REPORT_SCHEMA:
        raise StatisticsError("unsupported statistics-report schema")
    if data["evidence"] != HSSLEV0608F63():
        raise StatisticsError("statistics evidence marker changed")
    if data["protocol_sha256"] != DEFAULT_PROTOCOL_SHA256:
        raise StatisticsError("statistics report protocol changed")
    plan = StatisticalPlan.from_dict(data["plan"])
    requests = tuple(
        AnalysisRequest.from_dict(item)
        for item in _array(data["requests"], "requests")
    )
    canonical_requests = tuple(
        sorted(requests, key=lambda item: item.spec.comparison_id)
    )
    if requests != canonical_requests:
        raise StatisticsError("statistics requests are not in canonical order")
    if data["requests"] != [item.to_dict() for item in canonical_requests]:
        raise StatisticsError(
            "statistics request observations are not in canonical order"
        )
    if sum(len(item.observations) for item in requests) > MAX_REPORT_OBSERVATIONS:
        raise StatisticsError("statistics report contains too many observations")
    derived_analyses = [
        item.to_dict() for item in analyze_requests(requests, plan=plan)
    ]
    if data["analyses"] != derived_analyses:
        raise StatisticsError(
            "serialized statistical analyses differ from case observations"
        )
    raw_inputs = data["pareto_inputs"]
    if raw_inputs is None:
        if data["pareto"] is not None:
            raise StatisticsError("Pareto result has no source inputs")
    else:
        inputs = _mapping(raw_inputs, "pareto_inputs")
        _exact_keys(inputs, {"objectives", "candidates"}, "pareto_inputs")
        objectives = tuple(
            ParetoObjective.from_dict(item)
            for item in _array(inputs["objectives"], "objectives")
        )
        candidates = tuple(
            ParetoCandidate.from_dict(item)
            for item in _array(inputs["candidates"], "candidates")
        )
        if objectives != tuple(
            sorted(objectives, key=lambda item: item.metric_id)
        ):
            raise StatisticsError("Pareto objectives are not in canonical order")
        if candidates != tuple(
            sorted(candidates, key=lambda item: item.candidate_id)
        ):
            raise StatisticsError("Pareto candidates are not in canonical order")
        analyses_by_digest = {
            _sha256_json(item): item for item in derived_analyses
        }
        for candidate in candidates:
            unknown = sorted(
                set(candidate.analysis_sha256s) - set(analyses_by_digest)
            )
            if unknown:
                raise StatisticsError(
                    f"Pareto candidate {candidate.candidate_id} links unknown "
                    f"analyses: {unknown}"
                )
            linked_case_receipts: set[str] = set()
            for analysis_sha256 in candidate.analysis_sha256s:
                analysis = _mapping(
                    analyses_by_digest[analysis_sha256], "linked_analysis"
                )
                for trace_value in _array(
                    analysis["case_traces"], "case_traces"
                ):
                    trace = _mapping(trace_value, "case_trace")
                    linked_case_receipts.add(
                        _digest(
                            trace["baseline_result_sha256"],
                            "baseline_result_sha256",
                        )
                    )
                    linked_case_receipts.add(
                        _digest(
                            trace["candidate_result_sha256"],
                            "candidate_result_sha256",
                        )
                    )
            if set(candidate.case_result_sha256s) != linked_case_receipts:
                raise StatisticsError(
                    f"Pareto candidate {candidate.candidate_id} case-result "
                    "links differ from its source analyses"
                )
        derived_pareto = pareto_frontier(candidates, objectives)
        if data["pareto"] != derived_pareto:
            raise StatisticsError(
                "serialized Pareto result differs from linked inputs"
            )
    if data["artifact_sha256"] != _artifact_digest(data):
        raise StatisticsError("statistics report artifact digest changed")
    return dict(data)


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StatisticsError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_statistics_report(path: str | Path) -> dict[str, object]:
    """Load strict canonical newline JSON and validate all derived fields."""

    report_path = Path(path)
    try:
        text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StatisticsError(
            f"cannot read statistics report: {report_path}"
        ) from exc
    if not text.endswith("\n"):
        raise StatisticsError("statistics report is not canonical newline JSON")
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, StatisticsError) as exc:
        raise StatisticsError("statistics report is not strict JSON") from exc
    if canonical_json(value) + "\n" != text:
        raise StatisticsError("statistics report is not canonical JSON")
    return validate_statistics_report(value)


def statistics_summary(value: object) -> dict[str, object]:
    """Return a compact CLI-safe summary after full validation."""

    report = validate_statistics_report(value)
    analyses = _array(report["analyses"], "analyses")
    pareto = report["pareto"]
    frontier = (
        []
        if pareto is None
        else _array(
            _mapping(pareto, "pareto")["frontier_candidate_ids"],
            "frontier_candidate_ids",
        )
    )
    return {
        "section": "statistics",
        "status": "valid",
        "artifact_sha256": report["artifact_sha256"],
        "comparison_count": len(analyses),
        "scheduled_pair_count": sum(
            int(_mapping(item, "analysis")["scheduled_count"])
            for item in analyses
        ),
        "missing_pair_count": sum(
            int(_mapping(item, "analysis")["missing_count"])
            for item in analyses
        ),
        "frontier_candidate_ids": frontier,
    }


__all__ = [
    "CAUSAL_BINOMIAL_RATE_SCHEMA",
    "CAUSAL_RESCUE_RATE_BUNDLE_SCHEMA",
    "COMPARISON_SPEC_SCHEMA",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "PAIRED_ANALYSIS_SCHEMA",
    "PAIRED_OBSERVATION_SCHEMA",
    "PARETO_RESULT_SCHEMA",
    "STATISTICAL_PLAN_SCHEMA",
    "STATISTICS_REPORT_SCHEMA",
    "AnalysisRequest",
    "AnalysisDomain",
    "AnalysisRole",
    "CausalBinomialRate",
    "ComparisonSpec",
    "Estimator",
    "HSSLEV0608F63",
    "MetricKind",
    "MissingKind",
    "PairedAnalysis",
    "PairedCaseObservation",
    "PairedObservation",
    "ParetoCandidate",
    "ParetoObjective",
    "StatisticalPlan",
    "StatisticsError",
    "StratumDimension",
    "adjust_exploratory_multiplicity",
    "analyze_paired",
    "analyze_paired_results",
    "analyze_requests",
    "build_statistics_report",
    "build_causal_rescue_rate_bundle",
    "load_statistics_report",
    "observation_from_case_results",
    "observation_from_outcomes",
    "pareto_frontier",
    "statistics_summary",
    "validate_statistics_report",
    "validate_causal_rescue_rate_bundle",
]
