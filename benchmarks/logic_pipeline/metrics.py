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


# Descriptive alias for callers that discover this boundary through the
# objective title rather than the lower-level case-result vocabulary.
aggregate_kernel_bound_results = aggregate_case_results


__all__ = [
    "HSSLEV0357C0D",
    "KERNEL_BOUND_AGGREGATE_SCHEMA",
    "KernelBoundAggregate",
    "MetricsContractError",
    "aggregate_case_results",
    "aggregate_kernel_bound_results",
    "validate_kernel_bound_result",
]
