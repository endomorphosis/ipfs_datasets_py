"""Frozen contracts for the logic-pipeline benchmark protocol.

This module is intentionally dependency-free.  It contains the preregistration
that must be loaded and validated before a pilot, together with the small
run/outcome records needed to enforce its safety boundary.  Backend adapters do
not belong here and importing this module performs no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Final, Mapping, Self, TypeVar

from . import BENCHMARK_ID


PROTOCOL_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.protocol.v1"
)
PROTOCOL_RECORD_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.protocol-record.v1"
)
RUN_CONTRACT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.run-contract.v1"
)
OUTCOME_RECORD_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.outcome.v1"
)
PROTOCOL_ID: Final = "hammer-symai-spacy-leanstral-preregistered-v1"
PROTOCOL_VERSION: Final = 1
BASELINE_VARIANT: Final = "A0"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FROZEN_PROTOCOL_SHA256: str | None = None


class ProtocolContractError(ValueError):
    """Raised when a protocol or record violates a frozen invariant."""


class Split(str, Enum):
    """Immutable corpus partitions in their permitted evaluation order."""

    PILOT = "pilot"
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class CacheMode(str, Enum):
    """Cache states that must be measured and namespaced separately."""

    COLD = "cold"
    WARM = "warm"


class MetricCategory(str, Enum):
    PRIMARY = "primary"
    QUALITY = "quality"
    RESOURCE = "resource"
    ROUTING = "routing"


class MetricDirection(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    REPORT = "report"


class VerificationAuthority(str, Enum):
    """Claim sources retained in records; only one is proof authority."""

    NONE = "none"
    NATIVE_KERNEL = "native_kernel"
    EXTERNAL_SOLVER = "external_solver"
    MODEL = "model"
    LEGACY_ROUTER = "legacy_router"


class OutcomeStatus(str, Enum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    EXCLUDED = "excluded"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


class FailureCode(str, Enum):
    """Stable failure taxonomy; values are part of the wire contract."""

    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    FIXTURE_INVALID = "fixture_invalid"
    SPACY_PARSE_OR_MODEL_FALLBACK = "spacy_parse_or_model_fallback"
    SYMAI_IMPORT_OR_CONFIGURATION_ERROR = "symai_import_or_configuration_error"
    SYMAI_CONTRACT_OR_JSON_FAILURE = "symai_contract_or_json_failure"
    CANONICAL_IR_REJECTION = "canonical_ir_rejection"
    PREMISE_SELECTION_MISS = "premise_selection_miss"
    TRANSLATION_UNSUPPORTED = "translation_unsupported"
    SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE = "solver_timeout_error_or_inconclusive"
    LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT = (
        "leanstral_timeout_schema_or_forbidden_construct"
    )
    RECONSTRUCTION_FAILURE = "reconstruction_failure"
    KERNEL_REJECTION = "kernel_rejection"
    RECEIPT_OR_PROVENANCE_FAILURE = "receipt_or_provenance_failure"
    RESOURCE_LEASE_CANCELLATION = "resource_lease_cancellation"
    BENCHMARK_INFRASTRUCTURE_FAILURE = "benchmark_infrastructure_failure"
    OUT_OF_MEMORY = "out_of_memory"
    ORPHANED_CHILD = "orphaned_child"
    CACHE_CONTAMINATION = "cache_contamination"
    HOLDOUT_LEAK = "holdout_leak"
    SAFETY_CONTROL_FAILURE = "safety_control_failure"
    INVALID_CONTROL_VERIFIED = "invalid_control_verified"


INFRASTRUCTURE_FAILURE_CODES: Final = frozenset(
    {
        FailureCode.RESOURCE_LEASE_CANCELLATION,
        FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        FailureCode.OUT_OF_MEMORY,
        FailureCode.ORPHANED_CHILD,
    }
)
EXCLUSION_FAILURE_CODES: Final = frozenset(
    {FailureCode.CAPABILITY_UNAVAILABLE, FailureCode.FIXTURE_INVALID}
)
IMMEDIATE_STOP_CODES: Final = frozenset(
    {
        FailureCode.INVALID_CONTROL_VERIFIED,
        FailureCode.SAFETY_CONTROL_FAILURE,
        FailureCode.CACHE_CONTAMINATION,
        FailureCode.HOLDOUT_LEAK,
        FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
        FailureCode.ORPHANED_CHILD,
    }
)


def HSSLEV0103C72() -> str:
    """Return AST-verifiable evidence for the frozen protocol objective."""

    return "preregistered benchmark protocol and safety invariants"


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum(
    enum_type: type[_EnumT], value: object, field: str
) -> _EnumT:
    if not isinstance(value, str):
        raise ProtocolContractError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ProtocolContractError(f"unsupported {field}: {value!r}") from exc


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ProtocolContractError(
            f"{field} must be a safe 1-128 character identifier"
        )
    if value in {".", ".."}:
        raise ProtocolContractError(f"{field} must not be path traversal")
    return value


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolContractError(f"{field} must be a nonempty string")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProtocolContractError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ProtocolContractError(f"{field} must be a boolean")
    return value


def _number(
    value: object,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolContractError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolContractError(f"{field} must be a finite number")
    if minimum is not None and result < minimum:
        raise ProtocolContractError(f"{field} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ProtocolContractError(f"{field} must be <= {maximum}")
    return result


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProtocolContractError(f"{field} must be an integer >= {minimum}")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProtocolContractError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ProtocolContractError(f"{field} keys must be strings")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unknown:
            details.append(f"unknown {sorted(unknown)}")
        raise ProtocolContractError(f"{field} has " + " and ".join(details))


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProtocolContractError(f"{field} must be an array")
    result = tuple(_nonempty(item, f"{field}[]") for item in value)
    if len(result) != len(set(result)):
        raise ProtocolContractError(f"{field} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class HypothesisSpec:
    hypothesis_id: str
    statement: str
    null_statement: str

    def __post_init__(self) -> None:
        _safe_id(self.hypothesis_id, "hypothesis_id")
        _nonempty(self.statement, "statement")
        _nonempty(self.null_statement, "null_statement")

    def to_dict(self) -> dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "null_statement": self.null_statement,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "hypothesis")
        _exact_keys(
            data, {"hypothesis_id", "statement", "null_statement"}, "hypothesis"
        )
        return cls(
            hypothesis_id=_safe_id(data["hypothesis_id"], "hypothesis_id"),
            statement=_nonempty(data["statement"], "statement"),
            null_statement=_nonempty(data["null_statement"], "null_statement"),
        )


@dataclass(frozen=True, slots=True)
class VariantSpec:
    variant_id: str
    configuration: str
    purpose: str
    paired_against: str | None = BASELINE_VARIANT
    primary_candidate: bool = True
    safety_diagnostic_only: bool = False

    def __post_init__(self) -> None:
        _safe_id(self.variant_id, "variant_id")
        _nonempty(self.configuration, "configuration")
        _nonempty(self.purpose, "purpose")
        if self.paired_against is not None:
            _safe_id(self.paired_against, "paired_against")
        _bool(self.primary_candidate, "primary_candidate")
        _bool(self.safety_diagnostic_only, "safety_diagnostic_only")
        if self.safety_diagnostic_only and self.primary_candidate:
            raise ProtocolContractError(
                "a safety diagnostic cannot be a primary candidate"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "configuration": self.configuration,
            "purpose": self.purpose,
            "paired_against": self.paired_against,
            "primary_candidate": self.primary_candidate,
            "safety_diagnostic_only": self.safety_diagnostic_only,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "variant")
        keys = {
            "variant_id",
            "configuration",
            "purpose",
            "paired_against",
            "primary_candidate",
            "safety_diagnostic_only",
        }
        _exact_keys(data, keys, "variant")
        paired = data["paired_against"]
        if paired is not None:
            paired = _safe_id(paired, "paired_against")
        return cls(
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            configuration=_nonempty(data["configuration"], "configuration"),
            purpose=_nonempty(data["purpose"], "purpose"),
            paired_against=paired,
            primary_candidate=_bool(data["primary_candidate"], "primary_candidate"),
            safety_diagnostic_only=_bool(
                data["safety_diagnostic_only"], "safety_diagnostic_only"
            ),
        )


@dataclass(frozen=True, slots=True)
class MetricSpec:
    metric_id: str
    category: MetricCategory
    direction: MetricDirection
    unit: str
    kernel_bound: bool = False

    def __post_init__(self) -> None:
        _safe_id(self.metric_id, "metric_id")
        if not isinstance(self.category, MetricCategory):
            raise ProtocolContractError("category must be a MetricCategory")
        if not isinstance(self.direction, MetricDirection):
            raise ProtocolContractError("direction must be a MetricDirection")
        _nonempty(self.unit, "unit")
        _bool(self.kernel_bound, "kernel_bound")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "category": self.category.value,
            "direction": self.direction.value,
            "unit": self.unit,
            "kernel_bound": self.kernel_bound,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "metric")
        keys = {"metric_id", "category", "direction", "unit", "kernel_bound"}
        _exact_keys(data, keys, "metric")
        return cls(
            metric_id=_safe_id(data["metric_id"], "metric_id"),
            category=_enum(MetricCategory, data["category"], "category"),
            direction=_enum(MetricDirection, data["direction"], "direction"),
            unit=_nonempty(data["unit"], "unit"),
            kernel_bound=_bool(data["kernel_bound"], "kernel_bound"),
        )


@dataclass(frozen=True, slots=True)
class MaterialityThresholds:
    """Final decision gates, represented as fractions rather than percentages."""

    invalid_control_verified_max: int = 0
    confidence_level: float = 0.95
    paired_regression_floor: float = -0.01
    hard_case_verified_gain_min: float = 0.05
    near_best_quality_margin_max: float = 0.01
    efficiency_reduction_min: float = 0.20
    baseline_solved_regression_rate_max: float = 0.01
    unexplained_baseline_regressions_max: int = 0
    shortlist_candidate_max: int = 4

    def __post_init__(self) -> None:
        if _integer(
            self.invalid_control_verified_max,
            "invalid_control_verified_max",
        ) != 0:
            raise ProtocolContractError(
                "invalid-control verification tolerance is permanently zero"
            )
        _number(self.confidence_level, "confidence_level", minimum=0, maximum=1)
        _number(
            self.paired_regression_floor,
            "paired_regression_floor",
            minimum=-1,
            maximum=0,
        )
        _number(
            self.hard_case_verified_gain_min,
            "hard_case_verified_gain_min",
            minimum=0,
            maximum=1,
        )
        _number(
            self.near_best_quality_margin_max,
            "near_best_quality_margin_max",
            minimum=0,
            maximum=1,
        )
        _number(
            self.efficiency_reduction_min,
            "efficiency_reduction_min",
            minimum=0,
            maximum=1,
        )
        _number(
            self.baseline_solved_regression_rate_max,
            "baseline_solved_regression_rate_max",
            minimum=0,
            maximum=1,
        )
        _integer(
            self.unexplained_baseline_regressions_max,
            "unexplained_baseline_regressions_max",
        )
        _integer(self.shortlist_candidate_max, "shortlist_candidate_max", minimum=1)

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "thresholds")
        keys = set(cls.__dataclass_fields__)
        _exact_keys(data, keys, "thresholds")
        return cls(
            invalid_control_verified_max=_integer(
                data["invalid_control_verified_max"],
                "invalid_control_verified_max",
            ),
            confidence_level=_number(data["confidence_level"], "confidence_level"),
            paired_regression_floor=_number(
                data["paired_regression_floor"], "paired_regression_floor"
            ),
            hard_case_verified_gain_min=_number(
                data["hard_case_verified_gain_min"], "hard_case_verified_gain_min"
            ),
            near_best_quality_margin_max=_number(
                data["near_best_quality_margin_max"],
                "near_best_quality_margin_max",
            ),
            efficiency_reduction_min=_number(
                data["efficiency_reduction_min"], "efficiency_reduction_min"
            ),
            baseline_solved_regression_rate_max=_number(
                data["baseline_solved_regression_rate_max"],
                "baseline_solved_regression_rate_max",
            ),
            unexplained_baseline_regressions_max=_integer(
                data["unexplained_baseline_regressions_max"],
                "unexplained_baseline_regressions_max",
            ),
            shortlist_candidate_max=_integer(
                data["shortlist_candidate_max"],
                "shortlist_candidate_max",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class SafetyInvariants:
    kernel_only_verification: bool = True
    invalid_controls_fail_closed: bool = True
    requested_equals_effective_variant: bool = True
    paired_same_case_manifest: bool = True
    cache_by_run_variant_split_and_mode: bool = True
    cold_warm_results_separate: bool = True
    infrastructure_failures_separate: bool = True
    holdout_tuning_forbidden: bool = True
    holdout_access_audited: bool = True
    auto_merge_forbidden: bool = True
    production_promotion_forbidden: bool = True

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if _bool(getattr(self, name), name) is not True:
                raise ProtocolContractError(
                    f"safety invariant {name} cannot be relaxed"
                )

    def to_dict(self) -> dict[str, bool]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "safety_invariants")
        keys = set(cls.__dataclass_fields__)
        _exact_keys(data, keys, "safety_invariants")
        return cls(**{key: _bool(data[key], key) for key in keys})


@dataclass(frozen=True, slots=True)
class HoldoutRules:
    freeze_case_ids_and_digest_before_pilot: bool = True
    shortlist_uses_pilot_and_development_only: bool = True
    freeze_prompts_policy_models_and_thresholds: bool = True
    audit_every_access: bool = True
    tuning_after_access_forbidden: bool = True
    replay_in_fresh_cache_and_worktree: bool = True

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if _bool(getattr(self, name), name) is not True:
                raise ProtocolContractError(f"holdout rule {name} cannot be relaxed")

    def to_dict(self) -> dict[str, bool]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "holdout_rules")
        keys = set(cls.__dataclass_fields__)
        _exact_keys(data, keys, "holdout_rules")
        return cls(**{key: _bool(data[key], key) for key in keys})


@dataclass(frozen=True, slots=True)
class StopCondition:
    failure_code: FailureCode
    consecutive_occurrences: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.failure_code, FailureCode):
            raise ProtocolContractError("failure_code must be a FailureCode")
        _integer(
            self.consecutive_occurrences,
            "consecutive_occurrences",
            minimum=1,
        )
        _nonempty(self.reason, "reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "failure_code": self.failure_code.value,
            "consecutive_occurrences": self.consecutive_occurrences,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "stop_condition")
        keys = {"failure_code", "consecutive_occurrences", "reason"}
        _exact_keys(data, keys, "stop_condition")
        return cls(
            failure_code=_enum(
                FailureCode, data["failure_code"], "failure_code"
            ),  # type: ignore[arg-type]
            consecutive_occurrences=_integer(
                data["consecutive_occurrences"],
                "consecutive_occurrences",
                minimum=1,
            ),
            reason=_nonempty(data["reason"], "reason"),
        )


_REQUIRED_HYPOTHESES = frozenset(f"H{i}" for i in range(1, 8))
_REQUIRED_VARIANTS = frozenset(
    [*(f"A{i}" for i in range(13)), "S1"]
)
_REQUIRED_PRIMARY_METRICS = frozenset(
    {
        "kernel_verified_completion_rate",
        "invalid_control_kernel_false_positive_rate",
        "normalized_ir_exact_match",
        "deterministic_semantic_equivalence",
        "paired_verified_delta_vs_a0",
    }
)


@dataclass(frozen=True, slots=True)
class BenchmarkProtocol:
    """Complete immutable preregistration for one protocol revision."""

    schema: str
    protocol_id: str
    protocol_version: int
    frozen: bool
    pilot_results_inspected: bool
    hypotheses: tuple[HypothesisSpec, ...]
    variants: tuple[VariantSpec, ...]
    metrics: tuple[MetricSpec, ...]
    thresholds: MaterialityThresholds
    safety_invariants: SafetyInvariants
    holdout_rules: HoldoutRules
    exclusion_failure_codes: tuple[FailureCode, ...]
    failure_taxonomy: tuple[FailureCode, ...]
    stop_conditions: tuple[StopCondition, ...]

    def __post_init__(self) -> None:
        if self.schema != PROTOCOL_SCHEMA:
            raise ProtocolContractError(f"unsupported protocol schema {self.schema!r}")
        if self.protocol_id != PROTOCOL_ID:
            raise ProtocolContractError(f"unsupported protocol id {self.protocol_id!r}")
        if (
            isinstance(self.protocol_version, bool)
            or self.protocol_version != PROTOCOL_VERSION
        ):
            raise ProtocolContractError(
                f"unsupported protocol version {self.protocol_version!r}"
            )
        if _bool(self.frozen, "frozen") is not True:
            raise ProtocolContractError("protocol must be frozen")
        if _bool(self.pilot_results_inspected, "pilot_results_inspected"):
            raise ProtocolContractError(
                "a preregistration cannot inspect pilot results before freezing"
            )
        for name in (
            "hypotheses",
            "variants",
            "metrics",
            "exclusion_failure_codes",
            "failure_taxonomy",
            "stop_conditions",
        ):
            if not isinstance(getattr(self, name), tuple):
                raise ProtocolContractError(f"{name} must be an immutable tuple")
        hypothesis_ids = tuple(item.hypothesis_id for item in self.hypotheses)
        variant_ids = tuple(item.variant_id for item in self.variants)
        metric_ids = tuple(item.metric_id for item in self.metrics)
        stop_codes = tuple(item.failure_code for item in self.stop_conditions)
        for field, ids in (
            ("hypotheses", hypothesis_ids),
            ("variants", variant_ids),
            ("metrics", metric_ids),
            ("stop_conditions", stop_codes),
        ):
            if len(ids) != len(set(ids)):
                raise ProtocolContractError(f"{field} contain duplicate identifiers")
        if set(hypothesis_ids) != _REQUIRED_HYPOTHESES:
            raise ProtocolContractError("protocol must contain exactly H1 through H7")
        if set(variant_ids) != _REQUIRED_VARIANTS:
            raise ProtocolContractError("protocol must contain exactly A0-A12 and S1")
        variants = {variant.variant_id: variant for variant in self.variants}
        baseline = variants[BASELINE_VARIANT]
        if baseline.paired_against is not None or not baseline.primary_candidate:
            raise ProtocolContractError("A0 must be the unpaired primary baseline")
        for variant in self.variants:
            if variant.variant_id != BASELINE_VARIANT:
                if variant.paired_against != BASELINE_VARIANT:
                    raise ProtocolContractError(
                        f"{variant.variant_id} must be paired against A0"
                    )
        if not variants["S1"].safety_diagnostic_only:
            raise ProtocolContractError("S1 must remain safety-diagnostic only")
        primary_metrics = {
            metric.metric_id
            for metric in self.metrics
            if metric.category is MetricCategory.PRIMARY
        }
        if not _REQUIRED_PRIMARY_METRICS.issubset(primary_metrics):
            raise ProtocolContractError("required primary metrics are missing")
        if not any(
            metric.category is MetricCategory.RESOURCE for metric in self.metrics
        ):
            raise ProtocolContractError("at least one resource metric is required")
        if not any(
            metric.category is MetricCategory.ROUTING for metric in self.metrics
        ):
            raise ProtocolContractError("at least one routing metric is required")
        if tuple(self.failure_taxonomy) != tuple(FailureCode):
            raise ProtocolContractError(
                "failure taxonomy must contain every stable code in wire order"
            )
        if set(self.exclusion_failure_codes) != EXCLUSION_FAILURE_CODES:
            raise ProtocolContractError(
                "only preregistered capability and invalid-fixture exclusions "
                "are allowed"
            )
        expected_stops = {
            **{code: 1 for code in IMMEDIATE_STOP_CODES},
            FailureCode.OUT_OF_MEMORY: 2,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE: 3,
        }
        actual_stops = {
            item.failure_code: item.consecutive_occurrences
            for item in self.stop_conditions
        }
        if actual_stops != expected_stops:
            raise ProtocolContractError("stop-condition thresholds cannot be changed")
        if (
            _FROZEN_PROTOCOL_SHA256 is not None
            and protocol_sha256(self) != _FROZEN_PROTOCOL_SHA256
        ):
            raise ProtocolContractError(
                "protocol revision 1 content is frozen; create a new schema "
                "and version for amendments"
            )

    @property
    def variant_map(self) -> Mapping[str, VariantSpec]:
        """Read-only lookup without exposing mutable protocol state."""

        return MappingProxyType(
            {variant.variant_id: variant for variant in self.variants}
        )

    @property
    def digest(self) -> str:
        return protocol_sha256(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "frozen": self.frozen,
            "pilot_results_inspected": self.pilot_results_inspected,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "variants": [item.to_dict() for item in self.variants],
            "metrics": [item.to_dict() for item in self.metrics],
            "thresholds": self.thresholds.to_dict(),
            "safety_invariants": self.safety_invariants.to_dict(),
            "holdout_rules": self.holdout_rules.to_dict(),
            "exclusion_failure_codes": [
                item.value for item in self.exclusion_failure_codes
            ],
            "failure_taxonomy": [item.value for item in self.failure_taxonomy],
            "stop_conditions": [item.to_dict() for item in self.stop_conditions],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "protocol")
        keys = {
            "schema",
            "protocol_id",
            "protocol_version",
            "frozen",
            "pilot_results_inspected",
            "hypotheses",
            "variants",
            "metrics",
            "thresholds",
            "safety_invariants",
            "holdout_rules",
            "exclusion_failure_codes",
            "failure_taxonomy",
            "stop_conditions",
        }
        _exact_keys(data, keys, "protocol")
        arrays = {}
        for key in ("hypotheses", "variants", "metrics", "stop_conditions"):
            raw = data[key]
            if not isinstance(raw, list):
                raise ProtocolContractError(f"{key} must be an array")
            arrays[key] = raw
        exclusions = data["exclusion_failure_codes"]
        taxonomy = data["failure_taxonomy"]
        if not isinstance(exclusions, list) or not isinstance(taxonomy, list):
            raise ProtocolContractError("failure-code fields must be arrays")
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            protocol_id=_nonempty(data["protocol_id"], "protocol_id"),
            protocol_version=_integer(
                data["protocol_version"], "protocol_version", minimum=1
            ),
            frozen=_bool(data["frozen"], "frozen"),
            pilot_results_inspected=_bool(
                data["pilot_results_inspected"], "pilot_results_inspected"
            ),
            hypotheses=tuple(
                HypothesisSpec.from_dict(item) for item in arrays["hypotheses"]
            ),
            variants=tuple(
                VariantSpec.from_dict(item) for item in arrays["variants"]
            ),
            metrics=tuple(MetricSpec.from_dict(item) for item in arrays["metrics"]),
            thresholds=MaterialityThresholds.from_dict(data["thresholds"]),
            safety_invariants=SafetyInvariants.from_dict(
                data["safety_invariants"]
            ),
            holdout_rules=HoldoutRules.from_dict(data["holdout_rules"]),
            exclusion_failure_codes=tuple(
                _enum(FailureCode, item, "exclusion_failure_codes[]")
                for item in exclusions
            ),
            failure_taxonomy=tuple(
                _enum(FailureCode, item, "failure_taxonomy[]")
                for item in taxonomy
            ),
            stop_conditions=tuple(
                StopCondition.from_dict(item) for item in arrays["stop_conditions"]
            ),
        )

    def stop_required(
        self, failure_code: FailureCode, *, consecutive_occurrences: int = 1
    ) -> bool:
        """Return whether the preregistered stop threshold has been met."""

        if not isinstance(failure_code, FailureCode):
            raise ProtocolContractError("failure_code must be a FailureCode")
        count = _integer(
            consecutive_occurrences, "consecutive_occurrences", minimum=1
        )
        thresholds = {
            item.failure_code: item.consecutive_occurrences
            for item in self.stop_conditions
        }
        threshold = thresholds.get(failure_code)
        return threshold is not None and count >= threshold


def _hypotheses() -> tuple[HypothesisSpec, ...]:
    null = (
        "The addition does not improve paired kernel-verified outcomes enough "
        "to justify latency, resource use, and operational complexity."
    )
    statements = (
        ("H1", "Full spaCy improves normalized IR accuracy on difficult syntax."),
        ("H2", "SyMAI improves semantic accuracy primarily on ambiguous inputs."),
        ("H3", "Hammer improves completion for structured proof obligations."),
        ("H4", "Leanstral improves Lean-native completion and bounded repair."),
        ("H5", "Hammer-first with Leanstral fallback is safer and cheaper."),
        (
            "H6",
            "Conditional routing retains quality with fewer calls and lower latency.",
        ),
        ("H7", "Unverified proved-claim gains disappear under kernel verification."),
    )
    return tuple(
        HypothesisSpec(item, statement, null) for item, statement in statements
    )


def _variants() -> tuple[VariantSpec, ...]:
    rows = (
        (
            "A0",
            "Exact current effective configuration and revisions",
            "Frozen baseline",
        ),
        (
            "A1",
            "Full spaCy; SyMAI and Leanstral off; native proof routes",
            "Deterministic core",
        ),
        (
            "A2",
            "A1 plus deterministic Hammer and verified reconstruction",
            "Hammer marginal value",
        ),
        ("A3", "A2 plus Leanstral only after bounded proof failure", "Proof cascade"),
        ("A4", "A3 plus ambiguity-gated SyMAI", "Conditional stack"),
        ("A5", "A4 with SyMAI always on", "SyMAI gate efficiency"),
        ("A6", "A4 with Leanstral before Hammer", "Proof ordering"),
        ("A7", "A4 with regex/legal parser instead of spaCy", "spaCy marginal value"),
        (
            "A8",
            "A4 with forced spaCy blank-model fallback",
            "Full model versus fallback",
        ),
        ("A9", "A4 without Hammer; native then Leanstral", "Hammer marginal value"),
        ("A10", "A4 with pinned learned Hammer selector", "Learned selector"),
        ("A11", "A4 with SyMAI/LLM premise ranking", "Premise-ranking overlap"),
        (
            "A12",
            "SyMAI always; Leanstral first; Hammer always",
            "Duplicated-work stress",
        ),
    )
    variants: list[VariantSpec] = []
    for variant_id, configuration, purpose in rows:
        variants.append(
            VariantSpec(
                variant_id,
                configuration,
                purpose,
                paired_against=(
                    None if variant_id == BASELINE_VARIANT else BASELINE_VARIANT
                ),
            )
        )
    variants.append(
        VariantSpec(
            "S1",
            "Legacy SymbolicAI prediction compared with native kernel truth",
            "False-positive safety diagnostic",
            primary_candidate=False,
            safety_diagnostic_only=True,
        )
    )
    return tuple(variants)


def _metrics() -> tuple[MetricSpec, ...]:
    rows = (
        (
            "kernel_verified_completion_rate",
            MetricCategory.PRIMARY,
            MetricDirection.MAXIMIZE,
            "fraction",
            True,
        ),
        (
            "invalid_control_kernel_false_positive_rate",
            MetricCategory.PRIMARY,
            MetricDirection.MINIMIZE,
            "fraction",
            True,
        ),
        (
            "normalized_ir_exact_match",
            MetricCategory.PRIMARY,
            MetricDirection.MAXIMIZE,
            "fraction",
            False,
        ),
        (
            "deterministic_semantic_equivalence",
            MetricCategory.PRIMARY,
            MetricDirection.MAXIMIZE,
            "fraction",
            False,
        ),
        (
            "paired_verified_delta_vs_a0",
            MetricCategory.PRIMARY,
            MetricDirection.MAXIMIZE,
            "fraction",
            True,
        ),
        (
            "ambiguity_classification_accuracy",
            MetricCategory.QUALITY,
            MetricDirection.MAXIMIZE,
            "fraction",
            False,
        ),
        (
            "premise_recall_at_budget",
            MetricCategory.QUALITY,
            MetricDirection.MAXIMIZE,
            "fraction",
            False,
        ),
        (
            "reconstruction_rate",
            MetricCategory.QUALITY,
            MetricDirection.MAXIMIZE,
            "fraction",
            True,
        ),
        (
            "unsupported_fail_closed_accuracy",
            MetricCategory.QUALITY,
            MetricDirection.MAXIMIZE,
            "fraction",
            False,
        ),
        (
            "end_to_end_latency_p95",
            MetricCategory.RESOURCE,
            MetricDirection.MINIMIZE,
            "milliseconds",
            False,
        ),
        (
            "peak_rss",
            MetricCategory.RESOURCE,
            MetricDirection.MINIMIZE,
            "bytes",
            False,
        ),
        (
            "model_calls",
            MetricCategory.RESOURCE,
            MetricDirection.MINIMIZE,
            "count",
            False,
        ),
        (
            "accelerator_minutes",
            MetricCategory.RESOURCE,
            MetricDirection.MINIMIZE,
            "minutes",
            False,
        ),
        (
            "unnecessary_call_rate",
            MetricCategory.ROUTING,
            MetricDirection.MINIMIZE,
            "fraction",
            False,
        ),
        (
            "escalation_precision",
            MetricCategory.ROUTING,
            MetricDirection.MAXIMIZE,
            "fraction",
            False,
        ),
        (
            "component_unique_verified_wins",
            MetricCategory.ROUTING,
            MetricDirection.REPORT,
            "count",
            True,
        ),
    )
    return tuple(MetricSpec(*row) for row in rows)


def _stop_conditions() -> tuple[StopCondition, ...]:
    rows = (
        (
            FailureCode.INVALID_CONTROL_VERIFIED,
            1,
            "Any verified invalid control is a fatal safety incident.",
        ),
        (FailureCode.SAFETY_CONTROL_FAILURE, 1, "Safety controls fail closed."),
        (
            FailureCode.CACHE_CONTAMINATION,
            1,
            "Cross-arm cache contamination invalidates the run.",
        ),
        (
            FailureCode.HOLDOUT_LEAK,
            1,
            "Holdout leakage invalidates selection evidence.",
        ),
        (
            FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
            1,
            "A corrupt receipt invalidates trustworthy continuation.",
        ),
        (FailureCode.ORPHANED_CHILD, 1, "An orphaned process breaches isolation."),
        (
            FailureCode.OUT_OF_MEMORY,
            2,
            "Two consecutive OOMs stop the affected variant.",
        ),
        (
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            3,
            "Three consecutive infrastructure failures stop the affected variant.",
        ),
    )
    return tuple(StopCondition(*row) for row in rows)


def build_default_protocol() -> BenchmarkProtocol:
    """Construct the canonical pre-pilot protocol."""

    return BenchmarkProtocol(
        schema=PROTOCOL_SCHEMA,
        protocol_id=PROTOCOL_ID,
        protocol_version=PROTOCOL_VERSION,
        frozen=True,
        pilot_results_inspected=False,
        hypotheses=_hypotheses(),
        variants=_variants(),
        metrics=_metrics(),
        thresholds=MaterialityThresholds(),
        safety_invariants=SafetyInvariants(),
        holdout_rules=HoldoutRules(),
        exclusion_failure_codes=tuple(
            code for code in FailureCode if code in EXCLUSION_FAILURE_CODES
        ),
        failure_taxonomy=tuple(FailureCode),
        stop_conditions=_stop_conditions(),
    )


def canonical_json(value: object) -> str:
    """Return strict, deterministic JSON; NaN and infinity are rejected."""

    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolContractError("value is not canonical JSON data") from exc


def canonical_protocol_json(protocol: BenchmarkProtocol) -> str:
    if not isinstance(protocol, BenchmarkProtocol):
        raise ProtocolContractError("protocol must be a BenchmarkProtocol")
    return canonical_json(protocol.to_dict())


def protocol_sha256(protocol: BenchmarkProtocol) -> str:
    return hashlib.sha256(canonical_protocol_json(protocol).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProtocolRecord:
    """Self-validating versioned envelope for storing a protocol."""

    schema: str
    protocol_sha256: str
    protocol: BenchmarkProtocol

    def __post_init__(self) -> None:
        if self.schema != PROTOCOL_RECORD_SCHEMA:
            raise ProtocolContractError("unsupported protocol-record schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        if self.protocol_sha256 != protocol_sha256(self.protocol):
            raise ProtocolContractError("protocol record digest does not match payload")

    @classmethod
    def create(cls, protocol: BenchmarkProtocol) -> Self:
        return cls(PROTOCOL_RECORD_SCHEMA, protocol_sha256(protocol), protocol)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "protocol": self.protocol.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "protocol_record")
        _exact_keys(
            data,
            {"schema", "protocol_sha256", "protocol"},
            "protocol_record",
        )
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            protocol_sha256=_digest(
                data["protocol_sha256"], "protocol_sha256"
            ),
            protocol=BenchmarkProtocol.from_dict(data["protocol"]),
        )


@dataclass(frozen=True, slots=True)
class CacheScope:
    """Collision-resistant cache identity for one execution arm."""

    run_id: str
    protocol_sha256: str
    variant_id: str
    split: Split
    mode: CacheMode

    def __post_init__(self) -> None:
        _safe_id(self.run_id, "run_id")
        _digest(self.protocol_sha256, "protocol_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in _REQUIRED_VARIANTS:
            raise ProtocolContractError(
                f"variant_id is not registered: {self.variant_id!r}"
            )
        if not isinstance(self.split, Split):
            raise ProtocolContractError("split must be a Split")
        if not isinstance(self.mode, CacheMode):
            raise ProtocolContractError("mode must be a CacheMode")

    @property
    def namespace(self) -> str:
        return (
            f"{BENCHMARK_ID}/protocol-v1/run/{self.run_id}/"
            f"protocol/{self.protocol_sha256}/variant/{self.variant_id}/"
            f"split/{self.split.value}/cache/{self.mode.value}"
        )


@dataclass(frozen=True, slots=True)
class RunContract:
    """Versioned execution record enforcing identity and holdout sequencing."""

    schema: str
    protocol_sha256: str
    run_id: str
    requested_variant_id: str
    effective_variant_id: str
    split: Split
    cache_mode: CacheMode
    cache_namespace: str
    case_manifest_sha256: str
    configuration_sha256: str
    prompts_frozen: bool
    policy_frozen: bool
    model_identities_frozen: bool
    thresholds_frozen: bool
    tuning_permitted: bool
    holdout_access_log_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema != RUN_CONTRACT_SCHEMA:
            raise ProtocolContractError("unsupported run-contract schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        if (
            _FROZEN_PROTOCOL_SHA256 is not None
            and self.protocol_sha256 != _FROZEN_PROTOCOL_SHA256
        ):
            raise ProtocolContractError(
                "run contract does not bind frozen protocol revision 1"
            )
        _safe_id(self.run_id, "run_id")
        _safe_id(self.requested_variant_id, "requested_variant_id")
        _safe_id(self.effective_variant_id, "effective_variant_id")
        if self.requested_variant_id not in _REQUIRED_VARIANTS:
            raise ProtocolContractError(
                f"requested variant is not registered: "
                f"{self.requested_variant_id!r}"
            )
        if self.requested_variant_id != self.effective_variant_id:
            raise ProtocolContractError(
                "requested and effective variants differ; record unavailable "
                "instead of silently substituting an arm"
            )
        if not isinstance(self.split, Split):
            raise ProtocolContractError("split must be a Split")
        if not isinstance(self.cache_mode, CacheMode):
            raise ProtocolContractError("cache_mode must be a CacheMode")
        expected = CacheScope(
            self.run_id,
            self.protocol_sha256,
            self.requested_variant_id,
            self.split,
            self.cache_mode,
        ).namespace
        if self.cache_namespace != expected:
            raise ProtocolContractError(
                "cache_namespace must bind run, protocol, variant, split, and mode"
            )
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _digest(self.configuration_sha256, "configuration_sha256")
        for field in (
            "prompts_frozen",
            "policy_frozen",
            "model_identities_frozen",
            "thresholds_frozen",
            "tuning_permitted",
        ):
            _bool(getattr(self, field), field)
        if self.split is Split.HOLDOUT:
            if self.tuning_permitted:
                raise ProtocolContractError("tuning is forbidden on holdout")
            if not all(
                (
                    self.prompts_frozen,
                    self.policy_frozen,
                    self.model_identities_frozen,
                    self.thresholds_frozen,
                )
            ):
                raise ProtocolContractError(
                    "all selection inputs must be frozen before holdout access"
                )
            _safe_id(self.holdout_access_log_id, "holdout_access_log_id")
        elif self.holdout_access_log_id is not None:
            raise ProtocolContractError(
                "holdout_access_log_id is only valid for holdout records"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "run_id": self.run_id,
            "requested_variant_id": self.requested_variant_id,
            "effective_variant_id": self.effective_variant_id,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "cache_namespace": self.cache_namespace,
            "case_manifest_sha256": self.case_manifest_sha256,
            "configuration_sha256": self.configuration_sha256,
            "prompts_frozen": self.prompts_frozen,
            "policy_frozen": self.policy_frozen,
            "model_identities_frozen": self.model_identities_frozen,
            "thresholds_frozen": self.thresholds_frozen,
            "tuning_permitted": self.tuning_permitted,
            "holdout_access_log_id": self.holdout_access_log_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "run_contract")
        keys = set(cls.__dataclass_fields__)
        _exact_keys(data, keys, "run_contract")
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            run_id=_safe_id(data["run_id"], "run_id"),
            requested_variant_id=_safe_id(
                data["requested_variant_id"], "requested_variant_id"
            ),
            effective_variant_id=_safe_id(
                data["effective_variant_id"], "effective_variant_id"
            ),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            cache_mode=_enum(
                CacheMode, data["cache_mode"], "cache_mode"
            ),  # type: ignore[arg-type]
            cache_namespace=_nonempty(
                data["cache_namespace"], "cache_namespace"
            ),
            case_manifest_sha256=_digest(
                data["case_manifest_sha256"], "case_manifest_sha256"
            ),
            configuration_sha256=_digest(
                data["configuration_sha256"], "configuration_sha256"
            ),
            prompts_frozen=_bool(data["prompts_frozen"], "prompts_frozen"),
            policy_frozen=_bool(data["policy_frozen"], "policy_frozen"),
            model_identities_frozen=_bool(
                data["model_identities_frozen"], "model_identities_frozen"
            ),
            thresholds_frozen=_bool(
                data["thresholds_frozen"], "thresholds_frozen"
            ),
            tuning_permitted=_bool(
                data["tuning_permitted"], "tuning_permitted"
            ),
            holdout_access_log_id=(
                None
                if data["holdout_access_log_id"] is None
                else _safe_id(
                    data["holdout_access_log_id"], "holdout_access_log_id"
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """Minimal case outcome enforcing proof authority and missingness semantics."""

    schema: str
    protocol_sha256: str
    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str
    split: Split
    cache_mode: CacheMode
    status: OutcomeStatus
    invalid_control: bool
    verification_authority: VerificationAuthority = VerificationAuthority.NONE
    kernel_accepted: bool = False
    kernel_receipt_sha256: str | None = None
    failure_code: FailureCode | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.schema != OUTCOME_RECORD_SCHEMA:
            raise ProtocolContractError("unsupported outcome schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        if (
            _FROZEN_PROTOCOL_SHA256 is not None
            and self.protocol_sha256 != _FROZEN_PROTOCOL_SHA256
        ):
            raise ProtocolContractError(
                "outcome does not bind frozen protocol revision 1"
            )
        _safe_id(self.run_id, "run_id")
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in _REQUIRED_VARIANTS:
            raise ProtocolContractError(
                f"variant_id is not registered: {self.variant_id!r}"
            )
        if not isinstance(self.split, Split):
            raise ProtocolContractError("split must be a Split")
        if not isinstance(self.cache_mode, CacheMode):
            raise ProtocolContractError("cache_mode must be a CacheMode")
        if not isinstance(self.status, OutcomeStatus):
            raise ProtocolContractError("status must be an OutcomeStatus")
        if not isinstance(self.verification_authority, VerificationAuthority):
            raise ProtocolContractError(
                "verification_authority must be a VerificationAuthority"
            )
        _bool(self.invalid_control, "invalid_control")
        _bool(self.kernel_accepted, "kernel_accepted")
        if self.failure_code is not None and not isinstance(
            self.failure_code, FailureCode
        ):
            raise ProtocolContractError("failure_code must be a FailureCode")
        if self.failure_detail is not None:
            _nonempty(self.failure_detail, "failure_detail")
        if self.status is OutcomeStatus.VERIFIED:
            if (
                self.verification_authority is not VerificationAuthority.NATIVE_KERNEL
                or not self.kernel_accepted
                or self.kernel_receipt_sha256 is None
            ):
                raise ProtocolContractError(
                    "verified requires an accepted native-kernel receipt"
                )
            _digest(self.kernel_receipt_sha256, "kernel_receipt_sha256")
            if self.failure_code is not None:
                raise ProtocolContractError(
                    "a verified outcome cannot also carry a failure code"
                )
        else:
            if self.kernel_accepted or self.kernel_receipt_sha256 is not None:
                raise ProtocolContractError(
                    "non-verified outcomes cannot claim kernel acceptance"
                )
        if self.status is OutcomeStatus.INFRASTRUCTURE_FAILURE:
            if self.failure_code not in INFRASTRUCTURE_FAILURE_CODES:
                raise ProtocolContractError(
                    "infrastructure failure requires an infrastructure code"
                )
            _nonempty(self.failure_detail, "failure_detail")
        elif self.failure_code in INFRASTRUCTURE_FAILURE_CODES:
            raise ProtocolContractError(
                "infrastructure codes require infrastructure_failure status"
            )
        if self.status in {OutcomeStatus.UNAVAILABLE, OutcomeStatus.EXCLUDED}:
            if self.failure_code not in EXCLUSION_FAILURE_CODES:
                raise ProtocolContractError(
                    "unavailable/excluded outcomes require a preregistered code"
                )
        if self.status in {OutcomeStatus.NOT_VERIFIED, OutcomeStatus.REJECTED}:
            if self.failure_code in EXCLUSION_FAILURE_CODES:
                raise ProtocolContractError(
                    "an exclusion code cannot hide a logical outcome"
                )

    @property
    def eligible_for_paired_statistics(self) -> bool:
        return self.status not in {
            OutcomeStatus.UNAVAILABLE,
            OutcomeStatus.EXCLUDED,
            OutcomeStatus.INFRASTRUCTURE_FAILURE,
        }

    @property
    def safety_violations(self) -> tuple[FailureCode, ...]:
        if self.invalid_control and self.status is OutcomeStatus.VERIFIED:
            return (FailureCode.INVALID_CONTROL_VERIFIED,)
        return ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "variant_id": self.variant_id,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "status": self.status.value,
            "invalid_control": self.invalid_control,
            "verification_authority": self.verification_authority.value,
            "kernel_accepted": self.kernel_accepted,
            "kernel_receipt_sha256": self.kernel_receipt_sha256,
            "failure_code": (
                None if self.failure_code is None else self.failure_code.value
            ),
            "failure_detail": self.failure_detail,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "outcome")
        keys = set(cls.__dataclass_fields__)
        _exact_keys(data, keys, "outcome")
        receipt = data["kernel_receipt_sha256"]
        failure_code = data["failure_code"]
        detail = data["failure_detail"]
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            run_id=_safe_id(data["run_id"], "run_id"),
            case_id=_safe_id(data["case_id"], "case_id"),
            case_manifest_sha256=_digest(
                data["case_manifest_sha256"], "case_manifest_sha256"
            ),
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            cache_mode=_enum(
                CacheMode, data["cache_mode"], "cache_mode"
            ),  # type: ignore[arg-type]
            status=_enum(
                OutcomeStatus, data["status"], "status"
            ),  # type: ignore[arg-type]
            invalid_control=_bool(data["invalid_control"], "invalid_control"),
            verification_authority=_enum(
                VerificationAuthority,
                data["verification_authority"],
                "verification_authority",
            ),  # type: ignore[arg-type]
            kernel_accepted=_bool(data["kernel_accepted"], "kernel_accepted"),
            kernel_receipt_sha256=(
                None if receipt is None else _digest(receipt, "kernel_receipt_sha256")
            ),
            failure_code=(
                None
                if failure_code is None
                else _enum(FailureCode, failure_code, "failure_code")
            ),  # type: ignore[arg-type]
            failure_detail=(
                None if detail is None else _nonempty(detail, "failure_detail")
            ),
        )


def validate_paired_outcomes(
    baseline: OutcomeRecord,
    candidate: OutcomeRecord,
    *,
    protocol: BenchmarkProtocol,
) -> None:
    """Validate the identity and eligibility boundary for a paired comparison."""

    if not isinstance(baseline, OutcomeRecord) or not isinstance(
        candidate, OutcomeRecord
    ):
        raise ProtocolContractError("pair members must be OutcomeRecord values")
    if protocol.digest not in {
        baseline.protocol_sha256,
        candidate.protocol_sha256,
    } or baseline.protocol_sha256 != candidate.protocol_sha256:
        raise ProtocolContractError("pair members must bind the same protocol")
    if baseline.variant_id != BASELINE_VARIANT:
        raise ProtocolContractError("the first pair member must be A0")
    variant = protocol.variant_map.get(candidate.variant_id)
    if variant is None or variant.paired_against != BASELINE_VARIANT:
        raise ProtocolContractError("candidate is not a registered A0-paired arm")
    if variant.safety_diagnostic_only:
        raise ProtocolContractError("S1 cannot enter primary paired outcomes")
    if baseline.safety_violations or candidate.safety_violations:
        raise ProtocolContractError(
            "verified invalid controls are fatal and cannot enter statistics"
        )
    fields = ("run_id", "case_id", "case_manifest_sha256", "split", "cache_mode")
    if any(getattr(baseline, field) != getattr(candidate, field) for field in fields):
        raise ProtocolContractError(
            "paired outcomes must share run, case, manifest, split, and cache mode"
        )
    if (
        baseline.eligible_for_paired_statistics
        != candidate.eligible_for_paired_statistics
    ):
        raise ProtocolContractError(
            "an incomplete pair cannot support a quality claim"
        )


class GateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class CandidateGateObservation:
    invalid_control_verified_count: int
    paired_interval_low: float
    hard_case_verified_gain: float
    quality_gap_from_best: float
    p95_latency_reduction: float
    model_usage_reduction: float
    baseline_solved_regression_rate: float
    unexplained_baseline_regressions: int
    all_successes_kernel_bound_and_replayable: bool
    infrastructure_failure_count: int = 0

    def __post_init__(self) -> None:
        for name in (
            "invalid_control_verified_count",
            "unexplained_baseline_regressions",
            "infrastructure_failure_count",
        ):
            _integer(getattr(self, name), name)
        _number(
            self.paired_interval_low,
            "paired_interval_low",
            minimum=-1,
            maximum=1,
        )
        _number(
            self.hard_case_verified_gain,
            "hard_case_verified_gain",
            minimum=-1,
            maximum=1,
        )
        _number(
            self.quality_gap_from_best,
            "quality_gap_from_best",
            minimum=0,
            maximum=1,
        )
        _number(
            self.p95_latency_reduction,
            "p95_latency_reduction",
            minimum=-1,
            maximum=1,
        )
        _number(
            self.model_usage_reduction,
            "model_usage_reduction",
            minimum=-1,
            maximum=1,
        )
        _number(
            self.baseline_solved_regression_rate,
            "baseline_solved_regression_rate",
            minimum=0,
            maximum=1,
        )
        _bool(
            self.all_successes_kernel_bound_and_replayable,
            "all_successes_kernel_bound_and_replayable",
        )


@dataclass(frozen=True, slots=True)
class GateDecision:
    status: GateStatus
    reasons: tuple[str, ...]


def evaluate_candidate_gate(
    observation: CandidateGateObservation,
    *,
    protocol: BenchmarkProtocol,
) -> GateDecision:
    """Apply the frozen materiality and safety gates to aggregate evidence."""

    if not isinstance(observation, CandidateGateObservation):
        raise ProtocolContractError(
            "observation must be a CandidateGateObservation"
        )
    thresholds = protocol.thresholds
    if observation.infrastructure_failure_count:
        return GateDecision(
            GateStatus.INCOMPLETE,
            ("infrastructure failures require repair or an explicit rerun",),
        )
    reasons: list[str] = []
    if (
        observation.invalid_control_verified_count
        > thresholds.invalid_control_verified_max
    ):
        reasons.append("invalid-control verification tolerance exceeded")
    if observation.paired_interval_low < thresholds.paired_regression_floor:
        reasons.append("paired confidence interval crosses regression floor")
    quality_gain = (
        observation.hard_case_verified_gain
        >= thresholds.hard_case_verified_gain_min
    )
    efficient_near_best = (
        observation.quality_gap_from_best
        <= thresholds.near_best_quality_margin_max
        and max(
            observation.p95_latency_reduction,
            observation.model_usage_reduction,
        )
        >= thresholds.efficiency_reduction_min
    )
    if not (quality_gain or efficient_near_best):
        reasons.append("neither hard-case gain nor near-best efficiency gate passed")
    if (
        observation.baseline_solved_regression_rate
        > thresholds.baseline_solved_regression_rate_max
    ):
        reasons.append("A0-solved regression rate exceeded")
    if (
        observation.unexplained_baseline_regressions
        > thresholds.unexplained_baseline_regressions_max
    ):
        reasons.append("unexplained A0-solved regressions remain")
    if not observation.all_successes_kernel_bound_and_replayable:
        reasons.append("success receipts are not all kernel-bound and replayable")
    return GateDecision(
        GateStatus.FAILED if reasons else GateStatus.PASSED,
        tuple(reasons),
    )


DEFAULT_PROTOCOL: Final = build_default_protocol()
DEFAULT_PROTOCOL_SHA256: Final = protocol_sha256(DEFAULT_PROTOCOL)
_FROZEN_PROTOCOL_SHA256 = DEFAULT_PROTOCOL_SHA256


__all__ = [
    "BASELINE_VARIANT",
    "BenchmarkProtocol",
    "CacheMode",
    "CacheScope",
    "CandidateGateObservation",
    "DEFAULT_PROTOCOL",
    "DEFAULT_PROTOCOL_SHA256",
    "EXCLUSION_FAILURE_CODES",
    "FailureCode",
    "GateDecision",
    "GateStatus",
    "HSSLEV0103C72",
    "HoldoutRules",
    "HypothesisSpec",
    "IMMEDIATE_STOP_CODES",
    "INFRASTRUCTURE_FAILURE_CODES",
    "MaterialityThresholds",
    "MetricCategory",
    "MetricDirection",
    "MetricSpec",
    "OUTCOME_RECORD_SCHEMA",
    "OutcomeRecord",
    "OutcomeStatus",
    "PROTOCOL_ID",
    "PROTOCOL_RECORD_SCHEMA",
    "PROTOCOL_SCHEMA",
    "PROTOCOL_VERSION",
    "ProtocolContractError",
    "ProtocolRecord",
    "RUN_CONTRACT_SCHEMA",
    "RunContract",
    "SafetyInvariants",
    "Split",
    "StopCondition",
    "VariantSpec",
    "VerificationAuthority",
    "build_default_protocol",
    "canonical_json",
    "canonical_protocol_json",
    "evaluate_candidate_gate",
    "protocol_sha256",
    "validate_paired_outcomes",
]
