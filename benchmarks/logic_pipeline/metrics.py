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
from enum import Enum
import hashlib
import math
import re
from types import MappingProxyType
from typing import Final, Iterable, Mapping, Self

from . import contracts as _contracts
from .content_addressing import (
    cid_for_dag_json,
    sha256_digest_for_cid,
    validate_cid,
)
from .contracts import (
    CacheMode,
    CaseResultRecord,
    FailureCode,
    NATIVE_KERNEL_RECEIPT_SCHEMA,
    OutcomeStatus,
    ProtocolContractError,
    ResourceLane,
    Split,
    StageName,
    StageStatus,
    canonical_json,
    validate_native_kernel_receipt,
    validate_native_kernel_stage_receipt,
)
from .cache_measurement import (
    extract_symai_cache_setup_telemetry,
    symai_backend_invocation_count,
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
CAUSAL_RESCUE_CASE_RECEIPT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-rescue-case-receipt.v2"
)
CAUSAL_RESCUE_AGGREGATE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.causal-rescue-aggregate.v2"
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


class LeanstralFailureClass(str, Enum):
    """Non-collapsed G210 model failure classes used by causal accounting."""

    NONE = "none"
    OUTPUT_LIMIT = "output_limit"
    SCHEMA = "schema"
    FORBIDDEN_CONSTRUCT = "forbidden_construct"
    PROVIDER = "provider"
    TIMEOUT = "timeout"


_LEANSTRAL_FAILURE_CLASS_BY_SAFE_CLASS: Final = MappingProxyType(
    {
        "length_exhausted": LeanstralFailureClass.OUTPUT_LIMIT,
        "malformed_request": LeanstralFailureClass.SCHEMA,
        "malformed_response": LeanstralFailureClass.SCHEMA,
        "inadmissible_proposal": LeanstralFailureClass.FORBIDDEN_CONSTRUCT,
        "provider_error": LeanstralFailureClass.PROVIDER,
        "unavailable": LeanstralFailureClass.PROVIDER,
        "timed_out": LeanstralFailureClass.TIMEOUT,
        "resource_exhausted": LeanstralFailureClass.PROVIDER,
    }
)
_LEANSTRAL_FAILURE_CLASS_BY_G210_CODE: Final = MappingProxyType(
    {
        "leanstral_output_limit": LeanstralFailureClass.OUTPUT_LIMIT,
        "leanstral_schema_invalid": LeanstralFailureClass.SCHEMA,
        "leanstral_forbidden_construct": (
            LeanstralFailureClass.FORBIDDEN_CONSTRUCT
        ),
        "leanstral_provider_failure": LeanstralFailureClass.PROVIDER,
        "leanstral_timeout": LeanstralFailureClass.TIMEOUT,
    }
)


def classify_leanstral_failure_code(
    failure_code: str | None,
) -> LeanstralFailureClass:
    """Return the exact non-collapsed G210 Leanstral failure class."""

    if failure_code is None:
        return LeanstralFailureClass.NONE
    failure_class = _LEANSTRAL_FAILURE_CLASS_BY_G210_CODE.get(failure_code)
    if failure_class is None:
        raise MetricsContractError(
            "Leanstral G210 failure code is not split and preregistered"
        )
    return failure_class


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


def HSSLEV2108F34() -> str:
    """Return the G210 causal-rescue accounting evidence marker."""

    return _contracts.HSSLEV2108F34()


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


def _cid(
    value: object,
    field_name: str,
    *,
    codecs: tuple[str, ...] = ("dag-json",),
) -> str:
    try:
        return validate_cid(value, codecs=codecs)
    except ValueError as exc:
        raise MetricsContractError(
            f"{field_name} must be a canonical CIDv1"
        ) from exc


def _plain_json(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
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
        kernel = next(
            (
                stage
                for stage in result.stages
                if stage.stage is StageName.KERNEL
            ),
            None,
        )
        if kernel is not None:
            graph_invoked = kernel.provenance.effective_identity.get(
                "graph_invoked"
            )
            graph_bound = any(
                type(
                    stage.provenance.effective_identity.get(
                        "graph_invoked"
                    )
                )
                is bool
                for stage in result.stages
            )
            has_native_receipt = (
                isinstance(kernel.data, Mapping)
                and kernel.data.get("schema")
                == NATIVE_KERNEL_RECEIPT_SCHEMA
            )
            if graph_invoked is True:
                validate_native_kernel_stage_receipt(kernel)
            elif graph_invoked is False and (
                kernel.kernel_accepted or has_native_receipt
            ):
                raise ProtocolContractError(
                    "suppressed kernel stage contains native receipt authority"
                )
            elif graph_bound and graph_invoked is not False:
                raise ProtocolContractError(
                    "kernel stage lacks an explicit graph invocation decision"
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
            setup = extract_symai_cache_setup_telemetry(stage)
            if setup is not None:
                _add_telemetry(telemetry_totals, setup)
                setup_lane = lanes[setup.resource_lane.value]
                try:
                    setup_lane["stage_count"] += max(
                        0,
                        symai_backend_invocation_count(stage) - 1,
                    )
                except ProtocolContractError as exc:
                    raise MetricsContractError(
                        "SyMAI backend invocation accounting is invalid"
                    ) from exc
                _add_telemetry(setup_lane, setup)

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
        graph_bound = any(
            type(
                stage.provenance.effective_identity.get(
                    "graph_invoked"
                )
            )
            is bool
            for stage in result.stages
        )
        selected_candidate_source: str | None = None
        if graph_bound:
            kernel = next(
                (
                    stage
                    for stage in result.stages
                    if stage.stage is StageName.KERNEL
                ),
                None,
            )
            if (
                kernel is not None
                and kernel.provenance.effective_identity.get(
                    "graph_invoked"
                )
                is True
            ):
                accepted = validate_native_kernel_stage_receipt(kernel)
                candidate_source = (
                    kernel.data.get("candidate_source")
                    if isinstance(kernel.data, Mapping)
                    else None
                )
                if accepted and isinstance(candidate_source, str):
                    selected_candidate_source = candidate_source
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
            setup = extract_symai_cache_setup_telemetry(stage)
            inclusive_retries = stage.telemetry.retries + (
                0 if setup is None else setup.retries
            )
            if (
                cost.model_calls
                != stage.telemetry.model_calls
                + (0 if setup is None else setup.model_calls)
                or cost.retries != inclusive_retries
            ):
                raise MetricsContractError(
                    f"{cost.component_id} model-call/retry cost does not match "
                    "case-result telemetry"
                )
            if graph_bound:
                graph_invoked = (
                    stage.provenance.effective_identity.get(
                        "graph_invoked"
                    )
                    is True
                )
                if stage.stage is StageName.SYMAI:
                    try:
                        expected_component_calls = (
                            symai_backend_invocation_count(stage)
                        )
                    except ProtocolContractError as exc:
                        raise MetricsContractError(
                            "SyMAI backend invocation accounting is invalid"
                        ) from exc
                else:
                    expected_component_calls = int(graph_invoked)
                expected_failed_attempts = (
                    inclusive_retries
                    + int(
                        graph_invoked
                        and stage.status is not StageStatus.SUCCESS
                    )
                )
                expected_useful_calls = int(
                    graph_invoked
                    and result.status is OutcomeStatus.VERIFIED
                    and selected_candidate_source == cost.component_id
                )
                if (
                    cost.component_calls != expected_component_calls
                    or cost.failed_attempts
                    != expected_failed_attempts
                    or cost.useful_component_calls
                    != expected_useful_calls
                ):
                    raise MetricsContractError(
                        f"{cost.component_id} component-call attribution "
                        "does not match graph, retry, failure, and terminal "
                        "candidate receipts"
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
            setup = extract_symai_cache_setup_telemetry(stage)
            retries += stage.telemetry.retries + (
                0 if setup is None else setup.retries
            )
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
            and item.case_result.terminal_kernel_accepted
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


def _validated_causal_selection_receipt(
    value: object,
) -> Mapping[str, object]:
    validator = getattr(
        _contracts,
        "validate_causal_proof_selection_receipt",
        None,
    )
    if not callable(validator):
        raise MetricsContractError(
            "the G210 causal proof selection contract is unavailable"
        )
    try:
        validated = validator(value)
    except ProtocolContractError as exc:
        raise MetricsContractError(
            f"invalid causal proof selection receipt: {exc}"
        ) from exc
    return _mapping(validated, "causal proof selection receipt")


def _causal_optional_candidates(
    selection: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    raw = selection.get("optional_candidates")
    if not isinstance(raw, (list, tuple)):
        raise MetricsContractError(
            "causal proof optional_candidates must be an array"
        )
    candidates = tuple(
        _mapping(item, "causal proof optional candidate") for item in raw
    )
    sources = tuple(item.get("source") for item in candidates)
    route_indexes = tuple(item.get("route_index") for item in candidates)
    if (
        route_indexes != tuple(range(len(candidates)))
        or len(sources) != len(set(sources))
        or any(source not in {"hammer", "leanstral"} for source in sources)
    ):
        raise MetricsContractError(
            "causal proof optional candidates must be unique and in route order"
        )
    return candidates


def _leanstral_failure_class(
    result: CaseResultRecord,
    candidate: Mapping[str, object] | None,
) -> LeanstralFailureClass:
    stage = next(
        (
            item
            for item in result.stages
            if item.stage is StageName.LEANSTRAL
        ),
        None,
    )
    invoked = candidate is not None and candidate.get("invoked") is True
    selection_failure_code = (
        None if candidate is None else candidate.get("failure_code")
    )
    if stage is None:
        if invoked:
            raise MetricsContractError(
                "invoked Leanstral candidate lacks a stage receipt"
            )
        return LeanstralFailureClass.NONE
    if not invoked:
        if selection_failure_code is not None:
            raise MetricsContractError(
                "suppressed Leanstral route carries a failure claim"
            )
        return LeanstralFailureClass.NONE
    if stage.status is StageStatus.SUCCESS:
        if selection_failure_code is not None:
            raise MetricsContractError(
                "successful Leanstral stage carries a failure claim"
            )
        return LeanstralFailureClass.NONE
    if selection_failure_code is None:
        raise MetricsContractError(
            "failed Leanstral stage lacks its selection failure code"
        )
    data = (
        stage.data
        if isinstance(stage.data, Mapping)
        else MappingProxyType({})
    )
    safe_class = data.get("safe_failure_class")
    failure_class = _LEANSTRAL_FAILURE_CLASS_BY_SAFE_CLASS.get(safe_class)
    if failure_class is None:
        raise MetricsContractError(
            "invoked failed Leanstral stage lacks a split G210 failure class"
        )
    selection_class = classify_leanstral_failure_code(
        str(selection_failure_code)
    )
    if selection_class is not failure_class:
        raise MetricsContractError(
            "Leanstral selection and stage failure classes disagree"
        )
    return failure_class


def _stage_component_measurement(
    result: CaseResultRecord,
    *,
    component_id: str,
    invoked: bool,
    kernel_checked: bool,
    causal_rescue: bool,
    overlap: bool,
    continuation_kind: str,
    failure_class: LeanstralFailureClass,
) -> dict[str, object]:
    stage_name = StageName(component_id)
    stage = next(
        (item for item in result.stages if item.stage is stage_name),
        None,
    )
    if stage is None:
        if invoked:
            raise MetricsContractError(
                f"invoked {component_id} lacks a stage receipt"
            )
        wall_time_ms = 0.0
        model_calls = 0
        retries = 0
        peak_memory_bytes = 0
    else:
        graph_invoked = stage.provenance.effective_identity.get(
            "graph_invoked"
        )
        if type(graph_invoked) is not bool:
            raise MetricsContractError(
                f"{component_id} stage lacks an exact graph_invoked marker"
            )
        if graph_invoked is not invoked:
            raise MetricsContractError(
                f"{component_id} selection invocation disagrees with graph receipt"
            )
        if not invoked:
            if stage.telemetry.model_calls or stage.telemetry.retries:
                raise MetricsContractError(
                    f"suppressed {component_id} stage recorded component work"
                )
            wall_time_ms = 0.0
            model_calls = 0
            retries = 0
            peak_memory_bytes = 0
        else:
            setup = extract_symai_cache_setup_telemetry(stage)
            wall_time_ms = stage.telemetry.wall_time_ms + (
                0.0 if setup is None else setup.wall_time_ms
            )
            model_calls = stage.telemetry.model_calls + (
                0 if setup is None else setup.model_calls
            )
            retries = stage.telemetry.retries + (
                0 if setup is None else setup.retries
            )
            peak_memory_bytes = max(
                stage.telemetry.peak_memory_bytes,
                0 if setup is None else setup.peak_memory_bytes,
            )
    unnecessary = invoked and not causal_rescue
    return {
        "component_id": component_id,
        "invoked": invoked,
        "component_calls": int(invoked),
        "model_calls": model_calls,
        "retries": retries,
        "wall_time_ms": wall_time_ms,
        "peak_memory_bytes": peak_memory_bytes,
        "kernel_checks": int(kernel_checked),
        "unique_wins": int(causal_rescue),
        "unnecessary_work": unnecessary,
        "unnecessary_component_calls": int(unnecessary),
        "overlap_zero_marginal": overlap,
        "continuation_kind": continuation_kind,
        "leanstral_failure_class": failure_class.value,
    }


def _replay_causal_kernel_sidecars(
    result: CaseResultRecord,
    selection: Mapping[str, object],
    kernel_stage: object,
) -> Mapping[str, Mapping[str, object]]:
    raw_sidecars = selection.get("kernel_receipts")
    if not isinstance(raw_sidecars, (list, tuple)):
        raise MetricsContractError(
            "causal selection kernel_receipts must be an array"
        )
    stage = kernel_stage
    if not isinstance(stage, _contracts.StageRecord):
        raise MetricsContractError(
            "causal sidecar replay requires a kernel StageRecord"
        )
    expected_environment = _result_environment_sha256(result)
    candidate_bindings: dict[str, tuple[str, str]] = {}
    compiler = _mapping(
        selection.get("compiler_reference"),
        "causal compiler reference",
    )
    if compiler.get("kernel_checked") is True:
        compiler_cid = _cid(
            compiler.get("candidate_cid"),
            "causal compiler candidate_cid",
            codecs=("raw",),
        )
        compiler_artifact_cid = _cid(
            compiler.get("artifact_cid"),
            "causal compiler artifact_cid",
            codecs=("raw", "dag-json"),
        )
        candidate_bindings[compiler_cid] = (
            StageName.COMPILER.value,
            compiler_artifact_cid,
        )
    for candidate in _causal_optional_candidates(selection):
        if candidate.get("kernel_checked") is not True:
            continue
        candidate_cid = _cid(
            candidate.get("candidate_cid"),
            "causal optional candidate_cid",
            codecs=("raw",),
        )
        artifact_cid = _cid(
            candidate.get("artifact_cid"),
            "causal optional artifact_cid",
            codecs=("raw", "dag-json"),
        )
        if candidate_cid in candidate_bindings:
            raise MetricsContractError(
                "causal checked candidate identity is duplicated"
            )
        candidate_bindings[candidate_cid] = (
            str(candidate["source"]),
            artifact_cid,
        )
    by_candidate: dict[str, Mapping[str, object]] = {}
    receipt_cids: set[str] = set()
    for raw in raw_sidecars:
        sidecar = _mapping(raw, "causal kernel sidecar")
        expected_fields = {
            "run_id": result.run_id,
            "case_id": result.case_id,
            "variant_id": result.variant_id,
            "source_cid": selection["source_cid"],
            "protocol_cid": selection["protocol_cid"],
            "variant_profile_cid": selection["variant_profile_cid"],
        }
        if any(
            sidecar.get(field) != expected
            for field, expected in expected_fields.items()
        ):
            raise MetricsContractError(
                "causal kernel sidecar coordinate or profile binding changed"
            )
        candidate_cid = _cid(
            sidecar.get("candidate_cid"),
            "causal sidecar candidate_cid",
            codecs=("raw",),
        )
        receipt_cid = _cid(
            sidecar.get("receipt_cid"),
            "causal sidecar receipt_cid",
        )
        if candidate_cid in by_candidate or receipt_cid in receipt_cids:
            raise MetricsContractError(
                "causal kernel sidecars repeat a candidate or receipt"
            )
        binding = candidate_bindings.get(candidate_cid)
        if binding is None:
            raise MetricsContractError(
                "causal kernel sidecar lacks a selected candidate binding"
            )
        expected_source, artifact_cid = binding
        artifact_sha256 = sha256_digest_for_cid(
            artifact_cid, codecs=("raw", "dag-json")
        )
        receipt = _mapping(
            sidecar.get("receipt"), "causal sidecar native receipt"
        )
        if cid_for_dag_json(_plain_json(receipt)) != receipt_cid:
            raise MetricsContractError(
                "causal sidecar native receipt CID changed"
            )
        try:
            stage_status = StageStatus(sidecar.get("stage_status"))
        except (TypeError, ValueError) as exc:
            raise MetricsContractError(
                "causal sidecar stage_status is invalid"
            ) from exc
        raw_failure_code = sidecar.get("failure_code")
        try:
            failure_code = (
                None
                if raw_failure_code is None
                else FailureCode(raw_failure_code)
            )
        except (TypeError, ValueError) as exc:
            raise MetricsContractError(
                "causal sidecar failure_code is invalid"
            ) from exc
        accepted = sidecar.get("kernel_accepted")
        if type(accepted) is not bool:
            raise MetricsContractError(
                "causal sidecar kernel_accepted must be boolean"
            )
        raw_consumed = sidecar.get("consumed_artifact_sha256s")
        if not isinstance(raw_consumed, (list, tuple)):
            raise MetricsContractError(
                "causal sidecar consumed artifacts must be an array"
            )
        consumed = tuple(
            _digest(item, "causal sidecar consumed_artifact_sha256s[]")
            for item in raw_consumed
        )
        if len(consumed) != len(set(consumed)):
            raise MetricsContractError(
                "causal sidecar consumed artifacts contain duplicates"
            )
        if (
            receipt.get("candidate_source") != expected_source
            or receipt.get("candidate_artifact_sha256") != artifact_sha256
            or artifact_sha256 not in consumed
        ):
            raise MetricsContractError(
                "causal candidate CID/artifact differs from native-kernel input"
            )
        attempts = receipt.get("candidate_attempts")
        if (
            not isinstance(attempts, list)
            or len(attempts) != 1
            or not isinstance(attempts[0], Mapping)
            or attempts[0].get("attempt_index") != 0
            or attempts[0].get("candidate_source") != expected_source
            or attempts[0].get("candidate_artifact_sha256")
            != artifact_sha256
        ):
            raise MetricsContractError(
                "causal native sidecar must contain one targeted candidate "
                "attempt"
            )
        if (
            receipt.get("protocol_sha256") != result.protocol_sha256
            or receipt.get("run_id") != result.run_id
            or receipt.get("case_id") != result.case_id
            or receipt.get("case_manifest_sha256")
            != result.case_manifest_sha256
            or receipt.get("variant_id") != result.variant_id
            or receipt.get("split") != result.split.value
            or receipt.get("cache_mode") != result.cache_mode.value
            or receipt.get("input_sha256")
            != stage.provenance.input_sha256
            or receipt.get("environment_sha256") != expected_environment
        ):
            raise MetricsContractError(
                "causal native receipt differs from the CaseResult binding"
            )
        receipt_sha256 = receipt.get("receipt_sha256")
        try:
            replayed = validate_native_kernel_receipt(
                receipt,
                protocol_sha256=result.protocol_sha256,
                run_id=result.run_id,
                case_id=result.case_id,
                case_manifest_sha256=result.case_manifest_sha256,
                variant_id=result.variant_id,
                split=result.split,
                cache_mode=result.cache_mode,
                input_sha256=stage.provenance.input_sha256,
                environment_sha256=expected_environment,
                stage_status=stage_status,
                kernel_accepted=accepted,
                kernel_receipt_sha256=(
                    _digest(
                        receipt_sha256,
                        "causal native receipt_sha256",
                    )
                    if accepted
                    else None
                ),
                consumed_artifact_sha256s=consumed,
                failure_code=failure_code,
            )
        except ProtocolContractError as exc:
            raise MetricsContractError(
                f"causal native sidecar failed replay: {exc}"
            ) from exc
        if replayed is not accepted:
            raise MetricsContractError(
                "causal native sidecar authority changed during replay"
            )
        by_candidate[candidate_cid] = MappingProxyType(
            {
                "candidate_cid": candidate_cid,
                "receipt_cid": receipt_cid,
                "accepted": accepted,
                "receipt": receipt,
            }
        )
        receipt_cids.add(receipt_cid)
    if set(by_candidate) != set(candidate_bindings):
        raise MetricsContractError(
            "causal checked candidate lacks a native-kernel sidecar"
        )
    return MappingProxyType(by_candidate)


def _causal_case_body(
    result: CaseResultRecord,
    selection: Mapping[str, object],
) -> dict[str, object]:
    validated_result = validate_kernel_bound_result(result)
    if selection.get("proof_authority") != "native_kernel":
        raise MetricsContractError(
            "causal rescue accounting requires native-kernel proof authority"
        )
    for field, expected in (
        ("run_id", validated_result.run_id),
        ("case_id", validated_result.case_id),
        ("variant_id", validated_result.variant_id),
    ):
        if selection.get(field) != expected:
            raise MetricsContractError(
                f"causal selection {field} differs from the case result"
            )
    source_cid = _cid(
        selection.get("source_cid"),
        "causal selection source_cid",
        codecs=("raw",),
    )
    proof_stages = {
        StageName.COMPILER,
        StageName.HAMMER,
        StageName.LEANSTRAL,
        StageName.KERNEL,
    }
    for stage in validated_result.stages:
        if stage.stage not in proof_stages:
            continue
        for identity_name, identity in (
            ("requested", stage.provenance.requested_identity),
            ("effective", stage.provenance.effective_identity),
        ):
            if identity.get("source_cid") != source_cid:
                raise MetricsContractError(
                    f"{stage.stage.value} {identity_name} identity is not "
                    "bound to the causal source CID"
                )

    selection_cid = _cid(
        selection.get("receipt_cid"),
        "causal selection receipt_cid",
    )
    selection_body = {
        key: _plain_json(item)
        for key, item in selection.items()
        if key != "receipt_cid"
    }
    if cid_for_dag_json(selection_body) != selection_cid:
        raise MetricsContractError(
            "causal selection receipt CID does not match its body"
        )

    kernel = next(
        (
            stage
            for stage in validated_result.stages
            if stage.stage is StageName.KERNEL
        ),
        None,
    )
    if kernel is None:
        raise MetricsContractError(
            "causal rescue accounting requires a native-kernel stage"
        )
    try:
        kernel_accepted = validate_native_kernel_stage_receipt(kernel)
    except ProtocolContractError as exc:
        raise MetricsContractError(
            f"causal native-kernel receipt is invalid: {exc}"
        ) from exc
    sidecars = _replay_causal_kernel_sidecars(
        validated_result,
        selection,
        kernel,
    )
    native_receipt_cids = sorted(
        str(item["receipt_cid"]) for item in sidecars.values()
    )

    compiler = _mapping(
        selection.get("compiler_reference"),
        "causal compiler reference",
    )
    compiler_state = compiler.get("state")
    if compiler_state not in {"absent", "rejected", "accepted"}:
        raise MetricsContractError(
            "causal compiler reference state is invalid"
        )
    compiler_candidate_cid = compiler.get("candidate_cid")
    if compiler_candidate_cid is not None:
        compiler_candidate_cid = _cid(
            compiler_candidate_cid,
            "compiler candidate_cid",
            codecs=("raw",),
        )
    compiler_check = (
        None
        if compiler_candidate_cid is None
        else sidecars.get(compiler_candidate_cid)
    )
    expected_compiler_state = (
        "absent"
        if compiler_candidate_cid is None
        else (
            "accepted"
            if compiler_check is not None
            and compiler_check.get("accepted") is True
            else "rejected"
        )
    )
    if compiler_state != expected_compiler_state:
        raise MetricsContractError(
            "compiler reference state disagrees with native-kernel evidence"
        )
    if compiler_candidate_cid is not None and compiler_check is None:
        raise MetricsContractError(
            "compiler reference lacks its replayed native sidecar"
        )
    if (
        compiler_check is not None
        and _mapping(
            compiler_check["receipt"], "compiler native receipt"
        ).get("candidate_source")
        != StageName.COMPILER.value
    ):
        raise MetricsContractError(
            "compiler sidecar validated a non-compiler candidate"
        )
    if compiler.get("kernel_checked") is not (compiler_check is not None):
        raise MetricsContractError(
            "compiler kernel-check flag disagrees with native-kernel evidence"
        )
    if compiler.get("kernel_receipt_cid") != (
        None if compiler_check is None else compiler_check["receipt_cid"]
    ):
        raise MetricsContractError(
            "compiler kernel receipt CID disagrees with its sidecar"
        )
    if compiler.get("accepted") is not (
        compiler_state == "accepted"
    ):
        raise MetricsContractError(
            "compiler acceptance disagrees with its reference state"
        )

    optionals = _causal_optional_candidates(selection)
    component_measurements: list[dict[str, object]] = []
    compiler_stage = next(
        (
            item
            for item in validated_result.stages
            if item.stage is StageName.COMPILER
        ),
        None,
    )
    if compiler_stage is None:
        raise MetricsContractError(
            "causal compiler reference lacks its immutable stage receipt"
        )
    compiler_process_invoked = (
        compiler_stage.provenance.effective_identity.get(
            "graph_invoked"
        )
    )
    if compiler_process_invoked is not True:
        raise MetricsContractError(
            "causal compiler reference lacks explicit process exposure"
        )
    if (
        compiler.get("invoked") is True
    ) is not (compiler_candidate_cid is not None):
        raise MetricsContractError(
            "compiler candidate-presence marker disagrees with its bytes"
        )
    component_measurements.append(
        _stage_component_measurement(
            validated_result,
            component_id=StageName.COMPILER.value,
            invoked=compiler_process_invoked,
            kernel_checked=compiler_check is not None,
            causal_rescue=False,
            overlap=False,
            continuation_kind="none",
            failure_class=LeanstralFailureClass.NONE,
        )
    )

    selected_source = selection.get("selected_source")
    selected_candidate_cid = selection.get("selected_candidate_cid")
    selected_kernel_receipt_cid = selection.get(
        "selected_kernel_receipt_cid"
    )
    selected_check: Mapping[str, object] | None = None
    if selected_candidate_cid is not None:
        selected_candidate_cid = _cid(
            selected_candidate_cid,
            "selected_candidate_cid",
            codecs=("raw",),
        )
        selected_check = sidecars.get(selected_candidate_cid)
    if kernel_accepted:
        if (
            selected_source not in {
                StageName.COMPILER.value,
                StageName.HAMMER.value,
                StageName.LEANSTRAL.value,
            }
            or selected_check is None
            or selected_check.get("accepted") is not True
            or selected_kernel_receipt_cid
            != selected_check.get("receipt_cid")
        ):
            raise MetricsContractError(
                "selected causal candidate differs from native-kernel authority"
            )
    elif any(
        item is not None
        for item in (
            selected_source,
            selected_candidate_cid,
            selected_kernel_receipt_cid,
        )
    ):
        raise MetricsContractError(
            "rejected native-kernel result cannot select a proof candidate"
        )
    terminal_selection_cid = kernel.provenance.effective_identity.get(
        "causal_selection_receipt_cid"
    )
    terminal_body = (
        {
            key: _plain_json(item)
            for key, item in _mapping(
                kernel.data, "causal terminal kernel receipt"
            ).items()
            if key != "routing_policy"
        }
    )
    if terminal_selection_cid != selection_cid:
        raise MetricsContractError(
            "terminal CaseResult is not bound to the causal selection receipt"
        )
    raw_sidecars = selection["kernel_receipts"]
    assert isinstance(raw_sidecars, list)
    if raw_sidecars:
        expected_terminal_cid = (
            selected_kernel_receipt_cid
            if selected_kernel_receipt_cid is not None
            else _mapping(
                raw_sidecars[-1], "terminal causal sidecar"
            )["receipt_cid"]
        )
        expected_terminal = next(
            (
                item
                for item in sidecars.values()
                if item["receipt_cid"] == expected_terminal_cid
            ),
            None,
        )
        if (
            expected_terminal is None
            or terminal_body != _plain_json(expected_terminal["receipt"])
        ):
            raise MetricsContractError(
                "terminal native receipt differs from the causal check sequence"
            )

    eligible_reference = compiler_state in {"absent", "rejected"}
    case_rescues: list[str] = []
    overlaps: list[str] = []
    continuation_after_model_failure: list[str] = []
    prior_candidate_cids = (
        set()
        if compiler_candidate_cid is None
        else {compiler_candidate_cid}
    )
    prior_model_failure = False
    prior_accepted = compiler_state == "accepted"
    for route_index, candidate in enumerate(optionals):
        source = str(candidate["source"])
        invoked = candidate.get("invoked") is True
        checked = candidate.get("kernel_checked") is True
        accepted = candidate.get("accepted") is True
        trigger_eligible = candidate.get("trigger_eligible") is True
        causal_credit_eligible = (
            candidate.get("causal_credit_eligible") is True
        )
        candidate_cid = candidate.get("candidate_cid")
        if candidate_cid is not None:
            candidate_cid = _cid(
                candidate_cid,
                f"{source} candidate_cid",
                codecs=("raw",),
            )
        check = (
            sidecars.get(candidate_cid)
            if checked and candidate_cid is not None
            else None
        )
        if checked and check is None:
            raise MetricsContractError(
                f"{source} kernel-check flag disagrees with native receipt"
            )
        if accepted is not (
            check is not None and check.get("accepted") is True
        ):
            raise MetricsContractError(
                f"{source} acceptance disagrees with native receipt"
            )
        if (
            check is not None
            and _mapping(
                check["receipt"], f"{source} native receipt"
            ).get("candidate_source")
            != source
        ):
            raise MetricsContractError(
                f"{source} sidecar validated a different candidate source"
            )
        if candidate.get("kernel_receipt_cid") != (
            None if check is None else check["receipt_cid"]
        ):
            raise MetricsContractError(
                f"{source} kernel receipt CID disagrees with its sidecar"
            )
        if checked and not invoked:
            raise MetricsContractError(
                f"{source} cannot be kernel checked without invocation"
            )
        if trigger_eligible and not eligible_reference:
            raise MetricsContractError(
                f"{source} escalation was eligible after compiler acceptance"
            )
        if causal_credit_eligible is not (
            eligible_reference
            and not prior_model_failure
            and not prior_accepted
        ):
            raise MetricsContractError(
                f"{source} causal-credit eligibility is not route-derived"
            )
        overlap = (
            candidate_cid is not None
            and candidate_cid in prior_candidate_cids
        )
        if candidate.get("overlap") is not overlap:
            raise MetricsContractError(
                f"{source} overlap differs from raw candidate CIDs"
            )
        continuation_kind = _text(
            candidate.get("continuation_kind"),
            f"{source} continuation_kind",
        )
        failure_code = candidate.get("failure_code")
        expected_continuation = (
            "suppressed"
            if not invoked
            else (
                (
                    "post_model_failure_continuation"
                    if source == StageName.LEANSTRAL.value
                    else "post_solver_failure_continuation"
                )
                if failure_code is not None
                and route_index + 1 < len(optionals)
                else (
                    "terminal_producer_failure"
                    if failure_code is not None
                    else (
                        "post_overlap_continuation"
                        if overlap
                        else (
                            (
                                "selected_post_model_failure_continuation"
                                if prior_model_failure
                                else "selected_causal_rescue"
                            )
                            if accepted
                            else "post_kernel_rejection_continuation"
                        )
                    )
                )
            )
        )
        if continuation_kind != expected_continuation:
            raise MetricsContractError(
                f"{source} continuation classification is not recomputable"
            )
        after_model_failure = continuation_kind in {
            "after_model_failure",
            "model_failure_continuation",
            "post_model_failure_continuation",
            "selected_post_model_failure_continuation",
        }
        causal_rescue = (
            eligible_reference
            and causal_credit_eligible
            and trigger_eligible
            and invoked
            and checked
            and accepted
            and candidate_cid is not None
            and not overlap
            and not after_model_failure
            and not prior_model_failure
        )
        if candidate.get("causal_rescue") is not causal_rescue:
            raise MetricsContractError(
                f"{source} causal-rescue claim is not source causal"
            )
        expected_credit = 1_000_000 if causal_rescue else 0
        if candidate.get("marginal_credit_millionths") != expected_credit:
            raise MetricsContractError(
                f"{source} marginal credit disagrees with causal rescue"
            )
        if overlap and expected_credit:
            raise MetricsContractError(
                "byte-identical overlap cannot receive marginal efficacy"
            )
        if causal_rescue:
            case_rescues.append(source)
        if overlap:
            overlaps.append(source)
        if after_model_failure:
            continuation_after_model_failure.append(source)
        if candidate_cid is not None:
            prior_candidate_cids.add(candidate_cid)
        if source == StageName.LEANSTRAL.value and failure_code is not None:
            prior_model_failure = True
        prior_accepted = bool(prior_accepted or accepted)
        failure_class = (
            _leanstral_failure_class(validated_result, candidate)
            if source == StageName.LEANSTRAL.value
            else LeanstralFailureClass.NONE
        )
        component_measurements.append(
            _stage_component_measurement(
                validated_result,
                component_id=source,
                invoked=invoked,
                kernel_checked=checked,
                causal_rescue=causal_rescue,
                overlap=overlap,
                continuation_kind=continuation_kind,
                failure_class=failure_class,
            )
        )

    if len(case_rescues) > 1:
        raise MetricsContractError(
            "one case cannot credit more than one causal rescue"
        )
    if case_rescues and selected_source != case_rescues[0]:
        raise MetricsContractError(
            "causal rescue does not match the native-kernel selected source"
        )
    case_result_value = _plain_json(validated_result.to_dict())
    case_result_cid = cid_for_dag_json(case_result_value)
    return {
        "schema": CAUSAL_RESCUE_CASE_RECEIPT_SCHEMA,
        "protocol_cid": selection["protocol_cid"],
        "variant_profile_cid": selection["variant_profile_cid"],
        "run_id": validated_result.run_id,
        "case_id": validated_result.case_id,
        "variant_id": validated_result.variant_id,
        "source_cid": source_cid,
        "case_result": case_result_value,
        "case_result_cid": case_result_cid,
        "selection_receipt": _plain_json(selection),
        "selection_receipt_cid": selection_cid,
        "native_kernel_receipt_cids": native_receipt_cids,
        "compiler_reference_state": compiler_state,
        "eligible_reference": eligible_reference,
        "causal_rescue_source": (
            None if not case_rescues else case_rescues[0]
        ),
        "overlap_sources": overlaps,
        "model_failure_continuation_sources": (
            continuation_after_model_failure
        ),
        "component_measurements": component_measurements,
    }


def build_causal_rescue_case_receipt(
    case_result: CaseResultRecord,
    selection_receipt: object,
) -> dict[str, object]:
    """Build a source- and native-kernel-bound G210 case measurement."""

    if not isinstance(case_result, CaseResultRecord):
        raise MetricsContractError(
            "causal rescue accounting requires a CaseResultRecord"
        )
    selection = _validated_causal_selection_receipt(selection_receipt)
    body = _causal_case_body(case_result, selection)
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def validate_causal_rescue_case_receipt(
    value: object,
) -> dict[str, object]:
    """Recompute every causal classification and resource field."""

    data = _mapping(value, "causal rescue case receipt")
    expected = {
        "schema",
        "protocol_cid",
        "variant_profile_cid",
        "run_id",
        "case_id",
        "variant_id",
        "source_cid",
        "case_result",
        "case_result_cid",
        "selection_receipt",
        "selection_receipt_cid",
        "native_kernel_receipt_cids",
        "compiler_reference_state",
        "eligible_reference",
        "causal_rescue_source",
        "overlap_sources",
        "model_failure_continuation_sources",
        "component_measurements",
        "receipt_cid",
    }
    _exact_keys(data, expected, "causal rescue case receipt")
    if data.get("schema") != CAUSAL_RESCUE_CASE_RECEIPT_SCHEMA:
        raise MetricsContractError(
            "unsupported causal rescue case-receipt schema"
        )
    try:
        result = CaseResultRecord.from_dict(data["case_result"])
    except ProtocolContractError as exc:
        raise MetricsContractError(
            f"invalid causal rescue case result: {exc}"
        ) from exc
    rebuilt = build_causal_rescue_case_receipt(
        result,
        data["selection_receipt"],
    )
    if _plain_json(data) != rebuilt:
        raise MetricsContractError(
            "causal rescue case receipt fields or CID changed"
        )
    return rebuilt


def _causal_component_aggregate(
    receipts: tuple[Mapping[str, object], ...],
    component_id: str,
) -> dict[str, object]:
    rows: list[tuple[str, Mapping[str, object], Mapping[str, object]]] = []
    for receipt in receipts:
        selection = _mapping(
            receipt["selection_receipt"], "selection_receipt"
        )
        optional = {
            str(item["source"]): item
            for item in _causal_optional_candidates(selection)
        }
        measurements = {
            str(item["component_id"]): item
            for item in (
                _mapping(raw, "component_measurement")
                for raw in receipt["component_measurements"]  # type: ignore[union-attr]
            )
        }
        rows.append(
            (
                str(receipt["receipt_cid"]),
                optional[component_id],
                measurements[component_id],
            )
        )

    def cids(predicate) -> list[str]:
        return sorted(
            receipt_cid
            for receipt_cid, candidate, measurement in rows
            if predicate(candidate, measurement)
        )

    eligible = cids(
        lambda candidate, measurement: candidate["trigger_eligible"] is True
    )
    credit_eligible = cids(
        lambda candidate, measurement: (
            candidate["causal_credit_eligible"] is True
        )
    )
    invoked = cids(
        lambda candidate, measurement: measurement["invoked"] is True
    )
    escalated = sorted(set(eligible).intersection(invoked))
    suppressed = cids(
        lambda candidate, measurement: (
            candidate["trigger_eligible"] is False
            and measurement["invoked"] is False
        )
    )
    checked = cids(
        lambda candidate, measurement: measurement["kernel_checks"] == 1
    )
    accepted = cids(
        lambda candidate, measurement: candidate["accepted"] is True
    )
    rescued = cids(
        lambda candidate, measurement: measurement["unique_wins"] == 1
    )
    overlap = cids(
        lambda candidate, measurement: (
            measurement["overlap_zero_marginal"] is True
        )
    )
    unnecessary = cids(
        lambda candidate, measurement: (
            measurement["unnecessary_work"] is True
        )
    )
    continuations = cids(
        lambda candidate, measurement: measurement["continuation_kind"]
        in {
            "after_model_failure",
            "model_failure_continuation",
            "post_model_failure_continuation",
            "selected_post_model_failure_continuation",
        }
    )
    failure_classes = {
        member.value: cids(
            lambda candidate, measurement, value=member.value: (
                measurement["leanstral_failure_class"] == value
            )
        )
        for member in LeanstralFailureClass
        if member is not LeanstralFailureClass.NONE
    }
    return {
        "component_id": component_id,
        "scheduled_receipt_cids": sorted(item[0] for item in rows),
        "eligible_receipt_cids": eligible,
        "causal_credit_eligible_receipt_cids": credit_eligible,
        "invoked_receipt_cids": invoked,
        "escalated_receipt_cids": escalated,
        "suppressed_receipt_cids": suppressed,
        "kernel_checked_receipt_cids": checked,
        "kernel_accepted_receipt_cids": accepted,
        "unique_win_receipt_cids": rescued,
        "overlap_receipt_cids": overlap,
        "unnecessary_work_receipt_cids": unnecessary,
        "model_failure_continuation_receipt_cids": continuations,
        "failure_class_receipt_cids": failure_classes,
        "scheduled_count": len(rows),
        "eligible_count": len(eligible),
        "causal_credit_eligible_count": len(credit_eligible),
        "invoked_count": len(invoked),
        "escalated_count": len(escalated),
        "suppressed_count": len(suppressed),
        "kernel_checked_count": len(checked),
        "kernel_accepted_count": len(accepted),
        "unique_win_count": len(rescued),
        "overlap_count": len(overlap),
        "unnecessary_work_count": len(unnecessary),
        "model_failure_continuation_count": len(continuations),
        "failure_class_counts": {
            key: len(value) for key, value in failure_classes.items()
        },
        "wall_time_ms": math.fsum(
            float(measurement["wall_time_ms"])
            for _, _, measurement in rows
        ),
        "component_calls": sum(
            int(measurement["component_calls"])
            for _, _, measurement in rows
        ),
        "model_calls": sum(
            int(measurement["model_calls"])
            for _, _, measurement in rows
        ),
        "retries": sum(
            int(measurement["retries"])
            for _, _, measurement in rows
        ),
        "peak_memory_bytes": max(
            (
                int(measurement["peak_memory_bytes"])
                for _, _, measurement in rows
            ),
            default=0,
        ),
        "rate_populations": {
            "escalation": {
                "event_receipt_cids": escalated,
                "population_receipt_cids": eligible,
            },
            "suppression": {
                "event_receipt_cids": suppressed,
                "population_receipt_cids": sorted(
                    item[0] for item in rows
                ),
            },
            "causal_rescue": {
                "event_receipt_cids": rescued,
                "population_receipt_cids": credit_eligible,
            },
            "kernel_acceptance": {
                "event_receipt_cids": accepted,
                "population_receipt_cids": checked,
            },
            "overlap": {
                "event_receipt_cids": overlap,
                "population_receipt_cids": invoked,
            },
            "unnecessary_work": {
                "event_receipt_cids": unnecessary,
                "population_receipt_cids": invoked,
            },
        },
    }


def aggregate_causal_rescue_receipts(
    values: Iterable[object],
) -> dict[str, object]:
    """Aggregate G210 receipts without changing native proof authority."""

    receipts = tuple(
        validate_causal_rescue_case_receipt(value) for value in values
    )
    if not receipts:
        raise MetricsContractError(
            "causal rescue aggregation requires case receipts"
        )
    identities = {
        (
            item["protocol_cid"],
            item["variant_profile_cid"],
            item["run_id"],
            item["variant_id"],
        )
        for item in receipts
    }
    if len(identities) != 1:
        raise MetricsContractError(
            "causal rescue aggregation cannot pool protocol, profile, run, "
            "or variant identities"
        )
    case_ids = [str(item["case_id"]) for item in receipts]
    if len(case_ids) != len(set(case_ids)):
        raise MetricsContractError(
            "causal rescue aggregation contains duplicate cases"
        )
    ordered = tuple(sorted(receipts, key=lambda item: str(item["case_id"])))
    protocol_cid, profile_cid, run_id, variant_id = identities.pop()
    optional_sources = tuple(
        str(item["source"])
        for item in _causal_optional_candidates(
            _mapping(
                ordered[0]["selection_receipt"],
                "selection_receipt",
            )
        )
    )
    for receipt in ordered[1:]:
        current_sources = tuple(
            str(item["source"])
            for item in _causal_optional_candidates(
                _mapping(
                    receipt["selection_receipt"],
                    "selection_receipt",
                )
            )
        )
        if current_sources != optional_sources:
            raise MetricsContractError(
                "causal aggregate mixed optional route profiles"
            )
    body = {
        "schema": CAUSAL_RESCUE_AGGREGATE_SCHEMA,
        "protocol_cid": protocol_cid,
        "variant_profile_cid": profile_cid,
        "run_id": run_id,
        "variant_id": variant_id,
        "case_count": len(ordered),
        "case_ids": [item["case_id"] for item in ordered],
        "case_receipt_cids": sorted(
            str(item["receipt_cid"]) for item in ordered
        ),
        "case_receipts": [_plain_json(item) for item in ordered],
        "proof_authority": "native_kernel",
        "components": {
            source: _causal_component_aggregate(ordered, source)
            for source in sorted(optional_sources)
        },
    }
    return {**body, "aggregate_cid": cid_for_dag_json(body)}


def validate_causal_rescue_aggregate(
    value: object,
) -> dict[str, object]:
    """Validate an aggregate when its complete case sidecars are present."""

    data = _mapping(value, "causal rescue aggregate")
    expected = {
        "schema",
        "protocol_cid",
        "variant_profile_cid",
        "run_id",
        "variant_id",
        "case_count",
        "case_ids",
        "case_receipt_cids",
        "case_receipts",
        "proof_authority",
        "components",
        "aggregate_cid",
    }
    _exact_keys(data, expected, "causal rescue aggregate")
    if data.get("schema") != CAUSAL_RESCUE_AGGREGATE_SCHEMA:
        raise MetricsContractError(
            "unsupported causal rescue aggregate schema"
        )
    aggregate_cid = _cid(
        data.get("aggregate_cid"),
        "causal rescue aggregate_cid",
    )
    body = {
        key: _plain_json(item)
        for key, item in data.items()
        if key != "aggregate_cid"
    }
    if cid_for_dag_json(body) != aggregate_cid:
        raise MetricsContractError(
            "causal rescue aggregate CID does not match its body"
        )
    case_receipts = data.get("case_receipts")
    if not isinstance(case_receipts, list):
        raise MetricsContractError(
            "causal rescue case_receipts must be an array"
        )
    rebuilt = aggregate_causal_rescue_receipts(case_receipts)
    if _plain_json(data) != rebuilt:
        raise MetricsContractError(
            "causal rescue aggregate fields, denominators, costs, or CID changed"
        )
    return rebuilt


# Descriptive alias for callers that discover this boundary through the
# objective title rather than the lower-level case-result vocabulary.
aggregate_kernel_bound_results = aggregate_case_results


__all__ = [
    "CAUSAL_RESCUE_AGGREGATE_SCHEMA",
    "CAUSAL_RESCUE_CASE_RECEIPT_SCHEMA",
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
    "HSSLEV2108F34",
    "KERNEL_BOUND_AGGREGATE_SCHEMA",
    "KernelBoundAggregate",
    "LeanstralFailureClass",
    "MetricsContractError",
    "aggregate_causal_rescue_receipts",
    "analyze_delegation_efficiency",
    "aggregate_case_results",
    "aggregate_kernel_bound_results",
    "build_causal_rescue_case_receipt",
    "classify_leanstral_failure_code",
    "validate_causal_rescue_aggregate",
    "validate_causal_rescue_case_receipt",
    "validate_kernel_bound_result",
]
