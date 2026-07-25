"""Frozen contracts for the logic-pipeline benchmark protocol.

This module contains the preregistration that must be loaded and validated
before a pilot, together with the small run/outcome records needed to enforce
its safety boundary.  Backend adapters do not belong here and importing this
module does not contact a benchmark backend.  Revision-2 semantic artifacts use
the repository's multiformats helpers for canonical IPFS content identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
import unicodedata
from types import MappingProxyType
from typing import Final, Mapping, Self, Sequence, TypeVar

from .content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)

from . import BENCHMARK_ID


PROTOCOL_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.protocol.v1"
)
PROTOCOL_RECORD_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.protocol-record.v1"
)
TELEMETRY_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.telemetry.v1"
)
STAGE_PROVENANCE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.stage-provenance.v1"
)
STAGE_RECORD_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.stage-record.v1"
)
CASE_RESULT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.case-result.v2"
)
CASE_RESULT_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.case-result-receipt.v1"
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


class StageName(str, Enum):
    """The stable names of stages in the benchmark route.

    These names are benchmark vocabulary, not production router settings.  A
    stage adapter may observe a production implementation, but it cannot
    mutate or replace that implementation through this contract.
    """

    COMPILER = "compiler"
    SPACY = "spacy"
    SYMAI = "symai"
    HAMMER = "hammer"
    LEANSTRAL = "leanstral"
    KERNEL = "kernel"


class StageStatus(str, Enum):
    """Bounded stage outcomes; verification is deliberately not a stage state."""

    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResourceLane(str, Enum):
    """Mutually visible resource classes used to keep model/kernel work apart."""

    CPU = "cpu"
    MODEL = "model"
    SOLVER = "solver"
    KERNEL = "kernel"


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

# A proof backend is an advisory candidate producer, not the verification
# authority.  These failures mean that an invoked proof attempt did not
# produce a usable candidate.  They remain durable reliability evidence, but
# they cannot override a later, independent native-kernel acceptance of a
# different source-bound candidate (for example the deterministic compiler
# candidate).  All other failures remain blocking.
RECOVERABLE_PROOF_ATTEMPT_FAILURE_CODES: Final = frozenset(
    {
        FailureCode.PREMISE_SELECTION_MISS,
        FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
        FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
    }
)


def HSSLEV0103C72() -> str:
    """Return AST-verifiable evidence for the frozen protocol objective."""

    return "preregistered benchmark protocol and safety invariants"


def HSSLEV0357C0D() -> str:
    """Return AST-verifiable evidence for kernel-bound result receipts."""

    return "kernel and provenance receipts for all claimed successes"


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


def _semantic_cid(
    value: object,
    field: str,
    *,
    codecs: tuple[str, ...] = ("raw", "dag-json"),
) -> str:
    """Return one canonical CIDv1/base32/sha2-256 identity or fail closed."""

    try:
        return validate_cid(value, codecs=codecs)
    except (TypeError, ValueError) as exc:
        raise ProtocolContractError(f"{field} is not a canonical CID") from exc


SEMANTIC_PROTOCOL_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-protocol.v2"
)
SEMANTIC_PROTOCOL_ID_V2: Final = (
    "hammer-symai-spacy-leanstral-source-only-semantics-v2"
)
SEMANTIC_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-projection.v2"
)
SEMANTIC_PROMPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-prompt.v2"
)
SEMANTIC_RESPONSE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.symai-response.v2"
)
SEMANTIC_FAILURE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-failure.v2"
)
SEMANTIC_FAILURE_CODES_V2: Final = (
    "semantic_input_leakage",
    "semantic_schema_incompatible",
    "semantic_projection_incomplete",
    "semantic_validation_failed",
    "semantic_evidence_mismatch",
)
SEMANTIC_PRODUCER_REGISTRY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-producer-registry.v2"
)
SEMANTIC_PROTOCOL_VERSION_V2: Final = 2
SEMANTIC_CALIBRATION_CASE_COUNT_V2: Final = 20
SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2: Final = 100
SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2: Final = 20
SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2: Final = 750_000
SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2: Final = 950_000
SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2: Final = 500_000
SEMANTIC_PARENT_PROTOCOL_SHA256_V1: Final = (
    "a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3"
)
SEMANTIC_PARENT_VARIANT_REGISTRY_SHA256_V1: Final = (
    "53a106ddd6c68af445d0a3a912b0d7d09e04c6b23500d4c6362bb5c089f2e44f"
)
SEMANTIC_PROJECTION_CLASSES_V2: Final = (
    "proved",
    "disproved",
    "ambiguous",
    "unsupported",
)
SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2: Final = (
    "logic_family",
    "target",
    "class",
    "predicates",
    "entities",
)
SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2: Final = (
    "expected_class",
    "expected_ir",
    "required_predicates",
    "required_entities",
    "proof_obligation",
    "obligation_id",
    "negative_controls",
    "kernel_outcome",
    "kernel_receipt",
    "compiled_obligation",
    "semantic_target",
)
SEMANTIC_PRODUCER_IDS_V2: Final = (
    "compiler",
    "spacy_full_model",
    "spacy_regex_legal",
    "spacy_blank_model",
    "symai",
)
SEMANTIC_CALIBRATION_ROUTE_MANIFEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "semantic-calibration-routes.v2"
)
SEMANTIC_CALIBRATION_METRIC_SPEC_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "semantic-calibration-metrics.v2"
)
SEMANTIC_REVIEWED_TARGET_SOURCE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "semantic-reviewed-target-source.v2"
)


def semantic_calibration_route_manifest_v2() -> dict[str, object]:
    """Return the precommitted producer-to-stage-prefix calibration routes."""

    return {
        "schema": SEMANTIC_CALIBRATION_ROUTE_MANIFEST_SCHEMA_V2,
        "cache_mode": CacheMode.COLD.value,
        "coordinate_count": SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2,
        "cases_per_producer": (
            SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
        ),
        "routes": [
            {
                "producer_id": "compiler",
                "variant_id": "A0",
                "selected_stage": StageName.COMPILER.value,
                "stage_prefix": [StageName.COMPILER.value],
            },
            {
                "producer_id": "spacy_full_model",
                "variant_id": "A1",
                "selected_stage": StageName.SPACY.value,
                "stage_prefix": [
                    StageName.COMPILER.value,
                    StageName.SPACY.value,
                ],
            },
            {
                "producer_id": "spacy_regex_legal",
                "variant_id": "A7",
                "selected_stage": StageName.SPACY.value,
                "stage_prefix": [
                    StageName.COMPILER.value,
                    StageName.SPACY.value,
                ],
            },
            {
                "producer_id": "spacy_blank_model",
                "variant_id": "A8",
                "selected_stage": StageName.SPACY.value,
                "stage_prefix": [
                    StageName.COMPILER.value,
                    StageName.SPACY.value,
                ],
            },
            {
                "producer_id": "symai",
                "variant_id": "A5",
                "selected_stage": StageName.SYMAI.value,
                "stage_prefix": [
                    StageName.COMPILER.value,
                    StageName.SPACY.value,
                    StageName.SYMAI.value,
                ],
            },
        ],
        "selection_time": "frozen_before_execution",
        "post_hoc_route_or_cache_selection": False,
        "proof_stages_permitted": False,
        "measurement_unit": "integrated_frontend_stage_prefix",
        "quality_attribution": (
            "terminal_projection_with_required_upstream_dependencies"
        ),
        "cost_attribution": "complete_selected_stage_prefix",
        "standalone_producer_claims_permitted": False,
    }


SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID: Final = cid_for_dag_json(
    semantic_calibration_route_manifest_v2()
)


def semantic_calibration_metric_spec_v2() -> dict[str, object]:
    """Return non-vacuous absolute and relative selection rules."""

    return {
        "schema": SEMANTIC_CALIBRATION_METRIC_SPEC_SCHEMA_V2,
        "cases_per_producer": (
            SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
        ),
        "primary_quality": {
            "name": "all_five_semantic_fields_exact",
            "fields": list(
                SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
            ),
            "minimum_rate_millionths": (
                SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
            ),
            "minimum_successes": 15,
        },
        "uncertainty": {
            "method": "wilson_score_interval",
            "confidence_millionths": (
                SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2
            ),
            "minimum_lower_bound_millionths": (
                SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2
            ),
        },
        "eligibility": {
            "requires_all_coordinates_measured": True,
            "schema_incompatible_coordinates_permitted": 0,
            "vacuous_coordinates_permitted": 0,
            "requires_recomputed_projection_evidence_cid": True,
        },
        "required_quality_breakdown": [
            "logic_family_accuracy",
            "target_accuracy",
            "class_accuracy",
            "predicates_accuracy",
            "entities_accuracy",
            "availability_rate",
            "vacuity_rate",
        ],
        "required_cost_breakdown": [
            "wall_time_ms",
            "cpu_time_ms",
            "peak_memory_bytes",
            "model_calls",
            "cache_hits",
            "cache_misses",
            "retries",
        ],
        "selection": {
            "absolute_gate_precedes_relative_selection": True,
            "eligible_route_terminal_producer_is_unit_of_selection": True,
            "post_hoc_coordinate_selection": False,
            "standalone_producer_delegation_claims_permitted": False,
        },
    }


SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID: Final = cid_for_dag_json(
    semantic_calibration_metric_spec_v2()
)


def semantic_reviewed_target_source_v2() -> dict[str, object]:
    """Bind target derivation to the frozen reviewed v1 corpus roots."""

    return {
        "schema": SEMANTIC_REVIEWED_TARGET_SOURCE_SCHEMA_V2,
        "corpus_manifest_sha256": (
            "58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26"
        ),
        "split_manifest_sha256": {
            "pilot": (
                "a050371dae1248deecfb17f2d9e610124c6e493a1a227ec3c161008891ce1881"
            ),
            "development": (
                "530860019b164c9750083ec5affd6ae71202b695c8c8042400d0f02488436b74"
            ),
        },
        "case_count": SEMANTIC_CALIBRATION_CASE_COUNT_V2,
        "case_identity": [
            "reviewed_case_cid",
            "frozen_manifest_case_sha256_compatibility_join",
        ],
        "source_identity": [
            "raw_source_cid",
            "source_sha256_compatibility_join",
        ],
        "target_fields": [
            "expected_ir.logic",
            "expected_ir.target",
            "expected_class",
            "required_predicates",
            "required_entities",
        ],
        "review_attestation_required": True,
        "derive_targets_before_observing_producer_outputs": True,
        "holdout_included": False,
    }


SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID: Final = cid_for_dag_json(
    semantic_reviewed_target_source_v2()
)
_SEMANTIC_VACUOUS_TERMS: Final = frozenset(
    {"", "none", "null", "unknown", "unspecified"}
)
_SEMANTIC_LOGIC_ALIASES: Final = MappingProxyType(
    {
        "first_order": "fol",
        "first_order_logic": "fol",
        "fol": "fol",
        "deontic": "deontic",
        "deontic_logic": "deontic",
        "temporal": "temporal",
        "temporal_logic": "temporal",
    }
)
_SEMANTIC_TERM_SCHEMA_PATTERN: Final = (
    r"^[^\W_][\w.:-]{0,255}$"
)
_SEMANTIC_TERM = re.compile(
    r"[^\W_][\w.:-]{0,255}\Z",
    flags=re.UNICODE,
)
_SEMANTIC_NORMALIZATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-normalization.v2"
)
_SEMANTIC_TERM_UNICODE_FORM_V2: Final = "NFKC"
_SEMANTIC_TERM_CASE_RULE_V2: Final = "casefold"
_SEMANTIC_TERM_SEPARATOR_V2: Final = "_"
_SEMANTIC_TERM_PRESERVED_PUNCTUATION_V2: Final = (".", ":", "-")
_SEMANTIC_TERM_MAX_LENGTH_V2: Final = 256
_SEMANTIC_PROJECTION_MAX_TERMS_V2: Final = 24
_SEMANTIC_MODAL_IR_FORMULAS_FIELD_V2: Final = "formulas"
_SEMANTIC_MODAL_IR_OPERATOR_FIELD_V2: Final = "operator"
_SEMANTIC_MODAL_IR_OPERATOR_FAMILY_FIELD_V2: Final = "family"
_SEMANTIC_MODAL_IR_PREDICATE_FIELD_V2: Final = "predicate"
_SEMANTIC_MODAL_IR_PREDICATE_NAME_FIELD_V2: Final = "name"
_SEMANTIC_MODAL_IR_PREDICATE_ARGUMENTS_FIELD_V2: Final = "arguments"
_SEMANTIC_MODAL_IR_PREDICATE_ROLE_FIELD_V2: Final = "role"
_SEMANTIC_MODAL_IR_PRIMARY_ROLE_V2: Final = "clause"
_SEMANTIC_MODAL_IR_PROVENANCE_FIELD_V2: Final = "provenance"
_SEMANTIC_MODAL_IR_PROVENANCE_START_FIELD_V2: Final = "start_char"
_SEMANTIC_MODAL_IR_PROVENANCE_END_FIELD_V2: Final = "end_char"
_SEMANTIC_MODAL_IR_FORMULA_ID_FIELD_V2: Final = "formula_id"
_SEMANTIC_MODAL_IR_ENTITY_QUALIFIER_V2: Final = ":"
_SEMANTIC_MISSING_TERM_V2: Final = "unknown"
_SEMANTIC_SOURCE_UNCERTAINTY_PATTERN_V2: Final = (
    r"(?<!not )\b(?:ambiguous|unclear)\b|"
    r"\bnot\s+(?:specified|stated)\b"
)
_SEMANTIC_SOURCE_DISPROOF_PATTERN_V2: Final = (
    r"\b(?:counterexample|disprov(?:e|ed|en|ing)|"
    r"not\s+entailed|is\s+false)\b"
)
_SEMANTIC_CLASS_CONFLICT_ERROR_V2: Final = "class_evidence_conflict"
_SEMANTIC_VALIDATION_ERROR_BY_FIELD_V2: Final = MappingProxyType(
    {
        "logic_family": "logic_family_missing",
        "target": "target_missing",
        "predicates": "predicates_missing",
    }
)
_SEMANTIC_CONFIDENCE_EXPLICIT_SIGNAL_V2: Final = 1_000_000
_SEMANTIC_CONFIDENCE_UNSUPPORTED_V2: Final = 0
SEMANTIC_PROMPT_INSTRUCTION_V2: Final = (
    "Derive one untrusted semantic projection using only SOURCE_TEXT and "
    "OPTIONAL_PRODUCER_EVIDENCE. Return exactly the strict JSON object "
    "described by RESPONSE_SCHEMA. Populate logic_family, target, class, "
    "predicates, entities, completeness, ambiguity_flags, "
    "confidence_millionths, and validation_errors. Every value must be "
    "source-derived. Validation "
    "errors take precedence over ambiguity. Never infer or copy a reviewed "
    "answer, proof obligation, expected IR, kernel outcome, verification, "
    "or authority claim. Return no Markdown or wrapper object."
)


def normalize_semantic_term(value: object) -> str:
    """Return the canonical label-blind spelling used by semantic protocol v2."""

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize(
        _SEMANTIC_TERM_UNICODE_FORM_V2,
        value,
    ).casefold()
    return _SEMANTIC_TERM_SEPARATOR_V2.join(
        "".join(
            (
                character
                if character.isalnum()
                or character
                in _SEMANTIC_TERM_PRESERVED_PUNCTUATION_V2
                else " "
            )
            for character in normalized
        ).split()
    )[:_SEMANTIC_TERM_MAX_LENGTH_V2]


def _is_semantic_term(value: object) -> bool:
    """Return whether ``value`` is canonical under the frozen Unicode profile."""

    return bool(
        isinstance(value, str)
        and 1 <= len(value) <= _SEMANTIC_TERM_MAX_LENGTH_V2
        and normalize_semantic_term(value) == value
        and value[0].isalnum()
        and all(
            character.isalnum()
            or character in _SEMANTIC_TERM_PRESERVED_PUNCTUATION_V2
            or character == _SEMANTIC_TERM_SEPARATOR_V2
            for character in value
        )
    )


def _normalize_logic_family(value: object) -> str:
    normalized = normalize_semantic_term(value)
    return _SEMANTIC_LOGIC_ALIASES.get(normalized, normalized)


def semantic_response_json_schema_v2() -> dict[str, object]:
    """Return a detached strict JSON schema for the SyMAI v2 response."""

    string_array = {
        "type": "array",
        "maxItems": _SEMANTIC_PROJECTION_MAX_TERMS_V2,
        "items": {
            "type": "string",
            "minLength": 1,
            "maxLength": _SEMANTIC_TERM_MAX_LENGTH_V2,
        },
    }
    return {
        "$id": SEMANTIC_RESPONSE_SCHEMA_V2,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "logic_family",
            "target",
            "class",
            "predicates",
            "entities",
            "completeness",
            "ambiguity_flags",
            "confidence_millionths",
            "validation_errors",
        ],
        "properties": {
            "logic_family": {
                "type": "string",
                "minLength": 1,
                "maxLength": _SEMANTIC_TERM_MAX_LENGTH_V2,
            },
            "target": {
                "type": "string",
                "minLength": 1,
                "maxLength": _SEMANTIC_TERM_MAX_LENGTH_V2,
            },
            "class": {
                "type": "string",
                "enum": list(SEMANTIC_PROJECTION_CLASSES_V2),
            },
            "predicates": dict(string_array),
            "entities": dict(string_array),
            "completeness": {
                "type": "object",
                "additionalProperties": False,
                "required": list(
                    SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                ),
                "properties": {
                    field: {"type": "boolean"}
                    for field in SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                },
            },
            "ambiguity_flags": dict(string_array),
            "confidence_millionths": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1_000_000,
            },
            "validation_errors": dict(string_array),
        },
    }


def semantic_producer_registry_v2() -> dict[str, object]:
    """Return the frozen set of producer identities covered by calibration."""

    return {
        "schema": SEMANTIC_PRODUCER_REGISTRY_SCHEMA_V2,
        "producers": [
            {
                "producer_id": "compiler",
                "stage": StageName.COMPILER.value,
                "mode": "current_modal_codec",
                "adapter_version": "2",
                "evidence_schema": (
                    "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v2"
                ),
                "projection_evidence": "modal_ir",
                "evidence_cid_codec": "dag-json",
            },
            {
                "producer_id": "spacy_full_model",
                "stage": StageName.SPACY.value,
                "mode": "full_model",
                "adapter_version": "2",
                "evidence_schema": (
                    "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
                ),
                "projection_evidence": "modal_ir",
                "evidence_cid_codec": "dag-json",
            },
            {
                "producer_id": "spacy_regex_legal",
                "stage": StageName.SPACY.value,
                "mode": "regex_legal",
                "adapter_version": "2",
                "evidence_schema": (
                    "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
                ),
                "projection_evidence": "modal_ir",
                "evidence_cid_codec": "dag-json",
            },
            {
                "producer_id": "spacy_blank_model",
                "stage": StageName.SPACY.value,
                "mode": "blank_model",
                "adapter_version": "2",
                "evidence_schema": (
                    "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
                ),
                "projection_evidence": "modal_ir",
                "evidence_cid_codec": "dag-json",
            },
            {
                "producer_id": "symai",
                "stage": StageName.SYMAI.value,
                "mode": "structured_source_only",
                "adapter_version": "2",
                "evidence_schema": (
                    "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
                ),
                "projection_evidence": "validated_response",
                "evidence_cid_codec": "dag-json",
                "raw_output_cid_codec": "raw",
            },
        ],
    }


def semantic_projection_json_schema_v2() -> dict[str, object]:
    """Return the strict persisted shape shared by every v2 producer."""

    cid = {
        "type": "string",
        "minLength": 10,
        "maxLength": 128,
        "pattern": "^b[a-z2-7]+$",
    }
    term = {
        "type": "string",
        "minLength": 1,
        "maxLength": _SEMANTIC_TERM_MAX_LENGTH_V2,
        "pattern": _SEMANTIC_TERM_SCHEMA_PATTERN,
    }
    term_array = {
        "type": "array",
        "maxItems": _SEMANTIC_PROJECTION_MAX_TERMS_V2,
        "uniqueItems": True,
        "items": dict(term),
    }
    return {
        "$id": SEMANTIC_PROJECTION_SCHEMA_V2,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema",
            "semantic_protocol_cid",
            "producer_id",
            "source_cid",
            "logic_family",
            "target",
            "class",
            "predicates",
            "entities",
            "completeness",
            "ambiguity_flags",
            "confidence_millionths",
            "validation_errors",
            "evidence_cid",
            "semantic_content_cid",
            "projection_cid",
        ],
        "properties": {
            "schema": {"const": SEMANTIC_PROJECTION_SCHEMA_V2},
            "semantic_protocol_cid": dict(cid),
            "producer_id": {"enum": list(SEMANTIC_PRODUCER_IDS_V2)},
            "source_cid": dict(cid),
            "logic_family": dict(term),
            "target": dict(term),
            "class": {"enum": list(SEMANTIC_PROJECTION_CLASSES_V2)},
            "predicates": dict(term_array),
            "entities": dict(term_array),
            "completeness": {
                "type": "object",
                "additionalProperties": False,
                "required": list(
                    SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                ),
                "properties": {
                    field: {"type": "boolean"}
                    for field in SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                },
            },
            "ambiguity_flags": dict(term_array),
            "confidence_millionths": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1_000_000,
            },
            "validation_errors": dict(term_array),
            "evidence_cid": dict(cid),
            "semantic_content_cid": dict(cid),
            "projection_cid": dict(cid),
        },
    }


def semantic_normalization_spec_v2() -> dict[str, object]:
    """Return every rule used by source-only ModalIR projection revision 2.

    This object is content-addressed below.  Runtime producers consume these
    same fields, so changing an accepted shape, extraction path, class signal,
    validation rule, completeness rule, or confidence value necessarily
    changes :data:`SEMANTIC_NORMALIZATION_V2_CID`.
    """

    return {
        "schema": _SEMANTIC_NORMALIZATION_SCHEMA_V2,
        "term_normalization": {
            "accepted_input_type": "string",
            "non_string_result": "",
            "unicode": _SEMANTIC_TERM_UNICODE_FORM_V2,
            "case": _SEMANTIC_TERM_CASE_RULE_V2,
            "token_separator": _SEMANTIC_TERM_SEPARATOR_V2,
            "preserved_punctuation": list(
                _SEMANTIC_TERM_PRESERVED_PUNCTUATION_V2
            ),
            "other_characters": "replace_with_space",
            "whitespace": "split_collapse",
            "maximum_length": _SEMANTIC_TERM_MAX_LENGTH_V2,
            "alphanumeric_profile": "python_str_isalnum_unicode",
            "persisted_term_schema_pattern": (
                _SEMANTIC_TERM_SCHEMA_PATTERN
            ),
            "authoritative_validation": (
                "exact_normalization_fixed_point_and_leading_and_body_"
                "characters_checked_with_unicode_isalnum"
            ),
            "noncanonical_persisted_terms": "reject_projection",
        },
        "logic_aliases": dict(_SEMANTIC_LOGIC_ALIASES),
        "modal_ir": {
            "document": {
                "accepted_shape": "mapping",
                "formulas_field": _SEMANTIC_MODAL_IR_FORMULAS_FIELD_V2,
            },
            "formulas": {
                "accepted_container": (
                    "sequence_excluding_string_bytes_bytearray"
                ),
                "accepted_item_shape": "mapping",
                "invalid_container_result": "empty",
                "invalid_items": "ignore",
                "collection_order": "input_sequence",
            },
            "operator": {
                "field": _SEMANTIC_MODAL_IR_OPERATOR_FIELD_V2,
                "accepted_shapes": ["mapping", "string"],
                "mapping_family_field": (
                    _SEMANTIC_MODAL_IR_OPERATOR_FAMILY_FIELD_V2
                ),
                "string_value_is_family": True,
                "unsupported_or_non_string_family_result": "missing",
            },
            "predicate": {
                "field": _SEMANTIC_MODAL_IR_PREDICATE_FIELD_V2,
                "accepted_shapes": ["mapping", "string"],
                "mapping_name_field": (
                    _SEMANTIC_MODAL_IR_PREDICATE_NAME_FIELD_V2
                ),
                "mapping_arguments_field": (
                    _SEMANTIC_MODAL_IR_PREDICATE_ARGUMENTS_FIELD_V2
                ),
                "mapping_role_field": (
                    _SEMANTIC_MODAL_IR_PREDICATE_ROLE_FIELD_V2
                ),
                "string_value_is_name": True,
                "unsupported_or_non_string_name_result": "missing",
            },
            "arguments": {
                "accepted_container": (
                    "sequence_excluding_string_bytes_bytearray"
                ),
                "accepted_item_type": "string",
                "invalid_container_result": "empty",
                "invalid_items": "ignore",
                "entity_values": [
                    "exact_argument",
                    (
                        "suffix_after_final_"
                        + _SEMANTIC_MODAL_IR_ENTITY_QUALIFIER_V2
                    ),
                ],
                "suffix_only_when_qualifier_present": True,
                "empty_normalized_values": "omit",
                "normalization": "term_normalization",
                "canonicalization": "sorted_unique",
                "maximum_persisted_items": (
                    _SEMANTIC_PROJECTION_MAX_TERMS_V2
                ),
                "overflow": "reject_projection",
            },
            "primary_formula_selection": {
                "candidates": "all_accepted_mapping_formulas",
                "preferred_role": {
                    "path": [
                        _SEMANTIC_MODAL_IR_PREDICATE_FIELD_V2,
                        _SEMANTIC_MODAL_IR_PREDICATE_ROLE_FIELD_V2,
                    ],
                    "normalized_value": (
                        _SEMANTIC_MODAL_IR_PRIMARY_ROLE_V2
                    ),
                    "missing_or_non_string": "not_preferred",
                },
                "ordered_tiebreakers": [
                    {
                        "path": [
                            _SEMANTIC_MODAL_IR_PROVENANCE_FIELD_V2,
                            _SEMANTIC_MODAL_IR_PROVENANCE_START_FIELD_V2,
                        ],
                        "accepted_type": "integer_excluding_boolean",
                        "missing_or_invalid": "positive_infinity",
                    },
                    {
                        "path": [
                            _SEMANTIC_MODAL_IR_PROVENANCE_FIELD_V2,
                            _SEMANTIC_MODAL_IR_PROVENANCE_END_FIELD_V2,
                        ],
                        "accepted_type": "integer_excluding_boolean",
                        "missing_or_invalid": "positive_infinity",
                    },
                    {
                        "path": [_SEMANTIC_MODAL_IR_FORMULA_ID_FIELD_V2],
                        "coercion": "python_str",
                        "missing": "",
                    },
                    {
                        "path": ["array_index"],
                        "accepted_type": "integer",
                    },
                ],
                "empty_result": "no_primary_formula",
            },
            "projection_fields": {
                "logic_family": (
                    "primary_formula.operator.family"
                ),
                "target": "primary_formula.predicate.name",
                "predicates": "all_accepted_formula_predicate_names",
                "entities": "all_accepted_predicate_arguments",
                "normalization": "term_normalization",
                "predicate_and_entity_canonicalization": "sorted_unique",
                "empty_normalized_values": "omit",
                "maximum_persisted_items": (
                    _SEMANTIC_PROJECTION_MAX_TERMS_V2
                ),
                "overflow": "reject_projection",
                "missing_term": _SEMANTIC_MISSING_TERM_V2,
            },
        },
        "class_inference": {
            "input": "exact_source_text",
            "regex_engine": "python_re_search",
            "regex_flags": ["IGNORECASE"],
            "validation_errors_precede_class_signals": True,
            "ambiguity_flags_retained_with_validation_errors": True,
            "multiple_matching_signals_of_one_class": (
                "first_ordered_signal_sets_class_and_confidence"
            ),
            "conflicting_distinct_signal_classes": {
                "class": "unsupported",
                "validation_error": _SEMANTIC_CLASS_CONFLICT_ERROR_V2,
                "confidence_millionths": (
                    _SEMANTIC_CONFIDENCE_UNSUPPORTED_V2
                ),
            },
            "ordered_explicit_signals": [
                {
                    "id": "source_uncertainty",
                    "pattern": _SEMANTIC_SOURCE_UNCERTAINTY_PATTERN_V2,
                    "class": "ambiguous",
                    "ambiguity_flag": "source_uncertainty",
                    "confidence_millionths": (
                        _SEMANTIC_CONFIDENCE_EXPLICIT_SIGNAL_V2
                    ),
                },
                {
                    "id": "source_disproof",
                    "pattern": _SEMANTIC_SOURCE_DISPROOF_PATTERN_V2,
                    "class": "disproved",
                    "ambiguity_flag": None,
                    "confidence_millionths": (
                        _SEMANTIC_CONFIDENCE_EXPLICIT_SIGNAL_V2
                    ),
                },
            ],
            "proved_signals": [],
            "default": {
                "class": "unsupported",
                "reason": "no_explicit_source_derived_class_evidence",
                "confidence_millionths": (
                    _SEMANTIC_CONFIDENCE_UNSUPPORTED_V2
                ),
            },
        },
        "validation": {
            "missing_term": _SEMANTIC_MISSING_TERM_V2,
            "required_projection_fields": {
                field: {
                    "error": error,
                    "presence": (
                        "nonempty_nonmissing_string"
                        if field in {"logic_family", "target"}
                        else "nonempty_collection"
                    ),
                }
                for field, error in _SEMANTIC_VALIDATION_ERROR_BY_FIELD_V2.items()
            },
            "validation_error_class": "unsupported",
            "validation_error_confidence_millionths": (
                _SEMANTIC_CONFIDENCE_UNSUPPORTED_V2
            ),
            "validation_errors_take_precedence_over_ambiguity": True,
            "canonicalization": "sorted_unique",
        },
        "completeness": {
            "logic_family": "validation_presence.logic_family",
            "target": "validation_presence.target",
            "class": "assigned_enum_including_unsupported",
            "predicates": "validation_presence.predicates",
            "entities": "observed_collection_empty_is_complete",
        },
        "scoreability": {
            "requires_all_completeness_fields": True,
            "requires_no_validation_errors": True,
            "requires_nonvacuous_logic_family": True,
            "requires_nonvacuous_target": True,
            "vacuous_terms": sorted(_SEMANTIC_VACUOUS_TERMS),
            "requires_nonempty_predicates": True,
            "requires_target_in_predicates": True,
            "minimum_confidence_millionths": None,
            "unsupported_class_is_a_scoreable_observation": True,
        },
        "semantic_signature_fields": [
            "logic_family",
            "target",
            "class",
            "predicates",
            "entities",
        ],
        "content_addressing": {
            "cid_version": 1,
            "base": "base32",
            "multihash": "sha2-256",
            "json_codec": "dag-json",
            "bytes_codec": "raw",
        },
        "validation_error_precedence": True,
        "raw_evidence_cid_is_not_semantic_signature": True,
    }


SEMANTIC_PROJECTION_SCHEMA_V2_CID: Final = cid_for_dag_json(
    semantic_projection_json_schema_v2()
)
SEMANTIC_NORMALIZATION_V2_CID: Final = cid_for_dag_json(
    semantic_normalization_spec_v2()
)
SEMANTIC_RESPONSE_SCHEMA_V2_CID: Final = cid_for_dag_json(
    semantic_response_json_schema_v2()
)
SEMANTIC_PRODUCER_REGISTRY_V2_CID: Final = cid_for_dag_json(
    semantic_producer_registry_v2()
)


def semantic_prompt_spec_v2() -> dict[str, object]:
    """Return the prompt behavior frozen independently of model wording."""

    return {
        "schema": SEMANTIC_PROMPT_SCHEMA_V2,
        "task": "source_only_normalized_semantic_projection",
        "instruction_template": SEMANTIC_PROMPT_INSTRUCTION_V2,
        "input_fields": ["text", "optional_producer_evidence"],
        "response_schema_cid": SEMANTIC_RESPONSE_SCHEMA_V2_CID,
        "required_projection_fields": list(
            SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
        ),
        "validation_error_precedence": True,
        "proof_authority": False,
        "forbidden_input_fields": list(
            SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2
        ),
    }


SEMANTIC_PROMPT_V2_CID: Final = cid_for_dag_json(semantic_prompt_spec_v2())


@dataclass(frozen=True, slots=True)
class SemanticProtocolSpec:
    """Additive semantic subprotocol; revision-1 benchmark records stay valid."""

    schema: str
    protocol_id: str
    protocol_version: int
    frozen: bool
    projection_schema: str
    projection_schema_cid: str
    normalization_cid: str
    parent_protocol_sha256: str
    parent_variant_registry_sha256: str
    response_schema_cid: str
    prompt_cid: str
    producer_registry_cid: str
    calibration_route_manifest_cid: str
    calibration_metric_spec_cid: str
    reviewed_target_source_cid: str
    calibration_case_count: int
    calibration_coordinate_count: int
    calibration_cases_per_producer: int
    absolute_quality_min_millionths: int
    wilson_confidence_millionths: int
    wilson_lower_bound_min_millionths: int
    required_projection_fields: tuple[str, ...]
    forbidden_producer_input_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != SEMANTIC_PROTOCOL_SCHEMA_V2:
            raise ProtocolContractError("unsupported semantic protocol schema")
        if self.protocol_id != SEMANTIC_PROTOCOL_ID_V2:
            raise ProtocolContractError("unsupported semantic protocol id")
        if self.protocol_version != SEMANTIC_PROTOCOL_VERSION_V2:
            raise ProtocolContractError("unsupported semantic protocol version")
        if self.frozen is not True:
            raise ProtocolContractError("semantic protocol must be frozen")
        if (
            self.calibration_case_count
            != SEMANTIC_CALIBRATION_CASE_COUNT_V2
            or self.calibration_coordinate_count
            != SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
            or self.calibration_cases_per_producer
            != SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
            or self.absolute_quality_min_millionths
            != SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
            or self.wilson_confidence_millionths
            != SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2
            or self.wilson_lower_bound_min_millionths
            != SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2
        ):
            raise ProtocolContractError(
                "semantic calibration policy drifted"
            )
        if self.calibration_coordinate_count != (
            self.calibration_case_count * len(SEMANTIC_PRODUCER_IDS_V2)
        ):
            raise ProtocolContractError(
                "semantic calibration coordinate count is inconsistent"
            )
        if self.projection_schema != SEMANTIC_PROJECTION_SCHEMA_V2:
            raise ProtocolContractError("semantic projection schema drifted")
        for field in (
            "parent_protocol_sha256",
            "parent_variant_registry_sha256",
        ):
            _digest(getattr(self, field), field)
        for field in (
            "projection_schema_cid",
            "normalization_cid",
            "response_schema_cid",
            "prompt_cid",
            "producer_registry_cid",
            "calibration_route_manifest_cid",
            "calibration_metric_spec_cid",
            "reviewed_target_source_cid",
        ):
            _semantic_cid(
                getattr(self, field),
                field,
                codecs=("dag-json",),
            )
        if (
            self.parent_protocol_sha256
            != SEMANTIC_PARENT_PROTOCOL_SHA256_V1
            or self.parent_variant_registry_sha256
            != SEMANTIC_PARENT_VARIANT_REGISTRY_SHA256_V1
            or self.projection_schema_cid
            != SEMANTIC_PROJECTION_SCHEMA_V2_CID
            or self.normalization_cid != SEMANTIC_NORMALIZATION_V2_CID
            or self.response_schema_cid != SEMANTIC_RESPONSE_SCHEMA_V2_CID
            or self.prompt_cid != SEMANTIC_PROMPT_V2_CID
            or self.producer_registry_cid
            != SEMANTIC_PRODUCER_REGISTRY_V2_CID
            or self.calibration_route_manifest_cid
            != SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
            or self.calibration_metric_spec_cid
            != SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
            or self.reviewed_target_source_cid
            != SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        ):
            raise ProtocolContractError(
                "semantic protocol component identity drifted"
            )
        if self.required_projection_fields != (
            SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
        ):
            raise ProtocolContractError(
                "semantic protocol required fields drifted"
            )
        if self.forbidden_producer_input_fields != (
            SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2
        ):
            raise ProtocolContractError(
                "semantic protocol leakage boundary drifted"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "frozen": self.frozen,
            "projection_schema": self.projection_schema,
            "projection_schema_cid": self.projection_schema_cid,
            "normalization_cid": self.normalization_cid,
            "parent_protocol_sha256": self.parent_protocol_sha256,
            "parent_variant_registry_sha256": (
                self.parent_variant_registry_sha256
            ),
            "response_schema_cid": self.response_schema_cid,
            "prompt_cid": self.prompt_cid,
            "producer_registry_cid": self.producer_registry_cid,
            "calibration_route_manifest_cid": (
                self.calibration_route_manifest_cid
            ),
            "calibration_metric_spec_cid": (
                self.calibration_metric_spec_cid
            ),
            "reviewed_target_source_cid": (
                self.reviewed_target_source_cid
            ),
            "calibration_case_count": self.calibration_case_count,
            "calibration_coordinate_count": (
                self.calibration_coordinate_count
            ),
            "calibration_cases_per_producer": (
                self.calibration_cases_per_producer
            ),
            "absolute_quality_min_millionths": (
                self.absolute_quality_min_millionths
            ),
            "wilson_confidence_millionths": (
                self.wilson_confidence_millionths
            ),
            "wilson_lower_bound_min_millionths": (
                self.wilson_lower_bound_min_millionths
            ),
            "required_projection_fields": list(
                self.required_projection_fields
            ),
            "forbidden_producer_input_fields": list(
                self.forbidden_producer_input_fields
            ),
        }


SEMANTIC_PROTOCOL_V2: Final = SemanticProtocolSpec(
    schema=SEMANTIC_PROTOCOL_SCHEMA_V2,
    protocol_id=SEMANTIC_PROTOCOL_ID_V2,
    protocol_version=SEMANTIC_PROTOCOL_VERSION_V2,
    frozen=True,
    projection_schema=SEMANTIC_PROJECTION_SCHEMA_V2,
    projection_schema_cid=SEMANTIC_PROJECTION_SCHEMA_V2_CID,
    normalization_cid=SEMANTIC_NORMALIZATION_V2_CID,
    parent_protocol_sha256=SEMANTIC_PARENT_PROTOCOL_SHA256_V1,
    parent_variant_registry_sha256=(
        SEMANTIC_PARENT_VARIANT_REGISTRY_SHA256_V1
    ),
    response_schema_cid=SEMANTIC_RESPONSE_SCHEMA_V2_CID,
    prompt_cid=SEMANTIC_PROMPT_V2_CID,
    producer_registry_cid=SEMANTIC_PRODUCER_REGISTRY_V2_CID,
    calibration_route_manifest_cid=(
        SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
    ),
    calibration_metric_spec_cid=SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    reviewed_target_source_cid=SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    calibration_case_count=SEMANTIC_CALIBRATION_CASE_COUNT_V2,
    calibration_coordinate_count=(
        SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2
    ),
    calibration_cases_per_producer=(
        SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2
    ),
    absolute_quality_min_millionths=(
        SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
    ),
    wilson_confidence_millionths=(
        SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2
    ),
    wilson_lower_bound_min_millionths=(
        SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2
    ),
    required_projection_fields=SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2,
    forbidden_producer_input_fields=(
        SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2
    ),
)
SEMANTIC_PROTOCOL_V2_CID: Final = cid_for_dag_json(
    SEMANTIC_PROTOCOL_V2.to_dict()
)


CAUSAL_PROOF_PROTOCOL_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-proof-protocol.v2"
)
CAUSAL_PROOF_PROTOCOL_ID_V2: Final = (
    "hammer-symai-spacy-leanstral-causal-proof-v2"
)
CAUSAL_PROOF_PROTOCOL_VERSION_V2: Final = 2
CAUSAL_PROOF_VARIANT_PROFILE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-proof-variant-profile.v2"
)
CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "causal-proof-selection-receipt.v2"
)
CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA: Final = (
    CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2
)
CAUSAL_PROOF_SELECTION_SPEC_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "causal-proof-selection-spec.v2"
)
CAUSAL_PROOF_RESCUE_POPULATION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "causal-proof-rescue-population-policy.v2"
)
CAUSAL_PROOF_PARENT_PROTOCOL_SHA256_V1: Final = (
    SEMANTIC_PARENT_PROTOCOL_SHA256_V1
)
CAUSAL_PROOF_PARENT_SEMANTIC_PROTOCOL_CID_V2: Final = (
    SEMANTIC_PROTOCOL_V2_CID
)
CAUSAL_PROOF_CANDIDATE_SOURCES_V2: Final = (
    "compiler",
    "hammer",
    "leanstral",
)
CAUSAL_PROOF_COMPILER_STATES_V2: Final = (
    "absent",
    "rejected",
    "accepted",
)
CAUSAL_PROOF_ZERO_CREDIT_REASONS_V2: Final = (
    "compiler_reference_accepted",
    "predecessor_candidate_accepted",
    "duplicate_certificate",
    "candidate_absent",
    "candidate_failed",
    "kernel_rejected",
    "not_routed_by_variant",
    "post_model_failure_continuation",
)
CAUSAL_PROOF_LEANSTRAL_FAILURE_CODES_V2: Final = (
    "leanstral_output_limit",
    "leanstral_schema_invalid",
    "leanstral_forbidden_construct",
    "leanstral_provider_failure",
    "leanstral_timeout",
)


def HSSLEV2108F34() -> str:
    """Return AST-verifiable evidence for causal proof attribution."""

    return (
        "equal compiler-kernel exposure and distinct optional-component "
        "rescue attribution"
    )


def causal_proof_variant_profile_v2() -> dict[str, object]:
    """Return the preregistered G210 route and trigger profile.

    The profile is additive: it does not reinterpret the frozen revision-1
    registry.  In particular, A0 gains an independent terminal kernel check
    only when a caller explicitly selects :data:`CAUSAL_PROOF_PROTOCOL_V2_CID`.
    Optional stages are lazy and may be invoked only after the preceding
    independently checked candidate was absent, rejected, or an exact
    duplicate.
    """

    routes = (
        ("A0", ("compiler", "kernel"), ()),
        ("A1", ("compiler", "spacy", "kernel"), ()),
        (
            "A2",
            ("compiler", "spacy", "hammer", "kernel"),
            ("hammer",),
        ),
        (
            "A3",
            ("compiler", "spacy", "hammer", "leanstral", "kernel"),
            ("hammer", "leanstral"),
        ),
        (
            "A4",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("hammer", "leanstral"),
        ),
        (
            "A5",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("hammer", "leanstral"),
        ),
        (
            "A6",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("leanstral", "hammer"),
        ),
        (
            "A7",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("hammer", "leanstral"),
        ),
        (
            "A8",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("hammer", "leanstral"),
        ),
        (
            "A9",
            ("compiler", "spacy", "symai", "leanstral", "kernel"),
            ("leanstral",),
        ),
        (
            "A10",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("hammer", "leanstral"),
        ),
        (
            "A11",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("hammer", "leanstral"),
        ),
        (
            "A12",
            (
                "compiler",
                "spacy",
                "symai",
                "hammer",
                "leanstral",
                "kernel",
            ),
            ("leanstral", "hammer"),
        ),
    )
    profiles: list[dict[str, object]] = []
    for variant_id, stages, optional_order in routes:
        optional: list[dict[str, object]] = []
        for route_index, source in enumerate(optional_order):
            predecessor = (
                "compiler" if route_index == 0 else optional_order[route_index - 1]
            )
            optional.append(
                {
                    "source": source,
                    "route_index": route_index,
                    "requires_compiler_reference_not_accepted": True,
                    "requires_predecessor_not_accepted": predecessor,
                    "allowed_predecessor_states": [
                        "candidate_absent",
                        "kernel_rejected",
                        "duplicate_certificate",
                        "producer_failed",
                    ],
                }
            )
        profiles.append(
            {
                "variant_id": variant_id,
                "effective_stages": list(stages),
                "compiler_reference_kernel_policy": (
                    "identical_independent_check"
                ),
                "optional_order": list(optional_order),
                "optional_routes": optional,
                "symai_can_receive_proof_credit": False,
                "terminal_proof_authority": "native_kernel",
            }
        )
    return {
        "schema": CAUSAL_PROOF_VARIANT_PROFILE_SCHEMA_V2,
        "protocol_scope": "pilot_and_development_only",
        "variant_ids": [f"A{index}" for index in range(13)],
        "profiles": profiles,
        "compiler_reference_population": (
            "identical_valid_compiled_obligations_for_every_variant"
        ),
        "optional_producers_are_lazy": True,
        "post_hoc_trigger_selection": False,
        "holdout_included": False,
    }


CAUSAL_PROOF_VARIANT_PROFILE_V2_CID: Final = cid_for_dag_json(
    causal_proof_variant_profile_v2()
)


def causal_proof_selection_spec_v2() -> dict[str, object]:
    """Return the exact candidate identity and marginal-credit rules."""

    return {
        "schema": CAUSAL_PROOF_SELECTION_SPEC_SCHEMA_V2,
        "receipt_schema": CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2,
        "candidate_identity": {
            "codec": "raw",
            "multihash": "sha2-256",
            "bytes": "exact_utf8_certificate_bytes",
            "exact_bytes_embedded_in_kernel_sidecar": True,
            "kernel_validator_receives_candidate_and_check": True,
        },
        "structured_identity": {
            "codec": "dag-json",
            "multihash": "sha2-256",
        },
        "selection": [
            "check_present_compiler_reference_first",
            "stop_when_compiler_reference_is_accepted",
            "invoke_only_the_next_preregistered_optional_producer",
            "suppress_byte_identical_candidates_without_a_second_kernel_call",
            "stop_after_the_first_distinct_independently_accepted_candidate",
        ],
        "causal_rescue_requires": [
            "compiler_reference_absent_or_independently_rejected",
            "optional_candidate_distinct_from_every_prior_candidate",
            "optional_candidate_independently_kernel_accepted",
            "no_prior_model_failure_in_the_route",
        ],
        "overlap_rule": {
            "same_raw_candidate_cid_is_duplicate": True,
            "marginal_credit_millionths": 0,
            "kernel_recheck_permitted": False,
        },
        "continuation_rule": {
            "producer_failure_is_recovery": False,
            "later_route_after_model_failure": (
                "post_model_failure_continuation"
            ),
            "accepted_later_candidate_credit_millionths": 0,
        },
        "proof_authority": "native_kernel",
        "solver_or_model_verdict_is_authority": False,
        "per_case_denominators_are_explicit_booleans": True,
        "per_case_denominators": [
            "compiler_reference",
            "compiler_candidate_present",
            "hammer_optional_route",
            "leanstral_optional_route",
            "hammer_escalation",
            "leanstral_escalation",
            "hammer_suppression",
            "leanstral_suppression",
            "hammer_unique_rescue",
            "leanstral_unique_rescue",
            "overlap",
            "unnecessary_work",
        ],
        "leanstral_failure_codes": list(
            CAUSAL_PROOF_LEANSTRAL_FAILURE_CODES_V2
        ),
    }


CAUSAL_PROOF_SELECTION_SPEC_V2_CID: Final = cid_for_dag_json(
    causal_proof_selection_spec_v2()
)


def causal_proof_rescue_population_policy_v2() -> dict[str, object]:
    """Return the fail-closed policy for the new reviewed rescue population."""

    return {
        "schema": CAUSAL_PROOF_RESCUE_POPULATION_SCHEMA_V2,
        "allowed_splits": ["pilot", "development"],
        "holdout_permitted": False,
        "new_independent_review_required": True,
        "source_bound_manifest_cid_required_at_execution": True,
        "manifest_codec": "dag-json",
        "minimum_cases": 1,
        "minimum_cases_per_optional_component": {
            "hammer": 1,
            "leanstral": 1,
        },
        "case_requirements": [
            "valid_reviewed_obligation",
            "deterministic_compilation_does_not_kernel_accept",
            "selected_before_optional_component_outcomes",
        ],
        "reuse_revision_1_holdout": False,
        "shortlist_or_production_authority": False,
    }


CAUSAL_PROOF_RESCUE_POPULATION_V2_CID: Final = cid_for_dag_json(
    causal_proof_rescue_population_policy_v2()
)


@dataclass(frozen=True, slots=True)
class CausalProofProtocolSpec:
    """Additive G210 proof protocol with equal external kernel exposure."""

    schema: str
    protocol_id: str
    protocol_version: int
    frozen: bool
    parent_protocol_sha256: str
    parent_semantic_protocol_cid: str
    variant_profile_cid: str
    selection_spec_cid: str
    rescue_population_policy_cid: str
    selection_receipt_schema: str
    candidate_sources: tuple[str, ...]
    proof_authority: str
    holdout_permitted: bool

    def __post_init__(self) -> None:
        if (
            self.schema != CAUSAL_PROOF_PROTOCOL_SCHEMA_V2
            or self.protocol_id != CAUSAL_PROOF_PROTOCOL_ID_V2
            or self.protocol_version != CAUSAL_PROOF_PROTOCOL_VERSION_V2
        ):
            raise ProtocolContractError("unsupported causal proof protocol")
        if self.frozen is not True:
            raise ProtocolContractError("causal proof protocol must be frozen")
        _digest(self.parent_protocol_sha256, "parent_protocol_sha256")
        for field in (
            "parent_semantic_protocol_cid",
            "variant_profile_cid",
            "selection_spec_cid",
            "rescue_population_policy_cid",
        ):
            _semantic_cid(getattr(self, field), field, codecs=("dag-json",))
        if (
            self.parent_protocol_sha256
            != CAUSAL_PROOF_PARENT_PROTOCOL_SHA256_V1
            or self.parent_semantic_protocol_cid
            != CAUSAL_PROOF_PARENT_SEMANTIC_PROTOCOL_CID_V2
            or self.variant_profile_cid
            != CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
            or self.selection_spec_cid
            != CAUSAL_PROOF_SELECTION_SPEC_V2_CID
            or self.rescue_population_policy_cid
            != CAUSAL_PROOF_RESCUE_POPULATION_V2_CID
        ):
            raise ProtocolContractError(
                "causal proof protocol component identity drifted"
            )
        if (
            self.selection_receipt_schema
            != CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2
            or self.candidate_sources != CAUSAL_PROOF_CANDIDATE_SOURCES_V2
            or self.proof_authority != "native_kernel"
            or self.holdout_permitted is not False
        ):
            raise ProtocolContractError(
                "causal proof protocol trust boundary drifted"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "frozen": self.frozen,
            "parent_protocol_sha256": self.parent_protocol_sha256,
            "parent_semantic_protocol_cid": (
                self.parent_semantic_protocol_cid
            ),
            "variant_profile_cid": self.variant_profile_cid,
            "selection_spec_cid": self.selection_spec_cid,
            "rescue_population_policy_cid": (
                self.rescue_population_policy_cid
            ),
            "selection_receipt_schema": self.selection_receipt_schema,
            "candidate_sources": list(self.candidate_sources),
            "proof_authority": self.proof_authority,
            "holdout_permitted": self.holdout_permitted,
        }


CAUSAL_PROOF_PROTOCOL_V2: Final = CausalProofProtocolSpec(
    schema=CAUSAL_PROOF_PROTOCOL_SCHEMA_V2,
    protocol_id=CAUSAL_PROOF_PROTOCOL_ID_V2,
    protocol_version=CAUSAL_PROOF_PROTOCOL_VERSION_V2,
    frozen=True,
    parent_protocol_sha256=CAUSAL_PROOF_PARENT_PROTOCOL_SHA256_V1,
    parent_semantic_protocol_cid=(
        CAUSAL_PROOF_PARENT_SEMANTIC_PROTOCOL_CID_V2
    ),
    variant_profile_cid=CAUSAL_PROOF_VARIANT_PROFILE_V2_CID,
    selection_spec_cid=CAUSAL_PROOF_SELECTION_SPEC_V2_CID,
    rescue_population_policy_cid=CAUSAL_PROOF_RESCUE_POPULATION_V2_CID,
    selection_receipt_schema=CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2,
    candidate_sources=CAUSAL_PROOF_CANDIDATE_SOURCES_V2,
    proof_authority="native_kernel",
    holdout_permitted=False,
)
CAUSAL_PROOF_PROTOCOL_V2_CID: Final = cid_for_dag_json(
    CAUSAL_PROOF_PROTOCOL_V2.to_dict()
)


def validate_causal_proof_selection_receipt(
    value: object,
) -> dict[str, object]:
    """Validate and return one complete G210 selection receipt.

    This validates the causal classification and the content identities of
    every embedded kernel sidecar.  A report consumer must additionally replay
    :func:`validate_native_kernel_receipt` against its source-bound case result;
    a selection receipt cannot create proof authority by itself.
    """

    # Typed runtime receipts are deeply frozen after their CID is established.
    # Replay always validates the detached DAG-JSON form so immutable tuples
    # and mapping proxies cannot change the wire contract.
    data = _mapping(
        _thaw_bounded_json(value),
        "causal proof selection receipt",
    )
    expected_top = {
        "schema",
        "protocol_cid",
        "variant_profile_cid",
        "run_id",
        "case_id",
        "variant_id",
        "source_cid",
        "compiler_reference",
        "optional_candidates",
        "selected_source",
        "selected_candidate_cid",
        "selected_kernel_receipt_cid",
        "proof_authority",
        "denominators",
        "kernel_receipts",
        "receipt_cid",
    }
    _exact_keys(data, expected_top, "causal proof selection receipt")
    if data["schema"] != CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2:
        raise ProtocolContractError(
            "unsupported causal proof selection receipt schema"
        )
    if data["protocol_cid"] != CAUSAL_PROOF_PROTOCOL_V2_CID:
        raise ProtocolContractError(
            "causal proof selection protocol CID drifted"
        )
    if (
        data["variant_profile_cid"]
        != CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
    ):
        raise ProtocolContractError(
            "causal proof selection profile CID drifted"
        )
    if data["proof_authority"] != "native_kernel":
        raise ProtocolContractError(
            "causal proof selection changed proof authority"
        )
    _nonempty(data["run_id"], "causal proof run_id")
    _nonempty(data["case_id"], "causal proof case_id")
    variant_id = _nonempty(data["variant_id"], "causal proof variant_id")
    if variant_id not in {f"A{index}" for index in range(13)}:
        raise ProtocolContractError(
            "causal proof variant is outside A0-A12"
        )
    source_cid = _semantic_cid(
        data["source_cid"], "causal proof source_cid", codecs=("raw",)
    )

    profiles = causal_proof_variant_profile_v2()["profiles"]
    assert isinstance(profiles, list)
    profile = next(
        item
        for item in profiles
        if isinstance(item, Mapping)
        and item.get("variant_id") == variant_id
    )
    expected_optional = profile["optional_order"]
    assert isinstance(expected_optional, list)

    compiler = _mapping(
        data["compiler_reference"], "causal compiler reference"
    )
    _exact_keys(
        compiler,
        {
            "state",
            "candidate_cid",
            "artifact_cid",
            "invoked",
            "kernel_checked",
            "kernel_receipt_cid",
            "accepted",
        },
        "causal compiler reference",
    )
    state = compiler["state"]
    if state not in CAUSAL_PROOF_COMPILER_STATES_V2:
        raise ProtocolContractError("causal compiler state is invalid")
    for field in ("invoked", "kernel_checked", "accepted"):
        _bool(compiler[field], f"causal compiler {field}")
    compiler_candidate_cid: str | None = None
    if state == "absent":
        if any(
            compiler[field] is not expected
            for field, expected in (
                ("candidate_cid", None),
                ("artifact_cid", None),
                ("invoked", False),
                ("kernel_checked", False),
                ("kernel_receipt_cid", None),
                ("accepted", False),
            )
        ):
            raise ProtocolContractError(
                "absent causal compiler reference has execution evidence"
            )
    else:
        compiler_candidate_cid = _semantic_cid(
            compiler["candidate_cid"],
            "causal compiler candidate_cid",
            codecs=("raw",),
        )
        _semantic_cid(
            compiler["artifact_cid"],
            "causal compiler artifact_cid",
        )
        _semantic_cid(
            compiler["kernel_receipt_cid"],
            "causal compiler kernel_receipt_cid",
            codecs=("dag-json",),
        )
        if (
            compiler["invoked"] is not True
            or compiler["kernel_checked"] is not True
            or compiler["accepted"] is not (state == "accepted")
        ):
            raise ProtocolContractError(
                "causal compiler state disagrees with its kernel check"
            )

    raw_optional = data["optional_candidates"]
    if (
        not isinstance(raw_optional, Sequence)
        or isinstance(raw_optional, (str, bytes, bytearray))
        or len(raw_optional) != len(expected_optional)
    ):
        raise ProtocolContractError(
            "causal optional candidate route is incomplete"
        )
    optional: list[Mapping[str, object]] = []
    seen_candidate_cids = (
        set() if compiler_candidate_cid is None else {compiler_candidate_cid}
    )
    predecessor = "compiler"
    predecessor_accepted = compiler["accepted"] is True
    prior_model_failure = False
    accepted_source: str | None = (
        "compiler" if predecessor_accepted else None
    )
    for index, raw in enumerate(raw_optional):
        record = _mapping(raw, "causal optional candidate")
        _exact_keys(
            record,
            {
                "source",
                "route_index",
                "trigger_condition",
                "trigger_eligible",
                "causal_credit_eligible",
                "invoked",
                "candidate_cid",
                "artifact_cid",
                "kernel_checked",
                "kernel_receipt_cid",
                "accepted",
                "overlap",
                "duplicate_of_candidate_cid",
                "causal_rescue",
                "marginal_credit_millionths",
                "zero_credit_reason",
                "failure_code",
                "continuation_kind",
            },
            "causal optional candidate",
        )
        source = record["source"]
        if source != expected_optional[index] or source not in {
            "hammer",
            "leanstral",
        }:
            raise ProtocolContractError(
                "causal optional source/order differs from its profile"
            )
        if record["route_index"] != index:
            raise ProtocolContractError(
                "causal optional route index changed"
            )
        if record["trigger_condition"] != (
            f"after_{predecessor}_not_accepted"
        ):
            raise ProtocolContractError(
                "causal optional trigger condition changed"
            )
        for field in (
            "trigger_eligible",
            "causal_credit_eligible",
            "invoked",
            "kernel_checked",
            "accepted",
            "overlap",
            "causal_rescue",
        ):
            _bool(record[field], f"causal optional {field}")
        if predecessor_accepted:
            if (
                record["trigger_eligible"] is not False
                or record["invoked"] is not False
            ):
                raise ProtocolContractError(
                "causal optional producer ran after an accepted predecessor"
            )
        elif (
            record["trigger_eligible"] is not True
            or record["invoked"] is not True
        ):
            raise ProtocolContractError(
                "causal optional producer was suppressed after a failure trigger"
            )
        expected_credit_eligibility = bool(
            not predecessor_accepted and not prior_model_failure
        )
        if (
            record["causal_credit_eligible"]
            is not expected_credit_eligibility
        ):
            raise ProtocolContractError(
                "causal optional credit eligibility is not route-derived"
            )
        candidate_cid = record["candidate_cid"]
        if candidate_cid is not None:
            candidate_cid = _semantic_cid(
                candidate_cid,
                "causal optional candidate_cid",
                codecs=("raw",),
            )
            _semantic_cid(
                record["artifact_cid"],
                "causal optional artifact_cid",
            )
        elif record["artifact_cid"] is not None:
            raise ProtocolContractError(
                "causal optional artifact lacks a candidate CID"
            )
        receipt_cid = record["kernel_receipt_cid"]
        if receipt_cid is not None:
            _semantic_cid(
                receipt_cid,
                "causal optional kernel_receipt_cid",
                codecs=("dag-json",),
            )
        if (
            record["kernel_checked"]
            is not (receipt_cid is not None)
            or record["accepted"] is True
            and record["kernel_checked"] is not True
        ):
            raise ProtocolContractError(
                "causal optional kernel fields disagree"
            )
        overlap = record["overlap"]
        duplicate_of = record["duplicate_of_candidate_cid"]
        if overlap:
            if (
                candidate_cid is None
                or candidate_cid not in seen_candidate_cids
                or duplicate_of != candidate_cid
                or record["kernel_checked"] is not False
                or record["zero_credit_reason"] != "duplicate_certificate"
            ):
                raise ProtocolContractError(
                    "causal duplicate-certificate classification is invalid"
                )
        elif duplicate_of is not None:
            raise ProtocolContractError(
                "non-overlap causal candidate has a duplicate binding"
            )
        rescue = bool(
            compiler["accepted"] is False
            and record["causal_credit_eligible"] is True
            and record["trigger_eligible"] is True
            and record["invoked"] is True
            and candidate_cid is not None
            and record["kernel_checked"] is True
            and record["accepted"] is True
            and overlap is False
        )
        if (
            record["causal_rescue"] is not rescue
            or record["marginal_credit_millionths"]
            != (1_000_000 if rescue else 0)
            or (record["zero_credit_reason"] is None) is not rescue
        ):
            raise ProtocolContractError(
                "causal rescue or marginal credit is inconsistent"
            )
        failure_code = record["failure_code"]
        if failure_code is not None:
            allowed = (
                {
                    "hammer_candidate_absent",
                    "hammer_solver_failure",
                    "hammer_timeout",
                    "hammer_schema_invalid",
                    "hammer_premise_selection_miss",
                }
                if source == "hammer"
                else set(CAUSAL_PROOF_LEANSTRAL_FAILURE_CODES_V2)
            )
            if failure_code not in allowed:
                raise ProtocolContractError(
                    "causal optional failure code is not preregistered"
                )
            if (
                candidate_cid is not None
                or record["accepted"] is True
                or record["causal_rescue"] is True
            ):
                raise ProtocolContractError(
                    "failed causal producer received candidate credit"
                )
        if record["invoked"] is False:
            if any(
                record[field] != expected
                for field, expected in (
                    ("candidate_cid", None),
                    ("artifact_cid", None),
                    ("kernel_checked", False),
                    ("kernel_receipt_cid", None),
                    ("accepted", False),
                    ("overlap", False),
                    ("duplicate_of_candidate_cid", None),
                    ("causal_rescue", False),
                    ("failure_code", None),
                    ("continuation_kind", "suppressed"),
                )
            ):
                raise ProtocolContractError(
                    "suppressed causal producer contains execution evidence"
                )
        elif candidate_cid is None and failure_code is None:
            raise ProtocolContractError(
                "invoked causal producer has neither candidate nor failure"
            )
        elif candidate_cid is not None and failure_code is not None:
            raise ProtocolContractError(
                "causal producer has both a candidate and failure"
            )
        if record["invoked"] is False:
            expected_continuation = "suppressed"
            expected_zero_credit = (
                "compiler_reference_accepted"
                if accepted_source == "compiler"
                else "predecessor_candidate_accepted"
            )
        elif failure_code is not None:
            expected_continuation = (
                (
                    "post_model_failure_continuation"
                    if source == "leanstral"
                    else "post_solver_failure_continuation"
                )
                if index + 1 < len(raw_optional)
                else "terminal_producer_failure"
            )
            expected_zero_credit = "candidate_failed"
        elif overlap:
            expected_continuation = "post_overlap_continuation"
            expected_zero_credit = "duplicate_certificate"
        elif record["accepted"] is True:
            expected_continuation = (
                "selected_post_model_failure_continuation"
                if prior_model_failure
                else "selected_causal_rescue"
            )
            expected_zero_credit = (
                "post_model_failure_continuation"
                if prior_model_failure
                else None
            )
        else:
            expected_continuation = (
                "post_kernel_rejection_continuation"
            )
            expected_zero_credit = "kernel_rejected"
        if (
            record["continuation_kind"] != expected_continuation
            or record["zero_credit_reason"] != expected_zero_credit
        ):
            raise ProtocolContractError(
                "causal continuation or zero-credit reason is inconsistent"
            )
        if candidate_cid is not None:
            seen_candidate_cids.add(candidate_cid)
        optional.append(record)
        if source == "leanstral" and failure_code is not None:
            prior_model_failure = True
        predecessor = str(source)
        if record["accepted"] is True:
            accepted_source = str(source)
        predecessor_accepted = bool(
            predecessor_accepted or record["accepted"] is True
        )

    raw_sidecars = data["kernel_receipts"]
    if (
        not isinstance(raw_sidecars, Sequence)
        or isinstance(raw_sidecars, (str, bytes, bytearray))
    ):
        raise ProtocolContractError("causal kernel sidecars must be an array")
    sidecars: dict[str, Mapping[str, object]] = {}
    for raw in raw_sidecars:
        sidecar = _mapping(raw, "causal kernel sidecar")
        _exact_keys(
            sidecar,
            {
                "run_id",
                "case_id",
                "variant_id",
                "source_cid",
                "protocol_cid",
                "variant_profile_cid",
                "candidate_cid",
                "candidate_bytes_utf8",
                "candidate_bytes_length",
                "receipt_cid",
                "stage_status",
                "failure_code",
                "kernel_accepted",
                "consumed_artifact_sha256s",
                "receipt",
            },
            "causal kernel sidecar",
        )
        if any(
            sidecar[field] != data[field]
            for field in ("run_id", "case_id", "variant_id", "source_cid")
        ) or (
            sidecar["protocol_cid"] != CAUSAL_PROOF_PROTOCOL_V2_CID
            or sidecar["variant_profile_cid"]
            != CAUSAL_PROOF_VARIANT_PROFILE_V2_CID
        ):
            raise ProtocolContractError(
                "causal kernel sidecar coordinate binding changed"
            )
        candidate_cid = _semantic_cid(
            sidecar["candidate_cid"],
            "causal sidecar candidate_cid",
            codecs=("raw",),
        )
        candidate_text = sidecar["candidate_bytes_utf8"]
        candidate_length = sidecar["candidate_bytes_length"]
        if (
            not isinstance(candidate_text, str)
            or not isinstance(candidate_length, int)
            or isinstance(candidate_length, bool)
            or candidate_length <= 0
        ):
            raise ProtocolContractError(
                "causal sidecar candidate bytes are invalid"
            )
        candidate_bytes = candidate_text.encode("utf-8")
        if (
            len(candidate_bytes) != candidate_length
            or cid_for_bytes(candidate_bytes) != candidate_cid
        ):
            raise ProtocolContractError(
                "causal sidecar raw candidate CID changed from exact bytes"
            )
        receipt_cid = _semantic_cid(
            sidecar["receipt_cid"],
            "causal sidecar receipt_cid",
            codecs=("dag-json",),
        )
        receipt = _mapping(sidecar["receipt"], "causal native receipt")
        if cid_for_dag_json(dict(receipt)) != receipt_cid:
            raise ProtocolContractError(
                "causal native receipt CID changed from its body"
            )
        accepted = _bool(
            sidecar["kernel_accepted"], "causal sidecar kernel_accepted"
        )
        if (
            receipt.get("independent") is not True
            or receipt.get("accepted") is not accepted
            or receipt.get("run_id") != data["run_id"]
            or receipt.get("case_id") != data["case_id"]
            or receipt.get("variant_id") != data["variant_id"]
        ):
            raise ProtocolContractError(
                "causal native receipt body is not source-coordinate bound"
            )
        status = _enum(
            StageStatus, sidecar["stage_status"], "causal sidecar stage_status"
        )
        failure_code = sidecar["failure_code"]
        if failure_code is not None:
            _enum(
                FailureCode,
                failure_code,
                "causal sidecar failure_code",
            )
        if accepted is not (status is StageStatus.SUCCESS):
            raise ProtocolContractError(
                "causal sidecar status disagrees with kernel acceptance"
            )
        consumed = sidecar["consumed_artifact_sha256s"]
        if (
            not isinstance(consumed, Sequence)
            or isinstance(consumed, (str, bytes, bytearray))
        ):
            raise ProtocolContractError(
                "causal sidecar consumed artifacts must be an array"
            )
        for digest in consumed:
            _digest(digest, "causal sidecar consumed artifact")
        if candidate_cid in sidecars:
            raise ProtocolContractError(
                "causal candidate was checked more than once"
            )
        sidecars[candidate_cid] = sidecar

    checked_candidate_cids: list[str] = []
    if compiler["kernel_checked"]:
        assert compiler_candidate_cid is not None
        checked_candidate_cids.append(compiler_candidate_cid)
        if (
            compiler_candidate_cid not in sidecars
            or sidecars[compiler_candidate_cid]["receipt_cid"]
            != compiler["kernel_receipt_cid"]
        ):
            raise ProtocolContractError(
                "causal compiler check lacks its native sidecar"
            )
    for record in optional:
        if record["kernel_checked"]:
            candidate_cid = record["candidate_cid"]
            assert isinstance(candidate_cid, str)
            checked_candidate_cids.append(candidate_cid)
            if (
                candidate_cid not in sidecars
                or sidecars[candidate_cid]["receipt_cid"]
                != record["kernel_receipt_cid"]
            ):
                raise ProtocolContractError(
                    "causal optional check lacks its native sidecar"
                )
    if set(checked_candidate_cids) != set(sidecars):
        raise ProtocolContractError(
            "causal kernel sidecar collection has an orphan"
        )

    accepted_entries: list[tuple[str, object, object]] = []
    if compiler["accepted"]:
        accepted_entries.append(
            (
                "compiler",
                compiler["candidate_cid"],
                compiler["kernel_receipt_cid"],
            )
        )
    accepted_entries.extend(
        (
            str(record["source"]),
            record["candidate_cid"],
            record["kernel_receipt_cid"],
        )
        for record in optional
        if record["accepted"] is True
    )
    if len(accepted_entries) > 1:
        raise ProtocolContractError(
            "causal graph continued after an accepted candidate"
        )
    selected = (
        (None, None, None)
        if not accepted_entries
        else accepted_entries[0]
    )
    if (
        data["selected_source"],
        data["selected_candidate_cid"],
        data["selected_kernel_receipt_cid"],
    ) != selected:
        raise ProtocolContractError(
            "causal selected candidate differs from kernel evidence"
        )

    denominators = _mapping(
        data["denominators"], "causal proof denominators"
    )
    expected_denominators = {
        "compiler_reference": True,
        "compiler_candidate_present": compiler_candidate_cid is not None,
        "hammer_optional_route": "hammer" in expected_optional,
        "leanstral_optional_route": "leanstral" in expected_optional,
        "hammer_escalation": any(
            item["source"] == "hammer"
            and item["trigger_eligible"] is True
            for item in optional
        ),
        "leanstral_escalation": any(
            item["source"] == "leanstral"
            and item["trigger_eligible"] is True
            for item in optional
        ),
        "hammer_suppression": any(
            item["source"] == "hammer"
            and item["trigger_eligible"] is False
            for item in optional
        ),
        "leanstral_suppression": any(
            item["source"] == "leanstral"
            and item["trigger_eligible"] is False
            for item in optional
        ),
        "hammer_unique_rescue": any(
            item["source"] == "hammer"
            and item["causal_credit_eligible"] is True
            and item["kernel_checked"] is True
            and item["overlap"] is False
            for item in optional
        ),
        "leanstral_unique_rescue": any(
            item["source"] == "leanstral"
            and item["causal_credit_eligible"] is True
            and item["kernel_checked"] is True
            and item["overlap"] is False
            for item in optional
        ),
        "overlap": any(item["overlap"] is True for item in optional),
        "unnecessary_work": any(
            item["invoked"] is True
            and item["causal_rescue"] is False
            for item in optional
        ),
    }
    if dict(denominators) != expected_denominators:
        raise ProtocolContractError(
            "causal proof denominators are not recomputable"
        )

    receipt_cid = _semantic_cid(
        data["receipt_cid"],
        "causal proof receipt_cid",
        codecs=("dag-json",),
    )
    body = {key: item for key, item in data.items() if key != "receipt_cid"}
    if cid_for_dag_json(body) != receipt_cid:
        raise ProtocolContractError(
            "causal proof receipt CID changed from its body"
        )
    return dict(data)


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    """Canonical, content-addressed semantic evidence shared by all producers."""

    schema: str
    semantic_protocol_cid: str
    producer_id: str
    source_cid: str
    logic_family: str
    target: str
    semantic_class: str
    predicates: tuple[str, ...]
    entities: tuple[str, ...]
    completeness: Mapping[str, bool]
    ambiguity_flags: tuple[str, ...]
    confidence_millionths: int
    validation_errors: tuple[str, ...]
    evidence_cid: str
    semantic_content_cid: str | None = None
    projection_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != SEMANTIC_PROJECTION_SCHEMA_V2:
            raise ProtocolContractError(
                "unsupported semantic projection schema"
            )
        _semantic_cid(
            self.semantic_protocol_cid,
            "semantic_protocol_cid",
            codecs=("dag-json",),
        )
        if self.semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID:
            raise ProtocolContractError(
                "semantic projection protocol identity drifted"
            )
        if self.producer_id not in SEMANTIC_PRODUCER_IDS_V2:
            raise ProtocolContractError(
                "semantic projection producer is not registered"
            )
        _semantic_cid(self.source_cid, "source_cid", codecs=("raw",))
        _semantic_cid(
            self.evidence_cid,
            "evidence_cid",
            codecs=("dag-json",),
        )
        for field in ("logic_family", "target"):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not _is_semantic_term(value)
            ):
                raise ProtocolContractError(
                    f"semantic projection {field} is not normalized"
                )
        if _normalize_logic_family(self.logic_family) != self.logic_family:
            raise ProtocolContractError(
                "semantic projection logic_family is not canonical"
            )
        if self.semantic_class not in SEMANTIC_PROJECTION_CLASSES_V2:
            raise ProtocolContractError(
                "semantic projection class is unsupported"
            )
        for field in (
            "predicates",
            "entities",
            "ambiguity_flags",
            "validation_errors",
        ):
            values = getattr(self, field)
            if (
                not isinstance(values, tuple)
                or len(values) > _SEMANTIC_PROJECTION_MAX_TERMS_V2
                or tuple(sorted(set(values))) != values
                or any(
                    not isinstance(value, str)
                    or not _is_semantic_term(value)
                    for value in values
                )
            ):
                raise ProtocolContractError(
                    f"semantic projection {field} is not canonical"
                )
        if (
            not isinstance(self.completeness, Mapping)
            or set(self.completeness)
            != set(SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2)
            or any(type(value) is not bool for value in self.completeness.values())
        ):
            raise ProtocolContractError(
                "semantic projection completeness fields are invalid"
            )
        object.__setattr__(
            self,
            "completeness",
            MappingProxyType(
                {
                    field: self.completeness[field]
                    for field in SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                }
            ),
        )
        if (
            isinstance(self.confidence_millionths, bool)
            or not isinstance(self.confidence_millionths, int)
            or not 0 <= self.confidence_millionths <= 1_000_000
        ):
            raise ProtocolContractError(
                "semantic projection confidence_millionths must be an "
                "integer from zero to one million"
            )
        expected_semantic = cid_for_dag_json(self._semantic_content())
        if self.semantic_content_cid is None:
            object.__setattr__(
                self,
                "semantic_content_cid",
                expected_semantic,
            )
        else:
            _semantic_cid(
                self.semantic_content_cid,
                "semantic_content_cid",
                codecs=("dag-json",),
            )
        if self.semantic_content_cid != expected_semantic:
            raise ProtocolContractError(
                "semantic projection semantic-content identity changed"
            )
        expected_projection = cid_for_dag_json(self._projection_content())
        if self.projection_cid is None:
            object.__setattr__(
                self,
                "projection_cid",
                expected_projection,
            )
        else:
            _semantic_cid(
                self.projection_cid,
                "projection_cid",
                codecs=("dag-json",),
            )
        if self.projection_cid != expected_projection:
            raise ProtocolContractError(
                "semantic projection provenance identity changed"
            )

    @classmethod
    def create(
        cls,
        *,
        producer_id: str,
        source_text: str,
        logic_family: str,
        target: str,
        semantic_class: str,
        predicates: Sequence[str] = (),
        entities: Sequence[str] = (),
        completeness: Mapping[str, bool] | None = None,
        ambiguity_flags: Sequence[str] = (),
        confidence_millionths: int = 1_000_000,
        validation_errors: Sequence[str] = (),
        evidence_cid: str,
    ) -> Self:
        if not isinstance(source_text, str) or not source_text.strip():
            raise ProtocolContractError(
                "semantic projection requires nonempty source text"
            )

        def terms(values: Sequence[str]) -> tuple[str, ...]:
            return tuple(
                sorted(
                    {
                        normalized
                        for value in values
                        if (normalized := normalize_semantic_term(value))
                    }
                )
            )

        normalized_logic = _normalize_logic_family(logic_family)
        normalized_target = normalize_semantic_term(target)
        return cls(
            schema=SEMANTIC_PROJECTION_SCHEMA_V2,
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
            producer_id=producer_id,
            source_cid=cid_for_bytes(source_text.encode("utf-8")),
            logic_family=normalized_logic,
            target=normalized_target,
            semantic_class=normalize_semantic_term(semantic_class),
            predicates=terms(predicates),
            entities=terms(entities),
            completeness=(
                {
                    field: True
                    for field in SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                }
                if completeness is None
                else dict(completeness)
            ),
            ambiguity_flags=terms(ambiguity_flags),
            confidence_millionths=confidence_millionths,
            validation_errors=terms(validation_errors),
            evidence_cid=evidence_cid,
        )

    @property
    def scoreable(self) -> bool:
        return bool(
            all(self.completeness.values())
            and not self.validation_errors
            and self.logic_family not in _SEMANTIC_VACUOUS_TERMS
            and self.target not in _SEMANTIC_VACUOUS_TERMS
            and self.predicates
            and self.target in self.predicates
        )

    def _semantic_content(self) -> dict[str, object]:
        return {
            "logic_family": self.logic_family,
            "target": self.target,
            "class": self.semantic_class,
            "predicates": list(self.predicates),
            "entities": list(self.entities),
        }

    def _projection_content(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "semantic_protocol_cid": self.semantic_protocol_cid,
            "producer_id": self.producer_id,
            "source_cid": self.source_cid,
            "logic_family": self.logic_family,
            "target": self.target,
            "class": self.semantic_class,
            "predicates": list(self.predicates),
            "entities": list(self.entities),
            "completeness": {
                field: self.completeness[field]
                for field in SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
            },
            "ambiguity_flags": list(self.ambiguity_flags),
            "confidence_millionths": self.confidence_millionths,
            "validation_errors": list(self.validation_errors),
            "evidence_cid": self.evidence_cid,
            "semantic_content_cid": self.semantic_content_cid,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._projection_content(),
            "projection_cid": self.projection_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "semantic_projection")
        expected = {
            "schema",
            "semantic_protocol_cid",
            "producer_id",
            "source_cid",
            "logic_family",
            "target",
            "class",
            "predicates",
            "entities",
            "completeness",
            "ambiguity_flags",
            "confidence_millionths",
            "validation_errors",
            "evidence_cid",
            "semantic_content_cid",
            "projection_cid",
        }
        _exact_keys(data, expected, "semantic_projection")
        arrays: dict[str, tuple[str, ...]] = {}
        for field in (
            "predicates",
            "entities",
            "ambiguity_flags",
            "validation_errors",
        ):
            raw = data[field]
            if not isinstance(raw, list):
                raise ProtocolContractError(
                    f"semantic_projection.{field} must be an array"
                )
            arrays[field] = tuple(
                _nonempty(item, f"semantic_projection.{field}[]")
                for item in raw
            )
        return cls(
            schema=_nonempty(data["schema"], "semantic_projection.schema"),
            semantic_protocol_cid=_semantic_cid(
                data["semantic_protocol_cid"],
                "semantic_projection.semantic_protocol_cid",
                codecs=("dag-json",),
            ),
            producer_id=_nonempty(
                data["producer_id"], "semantic_projection.producer_id"
            ),
            source_cid=_semantic_cid(
                data["source_cid"],
                "semantic_projection.source_cid",
                codecs=("raw",),
            ),
            logic_family=_nonempty(
                data["logic_family"], "semantic_projection.logic_family"
            ),
            target=_nonempty(
                data["target"], "semantic_projection.target"
            ),
            semantic_class=_nonempty(
                data["class"], "semantic_projection.class"
            ),
            predicates=arrays["predicates"],
            entities=arrays["entities"],
            completeness=_mapping(
                data["completeness"], "semantic_projection.completeness"
            ),  # type: ignore[arg-type]
            ambiguity_flags=arrays["ambiguity_flags"],
            confidence_millionths=data["confidence_millionths"],  # type: ignore[arg-type]
            validation_errors=arrays["validation_errors"],
            evidence_cid=_semantic_cid(
                data["evidence_cid"],
                "semantic_projection.evidence_cid",
            ),
            semantic_content_cid=_semantic_cid(
                data["semantic_content_cid"],
                "semantic_projection.semantic_content_cid",
                codecs=("dag-json",),
            ),
            projection_cid=_semantic_cid(
                data["projection_cid"],
                "semantic_projection.projection_cid",
                codecs=("dag-json",),
            ),
        )


_MAX_BOUNDED_JSON_DEPTH: Final = 8
_MAX_BOUNDED_JSON_ITEMS: Final = 256
_MAX_BOUNDED_JSON_STRING: Final = 4096
_MAX_STAGE_PAYLOAD_BYTES: Final = 64 * 1024
_MAX_CASE_RESULT_BYTES: Final = 512 * 1024


def _freeze_bounded_json(value: object, field: str, *, depth: int = 0) -> object:
    """Validate and deeply freeze the small JSON values carried by adapters."""

    if depth > _MAX_BOUNDED_JSON_DEPTH:
        raise ProtocolContractError(f"{field} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ProtocolContractError(f"{field} contains a non-finite number")
        if isinstance(value, str) and len(value) > _MAX_BOUNDED_JSON_STRING:
            raise ProtocolContractError(f"{field} contains an oversized string")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_BOUNDED_JSON_ITEMS:
            raise ProtocolContractError(f"{field} contains too many object keys")
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolContractError(f"{field} keys must be strings")
            frozen[key] = _freeze_bounded_json(
                item, f"{field}.{key}", depth=depth + 1
            )
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_BOUNDED_JSON_ITEMS:
            raise ProtocolContractError(f"{field} contains too many array items")
        return tuple(
            _freeze_bounded_json(item, f"{field}[]", depth=depth + 1)
            for item in value
        )
    raise ProtocolContractError(f"{field} must contain JSON-compatible values")


def _thaw_bounded_json(value: object) -> object:
    """Convert the immutable internal representation back to JSON values."""

    if isinstance(value, Mapping):
        return {str(key): _thaw_bounded_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_bounded_json(item) for item in value]
    return value


def _bounded_json(value: object, field: str, *, maximum: int) -> object:
    frozen = _freeze_bounded_json(value, field)
    try:
        encoded = canonical_json(_thaw_bounded_json(frozen)).encode("utf-8")
    except ProtocolContractError:
        raise
    if len(encoded) > maximum:
        raise ProtocolContractError(f"{field} exceeds {maximum} encoded bytes")
    return frozen


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


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    """Deterministic, bounded measurements emitted by every stage adapter.

    No wall-clock timestamp, host name, PID, or random identifier is stored.
    This keeps equivalent measurements canonically serializable while still
    retaining the resource counters needed by the benchmark protocol.
    """

    schema: str = TELEMETRY_SCHEMA
    wall_time_ms: float = 0.0
    cpu_time_ms: float = 0.0
    peak_memory_bytes: int = 0
    input_items: int = 0
    output_items: int = 0
    model_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    retries: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    resource_lane: ResourceLane = ResourceLane.CPU

    def __post_init__(self) -> None:
        if self.schema != TELEMETRY_SCHEMA:
            raise ProtocolContractError("unsupported telemetry schema")
        if not isinstance(self.resource_lane, ResourceLane):
            raise ProtocolContractError("resource_lane must be a ResourceLane")
        _number(self.wall_time_ms, "wall_time_ms", minimum=0, maximum=86_400_000)
        _number(self.cpu_time_ms, "cpu_time_ms", minimum=0, maximum=86_400_000)
        for field in (
            "peak_memory_bytes",
            "input_items",
            "output_items",
            "model_calls",
            "cache_hits",
            "cache_misses",
            "retries",
            "bytes_in",
            "bytes_out",
        ):
            _integer(getattr(self, field), field)
        if self.peak_memory_bytes > 1 << 40:
            raise ProtocolContractError("peak_memory_bytes exceeds the bound")
        if self.input_items > _MAX_BOUNDED_JSON_ITEMS * 1024:
            raise ProtocolContractError("input_items exceeds the bound")
        if self.output_items > _MAX_BOUNDED_JSON_ITEMS * 1024:
            raise ProtocolContractError("output_items exceeds the bound")
        for field in ("model_calls", "cache_hits", "cache_misses", "retries"):
            if getattr(self, field) > 1_000_000:
                raise ProtocolContractError(f"{field} exceeds the bound")
        for field in ("bytes_in", "bytes_out"):
            if getattr(self, field) > 1 << 40:
                raise ProtocolContractError(f"{field} exceeds the bound")

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "telemetry")
        _exact_keys(data, set(cls.__dataclass_fields__), "telemetry")
        return cls(
            schema=_nonempty(data["schema"], "telemetry.schema"),
            wall_time_ms=_number(data["wall_time_ms"], "wall_time_ms"),
            cpu_time_ms=_number(data["cpu_time_ms"], "cpu_time_ms"),
            peak_memory_bytes=_integer(data["peak_memory_bytes"], "peak_memory_bytes"),
            input_items=_integer(data["input_items"], "input_items"),
            output_items=_integer(data["output_items"], "output_items"),
            model_calls=_integer(data["model_calls"], "model_calls"),
            cache_hits=_integer(data["cache_hits"], "cache_hits"),
            cache_misses=_integer(data["cache_misses"], "cache_misses"),
            retries=_integer(data["retries"], "retries"),
            bytes_in=_integer(data["bytes_in"], "bytes_in"),
            bytes_out=_integer(data["bytes_out"], "bytes_out"),
            resource_lane=_enum(ResourceLane, data["resource_lane"], "resource_lane"),  # type: ignore[arg-type]
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StageProvenance:
    """Identity and source receipt for one adapter invocation."""

    schema: str
    adapter_id: str
    adapter_version: str
    source: tuple[str, ...]
    requested_identity: Mapping[str, object]
    effective_identity: Mapping[str, object]
    input_sha256: str
    environment_sha256: str | None = None
    upstream_stage_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != STAGE_PROVENANCE_SCHEMA:
            raise ProtocolContractError("unsupported stage-provenance schema")
        _safe_id(self.adapter_id, "adapter_id")
        _safe_id(self.adapter_version, "adapter_version")
        if not isinstance(self.source, tuple) or not self.source:
            raise ProtocolContractError("source must be a nonempty tuple")
        for item in self.source:
            _nonempty(item, "source[]")
        object.__setattr__(
            self,
            "requested_identity",
            _bounded_json(self.requested_identity, "requested_identity", maximum=16 * 1024),
        )
        object.__setattr__(
            self,
            "effective_identity",
            _bounded_json(self.effective_identity, "effective_identity", maximum=16 * 1024),
        )
        _digest(self.input_sha256, "input_sha256")
        if self.environment_sha256 is not None:
            _digest(self.environment_sha256, "environment_sha256")
        if not isinstance(self.upstream_stage_digests, tuple):
            raise ProtocolContractError("upstream_stage_digests must be a tuple")
        if len(self.upstream_stage_digests) > len(StageName):
            raise ProtocolContractError("too many upstream stage digests")
        for digest in self.upstream_stage_digests:
            _digest(digest, "upstream_stage_digests[]")
        if len(set(self.upstream_stage_digests)) != len(self.upstream_stage_digests):
            raise ProtocolContractError("upstream stage digests must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "source": list(self.source),
            "requested_identity": _thaw_bounded_json(self.requested_identity),
            "effective_identity": _thaw_bounded_json(self.effective_identity),
            "input_sha256": self.input_sha256,
            "environment_sha256": self.environment_sha256,
            "upstream_stage_digests": list(self.upstream_stage_digests),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "stage_provenance")
        _exact_keys(data, set(cls.__dataclass_fields__), "stage_provenance")
        source = data["source"]
        upstream = data["upstream_stage_digests"]
        if not isinstance(source, list) or not isinstance(upstream, list):
            raise ProtocolContractError("provenance arrays must be arrays")
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            adapter_id=_safe_id(data["adapter_id"], "adapter_id"),
            adapter_version=_safe_id(data["adapter_version"], "adapter_version"),
            source=tuple(_nonempty(item, "source[]") for item in source),
            requested_identity=_mapping(data["requested_identity"], "requested_identity"),
            effective_identity=_mapping(data["effective_identity"], "effective_identity"),
            input_sha256=_digest(data["input_sha256"], "input_sha256"),
            environment_sha256=(
                None
                if data["environment_sha256"] is None
                else _digest(data["environment_sha256"], "environment_sha256")
            ),
            upstream_stage_digests=tuple(
                _digest(item, "upstream_stage_digests[]") for item in upstream
            ),
        )


@dataclass(frozen=True, slots=True)
class StageRecord:
    """Versioned, content-addressed output of one benchmark stage."""

    schema: str
    protocol_sha256: str
    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str
    split: Split
    cache_mode: CacheMode
    stage: StageName
    adapter_version: str
    status: StageStatus
    provenance: StageProvenance
    telemetry: TelemetryRecord
    data: object = MappingProxyType({})
    output_sha256: str | None = None
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    kernel_accepted: bool = False
    kernel_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema != STAGE_RECORD_SCHEMA:
            raise ProtocolContractError("unsupported stage-record schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        if _FROZEN_PROTOCOL_SHA256 is not None and self.protocol_sha256 != _FROZEN_PROTOCOL_SHA256:
            raise ProtocolContractError("stage record does not bind frozen protocol revision 1")
        _safe_id(self.run_id, "run_id")
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in _REQUIRED_VARIANTS:
            raise ProtocolContractError(f"variant_id is not registered: {self.variant_id!r}")
        if not isinstance(self.split, Split) or not isinstance(self.cache_mode, CacheMode):
            raise ProtocolContractError("split and cache_mode must use protocol enums")
        if not isinstance(self.stage, StageName):
            raise ProtocolContractError("stage must be a StageName")
        _safe_id(self.adapter_version, "adapter_version")
        if not isinstance(self.status, StageStatus):
            raise ProtocolContractError("status must be a StageStatus")
        if not isinstance(self.provenance, StageProvenance):
            raise ProtocolContractError("provenance must be a StageProvenance")
        if self.provenance.adapter_version != self.adapter_version:
            raise ProtocolContractError("adapter versions disagree")
        if not isinstance(self.telemetry, TelemetryRecord):
            raise ProtocolContractError("telemetry must be a TelemetryRecord")
        frozen_data = _bounded_json(self.data, "data", maximum=_MAX_STAGE_PAYLOAD_BYTES)
        object.__setattr__(self, "data", frozen_data)
        calculated = hashlib.sha256(
            canonical_json(_thaw_bounded_json(frozen_data)).encode("utf-8")
        ).hexdigest()
        if self.status is StageStatus.SUCCESS:
            if self.output_sha256 is None:
                raise ProtocolContractError("successful stages require output_sha256")
            _digest(self.output_sha256, "output_sha256")
            if self.output_sha256 != calculated:
                raise ProtocolContractError("output_sha256 does not match stage data")
            if self.failure_code is not None or self.failure_detail is not None:
                raise ProtocolContractError("successful stages cannot carry failures")
        else:
            if self.output_sha256 is not None:
                raise ProtocolContractError("unavailable stages cannot carry output")
            if self.status is StageStatus.UNAVAILABLE and self.failure_code is not FailureCode.CAPABILITY_UNAVAILABLE:
                raise ProtocolContractError("unavailable stages require capability_unavailable")
            if self.failure_code is None:
                raise ProtocolContractError("non-success stages require a failure code")
            if self.failure_detail is not None:
                _nonempty(self.failure_detail, "failure_detail")
        if self.stage is not StageName.KERNEL and self.kernel_accepted:
            raise ProtocolContractError("only the kernel stage may accept a kernel receipt")
        _bool(self.kernel_accepted, "kernel_accepted")
        if self.kernel_accepted:
            if self.status is not StageStatus.SUCCESS or self.kernel_receipt_sha256 is None:
                raise ProtocolContractError("kernel acceptance requires a successful receipt")
            _digest(self.kernel_receipt_sha256, "kernel_receipt_sha256")
        elif self.kernel_receipt_sha256 is not None:
            raise ProtocolContractError("a receipt cannot be present without kernel acceptance")

    @classmethod
    def create(
        cls,
        *,
        protocol_sha256: str,
        run_id: str,
        case_id: str,
        case_manifest_sha256: str,
        variant_id: str,
        split: Split,
        cache_mode: CacheMode,
        stage: StageName,
        adapter_version: str,
        status: StageStatus,
        provenance: StageProvenance,
        telemetry: TelemetryRecord,
        data: object = None,
        failure_code: FailureCode | None = None,
        failure_detail: str | None = None,
        kernel_accepted: bool = False,
        kernel_receipt_sha256: str | None = None,
    ) -> Self:
        payload = {} if data is None else data
        output_digest = None
        if status is StageStatus.SUCCESS:
            output_digest = hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest()
        return cls(
            schema=STAGE_RECORD_SCHEMA,
            protocol_sha256=protocol_sha256,
            run_id=run_id,
            case_id=case_id,
            case_manifest_sha256=case_manifest_sha256,
            variant_id=variant_id,
            split=split,
            cache_mode=cache_mode,
            stage=stage,
            adapter_version=adapter_version,
            status=status,
            provenance=provenance,
            telemetry=telemetry,
            data=payload,
            output_sha256=output_digest,
            failure_code=failure_code,
            failure_detail=failure_detail,
            kernel_accepted=kernel_accepted,
            kernel_receipt_sha256=kernel_receipt_sha256,
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

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
            "stage": self.stage.value,
            "adapter_version": self.adapter_version,
            "status": self.status.value,
            "provenance": self.provenance.to_dict(),
            "telemetry": self.telemetry.to_dict(),
            "data": _thaw_bounded_json(self.data),
            "output_sha256": self.output_sha256,
            "failure_code": None if self.failure_code is None else self.failure_code.value,
            "failure_detail": self.failure_detail,
            "kernel_accepted": self.kernel_accepted,
            "kernel_receipt_sha256": self.kernel_receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "stage_record")
        _exact_keys(data, set(cls.__dataclass_fields__), "stage_record")
        failure_code = data["failure_code"]
        return cls(
            schema=_nonempty(data["schema"], "schema"),
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            run_id=_safe_id(data["run_id"], "run_id"),
            case_id=_safe_id(data["case_id"], "case_id"),
            case_manifest_sha256=_digest(data["case_manifest_sha256"], "case_manifest_sha256"),
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            cache_mode=_enum(CacheMode, data["cache_mode"], "cache_mode"),  # type: ignore[arg-type]
            stage=_enum(StageName, data["stage"], "stage"),  # type: ignore[arg-type]
            adapter_version=_safe_id(data["adapter_version"], "adapter_version"),
            status=_enum(StageStatus, data["status"], "status"),  # type: ignore[arg-type]
            provenance=StageProvenance.from_dict(data["provenance"]),
            telemetry=TelemetryRecord.from_dict(data["telemetry"]),
            data=data["data"],
            output_sha256=(None if data["output_sha256"] is None else _digest(data["output_sha256"], "output_sha256")),
            failure_code=(None if failure_code is None else _enum(FailureCode, failure_code, "failure_code")),  # type: ignore[arg-type]
            failure_detail=(None if data["failure_detail"] is None else _nonempty(data["failure_detail"], "failure_detail")),
            kernel_accepted=_bool(data["kernel_accepted"], "kernel_accepted"),
            kernel_receipt_sha256=(None if data["kernel_receipt_sha256"] is None else _digest(data["kernel_receipt_sha256"], "kernel_receipt_sha256")),
        )


NATIVE_KERNEL_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.native-kernel-receipt.v1"
)


_NATIVE_KERNEL_ATTEMPT_FIELDS: Final = frozenset(
    {
        "attempt_index",
        "candidate_source",
        "candidate_artifact_sha256",
        "source_sha256",
        "command_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "returncode",
        "timed_out",
        "cancelled",
        "resource_exhausted",
        "termination_reason",
        "process_group_reaped",
        "active_process_count",
        "accepted",
        "attempt_sha256",
    }
)
_NATIVE_KERNEL_SELECTED_ATTEMPT_FIELDS: Final = frozenset(
    {
        "attempt_index",
        "candidate_source",
        "candidate_artifact_sha256",
        "attempt_sha256",
        "accepted",
    }
)
_NATIVE_KERNEL_EXECUTED_RECEIPT_FIELDS: Final = frozenset(
    {
        "compiled_obligation_sha256",
        "obligation_sha256",
        "candidate_source",
        "candidate_artifact_sha256",
        "source_sha256",
        "semantic_context_sha256",
        "semantic_artifact_sha256s",
        "command_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "returncode",
        "timed_out",
        "cancelled",
        "resource_exhausted",
        "termination_reason",
        "process_group_reaped",
        "candidate_attempts",
        "candidate_attempts_sha256",
        "selected_attempt",
    }
)
_NATIVE_KERNEL_CANDIDATE_SOURCES: Final = frozenset(
    {StageName.COMPILER.value, StageName.HAMMER.value, StageName.LEANSTRAL.value}
)
_NATIVE_KERNEL_SAFE_COMPLETION_REASONS: Final = frozenset(
    {"completed", "completed_with_descendant_cleanup"}
)
_NATIVE_KERNEL_PROCESS_ERROR_REASONS: Final = frozenset(
    {"monitor_error", "spawn_error"}
)
_NATIVE_KERNEL_TERMINATION_REASONS: Final = frozenset(
    {
        *_NATIVE_KERNEL_SAFE_COMPLETION_REASONS,
        *_NATIVE_KERNEL_PROCESS_ERROR_REASONS,
        "cancelled",
        "cancelled_before_start",
        "orphaned_process_group",
        "resource_deadline",
        "wall_clock_deadline",
    }
)
_NATIVE_KERNEL_OUTER_ATTACHMENT_FIELDS: Final = frozenset(
    {"routing_policy"}
)


def _native_kernel_process_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolContractError(
            f"{field} must be a nonnegative integer"
        )
    return value


def _native_kernel_candidate_source(value: object, field: str) -> str:
    if value not in _NATIVE_KERNEL_CANDIDATE_SOURCES:
        raise ProtocolContractError(
            f"{field} is not a native-kernel candidate source"
        )
    return str(value)


def _validate_native_kernel_attempt_lifecycle(
    attempt: Mapping[str, object],
    *,
    active_process_count: int,
    process_group_reaped: bool,
) -> None:
    """Require the durable decision to match the reviewed process taxonomy."""

    reason = _nonempty(
        attempt["termination_reason"],
        "native kernel attempt termination_reason",
    )
    if reason not in _NATIVE_KERNEL_TERMINATION_REASONS:
        raise ProtocolContractError(
            "native kernel attempt termination reason is not reviewed"
        )
    returncode = attempt["returncode"]
    if reason in {"spawn_error", "cancelled_before_start"}:
        if returncode is not None:
            raise ProtocolContractError(
                "native kernel pre-spawn returncode must be null"
            )
    elif isinstance(returncode, bool) or not isinstance(returncode, int):
        raise ProtocolContractError(
            "native kernel attempt returncode must be an integer after spawn"
        )
    timed_out = attempt["timed_out"] is True
    cancelled = attempt["cancelled"] is True
    resource_exhausted = attempt["resource_exhausted"] is True
    lifecycle_flags = (timed_out, cancelled, resource_exhausted)
    flags_match = (
        (
            reason in _NATIVE_KERNEL_SAFE_COMPLETION_REASONS
            and lifecycle_flags == (False, False, False)
            and process_group_reaped
        )
        or (
            reason == "wall_clock_deadline"
            and lifecycle_flags == (True, False, False)
        )
        or (
            reason in {"cancelled", "cancelled_before_start"}
            and lifecycle_flags == (False, True, False)
        )
        or (
            reason == "resource_deadline"
            and not timed_out
            and cancelled is not resource_exhausted
        )
        or (
            reason in _NATIVE_KERNEL_PROCESS_ERROR_REASONS
            and lifecycle_flags == (False, False, False)
        )
        or (
            reason == "orphaned_process_group"
            and lifecycle_flags == (False, False, False)
            and not process_group_reaped
        )
    )
    if not flags_match:
        raise ProtocolContractError(
            "native kernel attempt termination reason disagrees with "
            "lifecycle flags"
        )
    process_accepted = (
        reason in _NATIVE_KERNEL_SAFE_COMPLETION_REASONS
        and returncode == 0
        and process_group_reaped
        and active_process_count == 0
    )
    if attempt["accepted"] is not process_accepted:
        raise ProtocolContractError(
            "native kernel attempt acceptance disagrees with its reviewed "
            "process outcome"
        )


def _validate_native_kernel_outer_attachments(
    data: Mapping[str, object],
    *,
    variant_id: str,
) -> bool:
    """Validate graph metadata attached after the kernel signs its receipt.

    The graph runner may attach a separately self-digested routing decision,
    and S1 may withhold authority from an otherwise accepted diagnostic
    receipt.  These fields remain covered by the enclosing StageRecord and
    CaseResult digests, but are deliberately outside the native process
    receipt's own self-digest.
    """

    if "routing_policy" in data:
        policy = _mapping(
            data["routing_policy"], "native kernel routing_policy"
        )
        decision_sha256 = _digest(
            policy.get("decision_sha256"),
            "native kernel routing_policy decision_sha256",
        )
        _nonempty(
            policy.get("schema"), "native kernel routing_policy schema"
        )
        _nonempty(
            policy.get("decision"), "native kernel routing_policy decision"
        )
        policy_body = {
            key: _thaw_bounded_json(value)
            for key, value in policy.items()
            if key != "decision_sha256"
        }
        if _record_digest(policy_body) != decision_sha256:
            raise ProtocolContractError(
                "native kernel routing-policy self-digest changed"
            )

    diagnostic_only = data.get("diagnostic_only")
    authority_withheld = data.get("authority_withheld")
    if diagnostic_only is None and authority_withheld is None:
        return False
    if (
        variant_id != "S1"
        or diagnostic_only is not True
        or authority_withheld is not True
    ):
        raise ProtocolContractError(
            "native kernel diagnostic authority attachment is invalid"
        )
    return True


def _validate_native_kernel_attempts(
    data: Mapping[str, object],
) -> bool:
    """Validate executed Lean evidence and return its selected decision."""

    missing = _NATIVE_KERNEL_EXECUTED_RECEIPT_FIELDS - set(data)
    if missing:
        raise ProtocolContractError(
            "executed native-kernel receipt is incomplete: "
            + ", ".join(sorted(missing))
        )
    for field in (
        "compiled_obligation_sha256",
        "obligation_sha256",
        "candidate_artifact_sha256",
        "source_sha256",
        "semantic_context_sha256",
        "command_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "candidate_attempts_sha256",
    ):
        _digest(data[field], f"native kernel {field}")
    _native_kernel_candidate_source(
        data["candidate_source"], "native kernel candidate_source"
    )
    semantic_artifacts = data["semantic_artifact_sha256s"]
    if not isinstance(semantic_artifacts, Sequence) or isinstance(
        semantic_artifacts, (str, bytes, bytearray)
    ):
        raise ProtocolContractError(
            "native kernel semantic_artifact_sha256s must be an array"
        )
    for value in semantic_artifacts:
        _digest(value, "native kernel semantic_artifact_sha256s[]")

    attempts_value = data["candidate_attempts"]
    if (
        not isinstance(attempts_value, Sequence)
        or isinstance(attempts_value, (str, bytes, bytearray))
        or not attempts_value
        or len(attempts_value) > len(StageName)
    ):
        raise ProtocolContractError(
            "native kernel candidate_attempts must be a bounded nonempty array"
        )
    attempts: list[dict[str, object]] = []
    for index, raw_attempt in enumerate(attempts_value):
        attempt = _mapping(
            raw_attempt, f"native kernel candidate_attempts[{index}]"
        )
        if set(attempt) != _NATIVE_KERNEL_ATTEMPT_FIELDS:
            raise ProtocolContractError(
                "native kernel candidate attempt has an invalid shape"
            )
        if (
            isinstance(attempt["attempt_index"], bool)
            or attempt["attempt_index"] != index
        ):
            raise ProtocolContractError(
                "native kernel candidate attempt index changed"
            )
        _native_kernel_candidate_source(
            attempt["candidate_source"],
            "native kernel attempt candidate_source",
        )
        for field in (
            "candidate_artifact_sha256",
            "source_sha256",
            "command_sha256",
            "stdout_sha256",
            "stderr_sha256",
            "attempt_sha256",
        ):
            _digest(
                attempt[field],
                f"native kernel attempt {field}",
            )
        for field in (
            "timed_out",
            "cancelled",
            "resource_exhausted",
            "process_group_reaped",
            "accepted",
        ):
            _bool(attempt[field], f"native kernel attempt {field}")
        active_process_count = _native_kernel_process_count(
            attempt["active_process_count"],
            "native kernel attempt active_process_count",
        )
        attempt_body = {
            key: _thaw_bounded_json(value)
            for key, value in attempt.items()
            if key != "attempt_sha256"
        }
        if _record_digest(attempt_body) != attempt["attempt_sha256"]:
            raise ProtocolContractError(
                "native kernel candidate attempt self-digest changed"
            )
        _validate_native_kernel_attempt_lifecycle(
            attempt,
            active_process_count=active_process_count,
            process_group_reaped=(
                attempt["process_group_reaped"] is True
            ),
        )
        attempts.append(
            {
                key: _thaw_bounded_json(value)
                for key, value in attempt.items()
            }
        )
    if _record_digest(attempts) != data["candidate_attempts_sha256"]:
        raise ProtocolContractError(
            "native kernel candidate-attempt collection changed"
        )
    if any(
        attempt["accepted"] is True
        for attempt in attempts[:-1]
    ):
        raise ProtocolContractError(
            "native kernel continued after an accepted candidate"
        )
    if any(
        attempt["timed_out"] is True
        or attempt["cancelled"] is True
        or attempt["resource_exhausted"] is True
        or attempt["process_group_reaped"] is not True
        or attempt["active_process_count"] != 0
        or attempt["termination_reason"]
        in _NATIVE_KERNEL_PROCESS_ERROR_REASONS
        for attempt in attempts[:-1]
    ):
        raise ProtocolContractError(
            "native kernel continued after an unsafe process outcome"
        )

    selected = _mapping(
        data["selected_attempt"], "native kernel selected_attempt"
    )
    if set(selected) != _NATIVE_KERNEL_SELECTED_ATTEMPT_FIELDS:
        raise ProtocolContractError(
            "native kernel selected attempt has an invalid shape"
        )
    last = attempts[-1]
    expected_selected = {
        key: last[key]
        for key in _NATIVE_KERNEL_SELECTED_ATTEMPT_FIELDS
    }
    if {
        key: _thaw_bounded_json(value)
        for key, value in selected.items()
    } != expected_selected:
        raise ProtocolContractError(
            "native kernel selected attempt changed"
        )
    selected_bindings = {
        "candidate_source": "candidate_source",
        "candidate_artifact_sha256": "candidate_artifact_sha256",
        "source_sha256": "source_sha256",
        "command_sha256": "command_sha256",
        "stdout_sha256": "stdout_sha256",
        "stderr_sha256": "stderr_sha256",
        "returncode": "returncode",
        "timed_out": "timed_out",
        "cancelled": "cancelled",
        "resource_exhausted": "resource_exhausted",
        "termination_reason": "termination_reason",
        "process_group_reaped": "process_group_reaped",
        "active_process_count": "active_process_count",
        "accepted": "accepted",
    }
    if any(
        data[receipt_field] != last[attempt_field]
        for receipt_field, attempt_field in selected_bindings.items()
    ):
        raise ProtocolContractError(
            "native kernel receipt differs from its selected attempt"
        )
    return selected["accepted"] is True


def validate_native_kernel_receipt(
    value: object,
    *,
    protocol_sha256: str,
    run_id: str,
    case_id: str,
    case_manifest_sha256: str,
    variant_id: str,
    split: Split,
    cache_mode: CacheMode,
    input_sha256: str,
    environment_sha256: str | None,
    stage_status: StageStatus,
    kernel_accepted: bool,
    kernel_receipt_sha256: str | None,
    consumed_artifact_sha256s: Sequence[str] | None = None,
    failure_code: FailureCode | None = None,
) -> bool:
    """Validate one canonical, source-bound native-kernel receipt.

    The return value is the authority decision carried by this receipt.  An
    S1 diagnostic rejection may bind a separately validated accepted receipt;
    callers that need that raw safety projection use
    :func:`validate_native_kernel_stage_receipt`.
    """

    data = _mapping(value, "native kernel receipt")
    if (
        data.get("schema") != NATIVE_KERNEL_RECEIPT_SCHEMA
        or data.get("independent") is not True
        or type(data.get("accepted")) is not bool
    ):
        raise ProtocolContractError(
            "kernel stage lacks an independent native receipt"
        )
    receipt_sha256 = _digest(
        data.get("receipt_sha256"), "native kernel receipt_sha256"
    )
    diagnostic_authority_withheld = (
        _validate_native_kernel_outer_attachments(
            data,
            variant_id=variant_id,
        )
    )
    body = {
        key: _thaw_bounded_json(value)
        for key, value in data.items()
        if key != "receipt_sha256"
        and key not in _NATIVE_KERNEL_OUTER_ATTACHMENT_FIELDS
    }
    if _record_digest(body) != receipt_sha256:
        # Immutable S1 evidence predates normalized diagnostic rejection
        # receipts: its runner attached these two flags after the native
        # process receipt was signed.  Accept only that exact, validated
        # compatibility shape; current negative receipts sign both fields.
        legacy_diagnostic_body = {
            key: value
            for key, value in body.items()
            if key not in {"diagnostic_only", "authority_withheld"}
        }
        if (
            not diagnostic_authority_withheld
            or data["accepted"] is not True
            or _record_digest(legacy_diagnostic_body) != receipt_sha256
        ):
            raise ProtocolContractError(
                "native-kernel receipt self-digest changed"
            )
    if not isinstance(split, Split) or not isinstance(cache_mode, CacheMode):
        raise ProtocolContractError(
            "native-kernel receipt split/cache binding is invalid"
        )
    if not isinstance(stage_status, StageStatus):
        raise ProtocolContractError(
            "native-kernel receipt stage status is invalid"
        )
    if failure_code is not None and not isinstance(
        failure_code, FailureCode
    ):
        raise ProtocolContractError(
            "native-kernel receipt failure code is invalid"
        )
    if (
        stage_status is StageStatus.SUCCESS
        and failure_code is not None
    ) or (
        stage_status is not StageStatus.SUCCESS
        and failure_code is None
    ):
        raise ProtocolContractError(
            "native-kernel stage status and failure code disagree"
        )
    _bool(kernel_accepted, "native kernel stage authority")
    expected_identity = {
        "protocol_sha256": protocol_sha256,
        "run_id": run_id,
        "case_id": case_id,
        "case_manifest_sha256": case_manifest_sha256,
        "variant_id": variant_id,
        "split": split.value,
        "cache_mode": cache_mode.value,
        "input_sha256": input_sha256,
        "environment_sha256": environment_sha256,
    }
    if any(
        data.get(field) != expected
        for field, expected in expected_identity.items()
    ):
        raise ProtocolContractError(
            "native-kernel receipt coordinate or source binding changed"
        )
    active_process_count = _native_kernel_process_count(
        data.get("active_process_count"),
        "native kernel active_process_count",
    )
    accepted = data["accepted"] is True
    executed = "candidate_attempts" in data
    consumed: tuple[str, ...] | None = None
    if consumed_artifact_sha256s is not None:
        if not isinstance(consumed_artifact_sha256s, Sequence) or isinstance(
            consumed_artifact_sha256s, (str, bytes, bytearray)
        ):
            raise ProtocolContractError(
                "native-kernel consumed-artifact binding is invalid"
            )
        consumed = tuple(
            _digest(
                item,
                "native kernel consumed_artifact_sha256s[]",
            )
            for item in consumed_artifact_sha256s
        )
    if accepted and not executed:
        raise ProtocolContractError(
            "accepted native-kernel receipt lacks executed Lean evidence"
        )
    if executed:
        selected_accepted = _validate_native_kernel_attempts(data)
        if selected_accepted is not accepted:
            raise ProtocolContractError(
                "native kernel decision differs from its selected attempt"
            )
        if consumed is None:
            raise ProtocolContractError(
                "executed native-kernel receipt lacks consumed-artifact binding"
            )
        if data["candidate_artifact_sha256"] not in consumed:
            raise ProtocolContractError(
                "native kernel candidate is not one of the consumed artifacts"
            )
    elif (
        accepted
        or not isinstance(data.get("reason"), str)
        or not str(data["reason"]).strip()
    ):
        raise ProtocolContractError(
            "pre-execution native-kernel rejection lacks a bounded reason"
        )
    if diagnostic_authority_withheld and not accepted:
        if (
            data.get("reason") != "diagnostic_only_authority_withheld"
            or data.get("diagnostic_kernel_accepted") is not True
        ):
            raise ProtocolContractError(
                "normalized S1 diagnostic rejection is incomplete"
            )
        diagnostic_receipt_sha256 = _digest(
            data.get("diagnostic_receipt_sha256"),
            "native kernel diagnostic_receipt_sha256",
        )
        diagnostic_receipt = _mapping(
            data.get("diagnostic_receipt"),
            "native kernel diagnostic_receipt",
        )
        if (
            diagnostic_receipt.get("receipt_sha256")
            != diagnostic_receipt_sha256
            or diagnostic_receipt.get("accepted") is not True
            or diagnostic_receipt.get("diagnostic_receipt") is not None
        ):
            raise ProtocolContractError(
                "normalized S1 diagnostic receipt binding is invalid"
            )
        if not validate_native_kernel_receipt(
            diagnostic_receipt,
            protocol_sha256=protocol_sha256,
            run_id=run_id,
            case_id=case_id,
            case_manifest_sha256=case_manifest_sha256,
            variant_id=variant_id,
            split=split,
            cache_mode=cache_mode,
            input_sha256=input_sha256,
            environment_sha256=environment_sha256,
            stage_status=stage_status,
            kernel_accepted=True,
            kernel_receipt_sha256=diagnostic_receipt_sha256,
            consumed_artifact_sha256s=consumed,
            failure_code=None,
        ):
            raise ProtocolContractError(
                "normalized S1 diagnostic receipt was not accepted"
            )
    if (
        not diagnostic_authority_withheld
        and kernel_accepted is not accepted
    ):
        raise ProtocolContractError(
            "kernel stage authority differs from its native receipt"
        )
    if diagnostic_authority_withheld and kernel_accepted:
        raise ProtocolContractError(
            "native kernel diagnostic receipt retained stage authority"
        )
    if accepted:
        if (
            stage_status is not StageStatus.SUCCESS
            or data["process_group_reaped"] is not True
            or active_process_count != 0
            or (
                diagnostic_authority_withheld
                and kernel_receipt_sha256 is not None
            )
            or (
                not diagnostic_authority_withheld
                and kernel_receipt_sha256 != receipt_sha256
            )
        ):
            raise ProtocolContractError(
                "accepted native-kernel receipt lacks stage authority"
            )
    elif executed:
        expected_failure_code = (
            FailureCode.ORPHANED_CHILD
            if (
                active_process_count
                or data["process_group_reaped"] is not True
            )
            else (
                FailureCode.OUT_OF_MEMORY
                if data["resource_exhausted"] is True
                else (
                    FailureCode.RESOURCE_LEASE_CANCELLATION
                    if (
                        data["timed_out"] is True
                        or data["cancelled"] is True
                    )
                    else (
                        FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
                        if (
                            data["termination_reason"]
                            in {"spawn_error", "monitor_error"}
                            or (
                                isinstance(data["returncode"], int)
                                and data["returncode"] < 0
                            )
                        )
                        else FailureCode.KERNEL_REJECTION
                    )
                )
            )
        )
        if (
            stage_status is not StageStatus.FAILED
            or failure_code is not expected_failure_code
            or kernel_receipt_sha256 is not None
        ):
            raise ProtocolContractError(
                "rejected native-kernel execution has invalid lifecycle "
                "failure authority"
            )
    elif active_process_count != 0:
        raise ProtocolContractError(
            "pre-execution native-kernel rejection left active processes"
        )
    elif (
        stage_status not in {StageStatus.SUCCESS, StageStatus.FAILED}
        or kernel_receipt_sha256 is not None
    ):
        raise ProtocolContractError(
            "rejected native-kernel receipt has invalid stage authority"
        )
    return accepted


def validate_native_kernel_stage_receipt(stage: StageRecord) -> bool:
    """Validate and return the raw source-bound kernel safety decision.

    Ordinarily this is the stage authority decision.  S1 is deliberately
    nonauthoritative, so its signed outer rejection returns the acceptance of
    the centrally revalidated nested diagnostic receipt instead.
    """

    if not isinstance(stage, StageRecord) or stage.stage is not StageName.KERNEL:
        raise ProtocolContractError(
            "native-kernel receipt validation requires a kernel stage"
        )
    consumed = stage.provenance.effective_identity.get(
        "consumed_artifact_sha256"
    )
    accepted = validate_native_kernel_receipt(
        stage.data,
        protocol_sha256=stage.protocol_sha256,
        run_id=stage.run_id,
        case_id=stage.case_id,
        case_manifest_sha256=stage.case_manifest_sha256,
        variant_id=stage.variant_id,
        split=stage.split,
        cache_mode=stage.cache_mode,
        input_sha256=stage.provenance.input_sha256,
        environment_sha256=stage.provenance.environment_sha256,
        stage_status=stage.status,
        kernel_accepted=stage.kernel_accepted,
        kernel_receipt_sha256=stage.kernel_receipt_sha256,
        consumed_artifact_sha256s=(
            consumed
            if isinstance(consumed, Sequence)
            and not isinstance(consumed, (str, bytes, bytearray))
            else None
        ),
        failure_code=stage.failure_code,
    )
    if accepted:
        return True
    if (
        isinstance(stage.data, Mapping)
        and stage.data.get("diagnostic_only") is True
        and stage.data.get("authority_withheld") is True
        and stage.data.get("diagnostic_kernel_accepted") is True
    ):
        # The low-level validator above has already recursively validated the
        # nested accepted receipt and its source/candidate bindings.
        return True
    return False


_STAGE_RESOURCE_LANES: Final[Mapping[StageName, ResourceLane]] = MappingProxyType(
    {
        StageName.COMPILER: ResourceLane.CPU,
        StageName.SPACY: ResourceLane.CPU,
        StageName.SYMAI: ResourceLane.MODEL,
        StageName.HAMMER: ResourceLane.SOLVER,
        StageName.LEANSTRAL: ResourceLane.MODEL,
        StageName.KERNEL: ResourceLane.KERNEL,
    }
)


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _is_recoverable_proof_attempt_failure(stage: StageRecord) -> bool:
    """Return whether ``stage`` is a non-authoritative failed proof attempt."""

    return (
        stage.stage in {StageName.HAMMER, StageName.LEANSTRAL}
        and stage.status is StageStatus.FAILED
        and stage.failure_code in RECOVERABLE_PROOF_ATTEMPT_FAILURE_CODES
    )


def _optional_mapping_member(
    value: Mapping[str, object],
    key: str,
    field: str,
) -> Mapping[str, object] | None:
    member = value.get(key)
    if member is None:
        return None
    return _mapping(member, field)


def _validate_hammer_stage_evidence(stage: StageRecord) -> str | None:
    """Validate cross-record joins in a serialized Hammer reconstruction.

    The adapter performs richer validation against native Hammer types.  This
    dependency-free check is deliberately repeated at the durable record
    boundary so a payload assembled without that adapter cannot join records
    from different requests, candidates, or environments.
    """

    if stage.stage is not StageName.HAMMER or not isinstance(stage.data, Mapping):
        return None
    if (
        stage.data.get("schema")
        != "ipfs-datasets.logic-pipeline-benchmark.hammer-evidence.v1"
    ):
        return None

    request = _mapping(stage.data.get("request"), "hammer.request")
    portfolio = _mapping(stage.data.get("portfolio"), "hammer.portfolio")
    candidate = _optional_mapping_member(
        stage.data, "proof_candidate", "hammer.proof_candidate"
    )
    reconstruction = _optional_mapping_member(
        stage.data, "reconstruction", "hammer.reconstruction"
    )
    environment = _optional_mapping_member(
        stage.data, "environment_lock", "hammer.environment_lock"
    )
    request_id = _nonempty(request.get("request_id"), "hammer.request.request_id")
    if portfolio.get("request_id") != request_id:
        raise ProtocolContractError(
            "Hammer portfolio and request identities do not match"
        )
    if candidate is not None and candidate.get("request_id") != request_id:
        raise ProtocolContractError(
            "Hammer candidate and request identities do not match"
        )
    if reconstruction is not None:
        if reconstruction.get("request_id") != request_id:
            raise ProtocolContractError(
                "Hammer reconstruction and request identities do not match"
            )
        if candidate is None or reconstruction.get("candidate_id") != candidate.get(
            "candidate_id"
        ):
            raise ProtocolContractError(
                "Hammer reconstruction and candidate identities do not match"
            )
        if environment is None or reconstruction.get(
            "environment_lock_id"
        ) != environment.get("lock_id"):
            raise ProtocolContractError(
                "Hammer reconstruction and environment identities do not match"
            )

    evidence_id = _digest(stage.data.get("evidence_id"), "hammer.evidence_id")
    evidence_payload = {
        key: _thaw_bounded_json(value)
        for key, value in stage.data.items()
        if key != "evidence_id"
    }
    if evidence_id != _record_digest(evidence_payload):
        raise ProtocolContractError("Hammer evidence_id does not match its payload")
    if reconstruction is None:
        return None
    return _record_digest(_thaw_bounded_json(reconstruction))


@dataclass(frozen=True, slots=True)
class CaseResultReceipt:
    """Content-addressed projection of every result trust dependency.

    The full stage records remain embedded in :class:`CaseResultRecord`.  This
    receipt makes their security-relevant joins explicit and independently
    digestible: route order, stage/provenance/telemetry digests, resource
    lanes, reconstruction, environment identity, and the terminal kernel
    outcome.
    """

    schema: str
    protocol_sha256: str
    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str
    split: Split
    cache_mode: CacheMode
    route: tuple[StageName, ...]
    stage_digests: tuple[str, ...]
    provenance_digests: tuple[str, ...]
    telemetry_digests: tuple[str, ...]
    resource_lanes: tuple[ResourceLane, ...]
    environment_sha256: str | None
    reconstruction_sha256: str | None
    kernel_stage_digest: str | None
    kernel_accepted: bool
    kernel_receipt_sha256: str | None

    def __post_init__(self) -> None:
        if self.schema != CASE_RESULT_RECEIPT_SCHEMA:
            raise ProtocolContractError("unsupported case-result receipt schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        _safe_id(self.run_id, "run_id")
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in _REQUIRED_VARIANTS:
            raise ProtocolContractError(
                f"variant_id is not registered: {self.variant_id!r}"
            )
        if not isinstance(self.split, Split) or not isinstance(
            self.cache_mode, CacheMode
        ):
            raise ProtocolContractError(
                "receipt split and cache_mode must use protocol enums"
            )
        for field in (
            "route",
            "stage_digests",
            "provenance_digests",
            "telemetry_digests",
            "resource_lanes",
        ):
            if not isinstance(getattr(self, field), tuple):
                raise ProtocolContractError(f"receipt {field} must be a tuple")
        if not self.route or len(self.route) > len(StageName):
            raise ProtocolContractError("receipt route has an invalid length")
        if any(not isinstance(stage, StageName) for stage in self.route):
            raise ProtocolContractError("receipt route must contain stage names")
        positions = tuple(tuple(StageName).index(stage) for stage in self.route)
        if tuple(sorted(positions)) != positions or len(set(self.route)) != len(
            self.route
        ):
            raise ProtocolContractError(
                "receipt route must be a unique canonical-order subsequence"
            )
        if StageName.KERNEL in self.route and self.route[-1] is not StageName.KERNEL:
            raise ProtocolContractError("kernel must be the terminal route stage")
        size = len(self.route)
        for field in (
            "stage_digests",
            "provenance_digests",
            "telemetry_digests",
            "resource_lanes",
        ):
            if len(getattr(self, field)) != size:
                raise ProtocolContractError(
                    f"receipt {field} must align with every route stage"
                )
        for field in (
            "stage_digests",
            "provenance_digests",
            "telemetry_digests",
        ):
            for value in getattr(self, field):
                _digest(value, f"{field}[]")
        for index, lane in enumerate(self.resource_lanes):
            if not isinstance(lane, ResourceLane):
                raise ProtocolContractError(
                    "receipt resource_lanes must contain ResourceLane values"
                )
            if lane is not _STAGE_RESOURCE_LANES[self.route[index]]:
                raise ProtocolContractError(
                    f"{self.route[index].value} receipt uses the wrong resource lane"
                )
        if self.environment_sha256 is not None:
            _digest(self.environment_sha256, "environment_sha256")
        if self.reconstruction_sha256 is not None:
            _digest(self.reconstruction_sha256, "reconstruction_sha256")
        _bool(self.kernel_accepted, "kernel_accepted")
        has_kernel = self.route[-1] is StageName.KERNEL
        if has_kernel:
            if self.kernel_stage_digest is None:
                raise ProtocolContractError(
                    "terminal kernel route requires its stage digest"
                )
            _digest(self.kernel_stage_digest, "kernel_stage_digest")
            if self.kernel_stage_digest != self.stage_digests[-1]:
                raise ProtocolContractError(
                    "kernel stage digest does not match the terminal route stage"
                )
        elif self.kernel_stage_digest is not None:
            raise ProtocolContractError(
                "kernel stage digest requires a terminal kernel route"
            )
        if self.kernel_accepted:
            if not has_kernel or self.kernel_receipt_sha256 is None:
                raise ProtocolContractError(
                    "accepted receipt requires a terminal kernel receipt"
                )
            _digest(self.kernel_receipt_sha256, "kernel_receipt_sha256")
        elif self.kernel_receipt_sha256 is not None:
            raise ProtocolContractError(
                "an unaccepted kernel outcome cannot carry a receipt"
            )

    @classmethod
    def from_stages(cls, stages: tuple[StageRecord, ...]) -> Self:
        if not stages:
            raise ProtocolContractError("cannot create a receipt without stages")
        first = stages[0]
        environments = {
            stage.provenance.environment_sha256
            for stage in stages
            if stage.provenance.environment_sha256 is not None
        }
        environment = next(iter(environments)) if len(environments) == 1 else None
        reconstruction_digests = tuple(
            digest
            for stage in stages
            if (digest := _validate_hammer_stage_evidence(stage)) is not None
        )
        if len(reconstruction_digests) > 1:
            raise ProtocolContractError(
                "case result contains multiple reconstruction records"
            )
        kernel = stages[-1] if stages[-1].stage is StageName.KERNEL else None
        accepted = bool(kernel is not None and kernel.kernel_accepted)
        return cls(
            schema=CASE_RESULT_RECEIPT_SCHEMA,
            protocol_sha256=first.protocol_sha256,
            run_id=first.run_id,
            case_id=first.case_id,
            case_manifest_sha256=first.case_manifest_sha256,
            variant_id=first.variant_id,
            split=first.split,
            cache_mode=first.cache_mode,
            route=tuple(stage.stage for stage in stages),
            stage_digests=tuple(stage.digest for stage in stages),
            provenance_digests=tuple(
                _record_digest(stage.provenance.to_dict()) for stage in stages
            ),
            telemetry_digests=tuple(stage.telemetry.digest for stage in stages),
            resource_lanes=tuple(
                stage.telemetry.resource_lane for stage in stages
            ),
            environment_sha256=environment,
            reconstruction_sha256=(
                reconstruction_digests[0] if reconstruction_digests else None
            ),
            kernel_stage_digest=kernel.digest if kernel else None,
            kernel_accepted=accepted,
            kernel_receipt_sha256=(
                kernel.kernel_receipt_sha256 if accepted and kernel else None
            ),
        )

    @property
    def digest(self) -> str:
        return _record_digest(self.to_dict())

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
            "route": [stage.value for stage in self.route],
            "stage_digests": list(self.stage_digests),
            "provenance_digests": list(self.provenance_digests),
            "telemetry_digests": list(self.telemetry_digests),
            "resource_lanes": [lane.value for lane in self.resource_lanes],
            "environment_sha256": self.environment_sha256,
            "reconstruction_sha256": self.reconstruction_sha256,
            "kernel_stage_digest": self.kernel_stage_digest,
            "kernel_accepted": self.kernel_accepted,
            "kernel_receipt_sha256": self.kernel_receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "case_result_receipt")
        _exact_keys(data, set(cls.__dataclass_fields__), "case_result_receipt")
        arrays: dict[str, list[object]] = {}
        for field in (
            "route",
            "stage_digests",
            "provenance_digests",
            "telemetry_digests",
            "resource_lanes",
        ):
            member = data[field]
            if not isinstance(member, list):
                raise ProtocolContractError(
                    f"case_result_receipt.{field} must be an array"
                )
            arrays[field] = member
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
            route=tuple(
                _enum(StageName, item, "route[]") for item in arrays["route"]
            ),  # type: ignore[arg-type]
            stage_digests=tuple(
                _digest(item, "stage_digests[]")
                for item in arrays["stage_digests"]
            ),
            provenance_digests=tuple(
                _digest(item, "provenance_digests[]")
                for item in arrays["provenance_digests"]
            ),
            telemetry_digests=tuple(
                _digest(item, "telemetry_digests[]")
                for item in arrays["telemetry_digests"]
            ),
            resource_lanes=tuple(
                _enum(ResourceLane, item, "resource_lanes[]")
                for item in arrays["resource_lanes"]
            ),  # type: ignore[arg-type]
            environment_sha256=(
                None
                if data["environment_sha256"] is None
                else _digest(data["environment_sha256"], "environment_sha256")
            ),
            reconstruction_sha256=(
                None
                if data["reconstruction_sha256"] is None
                else _digest(
                    data["reconstruction_sha256"], "reconstruction_sha256"
                )
            ),
            kernel_stage_digest=(
                None
                if data["kernel_stage_digest"] is None
                else _digest(data["kernel_stage_digest"], "kernel_stage_digest")
            ),
            kernel_accepted=_bool(data["kernel_accepted"], "kernel_accepted"),
            kernel_receipt_sha256=(
                None
                if data["kernel_receipt_sha256"] is None
                else _digest(
                    data["kernel_receipt_sha256"], "kernel_receipt_sha256"
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class CaseResultRecord:
    """Case-level result bound to every stage record and kernel authority."""

    schema: str
    protocol_sha256: str
    run_id: str
    case_id: str
    case_manifest_sha256: str
    variant_id: str
    split: Split
    cache_mode: CacheMode
    stages: tuple[StageRecord, ...]
    status: OutcomeStatus
    verification_authority: VerificationAuthority = VerificationAuthority.NONE
    kernel_accepted: bool = False
    kernel_receipt_sha256: str | None = None
    failure_code: FailureCode | None = None
    failure_detail: str | None = None
    receipt: CaseResultReceipt | None = None

    def __post_init__(self) -> None:
        if self.schema != CASE_RESULT_SCHEMA:
            raise ProtocolContractError("unsupported case-result schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        if _FROZEN_PROTOCOL_SHA256 is not None and self.protocol_sha256 != _FROZEN_PROTOCOL_SHA256:
            raise ProtocolContractError("case result does not bind frozen protocol revision 1")
        _safe_id(self.run_id, "run_id")
        _safe_id(self.case_id, "case_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if self.variant_id not in _REQUIRED_VARIANTS:
            raise ProtocolContractError(f"variant_id is not registered: {self.variant_id!r}")
        if not isinstance(self.split, Split) or not isinstance(self.cache_mode, CacheMode):
            raise ProtocolContractError("split and cache_mode must use protocol enums")
        if not isinstance(self.stages, tuple) or not self.stages:
            raise ProtocolContractError("a case result requires stage records")
        if len(self.stages) > len(StageName):
            raise ProtocolContractError("case result contains too many stages")
        names: set[StageName] = set()
        input_sha256: str | None = None
        environments: set[str | None] = set()
        positions: list[int] = []
        for stage in self.stages:
            if not isinstance(stage, StageRecord):
                raise ProtocolContractError("stages must contain StageRecord values")
            if stage.stage in names:
                raise ProtocolContractError("case result contains duplicate stages")
            names.add(stage.stage)
            positions.append(tuple(StageName).index(stage.stage))
            for field in ("protocol_sha256", "run_id", "case_id", "case_manifest_sha256", "variant_id", "split", "cache_mode"):
                if getattr(stage, field) != getattr(self, field):
                    raise ProtocolContractError("stage and case identities do not match")
            if stage.telemetry.resource_lane is not _STAGE_RESOURCE_LANES[stage.stage]:
                raise ProtocolContractError(
                    f"{stage.stage.value} stage uses the wrong resource lane"
                )
            if input_sha256 is None:
                input_sha256 = stage.provenance.input_sha256
            environments.add(stage.provenance.environment_sha256)
        if positions != sorted(positions):
            raise ProtocolContractError(
                "case result route must follow canonical stage order"
            )
        if StageName.KERNEL in names and self.stages[-1].stage is not StageName.KERNEL:
            raise ProtocolContractError("kernel must be the terminal route stage")
        if not isinstance(self.status, OutcomeStatus):
            raise ProtocolContractError("status must be an OutcomeStatus")
        if not isinstance(self.verification_authority, VerificationAuthority):
            raise ProtocolContractError("verification_authority must be a VerificationAuthority")
        _bool(self.kernel_accepted, "kernel_accepted")
        kernel = next((item for item in self.stages if item.stage is StageName.KERNEL), None)
        has_native_kernel_receipt = (
            kernel is not None
            and isinstance(kernel.data, Mapping)
            and kernel.data.get("schema") == NATIVE_KERNEL_RECEIPT_SCHEMA
        )
        if has_native_kernel_receipt:
            assert kernel is not None
            graph_invoked = kernel.provenance.effective_identity.get(
                "graph_invoked"
            )
            if graph_invoked is not True:
                raise ProtocolContractError(
                    "native kernel receipt requires an explicit graph invocation"
                )
            validate_native_kernel_stage_receipt(kernel)
        elif kernel is not None and kernel.kernel_accepted:
            graph_invoked = kernel.provenance.effective_identity.get(
                "graph_invoked"
            )
            if graph_invoked is False:
                raise ProtocolContractError(
                    "kernel authority cannot come from a suppressed graph stage"
                )
            if graph_invoked is not None and type(graph_invoked) is not bool:
                raise ProtocolContractError(
                    "kernel graph invocation marker must be boolean"
                )
        blocking_stage_failure = next(
            (
                item
                for item in self.stages
                if item.status is not StageStatus.SUCCESS
                and not _is_recoverable_proof_attempt_failure(item)
            ),
            None,
        )
        if self.status is OutcomeStatus.VERIFIED:
            if (
                blocking_stage_failure is not None
                or kernel is None
                or not kernel.kernel_accepted
            ):
                raise ProtocolContractError(
                    "verified case results require kernel acceptance without "
                    "a blocking stage failure"
                )
            expected_upstream: tuple[str, ...] = ()
            for stage in self.stages:
                if stage.provenance.upstream_stage_digests != expected_upstream:
                    raise ProtocolContractError(
                        "verified case result has a broken upstream stage digest chain"
                    )
                if stage.provenance.input_sha256 != input_sha256:
                    raise ProtocolContractError(
                        "verified case result mixes stage input identities"
                    )
                expected_upstream = (*expected_upstream, stage.digest)
            if None in environments or len(environments) != 1:
                raise ProtocolContractError(
                    "verified case results require one coherent environment identity"
                )
            if self.verification_authority is not VerificationAuthority.NATIVE_KERNEL:
                raise ProtocolContractError("verified case results require native-kernel authority")
            if not self.kernel_accepted or self.kernel_receipt_sha256 is None:
                raise ProtocolContractError("verified case results require a kernel receipt")
            _digest(self.kernel_receipt_sha256, "kernel_receipt_sha256")
            if self.kernel_receipt_sha256 != kernel.kernel_receipt_sha256:
                raise ProtocolContractError("case receipt does not match kernel stage receipt")
            if self.failure_code is not None:
                raise ProtocolContractError("verified case results cannot carry failures")
        else:
            if self.kernel_accepted or self.kernel_receipt_sha256 is not None:
                raise ProtocolContractError("non-verified case results cannot claim kernel acceptance")
            if self.failure_detail is not None:
                _nonempty(self.failure_detail, "failure_detail")
        if self.failure_code is not None and not isinstance(self.failure_code, FailureCode):
            raise ProtocolContractError("failure_code must be a FailureCode")
        if self.status in {OutcomeStatus.UNAVAILABLE, OutcomeStatus.EXCLUDED}:
            if self.failure_code not in EXCLUSION_FAILURE_CODES:
                raise ProtocolContractError("unavailable/excluded case results require an exclusion code")
        if self.status is OutcomeStatus.INFRASTRUCTURE_FAILURE:
            if self.failure_code not in INFRASTRUCTURE_FAILURE_CODES:
                raise ProtocolContractError("infrastructure case results require an infrastructure code")
            _nonempty(self.failure_detail, "failure_detail")
        if self.status in {OutcomeStatus.NOT_VERIFIED, OutcomeStatus.REJECTED}:
            if self.failure_code in EXCLUSION_FAILURE_CODES:
                raise ProtocolContractError("an exclusion code cannot hide a logical case result")
        calculated_receipt = CaseResultReceipt.from_stages(self.stages)
        if self.receipt is None:
            object.__setattr__(self, "receipt", calculated_receipt)
        elif not isinstance(self.receipt, CaseResultReceipt):
            raise ProtocolContractError("receipt must be a CaseResultReceipt")
        elif self.receipt != calculated_receipt:
            raise ProtocolContractError(
                "case-result receipt does not match its embedded stage records"
            )
        if self.status is OutcomeStatus.VERIFIED and (
            self.receipt.kernel_accepted != self.kernel_accepted
            or self.receipt.kernel_receipt_sha256 != self.kernel_receipt_sha256
        ):
            raise ProtocolContractError(
                "case and provenance-receipt kernel outcomes do not match"
            )

    @classmethod
    def from_stages(cls, stages: tuple[StageRecord, ...] | list[StageRecord]) -> Self:
        records = tuple(stages)
        if not records:
            raise ProtocolContractError("cannot build a case result without stages")
        first = records[0]
        unavailable = next(
            (
                item
                for item in records
                if item.status is StageStatus.UNAVAILABLE
            ),
            None,
        )
        failed = tuple(
            item
            for item in records
            if item.status in {StageStatus.FAILED, StageStatus.SKIPPED}
        )
        immediate_stop = next(
            (
                item
                for item in failed
                if item.failure_code in IMMEDIATE_STOP_CODES
            ),
            None,
        )
        infrastructure_failure = next(
            (
                item
                for item in failed
                if item.failure_code in INFRASTRUCTURE_FAILURE_CODES
            ),
            None,
        )
        blocking_failure = next(
            (
                item
                for item in failed
                if not _is_recoverable_proof_attempt_failure(item)
            ),
            None,
        )
        recovered_candidate_failure = next(
            (
                item
                for item in failed
                if _is_recoverable_proof_attempt_failure(item)
            ),
            None,
        )
        kernel = next((item for item in records if item.stage is StageName.KERNEL), None)
        terminal_failure = (
            immediate_stop
            or infrastructure_failure
            or unavailable
            or blocking_failure
        )
        if terminal_failure is not None:
            if terminal_failure.status is StageStatus.UNAVAILABLE:
                status = OutcomeStatus.UNAVAILABLE
            elif terminal_failure.failure_code in INFRASTRUCTURE_FAILURE_CODES:
                status = OutcomeStatus.INFRASTRUCTURE_FAILURE
            elif terminal_failure.failure_code in EXCLUSION_FAILURE_CODES:
                status = OutcomeStatus.EXCLUDED
            else:
                status = OutcomeStatus.REJECTED
            failure_code = terminal_failure.failure_code
            detail = terminal_failure.failure_detail
        elif kernel is not None and kernel.kernel_accepted:
            status = OutcomeStatus.VERIFIED
            failure_code = None
            detail = None
        elif recovered_candidate_failure is not None:
            status = OutcomeStatus.REJECTED
            failure_code = recovered_candidate_failure.failure_code
            detail = recovered_candidate_failure.failure_detail
        else:
            status = OutcomeStatus.NOT_VERIFIED
            failure_code = None
            detail = None
        return cls(
            schema=CASE_RESULT_SCHEMA,
            protocol_sha256=first.protocol_sha256,
            run_id=first.run_id,
            case_id=first.case_id,
            case_manifest_sha256=first.case_manifest_sha256,
            variant_id=first.variant_id,
            split=first.split,
            cache_mode=first.cache_mode,
            stages=records,
            status=status,
            verification_authority=(VerificationAuthority.NATIVE_KERNEL if status is OutcomeStatus.VERIFIED else VerificationAuthority.NONE),
            kernel_accepted=bool(status is OutcomeStatus.VERIFIED),
            kernel_receipt_sha256=(None if kernel is None else kernel.kernel_receipt_sha256) if status is OutcomeStatus.VERIFIED else None,
            failure_code=failure_code,
            failure_detail=detail,
            receipt=None,
        )

    @property
    def stage_digests(self) -> tuple[str, ...]:
        return tuple(stage.digest for stage in self.stages)

    @property
    def recovered_failures(self) -> tuple[StageRecord, ...]:
        """Proof-attempt failures recovered by terminal kernel acceptance."""

        if self.status is not OutcomeStatus.VERIFIED:
            return ()
        return tuple(
            stage
            for stage in self.stages
            if _is_recoverable_proof_attempt_failure(stage)
        )

    @property
    def recovered_failure_codes(self) -> tuple[FailureCode, ...]:
        """Stable reliability projection of recovered proof-attempt failures."""

        return tuple(
            stage.failure_code
            for stage in self.recovered_failures
            if stage.failure_code is not None
        )

    @property
    def terminal_kernel_accepted(self) -> bool:
        """Return raw terminal acceptance independently of top-level status.

        A legacy result may retain an accepted native-kernel stage while an
        earlier blocking failure prevents the case-level outcome from claiming
        verification.  Safety controls must still see that raw acceptance.
        """

        kernel = next(
            (
                stage
                for stage in self.stages
                if stage.stage is StageName.KERNEL
            ),
            None,
        )
        if kernel is None:
            return False
        graph_invoked = kernel.provenance.effective_identity.get(
            "graph_invoked"
        )
        if graph_invoked is False:
            return False
        if graph_invoked is True:
            return validate_native_kernel_stage_receipt(kernel)
        # Dependency-free protocol fixtures predate graph receipts. Persisted
        # ablation evidence is graph-marked and always takes the strict path.
        return kernel.kernel_accepted

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    @property
    def provenance_receipt_sha256(self) -> str:
        """Return the content address of the explicit provenance receipt."""

        if self.receipt is None:  # pragma: no cover - guarded by __post_init__
            raise ProtocolContractError("case result has no provenance receipt")
        return self.receipt.digest

    def validate_provenance(
        self, *, expected_environment_sha256: str | None = None
    ) -> None:
        """Revalidate this result and, when supplied, its pinned environment."""

        restored = type(self).from_dict(self.to_dict())
        if restored.digest != self.digest:
            raise ProtocolContractError(
                "case result changed during canonical provenance validation"
            )
        expected_upstream: tuple[str, ...] = ()
        expected_input = self.stages[0].provenance.input_sha256
        for stage in self.stages:
            if stage.provenance.upstream_stage_digests != expected_upstream:
                raise ProtocolContractError(
                    "case result has a broken upstream stage digest chain"
                )
            if stage.provenance.input_sha256 != expected_input:
                raise ProtocolContractError(
                    "case result mixes stage input identities"
                )
            expected_upstream = (*expected_upstream, stage.digest)
        kernel = next(
            (
                stage
                for stage in self.stages
                if stage.stage is StageName.KERNEL
            ),
            None,
        )
        if kernel is not None:
            graph_invoked = kernel.provenance.effective_identity.get(
                "graph_invoked"
            )
            has_native_receipt = (
                isinstance(kernel.data, Mapping)
                and kernel.data.get("schema")
                == NATIVE_KERNEL_RECEIPT_SCHEMA
            )
            if graph_invoked is True and (
                kernel.kernel_accepted or has_native_receipt
            ):
                validate_native_kernel_stage_receipt(kernel)
            elif graph_invoked is False and (
                kernel.kernel_accepted or has_native_receipt
            ):
                raise ProtocolContractError(
                    "suppressed kernel stage contains native receipt authority"
                )
            elif graph_invoked is not None and type(graph_invoked) is not bool:
                raise ProtocolContractError(
                    "kernel graph invocation marker must be boolean"
                )
            elif graph_invoked is None and has_native_receipt:
                raise ProtocolContractError(
                    "native kernel receipt lacks an explicit graph invocation"
                )
        if expected_environment_sha256 is not None:
            expected = _digest(
                expected_environment_sha256, "expected_environment_sha256"
            )
            if (
                self.status is OutcomeStatus.VERIFIED
                and self.receipt is not None
                and self.receipt.environment_sha256 != expected
            ):
                raise ProtocolContractError(
                    "verified case result binds a stale environment identity"
                )

    def to_outcome(self, *, invalid_control: bool = False) -> OutcomeRecord:
        return OutcomeRecord(
            schema=OUTCOME_RECORD_SCHEMA,
            protocol_sha256=self.protocol_sha256,
            run_id=self.run_id,
            case_id=self.case_id,
            case_manifest_sha256=self.case_manifest_sha256,
            variant_id=self.variant_id,
            split=self.split,
            cache_mode=self.cache_mode,
            status=self.status,
            invalid_control=invalid_control,
            verification_authority=self.verification_authority,
            kernel_accepted=self.kernel_accepted,
            kernel_receipt_sha256=self.kernel_receipt_sha256,
            failure_code=self.failure_code,
            failure_detail=self.failure_detail,
        )

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
            "stages": [stage.to_dict() for stage in self.stages],
            "status": self.status.value,
            "verification_authority": self.verification_authority.value,
            "kernel_accepted": self.kernel_accepted,
            "kernel_receipt_sha256": self.kernel_receipt_sha256,
            "failure_code": None if self.failure_code is None else self.failure_code.value,
            "failure_detail": self.failure_detail,
            "receipt": (
                None if self.receipt is None else self.receipt.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "case_result")
        _exact_keys(data, set(cls.__dataclass_fields__) - {"stage_digests"}, "case_result")
        stages = data["stages"]
        if not isinstance(stages, list):
            raise ProtocolContractError("case_result.stages must be an array")
        failure_code = data["failure_code"]
        result = cls(
            schema=_nonempty(data["schema"], "schema"),
            protocol_sha256=_digest(data["protocol_sha256"], "protocol_sha256"),
            run_id=_safe_id(data["run_id"], "run_id"),
            case_id=_safe_id(data["case_id"], "case_id"),
            case_manifest_sha256=_digest(data["case_manifest_sha256"], "case_manifest_sha256"),
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            split=_enum(Split, data["split"], "split"),  # type: ignore[arg-type]
            cache_mode=_enum(CacheMode, data["cache_mode"], "cache_mode"),  # type: ignore[arg-type]
            stages=tuple(StageRecord.from_dict(item) for item in stages),
            status=_enum(OutcomeStatus, data["status"], "status"),  # type: ignore[arg-type]
            verification_authority=_enum(VerificationAuthority, data["verification_authority"], "verification_authority"),  # type: ignore[arg-type]
            kernel_accepted=_bool(data["kernel_accepted"], "kernel_accepted"),
            kernel_receipt_sha256=(None if data["kernel_receipt_sha256"] is None else _digest(data["kernel_receipt_sha256"], "kernel_receipt_sha256")),
            failure_code=(None if failure_code is None else _enum(FailureCode, failure_code, "failure_code")),  # type: ignore[arg-type]
            failure_detail=(None if data["failure_detail"] is None else _nonempty(data["failure_detail"], "failure_detail")),
            receipt=(
                None
                if data["receipt"] is None
                else CaseResultReceipt.from_dict(data["receipt"])
            ),
        )
        if len(canonical_json(result.to_dict()).encode("utf-8")) > _MAX_CASE_RESULT_BYTES:
            raise ProtocolContractError("case result exceeds the encoded size bound")
        return result


def HSSLEV0306C18() -> str:
    """Return AST-verifiable evidence for the versioned adapter objective."""

    return "versioned stage adapters and deterministic telemetry"


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
    "CAUSAL_PROOF_CANDIDATE_SOURCES_V2",
    "CAUSAL_PROOF_COMPILER_STATES_V2",
    "CAUSAL_PROOF_LEANSTRAL_FAILURE_CODES_V2",
    "CAUSAL_PROOF_PARENT_PROTOCOL_SHA256_V1",
    "CAUSAL_PROOF_PARENT_SEMANTIC_PROTOCOL_CID_V2",
    "CAUSAL_PROOF_PROTOCOL_ID_V2",
    "CAUSAL_PROOF_PROTOCOL_SCHEMA_V2",
    "CAUSAL_PROOF_PROTOCOL_V2",
    "CAUSAL_PROOF_PROTOCOL_V2_CID",
    "CAUSAL_PROOF_PROTOCOL_VERSION_V2",
    "CAUSAL_PROOF_RESCUE_POPULATION_SCHEMA_V2",
    "CAUSAL_PROOF_RESCUE_POPULATION_V2_CID",
    "CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA",
    "CAUSAL_PROOF_SELECTION_RECEIPT_SCHEMA_V2",
    "CAUSAL_PROOF_SELECTION_SPEC_SCHEMA_V2",
    "CAUSAL_PROOF_SELECTION_SPEC_V2_CID",
    "CAUSAL_PROOF_VARIANT_PROFILE_SCHEMA_V2",
    "CAUSAL_PROOF_VARIANT_PROFILE_V2_CID",
    "CAUSAL_PROOF_ZERO_CREDIT_REASONS_V2",
    "CASE_RESULT_SCHEMA",
    "CASE_RESULT_RECEIPT_SCHEMA",
    "CaseResultRecord",
    "CaseResultReceipt",
    "CacheMode",
    "CacheScope",
    "CandidateGateObservation",
    "DEFAULT_PROTOCOL",
    "DEFAULT_PROTOCOL_SHA256",
    "EXCLUSION_FAILURE_CODES",
    "FailureCode",
    "GateDecision",
    "GateStatus",
    "HSSLEV0306C18",
    "HSSLEV0357C0D",
    "HSSLEV0103C72",
    "HSSLEV2108F34",
    "HoldoutRules",
    "HypothesisSpec",
    "IMMEDIATE_STOP_CODES",
    "INFRASTRUCTURE_FAILURE_CODES",
    "MaterialityThresholds",
    "MetricCategory",
    "MetricDirection",
    "MetricSpec",
    "NATIVE_KERNEL_RECEIPT_SCHEMA",
    "OUTCOME_RECORD_SCHEMA",
    "OutcomeRecord",
    "OutcomeStatus",
    "PROTOCOL_ID",
    "PROTOCOL_RECORD_SCHEMA",
    "PROTOCOL_SCHEMA",
    "PROTOCOL_VERSION",
    "ProtocolContractError",
    "ProtocolRecord",
    "RECOVERABLE_PROOF_ATTEMPT_FAILURE_CODES",
    "ResourceLane",
    "RUN_CONTRACT_SCHEMA",
    "RunContract",
    "SafetyInvariants",
    "SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2",
    "SEMANTIC_CALIBRATION_CASE_COUNT_V2",
    "SEMANTIC_CALIBRATION_CASES_PER_PRODUCER_V2",
    "SEMANTIC_CALIBRATION_COORDINATE_COUNT_V2",
    "SEMANTIC_CALIBRATION_METRIC_SPEC_SCHEMA_V2",
    "SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID",
    "SEMANTIC_CALIBRATION_ROUTE_MANIFEST_SCHEMA_V2",
    "SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID",
    "SEMANTIC_FAILURE_CODES_V2",
    "SEMANTIC_FAILURE_SCHEMA_V2",
    "SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2",
    "SEMANTIC_NORMALIZATION_V2_CID",
    "SEMANTIC_PARENT_PROTOCOL_SHA256_V1",
    "SEMANTIC_PARENT_VARIANT_REGISTRY_SHA256_V1",
    "SEMANTIC_PRODUCER_IDS_V2",
    "SEMANTIC_PRODUCER_REGISTRY_SCHEMA_V2",
    "SEMANTIC_PRODUCER_REGISTRY_V2_CID",
    "SEMANTIC_PROJECTION_CLASSES_V2",
    "SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2",
    "SEMANTIC_PROJECTION_SCHEMA_V2",
    "SEMANTIC_PROJECTION_SCHEMA_V2_CID",
    "SEMANTIC_PROMPT_INSTRUCTION_V2",
    "SEMANTIC_PROMPT_SCHEMA_V2",
    "SEMANTIC_PROMPT_V2_CID",
    "SEMANTIC_PROTOCOL_ID_V2",
    "SEMANTIC_PROTOCOL_SCHEMA_V2",
    "SEMANTIC_PROTOCOL_VERSION_V2",
    "SEMANTIC_PROTOCOL_V2",
    "SEMANTIC_PROTOCOL_V2_CID",
    "SEMANTIC_RESPONSE_SCHEMA_V2",
    "SEMANTIC_RESPONSE_SCHEMA_V2_CID",
    "SEMANTIC_REVIEWED_TARGET_SOURCE_SCHEMA_V2",
    "SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID",
    "SEMANTIC_WILSON_CONFIDENCE_MILLIONTHS_V2",
    "SEMANTIC_WILSON_LOWER_BOUND_MIN_MILLIONTHS_V2",
    "SemanticProjection",
    "SemanticProtocolSpec",
    "CausalProofProtocolSpec",
    "STAGE_PROVENANCE_SCHEMA",
    "STAGE_RECORD_SCHEMA",
    "StageName",
    "StageProvenance",
    "StageRecord",
    "StageStatus",
    "Split",
    "StopCondition",
    "TELEMETRY_SCHEMA",
    "TelemetryRecord",
    "VariantSpec",
    "VerificationAuthority",
    "build_default_protocol",
    "canonical_json",
    "canonical_protocol_json",
    "causal_proof_rescue_population_policy_v2",
    "causal_proof_selection_spec_v2",
    "causal_proof_variant_profile_v2",
    "evaluate_candidate_gate",
    "normalize_semantic_term",
    "protocol_sha256",
    "semantic_calibration_metric_spec_v2",
    "semantic_calibration_route_manifest_v2",
    "semantic_normalization_spec_v2",
    "semantic_reviewed_target_source_v2",
    "semantic_producer_registry_v2",
    "semantic_projection_json_schema_v2",
    "semantic_prompt_spec_v2",
    "semantic_response_json_schema_v2",
    "validate_paired_outcomes",
    "validate_native_kernel_receipt",
    "validate_native_kernel_stage_receipt",
    "validate_causal_proof_selection_receipt",
]
