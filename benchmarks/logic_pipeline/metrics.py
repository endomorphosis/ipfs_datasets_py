"""Fail-closed aggregation for kernel-bound logic-pipeline results.

Aggregate metrics are a trust boundary: a syntactically valid ``verified``
status is not sufficient evidence of a successful proof.  This module accepts
only complete :class:`~benchmarks.logic_pipeline.contracts.CaseResultRecord`
values, validates their route and provenance receipts, and retains the digest
of every contributing case result.

The module is dependency-free and performs no I/O.  Statistical comparisons
and confidence intervals belong in ``statistics.py``; this module provides the
small deterministic accounting layer on which those analyses can safely rely.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Self

from .contracts import (
    CacheMode,
    CaseResultRecord,
    OutcomeStatus,
    ProtocolContractError,
    ResourceLane,
    Split,
    canonical_json,
)


KERNEL_BOUND_AGGREGATE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.kernel-bound-aggregate.v1"
)
EFFICIENCY_COMPONENT_COST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.efficiency-component-cost.v1"
)
EFFICIENCY_RESOURCE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.efficiency-resource-receipt.v1"
)
EFFICIENCY_OBSERVATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.efficiency-observation.v1"
)
EFFICIENCY_ESCALATION_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.efficiency-escalation.v1"
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_TELEMETRY_FIELDS: Final = (
    "wall_time_ms",
    "cpu_time_ms",
    "peak_memory_bytes",
    "input_items",
    "output_items",
    "model_calls",
    "cache_hits",
    "cache_misses",
    "retries",
    "bytes_in",
    "bytes_out",
)
_FLOAT_TELEMETRY_FIELDS: Final = frozenset({"wall_time_ms", "cpu_time_ms"})
_LANE_MEASUREMENT_FIELDS: Final = ("stage_count", *_TELEMETRY_FIELDS)


class MetricsContractError(ProtocolContractError):
    """Raised when result evidence cannot support an aggregate claim."""


def HSSLEV0357C0D() -> str:
    """Return AST-verifiable evidence for kernel-bound result aggregation."""

    return "kernel and provenance receipts for all claimed successes"


def HSSLEV0615B24() -> str:
    """Return AST-verifiable evidence for delegation-value accounting."""

    return (
        "receipt-bound marginal and cumulative kernel-verified delegation "
        "value per model call, solver process, accelerator-minute, retry, "
        "and operational component with failure burden and a safety-gated "
        "multiobjective complexity Pareto frontier"
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise MetricsContractError(f"{field_name} must be an object with string keys")
    return value


def _exact_keys(
    value: Mapping[str, object], expected: set[str], field_name: str
) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing {missing}")
    if unknown:
        details.append(f"unknown {unknown}")
    raise MetricsContractError(f"{field_name} has " + " and ".join(details))


def _safe_id(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise MetricsContractError(
            f"{field_name} must be a safe 1-128 character identifier"
        )
    return value


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise MetricsContractError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetricsContractError(f"{field_name} must be a nonnegative integer")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsContractError(f"{field_name} must be a finite nonnegative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise MetricsContractError(f"{field_name} must be a finite nonnegative number")
    return result


def _enum(enum_type: type[Split] | type[CacheMode], value: object, field_name: str):
    if not isinstance(value, str):
        raise MetricsContractError(f"{field_name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise MetricsContractError(
            f"unsupported {field_name}: {value!r}"
        ) from exc


def _digest_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise MetricsContractError(f"{field_name} must be an array")
    result = tuple(
        _digest(item, f"{field_name}[]")
        for item in value
    )
    if len(result) != len(set(result)):
        raise MetricsContractError(f"{field_name} must not contain duplicates")
    return result


def _telemetry_mapping(
    value: object, field_name: str, *, lane: bool = False
) -> Mapping[str, int | float]:
    data = _mapping(value, field_name)
    expected = (
        set(_LANE_MEASUREMENT_FIELDS) if lane else set(_TELEMETRY_FIELDS)
    )
    _exact_keys(data, expected, field_name)
    result: dict[str, int | float] = {}
    for name in (("stage_count",) if lane else ()):
        result[name] = _integer(data[name], f"{field_name}.{name}")
    for name in _TELEMETRY_FIELDS:
        if name in _FLOAT_TELEMETRY_FIELDS:
            result[name] = _number(data[name], f"{field_name}.{name}")
        else:
            result[name] = _integer(data[name], f"{field_name}.{name}")
    return MappingProxyType(result)


def _lane_mapping(
    value: object,
) -> Mapping[str, Mapping[str, int | float]]:
    data = _mapping(value, "resource_lane_measurements")
    expected = {lane.value for lane in ResourceLane}
    _exact_keys(data, expected, "resource_lane_measurements")
    return MappingProxyType(
        {
            lane.value: _telemetry_mapping(
                data[lane.value],
                f"resource_lane_measurements.{lane.value}",
                lane=True,
            )
            for lane in ResourceLane
        }
    )


def _zero_telemetry(*, include_stage_count: bool = False) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    if include_stage_count:
        result["stage_count"] = 0
    for name in _TELEMETRY_FIELDS:
        result[name] = 0.0 if name in _FLOAT_TELEMETRY_FIELDS else 0
    return result


def _add_telemetry(
    target: dict[str, int | float],
    source: object,
) -> None:
    for name in _TELEMETRY_FIELDS:
        value = getattr(source, name)
        target[name] += value


@dataclass(frozen=True, slots=True)
class KernelBoundAggregate:
    """Content-addressed accounting over provenance-validated case results."""

    schema: str
    protocol_sha256: str
    run_id: str
    case_manifest_sha256: str
    variant_id: str
    split: Split
    cache_mode: CacheMode
    environment_sha256: str
    total_count: int
    verified_count: int
    nonverified_count: int
    excluded_count: int
    infrastructure_failure_count: int
    kernel_verified_completion_rate: float
    result_digests: tuple[str, ...]
    verified_result_digests: tuple[str, ...]
    telemetry_totals: Mapping[str, int | float]
    resource_lane_measurements: Mapping[
        str, Mapping[str, int | float]
    ]

    def __post_init__(self) -> None:
        if self.schema != KERNEL_BOUND_AGGREGATE_SCHEMA:
            raise MetricsContractError("unsupported kernel-bound aggregate schema")
        _digest(self.protocol_sha256, "protocol_sha256")
        _safe_id(self.run_id, "run_id")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        _safe_id(self.variant_id, "variant_id")
        if not isinstance(self.split, Split):
            raise MetricsContractError("split must be a Split")
        if not isinstance(self.cache_mode, CacheMode):
            raise MetricsContractError("cache_mode must be a CacheMode")
        _digest(self.environment_sha256, "environment_sha256")

        for field_name in (
            "total_count",
            "verified_count",
            "nonverified_count",
            "excluded_count",
            "infrastructure_failure_count",
        ):
            _integer(getattr(self, field_name), field_name)
        if not self.total_count:
            raise MetricsContractError("an aggregate requires at least one result")
        if self.total_count != (
            self.verified_count
            + self.nonverified_count
            + self.excluded_count
            + self.infrastructure_failure_count
        ):
            raise MetricsContractError("aggregate status counts do not sum to total_count")

        rate = _number(
            self.kernel_verified_completion_rate,
            "kernel_verified_completion_rate",
        )
        if rate > 1:
            raise MetricsContractError(
                "kernel_verified_completion_rate must be <= 1"
            )
        eligible_count = self.verified_count + self.nonverified_count
        expected_rate = (
            0.0 if eligible_count == 0 else self.verified_count / eligible_count
        )
        if not math.isclose(rate, expected_rate, rel_tol=0.0, abs_tol=1e-15):
            raise MetricsContractError(
                "kernel_verified_completion_rate does not match status counts"
            )
        object.__setattr__(self, "kernel_verified_completion_rate", rate)

        result_digests = _digest_tuple(self.result_digests, "result_digests")
        verified_digests = _digest_tuple(
            self.verified_result_digests,
            "verified_result_digests",
        )
        if len(result_digests) != self.total_count:
            raise MetricsContractError(
                "result_digests length does not match total_count"
            )
        if len(verified_digests) != self.verified_count:
            raise MetricsContractError(
                "verified_result_digests length does not match verified_count"
            )
        if not set(verified_digests).issubset(result_digests):
            raise MetricsContractError(
                "verified_result_digests must be a subset of result_digests"
            )

        telemetry = _telemetry_mapping(
            self.telemetry_totals, "telemetry_totals"
        )
        lanes = _lane_mapping(self.resource_lane_measurements)
        lane_stage_count = sum(
            int(item["stage_count"]) for item in lanes.values()
        )
        if lane_stage_count < self.total_count:
            raise MetricsContractError(
                "resource-lane stage count cannot be smaller than result count"
            )
        for name in _TELEMETRY_FIELDS:
            lane_total = sum(item[name] for item in lanes.values())
            if not math.isclose(
                float(lane_total),
                float(telemetry[name]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise MetricsContractError(
                    f"resource-lane {name} does not match telemetry total"
                )

        object.__setattr__(self, "result_digests", result_digests)
        object.__setattr__(
            self, "verified_result_digests", verified_digests
        )
        object.__setattr__(self, "telemetry_totals", telemetry)
        object.__setattr__(self, "resource_lane_measurements", lanes)

    @property
    def eligible_count(self) -> int:
        """Number of logical outcomes in the verified-rate denominator."""

        return self.verified_count + self.nonverified_count

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "run_id": self.run_id,
            "case_manifest_sha256": self.case_manifest_sha256,
            "variant_id": self.variant_id,
            "split": self.split.value,
            "cache_mode": self.cache_mode.value,
            "environment_sha256": self.environment_sha256,
            "total_count": self.total_count,
            "verified_count": self.verified_count,
            "nonverified_count": self.nonverified_count,
            "excluded_count": self.excluded_count,
            "infrastructure_failure_count": self.infrastructure_failure_count,
            "kernel_verified_completion_rate": self.kernel_verified_completion_rate,
            "result_digests": list(self.result_digests),
            "verified_result_digests": list(self.verified_result_digests),
            "telemetry_totals": dict(self.telemetry_totals),
            "resource_lane_measurements": {
                lane: dict(measurements)
                for lane, measurements in self.resource_lane_measurements.items()
            },
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "kernel_bound_aggregate")
        _exact_keys(
            data,
            set(cls.__dataclass_fields__),
            "kernel_bound_aggregate",
        )
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            protocol_sha256=_digest(
                data["protocol_sha256"], "protocol_sha256"
            ),
            run_id=_safe_id(data["run_id"], "run_id"),
            case_manifest_sha256=_digest(
                data["case_manifest_sha256"], "case_manifest_sha256"
            ),
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            split=_enum(Split, data["split"], "split"),
            cache_mode=_enum(CacheMode, data["cache_mode"], "cache_mode"),
            environment_sha256=_digest(
                data["environment_sha256"], "environment_sha256"
            ),
            total_count=_integer(data["total_count"], "total_count"),
            verified_count=_integer(
                data["verified_count"], "verified_count"
            ),
            nonverified_count=_integer(
                data["nonverified_count"], "nonverified_count"
            ),
            excluded_count=_integer(
                data["excluded_count"], "excluded_count"
            ),
            infrastructure_failure_count=_integer(
                data["infrastructure_failure_count"],
                "infrastructure_failure_count",
            ),
            kernel_verified_completion_rate=_number(
                data["kernel_verified_completion_rate"],
                "kernel_verified_completion_rate",
            ),
            result_digests=_digest_tuple(
                data["result_digests"], "result_digests"
            ),
            verified_result_digests=_digest_tuple(
                data["verified_result_digests"],
                "verified_result_digests",
            ),
            telemetry_totals=_telemetry_mapping(
                data["telemetry_totals"], "telemetry_totals"
            ),
            resource_lane_measurements=_lane_mapping(
                data["resource_lane_measurements"]
            ),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()


def _result_environment_sha256(result: CaseResultRecord) -> str:
    environments = {
        stage.provenance.environment_sha256
        for stage in result.stages
    }
    if len(environments) != 1 or None in environments:
        raise MetricsContractError(
            "case result does not bind one complete environment identity"
        )
    return _digest(next(iter(environments)), "environment_sha256")


def validate_kernel_bound_result(
    result: CaseResultRecord,
    expected_environment_sha256: str | None = None,
) -> CaseResultRecord:
    """Validate one case result before it can contribute to any metric.

    Validation is intentionally applied to every status, not only verified
    outcomes.  This prevents malformed failures and exclusions from changing a
    metric denominator or hiding a provenance incident.
    """

    if not isinstance(result, CaseResultRecord):
        raise MetricsContractError(
            "metrics require complete CaseResultRecord values"
        )
    if expected_environment_sha256 is not None:
        _digest(expected_environment_sha256, "expected_environment_sha256")
    try:
        result.validate_provenance(
            expected_environment_sha256=expected_environment_sha256
        )
    except (ProtocolContractError, AttributeError) as exc:
        raise MetricsContractError(
            f"case result {result.case_id!r} failed provenance validation: {exc}"
        ) from exc
    environment_sha256 = _result_environment_sha256(result)
    if (
        expected_environment_sha256 is not None
        and environment_sha256 != expected_environment_sha256
    ):
        raise MetricsContractError(
            f"case result {result.case_id!r} uses a stale environment"
        )
    return result


def aggregate_case_results(
    results: Iterable[CaseResultRecord],
    expected_environment_sha256: str | None = None,
) -> KernelBoundAggregate:
    """Create a traceable aggregate over one run/variant/split/cache arm."""

    if isinstance(results, (str, bytes, Mapping)):
        raise MetricsContractError("results must be an iterable of case results")
    try:
        records = tuple(results)
    except TypeError as exc:
        raise MetricsContractError(
            "results must be an iterable of case results"
        ) from exc
    if not records:
        raise MetricsContractError("cannot aggregate an empty result collection")

    first = validate_kernel_bound_result(
        records[0],
        expected_environment_sha256=expected_environment_sha256,
    )
    environment_sha256 = _result_environment_sha256(first)
    if expected_environment_sha256 is not None:
        environment_sha256 = expected_environment_sha256

    identity_fields = (
        "protocol_sha256",
        "run_id",
        "case_manifest_sha256",
        "variant_id",
        "split",
        "cache_mode",
    )
    by_case: dict[str, CaseResultRecord] = {}
    seen_digests: set[str] = set()
    for record in records:
        validated = validate_kernel_bound_result(
            record,
            expected_environment_sha256=environment_sha256,
        )
        if any(
            getattr(validated, name) != getattr(first, name)
            for name in identity_fields
        ):
            raise MetricsContractError(
                "case results must belong to the same run, manifest, variant, "
                "split, and cache arm"
            )
        if validated.case_id in by_case:
            raise MetricsContractError(
                f"duplicate case result: {validated.case_id!r}"
            )
        if validated.digest in seen_digests:
            raise MetricsContractError(
                f"duplicate case-result digest: {validated.digest}"
            )
        by_case[validated.case_id] = validated
        seen_digests.add(validated.digest)

    ordered = tuple(by_case[case_id] for case_id in sorted(by_case))
    verified = tuple(
        record for record in ordered
        if record.status is OutcomeStatus.VERIFIED
    )
    nonverified_count = sum(
        record.status in {OutcomeStatus.NOT_VERIFIED, OutcomeStatus.REJECTED}
        for record in ordered
    )
    excluded_count = sum(
        record.status in {OutcomeStatus.UNAVAILABLE, OutcomeStatus.EXCLUDED}
        for record in ordered
    )
    infrastructure_failure_count = sum(
        record.status is OutcomeStatus.INFRASTRUCTURE_FAILURE
        for record in ordered
    )
    eligible_count = len(verified) + nonverified_count

    telemetry_totals = _zero_telemetry()
    lanes = {
        lane.value: _zero_telemetry(include_stage_count=True)
        for lane in ResourceLane
    }
    for record in ordered:
        for stage in record.stages:
            _add_telemetry(telemetry_totals, stage.telemetry)
            lane = lanes[stage.telemetry.resource_lane.value]
            lane["stage_count"] += 1
            _add_telemetry(lane, stage.telemetry)

    return KernelBoundAggregate(
        schema=KERNEL_BOUND_AGGREGATE_SCHEMA,
        protocol_sha256=first.protocol_sha256,
        run_id=first.run_id,
        case_manifest_sha256=first.case_manifest_sha256,
        variant_id=first.variant_id,
        split=first.split,
        cache_mode=first.cache_mode,
        environment_sha256=environment_sha256,
        total_count=len(ordered),
        verified_count=len(verified),
        nonverified_count=nonverified_count,
        excluded_count=excluded_count,
        infrastructure_failure_count=infrastructure_failure_count,
        kernel_verified_completion_rate=(
            0.0 if eligible_count == 0 else len(verified) / eligible_count
        ),
        result_digests=tuple(record.digest for record in ordered),
        verified_result_digests=tuple(record.digest for record in verified),
        telemetry_totals=telemetry_totals,
        resource_lane_measurements=lanes,
    )


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetricsContractError(f"{field_name} must be a nonempty string")
    if len(value.encode("utf-8")) > 1024:
        raise MetricsContractError(f"{field_name} exceeds 1024 encoded bytes")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise MetricsContractError(f"{field_name} must be boolean")
    return value


def _nullable_measurement(
    value: object,
    reason: object,
    field_name: str,
    *,
    integer: bool,
) -> tuple[int | float | None, str | None]:
    if value is None:
        if reason is None:
            raise MetricsContractError(
                f"{field_name}_missing_reason is required when {field_name} is null"
            )
        return None, _text(reason, f"{field_name}_missing_reason")
    if reason is not None:
        raise MetricsContractError(
            f"{field_name}_missing_reason must be null when {field_name} is measured"
        )
    measured: int | float
    if integer:
        measured = _integer(value, field_name)
    else:
        measured = _number(value, field_name)
    return measured, None


@dataclass(frozen=True, slots=True)
class EfficiencyComponentCost:
    """Measured use of one operational component for one case result.

    Solver processes and accelerator minutes are explicit measurements.  They
    are never inferred from a Hammer stage or model-lane wall time.  A null
    measurement therefore carries a reason and propagates to every ratio that
    needs that denominator.
    """

    component_id: str
    model_calls: int
    solver_processes: int | None
    solver_processes_missing_reason: str | None
    accelerator_minutes: float | None
    accelerator_minutes_missing_reason: str | None
    retries: int
    component_calls: int
    useful_component_calls: int
    failed_attempts: int
    schema: str = EFFICIENCY_COMPONENT_COST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EFFICIENCY_COMPONENT_COST_SCHEMA:
            raise MetricsContractError("unsupported efficiency component-cost schema")
        _safe_id(self.component_id, "component_id")
        for field_name in (
            "model_calls",
            "retries",
            "component_calls",
            "useful_component_calls",
            "failed_attempts",
        ):
            object.__setattr__(
                self, field_name, _integer(getattr(self, field_name), field_name)
            )
        solver, solver_reason = _nullable_measurement(
            self.solver_processes,
            self.solver_processes_missing_reason,
            "solver_processes",
            integer=True,
        )
        accelerator, accelerator_reason = _nullable_measurement(
            self.accelerator_minutes,
            self.accelerator_minutes_missing_reason,
            "accelerator_minutes",
            integer=False,
        )
        if self.useful_component_calls > self.component_calls:
            raise MetricsContractError(
                "useful_component_calls cannot exceed component_calls"
            )
        object.__setattr__(self, "solver_processes", solver)
        object.__setattr__(
            self, "solver_processes_missing_reason", solver_reason
        )
        object.__setattr__(self, "accelerator_minutes", accelerator)
        object.__setattr__(
            self, "accelerator_minutes_missing_reason", accelerator_reason
        )

    def to_dict(self) -> dict[str, object]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "component_cost")
        _exact_keys(data, set(cls.__dataclass_fields__), "component_cost")
        return cls(
            component_id=_safe_id(data["component_id"], "component_id"),
            model_calls=_integer(data["model_calls"], "model_calls"),
            solver_processes=data["solver_processes"],  # type: ignore[arg-type]
            solver_processes_missing_reason=data[
                "solver_processes_missing_reason"
            ],  # type: ignore[arg-type]
            accelerator_minutes=data["accelerator_minutes"],  # type: ignore[arg-type]
            accelerator_minutes_missing_reason=data[
                "accelerator_minutes_missing_reason"
            ],  # type: ignore[arg-type]
            retries=_integer(data["retries"], "retries"),
            component_calls=_integer(data["component_calls"], "component_calls"),
            useful_component_calls=_integer(
                data["useful_component_calls"], "useful_component_calls"
            ),
            failed_attempts=_integer(data["failed_attempts"], "failed_attempts"),
            schema=_text(data["schema"], "schema"),
        )


@dataclass(frozen=True, slots=True)
class EfficiencyResourceReceipt:
    """Content-addressed operational metering bound to one case result."""

    case_result_sha256: str
    environment_sha256: str
    measurement_sha256: str
    component_costs: tuple[EfficiencyComponentCost, ...]
    schema: str = EFFICIENCY_RESOURCE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EFFICIENCY_RESOURCE_RECEIPT_SCHEMA:
            raise MetricsContractError("unsupported efficiency resource-receipt schema")
        _digest(self.case_result_sha256, "case_result_sha256")
        _digest(self.environment_sha256, "environment_sha256")
        _digest(self.measurement_sha256, "measurement_sha256")
        if (
            not isinstance(self.component_costs, tuple)
            or not self.component_costs
            or any(
                not isinstance(item, EfficiencyComponentCost)
                for item in self.component_costs
            )
        ):
            raise MetricsContractError(
                "component_costs must be a nonempty tuple of component costs"
            )
        component_ids = tuple(item.component_id for item in self.component_costs)
        if component_ids != tuple(sorted(component_ids)):
            raise MetricsContractError(
                "component_costs must use canonical component-id order"
            )
        if len(component_ids) != len(set(component_ids)):
            raise MetricsContractError("component_costs contain duplicate components")

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "case_result_sha256": self.case_result_sha256,
            "environment_sha256": self.environment_sha256,
            "measurement_sha256": self.measurement_sha256,
            "component_costs": [item.to_dict() for item in self.component_costs],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "resource_receipt")
        _exact_keys(data, set(cls.__dataclass_fields__), "resource_receipt")
        costs = data["component_costs"]
        if not isinstance(costs, list):
            raise MetricsContractError("component_costs must be an array")
        return cls(
            schema=_text(data["schema"], "schema"),
            case_result_sha256=_digest(
                data["case_result_sha256"], "case_result_sha256"
            ),
            environment_sha256=_digest(
                data["environment_sha256"], "environment_sha256"
            ),
            measurement_sha256=_digest(
                data["measurement_sha256"], "measurement_sha256"
            ),
            component_costs=tuple(
                EfficiencyComponentCost.from_dict(item) for item in costs
            ),
        )


@dataclass(frozen=True, slots=True)
class EfficiencyEscalation:
    """One ordered edge in a frozen delegation escalation chain."""

    chain_id: str
    step_index: int
    variant_id: str
    parent_variant_id: str | None
    added_components: tuple[str, ...]
    schema: str = EFFICIENCY_ESCALATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EFFICIENCY_ESCALATION_SCHEMA:
            raise MetricsContractError("unsupported efficiency escalation schema")
        _safe_id(self.chain_id, "chain_id")
        object.__setattr__(
            self, "step_index", _integer(self.step_index, "step_index")
        )
        _safe_id(self.variant_id, "variant_id")
        if self.parent_variant_id is not None:
            _safe_id(self.parent_variant_id, "parent_variant_id")
            if self.parent_variant_id == self.variant_id:
                raise MetricsContractError("an escalation cannot parent itself")
        if (
            not isinstance(self.added_components, tuple)
            or not self.added_components
        ):
            raise MetricsContractError("added_components must be a nonempty tuple")
        components = tuple(
            _safe_id(item, "added_components[]") for item in self.added_components
        )
        if components != tuple(sorted(components)) or len(components) != len(
            set(components)
        ):
            raise MetricsContractError(
                "added_components must be unique and canonically ordered"
            )
        object.__setattr__(self, "added_components", components)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "chain_id": self.chain_id,
            "step_index": self.step_index,
            "variant_id": self.variant_id,
            "parent_variant_id": self.parent_variant_id,
            "added_components": list(self.added_components),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "escalation")
        _exact_keys(data, set(cls.__dataclass_fields__), "escalation")
        components = data["added_components"]
        if not isinstance(components, list):
            raise MetricsContractError("added_components must be an array")
        parent = data["parent_variant_id"]
        return cls(
            schema=_text(data["schema"], "schema"),
            chain_id=_safe_id(data["chain_id"], "chain_id"),
            step_index=_integer(data["step_index"], "step_index"),
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            parent_variant_id=(
                None if parent is None else _safe_id(parent, "parent_variant_id")
            ),
            added_components=tuple(components),  # type: ignore[arg-type]
        )


DEFAULT_EFFICIENCY_ESCALATIONS: Final = (
    EfficiencyEscalation("a1-a4", 0, "A1", None, ("spacy",)),
    EfficiencyEscalation("a1-a4", 1, "A2", "A1", ("hammer",)),
    EfficiencyEscalation("a1-a4", 2, "A3", "A2", ("leanstral",)),
    EfficiencyEscalation("a1-a4", 3, "A4", "A3", ("symai",)),
)


@dataclass(frozen=True, slots=True)
class EfficiencyObservation:
    """Case result plus independently metered operational resource evidence."""

    case_result: CaseResultRecord
    resource_receipt: EfficiencyResourceReceipt
    invalid_control: bool = False
    schema: str = EFFICIENCY_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EFFICIENCY_OBSERVATION_SCHEMA:
            raise MetricsContractError("unsupported efficiency-observation schema")
        result = validate_kernel_bound_result(self.case_result)
        if not isinstance(self.resource_receipt, EfficiencyResourceReceipt):
            raise MetricsContractError(
                "resource_receipt must be an EfficiencyResourceReceipt"
            )
        environment_sha256 = _result_environment_sha256(result)
        if self.resource_receipt.case_result_sha256 != result.digest:
            raise MetricsContractError(
                "resource receipt does not bind the case-result digest"
            )
        if self.resource_receipt.environment_sha256 != environment_sha256:
            raise MetricsContractError(
                "resource receipt does not bind the case-result environment"
            )
        _boolean(self.invalid_control, "invalid_control")
        useful = sum(
            item.useful_component_calls
            for item in self.resource_receipt.component_costs
        )
        if useful and result.status is not OutcomeStatus.VERIFIED:
            raise MetricsContractError(
                "useful component calls require a kernel-verified result"
            )

        by_stage = {stage.stage.value: stage for stage in result.stages}
        for cost in self.resource_receipt.component_costs:
            stage = by_stage.get(cost.component_id)
            if stage is None:
                if (
                    cost.model_calls
                    or cost.retries
                    or cost.component_calls
                    or cost.useful_component_calls
                    or cost.failed_attempts
                    or cost.solver_processes not in {None, 0}
                    or cost.accelerator_minutes not in {None, 0.0}
                ):
                    raise MetricsContractError(
                        f"absent component {cost.component_id!r} has telemetry cost"
                    )
                continue
            if (
                cost.model_calls != stage.telemetry.model_calls
                or cost.retries != stage.telemetry.retries
            ):
                raise MetricsContractError(
                    f"{cost.component_id} model-call/retry cost does not match "
                    "case-result telemetry"
                )

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "case_result": self.case_result.to_dict(),
            "case_result_sha256": self.case_result.digest,
            "resource_receipt": self.resource_receipt.to_dict(),
            "resource_receipt_sha256": self.resource_receipt.digest,
            "invalid_control": self.invalid_control,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "efficiency_observation")
        expected = {
            "schema",
            "case_result",
            "case_result_sha256",
            "resource_receipt",
            "resource_receipt_sha256",
            "invalid_control",
        }
        _exact_keys(data, expected, "efficiency_observation")
        try:
            result = CaseResultRecord.from_dict(data["case_result"])
        except ProtocolContractError as exc:
            raise MetricsContractError(
                f"invalid efficiency case result: {exc}"
            ) from exc
        receipt = EfficiencyResourceReceipt.from_dict(data["resource_receipt"])
        if _digest(data["case_result_sha256"], "case_result_sha256") != result.digest:
            raise MetricsContractError("case_result_sha256 does not match case_result")
        if (
            _digest(data["resource_receipt_sha256"], "resource_receipt_sha256")
            != receipt.digest
        ):
            raise MetricsContractError(
                "resource_receipt_sha256 does not match resource_receipt"
            )
        return cls(
            schema=_text(data["schema"], "schema"),
            case_result=result,
            resource_receipt=receipt,
            invalid_control=_boolean(data["invalid_control"], "invalid_control"),
        )


_MEASURED_OUTCOMES: Final = frozenset(
    {OutcomeStatus.VERIFIED, OutcomeStatus.NOT_VERIFIED, OutcomeStatus.REJECTED}
)
_COST_AXES: Final = (
    "model_calls",
    "solver_processes",
    "accelerator_minutes",
    "retries",
    "operational_components",
)


def _validate_escalations(
    escalations: Iterable[EfficiencyEscalation],
) -> tuple[EfficiencyEscalation, ...]:
    records = tuple(escalations)
    if not records or any(
        not isinstance(item, EfficiencyEscalation) for item in records
    ):
        raise MetricsContractError("escalations must contain escalation records")
    ordered = tuple(sorted(records, key=lambda item: item.step_index))
    if ordered != records:
        raise MetricsContractError("escalations must be in canonical step order")
    if tuple(item.step_index for item in ordered) != tuple(range(len(ordered))):
        raise MetricsContractError("escalation step indexes must be contiguous")
    if len({item.variant_id for item in ordered}) != len(ordered):
        raise MetricsContractError("escalation variants must be unique")
    if len({item.chain_id for item in ordered}) != 1:
        raise MetricsContractError("one analysis cannot pool escalation chains")
    seen_components: set[str] = set()
    for index, item in enumerate(ordered):
        expected_parent = None if index == 0 else ordered[index - 1].variant_id
        if item.parent_variant_id != expected_parent:
            raise MetricsContractError(
                "escalation parents must form one contiguous chain"
            )
        if seen_components & set(item.added_components):
            raise MetricsContractError(
                "an operational component cannot be added more than once"
            )
        seen_components.update(item.added_components)
    return ordered


def _sum_component_costs(
    observations: Iterable[EfficiencyObservation],
    component_ids: set[str],
) -> dict[str, object]:
    selected = [
        cost
        for observation in observations
        for cost in observation.resource_receipt.component_costs
        if cost.component_id in component_ids
    ]
    solver_values = [item.solver_processes for item in selected]
    accelerator_values = [item.accelerator_minutes for item in selected]
    calls = sum(item.component_calls for item in selected)
    useful = sum(item.useful_component_calls for item in selected)
    return {
        "model_calls": sum(item.model_calls for item in selected),
        "solver_processes": (
            None
            if any(item is None for item in solver_values)
            else sum(int(item) for item in solver_values)
        ),
        "accelerator_minutes": (
            None
            if any(item is None for item in accelerator_values)
            else sum(float(item) for item in accelerator_values)
        ),
        "retries": sum(item.retries for item in selected),
        "operational_components": len(component_ids),
        "component_calls": calls,
        "useful_component_calls": useful,
        "unnecessary_component_calls": calls - useful,
        "unnecessary_call_rate": 0.0 if calls == 0 else (calls - useful) / calls,
        "failed_attempts": sum(item.failed_attempts for item in selected),
        "solver_processes_missing_reasons": sorted(
            {
                item.solver_processes_missing_reason
                for item in selected
                if item.solver_processes is None
            }
        ),
        "accelerator_minutes_missing_reasons": sorted(
            {
                item.accelerator_minutes_missing_reason
                for item in selected
                if item.accelerator_minutes is None
            }
        ),
    }


def _paired_value(
    baseline: Mapping[str, EfficiencyObservation],
    candidate: Mapping[str, EfficiencyObservation],
) -> tuple[dict[str, object], tuple[str, ...]]:
    measured: list[str] = []
    missing: list[dict[str, str]] = []
    wins: list[str] = []
    regressions: list[str] = []
    both: list[str] = []
    neither: list[str] = []
    for case_id in sorted(baseline):
        left = baseline[case_id].case_result.status
        right = candidate[case_id].case_result.status
        if left not in _MEASURED_OUTCOMES or right not in _MEASURED_OUTCOMES:
            missing.append(
                {
                    "case_id": case_id,
                    "baseline_status": left.value,
                    "candidate_status": right.value,
                }
            )
            continue
        measured.append(case_id)
        pair = (
            left is OutcomeStatus.VERIFIED,
            right is OutcomeStatus.VERIFIED,
        )
        if pair == (False, True):
            wins.append(case_id)
        elif pair == (True, False):
            regressions.append(case_id)
        elif pair == (True, True):
            both.append(case_id)
        else:
            neither.append(case_id)
    count = len(measured)
    net = len(wins) - len(regressions)
    return (
        {
            "paired_case_count": count,
            "paired_case_ids": measured,
            "missing_pair_count": len(missing),
            "missing_pairs": missing,
            "gross_verified_gain_count": len(wins),
            "gross_verified_gain_rate": None if not count else len(wins) / count,
            "verified_regression_count": len(regressions),
            "verified_regression_rate": (
                None if not count else len(regressions) / count
            ),
            "net_verified_gain_count": net,
            "net_verified_delta": None if not count else net / count,
            "candidate_only_verified_case_ids": wins,
            "baseline_only_verified_case_ids": regressions,
            "concordant_verified_case_ids": both,
            "concordant_nonverified_case_ids": neither,
        },
        tuple(measured),
    )


def _value_per_cost(
    pair: Mapping[str, object],
    cost: Mapping[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    gross = int(pair["gross_verified_gain_count"])
    net = int(pair["net_verified_gain_count"])
    paired = int(pair["paired_case_count"])
    for axis in _COST_AXES:
        denominator = cost[axis]
        if paired == 0:
            reason = "no_measured_pairs"
        elif denominator is None:
            reason = f"{axis}_measurement_missing"
        elif float(denominator) <= 0:
            reason = f"nonpositive_{axis}_denominator"
        else:
            reason = None
        result[axis] = {
            "denominator": denominator,
            "gross_verified_gains_per_unit": (
                None if reason else gross / float(denominator)
            ),
            "net_verified_gain_per_unit": (
                None if reason else net / float(denominator)
            ),
            "undefined_reason": reason,
        }
    return result


def _failure_burden(
    observations: Iterable[EfficiencyObservation],
) -> dict[str, object]:
    records = tuple(observations)
    status_counts = {
        status.value: sum(
            item.case_result.status is status for item in records
        )
        for status in OutcomeStatus
    }
    failure_codes: dict[str, int] = {}
    failed_stages = 0
    retries = 0
    for observation in records:
        result = observation.case_result
        if result.failure_code is not None:
            failure_codes[result.failure_code.value] = (
                failure_codes.get(result.failure_code.value, 0) + 1
            )
        for stage in result.stages:
            retries += stage.telemetry.retries
            if stage.failure_code is not None:
                failed_stages += 1
    return {
        "status_counts": status_counts,
        "logical_failure_count": (
            status_counts[OutcomeStatus.NOT_VERIFIED.value]
            + status_counts[OutcomeStatus.REJECTED.value]
        ),
        "excluded_or_unavailable_count": (
            status_counts[OutcomeStatus.UNAVAILABLE.value]
            + status_counts[OutcomeStatus.EXCLUDED.value]
        ),
        "infrastructure_failure_count": status_counts[
            OutcomeStatus.INFRASTRUCTURE_FAILURE.value
        ],
        "failed_stage_count": failed_stages,
        "retry_count": retries,
        "failure_code_counts": {
            key: failure_codes[key] for key in sorted(failure_codes)
        },
    }


def _pareto_points(
    step_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for row in step_rows:
        final = row["final"]
        assert isinstance(final, Mapping)
        costs = row["total_cost"]
        assert isinstance(costs, Mapping)
        safety = row["safety"]
        assert isinstance(safety, Mapping)
        reasons: list[str] = []
        if not safety["feasible"]:
            reasons.append("safety_violation")
        if final["kernel_verified_rate"] is None:
            reasons.append("quality_measurement_missing")
        if int(final["missing_case_count"]) > 0:
            reasons.append("incomplete_case_evidence")
        for axis in _COST_AXES:
            if costs[axis] is None:
                reasons.append(f"{axis}_measurement_missing")
        points.append(
            {
                "variant_id": row["variant_id"],
                "step_index": row["step_index"],
                "eligible": not reasons,
                "ineligibility_reasons": reasons,
                "kernel_verified_rate": final["kernel_verified_rate"],
                "costs": {axis: costs[axis] for axis in _COST_AXES},
                "unnecessary_call_rate": costs["unnecessary_call_rate"],
                "failed_attempts": costs["failed_attempts"],
                "frontier": False,
                "dominated_by": [],
            }
        )
    eligible = [item for item in points if item["eligible"]]
    minimize = (*_COST_AXES, "unnecessary_call_rate", "failed_attempts")
    for candidate in eligible:
        dominated_by: list[str] = []
        for other in eligible:
            if other is candidate:
                continue
            other_costs = dict(other["costs"])  # type: ignore[arg-type]
            candidate_costs = dict(candidate["costs"])  # type: ignore[arg-type]
            other_values = {
                **other_costs,
                "unnecessary_call_rate": other["unnecessary_call_rate"],
                "failed_attempts": other["failed_attempts"],
            }
            candidate_values = {
                **candidate_costs,
                "unnecessary_call_rate": candidate["unnecessary_call_rate"],
                "failed_attempts": candidate["failed_attempts"],
            }
            no_worse = (
                float(other["kernel_verified_rate"])
                >= float(candidate["kernel_verified_rate"])
                and all(
                    float(other_values[axis]) <= float(candidate_values[axis])
                    for axis in minimize
                )
            )
            strictly_better = (
                float(other["kernel_verified_rate"])
                > float(candidate["kernel_verified_rate"])
                or any(
                    float(other_values[axis]) < float(candidate_values[axis])
                    for axis in minimize
                )
            )
            if no_worse and strictly_better:
                dominated_by.append(str(other["variant_id"]))
        candidate["dominated_by"] = sorted(dominated_by)
        candidate["frontier"] = not dominated_by
    return points


def analyze_delegation_efficiency(
    escalations: Iterable[EfficiencyEscalation],
    observations: Iterable[EfficiencyObservation],
    *,
    allow_empty: bool = False,
) -> dict[str, object]:
    """Recompute paired delegation value and the safety-gated cost frontier."""

    steps = _validate_escalations(escalations)
    records = tuple(observations)
    if any(not isinstance(item, EfficiencyObservation) for item in records):
        raise MetricsContractError(
            "observations must contain EfficiencyObservation values"
        )
    if not records:
        if not allow_empty:
            raise MetricsContractError("measured efficiency analysis requires observations")
        active_components: set[str] = set()
        empty_rows: list[dict[str, object]] = []
        empty_points: list[dict[str, object]] = []
        root = steps[0]
        for step in steps:
            active_components.update(step.added_components)
            empty_pair = {
                "evidence_available": False,
                "paired_case_count": 0,
                "paired_case_ids": [],
                "missing_pair_count": 0,
                "missing_pairs": [],
                "gross_verified_gain_count": None,
                "gross_verified_gain_rate": None,
                "verified_regression_count": None,
                "verified_regression_rate": None,
                "net_verified_gain_count": None,
                "net_verified_delta": None,
                "candidate_only_verified_case_ids": [],
                "baseline_only_verified_case_ids": [],
                "concordant_verified_case_ids": [],
                "concordant_nonverified_case_ids": [],
                "undefined_reason": "no_measured_pairs",
            }
            empty_cost = {
                "model_calls": None,
                "solver_processes": None,
                "accelerator_minutes": None,
                "retries": None,
                "operational_components": len(active_components),
                "component_calls": None,
                "useful_component_calls": None,
                "unnecessary_component_calls": None,
                "unnecessary_call_rate": None,
                "failed_attempts": None,
                "undefined_reason": "no_measured_observations",
            }
            marginal = None
            cumulative = None
            if step.parent_variant_id is not None:
                marginal = {
                    "baseline_variant_id": step.parent_variant_id,
                    "candidate_variant_id": step.variant_id,
                    "pair": dict(empty_pair),
                    "incremental_cost": {
                        **empty_cost,
                        "operational_components": len(step.added_components),
                    },
                    "value_per_cost": {
                        axis: {
                            "denominator": None,
                            "gross_verified_gains_per_unit": None,
                            "net_verified_gain_per_unit": None,
                            "undefined_reason": "no_measured_pairs",
                        }
                        for axis in _COST_AXES
                    },
                }
                cumulative = {
                    "baseline_variant_id": root.variant_id,
                    "candidate_variant_id": step.variant_id,
                    "pair": dict(empty_pair),
                    "incremental_cost": dict(empty_cost),
                    "value_per_cost": {
                        axis: {
                            "denominator": None,
                            "gross_verified_gains_per_unit": None,
                            "net_verified_gain_per_unit": None,
                            "undefined_reason": "no_measured_pairs",
                        }
                        for axis in _COST_AXES
                    },
                }
            empty_rows.append(
                {
                    "variant_id": step.variant_id,
                    "step_index": step.step_index,
                    "parent_variant_id": step.parent_variant_id,
                    "added_components": list(step.added_components),
                    "observation_sha256s": [],
                    "final": {
                        "measured_case_count": 0,
                        "missing_case_count": None,
                        "kernel_verified_count": None,
                        "kernel_verified_rate": None,
                    },
                    "total_cost": empty_cost,
                    "failure_burden": None,
                    "safety": {
                        "invalid_control_verified_count": None,
                        "feasible": None,
                        "hard_constraint": True,
                    },
                    "marginal": marginal,
                    "cumulative": cumulative,
                }
            )
            empty_points.append(
                {
                    "variant_id": step.variant_id,
                    "step_index": step.step_index,
                    "eligible": False,
                    "ineligibility_reasons": ["no_measured_evidence"],
                    "kernel_verified_rate": None,
                    "costs": {axis: None for axis in _COST_AXES},
                    "unnecessary_call_rate": None,
                    "failed_attempts": None,
                    "frontier": False,
                    "dominated_by": [],
                }
            )
        return {
            "measured": False,
            "missing_reason": "no_measured_efficiency_observations",
            "case_count": 0,
            "escalations": empty_rows,
            "pareto_points": empty_points,
            "frontier_variant_ids": [],
            "safety_is_hard_constraint": True,
            "scalar_complexity_score": None,
        }

    by_variant = {step.variant_id: step for step in steps}
    matrix: dict[str, dict[str, EfficiencyObservation]] = {
        step.variant_id: {} for step in steps
    }
    identity: tuple[object, ...] | None = None
    environment_sha256: str | None = None
    input_by_case: dict[str, str] = {}
    for observation in records:
        result = observation.case_result
        if result.variant_id not in by_variant:
            raise MetricsContractError(
                f"observation variant is not in escalation chain: {result.variant_id}"
            )
        row = matrix[result.variant_id]
        if result.case_id in row:
            raise MetricsContractError(
                f"duplicate efficiency observation: {result.variant_id}/{result.case_id}"
            )
        current_identity = (
            result.protocol_sha256,
            result.run_id,
            result.case_manifest_sha256,
            result.split,
            result.cache_mode,
        )
        if identity is None:
            identity = current_identity
            environment_sha256 = observation.resource_receipt.environment_sha256
        elif current_identity != identity:
            raise MetricsContractError(
                "efficiency observations cannot pool run, protocol, manifest, "
                "split, or cache identities"
            )
        if observation.resource_receipt.environment_sha256 != environment_sha256:
            raise MetricsContractError(
                "efficiency observations cannot pool environments"
            )
        input_sha256 = result.stages[0].provenance.input_sha256
        previous_input = input_by_case.setdefault(result.case_id, input_sha256)
        if previous_input != input_sha256:
            raise MetricsContractError(
                f"case {result.case_id!r} mixes input identities"
            )
        row[result.case_id] = observation

    case_ids = tuple(sorted(next(iter(matrix.values()))))
    if not case_ids or any(tuple(sorted(row)) != case_ids for row in matrix.values()):
        raise MetricsContractError(
            "efficiency escalation matrix must contain every case at every step"
        )

    active_components: set[str] = set()
    components_by_variant: dict[str, set[str]] = {}
    for step in steps:
        active_components.update(step.added_components)
        components_by_variant[step.variant_id] = set(active_components)
        for observation in matrix[step.variant_id].values():
            actual = {
                item.component_id
                for item in observation.resource_receipt.component_costs
            }
            if actual != active_components:
                raise MetricsContractError(
                    f"{step.variant_id} resource receipt components do not match "
                    "the declared cumulative escalation"
                )

    root = steps[0]
    step_rows: list[dict[str, object]] = []
    for step in steps:
        current = matrix[step.variant_id]
        measured_current = tuple(
            observation
            for observation in current.values()
            if observation.case_result.status in _MEASURED_OUTCOMES
        )
        verified = sum(
            item.case_result.status is OutcomeStatus.VERIFIED
            for item in measured_current
        )
        final = {
            "measured_case_count": len(measured_current),
            "missing_case_count": len(case_ids) - len(measured_current),
            "kernel_verified_count": verified,
            "kernel_verified_rate": (
                None if not measured_current else verified / len(measured_current)
            ),
        }
        total_cost = _sum_component_costs(
            measured_current, components_by_variant[step.variant_id]
        )
        safety_count = sum(
            item.invalid_control
            and item.case_result.status is OutcomeStatus.VERIFIED
            for item in current.values()
        )
        row: dict[str, object] = {
            "variant_id": step.variant_id,
            "step_index": step.step_index,
            "parent_variant_id": step.parent_variant_id,
            "added_components": list(step.added_components),
            "observation_sha256s": [
                current[case_id].digest for case_id in case_ids
            ],
            "final": final,
            "total_cost": total_cost,
            "failure_burden": _failure_burden(current.values()),
            "safety": {
                "invalid_control_verified_count": safety_count,
                "feasible": safety_count == 0,
                "hard_constraint": True,
            },
            "marginal": None,
            "cumulative": None,
        }
        if step.parent_variant_id is not None:
            marginal_pair, measured_ids = _paired_value(
                matrix[step.parent_variant_id], current
            )
            marginal_observations = tuple(current[item] for item in measured_ids)
            marginal_cost = _sum_component_costs(
                marginal_observations, set(step.added_components)
            )
            row["marginal"] = {
                "baseline_variant_id": step.parent_variant_id,
                "candidate_variant_id": step.variant_id,
                "pair": marginal_pair,
                "incremental_cost": marginal_cost,
                "value_per_cost": _value_per_cost(
                    marginal_pair, marginal_cost
                ),
            }
            cumulative_pair, cumulative_ids = _paired_value(
                matrix[root.variant_id], current
            )
            cumulative_observations = tuple(
                current[item] for item in cumulative_ids
            )
            added_since_root = (
                components_by_variant[step.variant_id]
                - components_by_variant[root.variant_id]
            )
            cumulative_cost = _sum_component_costs(
                cumulative_observations, added_since_root
            )
            row["cumulative"] = {
                "baseline_variant_id": root.variant_id,
                "candidate_variant_id": step.variant_id,
                "pair": cumulative_pair,
                "incremental_cost": cumulative_cost,
                "value_per_cost": _value_per_cost(
                    cumulative_pair, cumulative_cost
                ),
            }
        step_rows.append(row)

    points = _pareto_points(step_rows)
    return {
        "measured": True,
        "missing_reason": None,
        "case_count": len(case_ids),
        "case_ids": list(case_ids),
        "protocol_sha256": identity[0],
        "run_id": identity[1],
        "case_manifest_sha256": identity[2],
        "split": identity[3].value,
        "cache_mode": identity[4].value,
        "environment_sha256": environment_sha256,
        "escalations": step_rows,
        "pareto_points": points,
        "frontier_variant_ids": [
            item["variant_id"] for item in points if item["frontier"]
        ],
        "safety_is_hard_constraint": True,
        "scalar_complexity_score": None,
    }


# Descriptive alias for callers that discover this boundary through the
# objective title rather than the lower-level case-result vocabulary.
aggregate_kernel_bound_results = aggregate_case_results


__all__ = [
    "DEFAULT_EFFICIENCY_ESCALATIONS",
    "EFFICIENCY_COMPONENT_COST_SCHEMA",
    "EFFICIENCY_ESCALATION_SCHEMA",
    "EFFICIENCY_OBSERVATION_SCHEMA",
    "EFFICIENCY_RESOURCE_RECEIPT_SCHEMA",
    "EfficiencyComponentCost",
    "EfficiencyEscalation",
    "EfficiencyObservation",
    "EfficiencyResourceReceipt",
    "HSSLEV0357C0D",
    "HSSLEV0615B24",
    "KERNEL_BOUND_AGGREGATE_SCHEMA",
    "KernelBoundAggregate",
    "MetricsContractError",
    "analyze_delegation_efficiency",
    "aggregate_case_results",
    "aggregate_kernel_bound_results",
    "validate_kernel_bound_result",
]
