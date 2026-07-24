"""Seeded, stage-aware execution for the logic-pipeline ablation protocol.

This module is the implementation behind the public facade in ``runner.py``.
It is separate only to keep the frozen A0 implementation readable.  Plans are
self-contained, immutable JSON records; each scheduled result is written once
and reparsed before it may be treated as completed during resume.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .adapters import (
    StageAdapter,
    StageArtifact,
    StageInvocation,
    StageOutput,
    StageRequest,
)
from .cases import BenchmarkCase
from .capabilities import (
    ResourceClass,
    ResourceLeaseCancelled,
    ResourceLeaseError,
    ResourceLeaseReceipt,
    ResourceLeaseRequest,
    ResourceLeaseTimeout,
    ResourcePolicy,
    ResourceScheduler,
)
from .contracts import (
    DEFAULT_PROTOCOL_SHA256,
    RUN_CONTRACT_SCHEMA,
    CacheMode,
    CacheScope,
    CaseResultRecord,
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    RunContract,
    Split,
    StageName,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from .variants import (
    ALL_VARIANT_IDS,
    StagePolicy,
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
    get_variant_definition,
)


ABLATION_PLAN_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.ablation-plan.v1"
)
ABLATION_RESULT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.ablation-result.v1"
)
ORDERING_ALGORITHM: Final = "sha256-seeded-counterbalanced-blocks-v2"
MAX_CASE_INPUT_BYTES: Final = 64 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class AblationValidationError(ValueError):
    """Raised when plan, persistence, or resume evidence fails closed."""


# Descriptive compatibility name used by operators and earlier plan drafts.
AblationRunnerError = AblationValidationError

def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise AblationValidationError(
            f"{field} must be a safe 1-128 character identifier"
        )
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise AblationValidationError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise AblationValidationError(f"{field} must be an object")
    return value


def _exact(
    value: Mapping[str, object], expected: set[str], field: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise AblationValidationError(
            f"{field} fields invalid: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _bounded_json(value: object, field: str) -> object:
    try:
        encoded = canonical_json(value).encode("utf-8")
    except (ProtocolContractError, TypeError, ValueError) as exc:
        raise AblationValidationError(
            f"{field} must contain JSON-compatible data"
        ) from exc
    if len(encoded) > MAX_CASE_INPUT_BYTES:
        raise AblationValidationError(
            f"{field} exceeds {MAX_CASE_INPUT_BYTES} encoded bytes"
        )
    # A canonical round trip detaches caller-owned containers before freezing.
    return _freeze(json.loads(encoded))


def _enum(enum_type: type, value: object, field: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise AblationValidationError(f"unsupported {field}: {value!r}") from exc


def _tuple_of_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AblationValidationError(f"{field} must be an array")
    return tuple(_safe_id(item, f"{field}[]") for item in value)


@dataclass(frozen=True, slots=True)
class AblationCase:
    """One case payload reused byte-for-byte by every paired arm."""

    case_id: str
    split: Split
    input_data: object
    case_sha256: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.case_id, "case_id")
        if not isinstance(self.split, Split):
            raise AblationValidationError("split must be a Split")
        frozen = _bounded_json(self.input_data, "input_data")
        object.__setattr__(self, "input_data", frozen)
        calculated = _sha(_thaw(frozen))
        if self.case_sha256 is None:
            object.__setattr__(self, "case_sha256", calculated)
        else:
            _digest(self.case_sha256, "case_sha256")

    @classmethod
    def create(
        cls,
        case_id: str,
        input_data: object,
        *,
        split: Split = Split.PILOT,
        case_sha256: str | None = None,
    ) -> "AblationCase":
        return cls(case_id, split, input_data, case_sha256)

    @classmethod
    def from_benchmark_case(cls, case: BenchmarkCase) -> "AblationCase":
        if not isinstance(case, BenchmarkCase):
            raise AblationValidationError("case must be a BenchmarkCase")
        payload = {
            "case_id": case.case_id,
            "text": case.source_text,
            "stratum": case.stratum,
            "difficulty": case.difficulty.value,
            "expected_class": case.expected_class.value,
            "expected_ir": _thaw(case.expected_ir),
            "proof_obligation": _thaw(case.proof_obligation),
            "obligation_id": (
                None
                if case.proof_obligation is None
                else f"{case.case_id}-obligation"
            ),
            "negative_controls": list(case.negative_controls),
        }
        return cls(
            case.case_id,
            case.split,
            payload,
            _sha(case.to_dict()),
        )

    @property
    def input_sha256(self) -> str:
        return _sha(_thaw(self.input_data))

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "split": self.split.value,
            "input_data": _thaw(self.input_data),
            "case_sha256": self.case_sha256,
            "input_sha256": self.input_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "AblationCase":
        data = _mapping(value, "ablation_case")
        _exact(
            data,
            {
                "case_id",
                "split",
                "input_data",
                "case_sha256",
                "input_sha256",
            },
            "ablation_case",
        )
        result = cls(
            _safe_id(data["case_id"], "case_id"),
            _enum(Split, data["split"], "split"),
            data["input_data"],
            _digest(data["case_sha256"], "case_sha256"),
        )
        if result.input_sha256 != _digest(
            data["input_sha256"], "input_sha256"
        ):
            raise AblationValidationError("ablation case input digest changed")
        return result


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Recorded ceilings applied to every sequential case execution."""

    max_workers: int = 1
    case_timeout_seconds: float = 120.0
    max_memory_bytes: int = 8 * 1024 * 1024 * 1024
    max_model_calls_per_case: int = 8
    max_solver_processes_per_case: int = 1

    def __post_init__(self) -> None:
        integer_limits = {
            "max_workers": (1, 32),
            "max_memory_bytes": (1, 1 << 40),
            "max_model_calls_per_case": (0, 1_000_000),
            "max_solver_processes_per_case": (0, 1_000),
        }
        for name, (minimum, maximum) in integer_limits.items():
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise AblationValidationError(
                    f"{name} must be an integer from {minimum} to {maximum}"
                )
        timeout = self.case_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or not 0 < float(timeout) <= 86_400
        ):
            raise AblationValidationError(
                "case_timeout_seconds must be finite and from 0 to 86400"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResourceLimits":
        data = _mapping(value, "resource_limits")
        _exact(data, set(cls.__dataclass_fields__), "resource_limits")
        try:
            return cls(**data)  # type: ignore[arg-type]
        except TypeError as exc:
            raise AblationValidationError("invalid resource limits") from exc


@dataclass(frozen=True, slots=True)
class ScheduledCase:
    """One arm invocation in a paired case/cache block."""

    ordinal: int
    block_ordinal: int
    within_block_ordinal: int
    block_id: str
    job_id: str
    variant_id: str
    cache_mode: CacheMode
    case: AblationCase

    def __post_init__(self) -> None:
        for field in ("ordinal", "block_ordinal", "within_block_ordinal"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AblationValidationError(
                    f"{field} must be a nonnegative integer"
                )
        _safe_id(self.block_id, "block_id")
        _safe_id(self.job_id, "job_id")
        get_variant_definition(self.variant_id)
        if not isinstance(self.cache_mode, CacheMode):
            raise AblationValidationError("cache_mode must be a CacheMode")
        if not isinstance(self.case, AblationCase):
            raise AblationValidationError("case must be an AblationCase")

    @property
    def input_sha256(self) -> str:
        return self.case.input_sha256

    @property
    def schedule_index(self) -> int:
        """Compatibility name for the job's global recorded ordinal."""

        return self.ordinal

    @property
    def case_id(self) -> str:
        return self.case.case_id

    @property
    def case_sha256(self) -> str:
        # ``AblationCase.__post_init__`` always materializes this digest.
        assert self.case.case_sha256 is not None
        return self.case.case_sha256

    @property
    def input_data(self) -> object:
        return self.case.input_data

    @property
    def stages(self) -> tuple[StageName, ...]:
        return get_variant_definition(self.variant_id).stages

    @property
    def requested_configuration_sha256(self) -> str:
        return get_variant_definition(self.variant_id).digest

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "block_ordinal": self.block_ordinal,
            "within_block_ordinal": self.within_block_ordinal,
            "block_id": self.block_id,
            "job_id": self.job_id,
            "variant_id": self.variant_id,
            "cache_mode": self.cache_mode.value,
            "case": self.case.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ScheduledCase":
        data = _mapping(value, "scheduled_case")
        _exact(data, set(cls.__dataclass_fields__), "scheduled_case")
        return cls(
            ordinal=data["ordinal"],  # type: ignore[arg-type]
            block_ordinal=data["block_ordinal"],  # type: ignore[arg-type]
            within_block_ordinal=data["within_block_ordinal"],  # type: ignore[arg-type]
            block_id=_safe_id(data["block_id"], "block_id"),
            job_id=_safe_id(data["job_id"], "job_id"),
            variant_id=_safe_id(data["variant_id"], "variant_id"),
            cache_mode=_enum(CacheMode, data["cache_mode"], "cache_mode"),
            case=AblationCase.from_dict(data["case"]),
        )


@dataclass(frozen=True, slots=True)
class AblationPlan:
    """Fully replayable schedule frozen before any stage is invoked."""

    schema: str
    protocol_sha256: str
    registry_sha256: str
    ordering_algorithm: str
    run_id: str
    split: Split
    case_manifest_sha256: str
    environment_sha256: str | None
    seed: int
    variant_ids: tuple[str, ...]
    cache_modes: tuple[CacheMode, ...]
    case_ids: tuple[str, ...]
    limits: ResourceLimits
    jobs: tuple[ScheduledCase, ...]
    holdout_access_log_id: str | None = None

    def __post_init__(self) -> None:
        if self.schema != ABLATION_PLAN_SCHEMA:
            raise AblationValidationError("unsupported ablation-plan schema")
        if self.protocol_sha256 != DEFAULT_PROTOCOL_SHA256:
            raise AblationValidationError(
                "plan must bind frozen protocol revision 1"
            )
        if self.registry_sha256 != VARIANT_REGISTRY_SHA256:
            raise AblationValidationError("plan variant registry changed")
        if self.ordering_algorithm != ORDERING_ALGORITHM:
            raise AblationValidationError("unsupported ordering algorithm")
        _safe_id(self.run_id, "run_id")
        if not isinstance(self.split, Split):
            raise AblationValidationError("split must be a Split")
        _digest(self.case_manifest_sha256, "case_manifest_sha256")
        if self.environment_sha256 is not None:
            _digest(self.environment_sha256, "environment_sha256")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed < 1 << 63
        ):
            raise AblationValidationError(
                "seed must be a nonnegative signed 63-bit integer"
            )
        variants = tuple(self.variant_ids)
        if (
            not variants
            or len(set(variants)) != len(variants)
            or any(item not in VARIANT_REGISTRY for item in variants)
        ):
            raise AblationValidationError(
                "variant_ids must be distinct registered variants"
            )
        object.__setattr__(self, "variant_ids", variants)
        modes = tuple(self.cache_modes)
        if (
            not modes
            or len(set(modes)) != len(modes)
            or any(not isinstance(item, CacheMode) for item in modes)
        ):
            raise AblationValidationError(
                "cache_modes must be distinct CacheMode values"
            )
        object.__setattr__(self, "cache_modes", modes)
        case_ids = tuple(_safe_id(item, "case_ids[]") for item in self.case_ids)
        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise AblationValidationError("case_ids must be distinct and nonempty")
        object.__setattr__(self, "case_ids", case_ids)
        if not isinstance(self.limits, ResourceLimits):
            raise AblationValidationError("limits must be ResourceLimits")
        jobs = tuple(self.jobs)
        expected_count = len(case_ids) * len(modes) * len(variants)
        if len(jobs) != expected_count:
            raise AblationValidationError(
                "jobs do not form complete case/cache/variant pairing"
            )
        if any(not isinstance(job, ScheduledCase) for job in jobs):
            raise AblationValidationError("jobs must contain ScheduledCase values")
        if tuple(job.ordinal for job in jobs) != tuple(range(len(jobs))):
            raise AblationValidationError("job ordinals must be contiguous")
        if len({job.job_id for job in jobs}) != len(jobs):
            raise AblationValidationError("job ids must be unique")
        expected = {
            (case_id, mode, variant)
            for case_id in case_ids
            for mode in modes
            for variant in variants
        }
        actual = {
            (job.case.case_id, job.cache_mode, job.variant_id)
            for job in jobs
        }
        if actual != expected:
            raise AblationValidationError(
                "jobs are missing or duplicate paired combinations"
            )
        blocks: dict[str, list[ScheduledCase]] = {}
        block_sequence: list[str] = []
        for job in jobs:
            if job.case.split is not self.split:
                raise AblationValidationError("job case belongs to another split")
            if not block_sequence or block_sequence[-1] != job.block_id:
                if job.block_id in block_sequence:
                    raise AblationValidationError(
                        "paired block jobs must be contiguous"
                    )
                block_sequence.append(job.block_id)
            blocks.setdefault(job.block_id, []).append(job)
        if len(blocks) != len(case_ids) * len(modes):
            raise AblationValidationError("paired block count is invalid")
        block_ordinals: set[int] = set()
        for items in blocks.values():
            first = items[0]
            if (
                len(items) != len(variants)
                or {item.variant_id for item in items} != set(variants)
                or {
                    item.within_block_ordinal for item in items
                } != set(range(len(variants)))
                or tuple(item.within_block_ordinal for item in items)
                != tuple(range(len(variants)))
                or any(
                    item.case.to_dict() != first.case.to_dict()
                    or item.cache_mode is not first.cache_mode
                    or item.block_ordinal != first.block_ordinal
                    for item in items
                )
            ):
                raise AblationValidationError(
                    "paired block does not share one input and every arm"
                )
            block_ordinals.add(first.block_ordinal)
        if block_ordinals != set(range(len(blocks))):
            raise AblationValidationError("block ordinals must be contiguous")
        if tuple(
            blocks[block_id][0].block_ordinal for block_id in block_sequence
        ) != tuple(range(len(blocks))):
            raise AblationValidationError(
                "recorded block sequence and ordinals disagree"
            )
        if self.split is Split.HOLDOUT and set(modes) == {
            CacheMode.COLD,
            CacheMode.WARM,
        }:
            ordered_cases = sorted(
                case_ids,
                key=lambda case_id: (
                    _rank(self.seed, "holdout-case", case_id),
                    case_id,
                ),
            )
            first_mode = (
                CacheMode.COLD
                if int(_rank(self.seed, "holdout-mode-start"), 16) % 2 == 0
                else CacheMode.WARM
            )
            expected_blocks = []
            for index, case_id in enumerate(ordered_cases):
                leading = (
                    first_mode
                    if index % 2 == 0
                    else (
                        CacheMode.WARM
                        if first_mode is CacheMode.COLD
                        else CacheMode.COLD
                    )
                )
                trailing = (
                    CacheMode.WARM
                    if leading is CacheMode.COLD
                    else CacheMode.COLD
                )
                expected_blocks.extend(
                    ((case_id, leading), (case_id, trailing))
                )
        else:
            expected_blocks = [
                (case_id, mode)
                for case_id in case_ids
                for mode in modes
            ]
            expected_blocks.sort(
                key=lambda item: (
                    _rank(self.seed, "block", item[0], item[1].value),
                    item[0],
                    item[1].value,
                )
            )
        actual_blocks = [
            (
                blocks[block_id][0].case.case_id,
                blocks[block_id][0].cache_mode,
            )
            for block_id in block_sequence
        ]
        if actual_blocks != expected_blocks:
            raise AblationValidationError(
                "block order does not match recorded seed and algorithm"
            )
        base_arm_order = sorted(
            variants,
            key=lambda arm: (_rank(self.seed, "arm-base", arm), arm),
        )
        position_counts = {
            arm: [0 for _ in variants] for arm in variants
        }
        for block_id in block_sequence:
            items = blocks[block_id]
            block_ordinal = items[0].block_ordinal
            rotation = block_ordinal % len(base_arm_order)
            expected_arms = (
                base_arm_order[rotation:] + base_arm_order[:rotation]
            )
            if [item.variant_id for item in items] != expected_arms:
                raise AblationValidationError(
                    "arm order does not match recorded seed and algorithm"
                )
            for position, arm in enumerate(expected_arms):
                position_counts[arm][position] += 1
            first = items[0]
            expected_block_id = (
                f"b-{first.cache_mode.value}-{first.case.case_id}"
            )
            if block_id != expected_block_id:
                raise AblationValidationError("block id is not canonical")
            for item in items:
                expected_job_id = (
                    f"j-{item.cache_mode.value}-{item.case.case_id}-"
                    f"{item.variant_id.lower()}"
                )
                if item.job_id != expected_job_id:
                    raise AblationValidationError("job id is not canonical")
        if any(
            max(counts) - min(counts) > 1
            for counts in position_counts.values()
        ):
            raise AblationValidationError(
                "arm positions are not counterbalanced across blocks"
            )
        object.__setattr__(self, "jobs", jobs)
        if self.split is Split.HOLDOUT:
            _safe_id(self.holdout_access_log_id, "holdout_access_log_id")
        elif self.holdout_access_log_id is not None:
            raise AblationValidationError(
                "holdout_access_log_id is only valid for holdout"
            )

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    @property
    def blocks(self) -> tuple[tuple[ScheduledCase, ...], ...]:
        grouped: list[list[ScheduledCase]] = []
        for job in self.jobs:
            if not grouped or grouped[-1][0].block_id != job.block_id:
                grouped.append([job])
            else:
                grouped[-1].append(job)
        return tuple(tuple(items) for items in grouped)

    @property
    def run_contracts(self) -> tuple[RunContract, ...]:
        """Return every isolated variant/cache contract in requested order."""

        return tuple(
            _contract(self, variant, mode)
            for variant in self.variant_ids
            for mode in self.cache_modes
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "protocol_sha256": self.protocol_sha256,
            "registry_sha256": self.registry_sha256,
            "ordering_algorithm": self.ordering_algorithm,
            "run_id": self.run_id,
            "split": self.split.value,
            "case_manifest_sha256": self.case_manifest_sha256,
            "environment_sha256": self.environment_sha256,
            "seed": self.seed,
            "variant_ids": list(self.variant_ids),
            "cache_modes": [item.value for item in self.cache_modes],
            "case_ids": list(self.case_ids),
            "limits": self.limits.to_dict(),
            "jobs": [job.to_dict() for job in self.jobs],
            "holdout_access_log_id": self.holdout_access_log_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "AblationPlan":
        data = _mapping(value, "ablation_plan")
        _exact(data, set(cls.__dataclass_fields__), "ablation_plan")
        if not isinstance(data["cache_modes"], list) or not isinstance(
            data["jobs"], list
        ):
            raise AblationValidationError("plan jobs/cache_modes must be arrays")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            protocol_sha256=data["protocol_sha256"],  # type: ignore[arg-type]
            registry_sha256=data["registry_sha256"],  # type: ignore[arg-type]
            ordering_algorithm=data["ordering_algorithm"],  # type: ignore[arg-type]
            run_id=data["run_id"],  # type: ignore[arg-type]
            split=_enum(Split, data["split"], "split"),
            case_manifest_sha256=data["case_manifest_sha256"],  # type: ignore[arg-type]
            environment_sha256=data["environment_sha256"],  # type: ignore[arg-type]
            seed=data["seed"],  # type: ignore[arg-type]
            variant_ids=_tuple_of_strings(data["variant_ids"], "variant_ids"),
            cache_modes=tuple(
                _enum(CacheMode, item, "cache_modes[]")
                for item in data["cache_modes"]
            ),
            case_ids=_tuple_of_strings(data["case_ids"], "case_ids"),
            limits=ResourceLimits.from_dict(data["limits"]),
            jobs=tuple(ScheduledCase.from_dict(item) for item in data["jobs"]),
            holdout_access_log_id=data["holdout_access_log_id"],  # type: ignore[arg-type]
        )


def _rank(seed: int, *parts: str) -> str:
    return _sha(
        {
            "ordering_algorithm": ORDERING_ALGORITHM,
            "seed": seed,
            "parts": list(parts),
        }
    )


def build_ablation_plan(
    run_id: str,
    cases: Sequence[AblationCase | BenchmarkCase],
    *,
    case_manifest_sha256: str,
    split: Split,
    seed: int,
    variant_ids: Sequence[str] = ALL_VARIANT_IDS,
    cache_modes: Sequence[CacheMode] = (CacheMode.COLD, CacheMode.WARM),
    limits: ResourceLimits = ResourceLimits(),
    environment_sha256: str | None = None,
    holdout_access_log_id: str | None = None,
) -> AblationPlan:
    """Create deterministic SHA-ranked paired blocks without filesystem I/O."""

    normalized = tuple(
        AblationCase.from_benchmark_case(case)
        if isinstance(case, BenchmarkCase)
        else case
        for case in cases
    )
    if (
        not normalized
        or any(not isinstance(case, AblationCase) for case in normalized)
        or len({case.case_id for case in normalized}) != len(normalized)
    ):
        raise AblationValidationError(
            "cases must be nonempty distinct AblationCase/BenchmarkCase values"
        )
    variants = tuple(variant_ids)
    modes = tuple(cache_modes)
    # Construction through AblationPlan performs the complete contract check;
    # validate these early to build useful schedule identifiers safely.
    _safe_id(run_id, "run_id")
    _digest(case_manifest_sha256, "case_manifest_sha256")
    if not isinstance(split, Split) or any(case.split is not split for case in normalized):
        raise AblationValidationError("all cases must belong to selected split")
    if (
        not variants
        or len(set(variants)) != len(variants)
        or any(item not in VARIANT_REGISTRY for item in variants)
    ):
        raise AblationValidationError("variant_ids must be distinct and registered")
    if (
        not modes
        or len(set(modes)) != len(modes)
        or any(not isinstance(mode, CacheMode) for mode in modes)
    ):
        raise AblationValidationError("cache_modes must be distinct CacheMode values")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 1 << 63:
        raise AblationValidationError("seed must be a nonnegative 63-bit integer")

    if split is Split.HOLDOUT and set(modes) == {
        CacheMode.COLD,
        CacheMode.WARM,
    }:
        ordered_cases = sorted(
            normalized,
            key=lambda case: (
                _rank(seed, "holdout-case", case.case_id),
                case.case_id,
            ),
        )
        first_mode = (
            CacheMode.COLD
            if int(_rank(seed, "holdout-mode-start"), 16) % 2 == 0
            else CacheMode.WARM
        )
        blocks = []
        for index, case in enumerate(ordered_cases):
            leading = (
                first_mode
                if index % 2 == 0
                else (
                    CacheMode.WARM
                    if first_mode is CacheMode.COLD
                    else CacheMode.COLD
                )
            )
            trailing = (
                CacheMode.WARM
                if leading is CacheMode.COLD
                else CacheMode.COLD
            )
            blocks.extend(((case, leading), (case, trailing)))
    else:
        blocks = [(case, mode) for case in normalized for mode in modes]
        blocks.sort(
            key=lambda item: (
                _rank(seed, "block", item[0].case_id, item[1].value),
                item[0].case_id,
                item[1].value,
            )
        )
    jobs: list[ScheduledCase] = []
    base_arm_order = sorted(
        variants,
        key=lambda arm: (_rank(seed, "arm-base", arm), arm),
    )
    for block_ordinal, (case, mode) in enumerate(blocks):
        block_id = f"b-{mode.value}-{case.case_id}"
        rotation = block_ordinal % len(base_arm_order)
        arm_order = (
            base_arm_order[rotation:] + base_arm_order[:rotation]
        )
        for within, arm in enumerate(arm_order):
            jobs.append(
                ScheduledCase(
                    ordinal=len(jobs),
                    block_ordinal=block_ordinal,
                    within_block_ordinal=within,
                    block_id=block_id,
                    job_id=f"j-{mode.value}-{case.case_id}-{arm.lower()}",
                    variant_id=arm,
                    cache_mode=mode,
                    case=case,
                )
            )
    return AblationPlan(
        schema=ABLATION_PLAN_SCHEMA,
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        registry_sha256=VARIANT_REGISTRY_SHA256,
        ordering_algorithm=ORDERING_ALGORITHM,
        run_id=run_id,
        split=split,
        case_manifest_sha256=case_manifest_sha256,
        environment_sha256=environment_sha256,
        seed=seed,
        variant_ids=variants,
        cache_modes=modes,
        case_ids=tuple(case.case_id for case in normalized),
        limits=limits,
        jobs=tuple(jobs),
        holdout_access_log_id=holdout_access_log_id,
    )


@dataclass(frozen=True, slots=True)
class AblationRunResult:
    """Complete execution result, including jobs validated during resume."""

    plan: AblationPlan
    contracts: tuple[RunContract, ...]
    results: tuple[CaseResultRecord, ...]
    executed_job_ids: tuple[str, ...]
    resumed_job_ids: tuple[str, ...]
    output_root: Path
    resource_receipts: tuple[ResourceLeaseReceipt, ...] = ()

    @property
    def complete(self) -> bool:
        return len(self.results) == len(self.plan.jobs)

    @property
    def executed_count(self) -> int:
        return len(self.executed_job_ids)

    @property
    def resumed_count(self) -> int:
        return len(self.resumed_job_ids)

    @property
    def result_paths(self) -> tuple[Path, ...]:
        return tuple(_result_path(self.output_root, job) for job in self.plan.jobs)


def _contract(plan: AblationPlan, variant: str, mode: CacheMode) -> RunContract:
    definition = get_variant_definition(variant)
    access_log_id = plan.holdout_access_log_id
    if plan.split is Split.HOLDOUT:
        # A plan owns one logical access ledger, while each run contract needs
        # a distinct immutable audit identity so the complete ledger can be
        # validated for duplicates and contiguous sequencing.
        access_log_id = "ha-" + _sha(
            {
                "ledger_id": plan.holdout_access_log_id,
                "variant_id": variant,
                "cache_mode": mode.value,
            }
        )[:32]
    return RunContract(
        schema=RUN_CONTRACT_SCHEMA,
        protocol_sha256=plan.protocol_sha256,
        run_id=plan.run_id,
        requested_variant_id=variant,
        effective_variant_id=variant,
        split=plan.split,
        cache_mode=mode,
        cache_namespace=CacheScope(
            plan.run_id, plan.protocol_sha256, variant, plan.split, mode
        ).namespace,
        case_manifest_sha256=plan.case_manifest_sha256,
        configuration_sha256=definition.digest,
        prompts_frozen=True,
        policy_frozen=True,
        model_identities_frozen=True,
        thresholds_frozen=True,
        tuning_permitted=plan.split is not Split.HOLDOUT,
        holdout_access_log_id=access_log_id,
    )


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write((canonical_json(value) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise AblationValidationError(
            f"refusing to overwrite immutable record: {path}"
        ) from exc


def _read_canonical(path: Path, field: str) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AblationValidationError(f"cannot read {field}: {path}") from exc
    if not text.endswith("\n"):
        raise AblationValidationError(f"{field} is not canonical newline JSON")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise AblationValidationError(f"{field} is not strict JSON") from exc
    if canonical_json(value) + "\n" != text:
        raise AblationValidationError(f"{field} is not canonical JSON")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _result_path(root: Path, job: ScheduledCase) -> Path:
    return (
        root
        / "results"
        / job.case.split.value
        / job.cache_mode.value
        / job.variant_id
        / f"{job.case.case_id}.json"
    )


def _contract_path(root: Path, contract: RunContract) -> Path:
    return (
        root
        / "state"
        / "run-contracts"
        / contract.split.value
        / contract.cache_mode.value
        / f"{contract.requested_variant_id}.json"
    )


def _cache_scope_path(root: Path, contract: RunContract) -> Path:
    return (
        root
        / "cache"
        / contract.split.value
        / contract.cache_mode.value
        / contract.requested_variant_id
        / "scope.json"
    )


def _select_adapters(
    adapters: Mapping[object, object], variant: str
) -> Mapping[StageName, StageAdapter]:
    selected: object = adapters
    if not all(isinstance(key, StageName) for key in adapters):
        selected = adapters.get(variant)
    if not isinstance(selected, Mapping):
        raise AblationValidationError(
            f"adapters do not provide requested variant {variant}"
        )
    result: dict[StageName, StageAdapter] = {}
    for stage, adapter in selected.items():
        if (
            not isinstance(stage, StageName)
            or not isinstance(adapter, StageAdapter)
            or adapter.stage is not stage
        ):
            raise AblationValidationError(
                "adapters must map matching StageName to StageAdapter"
            )
        result[stage] = adapter
    return MappingProxyType(result)


_RESOURCE_CLASS = MappingProxyType(
    {
        StageName.COMPILER: ResourceClass.CPU,
        StageName.SPACY: ResourceClass.CPU,
        StageName.SYMAI: ResourceClass.MODEL,
        StageName.HAMMER: ResourceClass.SOLVER,
        StageName.LEANSTRAL: ResourceClass.MODEL,
        StageName.KERNEL: ResourceClass.KERNEL,
    }
)

_RESOURCE_LANE = MappingProxyType(
    {
        StageName.COMPILER: ResourceLane.CPU,
        StageName.SPACY: ResourceLane.CPU,
        StageName.SYMAI: ResourceLane.MODEL,
        StageName.HAMMER: ResourceLane.SOLVER,
        StageName.LEANSTRAL: ResourceLane.MODEL,
        StageName.KERNEL: ResourceLane.KERNEL,
    }
)


def _ambiguity_decision(artifacts: Sequence[StageArtifact]) -> bool:
    """Return the deterministic frontend gate, defaulting open if unspecified."""

    found_signal = False
    ambiguous = False
    for artifact in artifacts:
        if artifact.stage not in {StageName.COMPILER, StageName.SPACY}:
            continue
        queue: list[object] = [artifact.data]
        while queue:
            value = queue.pop()
            if isinstance(value, Mapping):
                if "ambiguity_detected" in value:
                    found_signal = True
                    ambiguous = ambiguous or value["ambiguity_detected"] is True
                for key in ("ambiguity_flags", "ambiguities"):
                    if key in value and isinstance(
                        value[key], (list, tuple)
                    ):
                        found_signal = True
                        ambiguous = ambiguous or bool(value[key])
                queue.extend(value.values())
            elif isinstance(value, (list, tuple)):
                queue.extend(value)
    # An older injected adapter may not expose ambiguity evidence.  Keeping
    # the gate open retains the requested arm instead of silently disabling it.
    return ambiguous if found_signal else True


def _proof_succeeded(artifact: StageArtifact) -> bool:
    if not artifact.invoked or artifact.status is not StageStatus.SUCCESS:
        return False
    if not isinstance(artifact.data, Mapping):
        return False
    data = artifact.data
    explicit = data.get("proof_success")
    if isinstance(explicit, bool):
        return explicit
    if artifact.stage is StageName.HAMMER:
        return bool(
            data.get("proof_candidate")
            or data.get("candidate")
            or data.get("status") in {"candidate", "verified"}
        )
    if artifact.stage is StageName.LEANSTRAL:
        draft = data.get("draft")
        return isinstance(draft, Mapping) and bool(
            draft.get("proof_text", draft.get("draft_text"))
        )
    return False


def _has_obligation(input_data: object) -> bool:
    if not isinstance(input_data, Mapping):
        return False
    # Legacy/injected benchmark cases may omit reviewed-obligation metadata.
    # Treat that as unspecified (gate open) for compatibility.  Corpus-derived
    # cases always include an explicit mapping or explicit None, so the real
    # runtime can distinguish a reviewed proof target from a no-proof case.
    if "proof_obligation" not in input_data:
        return True
    return isinstance(input_data.get("proof_obligation"), Mapping) and isinstance(
        input_data.get("obligation_id"), str
    )


def _synthetic_invocation(
    stage: StageName,
    request: StageRequest,
    *,
    reason: str,
) -> StageInvocation:
    output = StageOutput(
        data={
            "schema": "ipfs-datasets.logic-pipeline-benchmark.policy-decision.v1",
            "stage": stage.value,
            "invoked": False,
            "reason": reason,
            "invocation_index": request.invocation_index,
            "consumed_artifact_sha256": [
                artifact.digest for artifact in request.upstream_artifacts
            ],
        },
        effective_identity={
            **dict(request.requested_identity),
            "invoked": False,
            "policy_reason": reason,
            "graph_invocation_index": request.invocation_index,
            "consumed_artifact_sha256": tuple(
                artifact.digest for artifact in request.upstream_artifacts
            ),
        },
        telemetry=TelemetryRecord(
            input_items=1,
            output_items=1,
            model_calls=0,
            bytes_in=request.input_bytes,
            resource_lane=_RESOURCE_LANE[stage],
        ),
    )
    return StageInvocation(output, output.telemetry)


def _artifact(
    stage: StageName,
    invocation: StageInvocation,
    *,
    invocation_index: int,
    invoked: bool,
    reason: str,
) -> StageArtifact:
    output = invocation.output
    output_sha256 = (
        hashlib.sha256(
            canonical_json(_thaw(output.data)).encode("utf-8")
        ).hexdigest()
        if output.status is StageStatus.SUCCESS
        else None
    )
    return StageArtifact(
        stage=stage,
        status=output.status,
        data=output.data,
        output_sha256=output_sha256,
        effective_identity=output.effective_identity,
        invocation_index=invocation_index,
        invoked=invoked,
        policy_reason=reason,
    )


def _failure(
    plan: AblationPlan,
    job: ScheduledCase,
    code: FailureCode,
    detail: str,
) -> CaseResultRecord:
    definition = get_variant_definition(job.variant_id)
    stage = definition.stages[0]

    def handler(_request: StageRequest) -> StageOutput:
        return StageOutput(
            status=StageStatus.FAILED,
            failure_code=code,
            failure_detail=(detail.strip() or "ablation failure")[:512],
        )

    request = StageRequest(
        run_id=plan.run_id,
        case_id=job.case.case_id,
        case_manifest_sha256=plan.case_manifest_sha256,
        variant_id=job.variant_id,
        split=plan.split,
        cache_mode=job.cache_mode,
        input_data=_thaw(job.case.input_data),
        requested_identity=definition.requested_identity(stage),
        environment_sha256=plan.environment_sha256,
        source=("ablation_plan", plan.digest, job.job_id),
    )
    return CaseResultRecord.from_stages(
        (StageAdapter(stage, handler=handler).run(request),)
    )


def _execute_job(
    plan: AblationPlan,
    job: ScheduledCase,
    adapters: Mapping[object, object],
    scheduler: ResourceScheduler,
) -> CaseResultRecord:
    definition = get_variant_definition(job.variant_id)
    try:
        selected = _select_adapters(adapters, job.variant_id)
        invocations: dict[StageName, StageInvocation] = {}
        artifacts: list[StageArtifact] = []
        invocation_index = 0
        terminal_failure = False

        def request_for(stage: StageName) -> StageRequest:
            return StageRequest(
                run_id=plan.run_id,
                case_id=job.case.case_id,
                case_manifest_sha256=plan.case_manifest_sha256,
                variant_id=job.variant_id,
                split=plan.split,
                cache_mode=job.cache_mode,
                input_data=_thaw(job.case.input_data),
                requested_identity=definition.requested_identity(stage),
                environment_sha256=plan.environment_sha256,
                source=("ablation_plan", plan.digest, job.job_id),
                upstream_artifacts=tuple(artifacts),
                invocation_index=invocation_index,
            )

        def invoke(
            stage: StageName,
            *,
            should_invoke: bool = True,
            reason: str = "scheduled",
        ) -> StageArtifact:
            nonlocal invocation_index
            adapter = selected.get(stage, StageAdapter(stage))
            request = request_for(stage)
            if not should_invoke:
                invocation = _synthetic_invocation(
                    stage, request, reason=reason
                )
            else:
                resource_class = _RESOURCE_CLASS[stage]
                requested_model = request.requested_identity.get(
                    "model",
                    request.requested_identity.get(
                        "requested_model", "shared-model-service"
                    ),
                )
                model_identity = (
                    re.sub(r"[^A-Za-z0-9._-]", "-", str(requested_model))[:128]
                    if resource_class is ResourceClass.MODEL
                    else None
                )
                if model_identity in {"", ".", ".."}:
                    model_identity = "shared-model-service"
                lease_request = ResourceLeaseRequest(
                    owner_id=f"lease-{job.ordinal}-{stage.value}",
                    resource_class=resource_class,
                    model_identity=model_identity,
                    timeout_seconds=plan.limits.case_timeout_seconds,
                )
                with scheduler.acquire(lease_request) as lease:
                    lease.assert_active()
                    invocation = adapter.invoke(request)
                identity = {
                    **dict(
                        invocation.output.effective_identity
                        or request.requested_identity
                    ),
                    "graph_invocation_index": invocation_index,
                    "graph_invoked": True,
                    "graph_policy_reason": reason,
                    "consumed_artifact_sha256": tuple(
                        artifact.digest for artifact in artifacts
                    ),
                }
                invocation = StageInvocation(
                    replace(
                        invocation.output,
                        effective_identity=identity,
                    ),
                    invocation.telemetry,
                )
            invocations[stage] = invocation
            artifact = _artifact(
                stage,
                invocation,
                invocation_index=invocation_index,
                invoked=should_invoke,
                reason=reason,
            )
            artifacts.append(artifact)
            invocation_index += 1
            return artifact

        proof_stages = {StageName.HAMMER, StageName.LEANSTRAL}
        frontend = tuple(
            stage
            for stage in definition.stages
            if stage not in proof_stages | {StageName.KERNEL}
        )
        for stage in frontend:
            should_invoke = not (
                stage is StageName.SYMAI
                and definition.symai_policy is StagePolicy.AMBIGUITY_GATED
                and not _ambiguity_decision(artifacts)
            )
            artifact = invoke(
                stage,
                should_invoke=should_invoke,
                reason=(
                    "frontend_ambiguity_gate_closed"
                    if not should_invoke
                    else (
                        "frontend_ambiguity_gate_open"
                        if stage is StageName.SYMAI
                        and definition.symai_policy
                        is StagePolicy.AMBIGUITY_GATED
                        else "frontend_scheduled"
                    )
                ),
            )
            if artifact.status is not StageStatus.SUCCESS:
                terminal_failure = True
                break

        has_obligation = _has_obligation(job.case.input_data)
        previous_proof: StageArtifact | None = None
        if not terminal_failure:
            for proof_index, stage in enumerate(definition.proof_order):
                should_invoke = has_obligation
                reason = "proof_scheduled"
                if not has_obligation:
                    reason = "no_reviewed_proof_obligation"
                elif proof_index and job.variant_id != "A12":
                    should_invoke = not (
                        previous_proof is not None
                        and _proof_succeeded(previous_proof)
                    )
                    reason = (
                        "proof_fallback_suppressed"
                        if not should_invoke
                        else "proof_failure_fallback"
                    )
                artifact = invoke(
                    stage,
                    should_invoke=should_invoke,
                    reason=reason,
                )
                previous_proof = artifact
            # A failed or unavailable first proof backend is exactly what a
            # bounded fallback is for.  The independent kernel remains the
            # terminal authority even when no proof backend produced a usable
            # candidate: its rejection is part of the complete frozen graph.

        if not terminal_failure and StageName.KERNEL in definition.stages:
            kernel_should_invoke = not (
                definition.proof_order and not has_obligation
            )
            kernel_artifact = invoke(
                StageName.KERNEL,
                should_invoke=kernel_should_invoke,
                reason=(
                    "no_reviewed_proof_obligation"
                    if not kernel_should_invoke
                    else (
                        "legacy_diagnostic_kernel"
                        if definition.safety_diagnostic_only
                        else "independent_native_kernel"
                    )
                ),
            )
            if (
                definition.safety_diagnostic_only
                and invocations[StageName.KERNEL].output.kernel_accepted
            ):
                original = invocations[StageName.KERNEL]
                data = (
                    {
                        **dict(original.output.data),
                        "diagnostic_only": True,
                        "authority_withheld": True,
                    }
                    if isinstance(original.output.data, Mapping)
                    else {
                        "diagnostic_payload": _thaw(original.output.data),
                        "diagnostic_only": True,
                        "authority_withheld": True,
                    }
                )
                invocations[StageName.KERNEL] = StageInvocation(
                    replace(
                        original.output,
                        data=data,
                        kernel_accepted=False,
                        kernel_receipt_sha256=None,
                    ),
                    original.telemetry,
                )
                replacement = _artifact(
                    StageName.KERNEL,
                    invocations[StageName.KERNEL],
                    invocation_index=kernel_artifact.invocation_index,
                    invoked=True,
                    reason="legacy_diagnostic_kernel",
                )
                artifacts[-1] = replacement

        records = []
        canonical_upstream: tuple[str, ...] = ()
        by_stage_artifacts = tuple(artifacts)
        for stage in definition.stages:
            invocation = invocations.get(stage)
            if invocation is None:
                break
            adapter = selected.get(stage, StageAdapter(stage))
            request = StageRequest(
                run_id=plan.run_id,
                case_id=job.case.case_id,
                case_manifest_sha256=plan.case_manifest_sha256,
                variant_id=job.variant_id,
                split=plan.split,
                cache_mode=job.cache_mode,
                input_data=_thaw(job.case.input_data),
                requested_identity=definition.requested_identity(stage),
                environment_sha256=plan.environment_sha256,
                source=("ablation_plan", plan.digest, job.job_id),
                upstream_stage_digests=canonical_upstream,
                upstream_artifacts=by_stage_artifacts,
                invocation_index=next(
                    artifact.invocation_index
                    for artifact in artifacts
                    if artifact.stage is stage
                ),
            )
            record = adapter.record(request, invocation)
            records.append(record)
            canonical_upstream = (*canonical_upstream, record.digest)
        result = CaseResultRecord.from_stages(tuple(records))
    except (ResourceLeaseTimeout, ResourceLeaseCancelled, ResourceLeaseError) as exc:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            f"resource lease failed for {job.job_id}: {type(exc).__name__}",
        )
    except Exception as exc:
        return _failure(
            plan,
            job,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            f"runner retained {type(exc).__name__} for {job.job_id}",
        )

    wall_ms = sum(record.telemetry.wall_time_ms for record in result.stages)
    peak_memory = max(
        (record.telemetry.peak_memory_bytes for record in result.stages),
        default=0,
    )
    model_calls = sum(record.telemetry.model_calls for record in result.stages)
    solver_stages = sum(
        record.telemetry.resource_lane is ResourceLane.SOLVER
        for record in result.stages
    )
    if peak_memory > plan.limits.max_memory_bytes:
        return _failure(
            plan, job, FailureCode.OUT_OF_MEMORY, "memory limit exceeded"
        )
    if wall_ms > plan.limits.case_timeout_seconds * 1_000:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            "case timeout exceeded",
        )
    if model_calls > plan.limits.max_model_calls_per_case:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            "model-call limit exceeded",
        )
    if solver_stages > plan.limits.max_solver_processes_per_case:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            "solver-process limit exceeded",
        )
    return result


def _envelope(
    plan: AblationPlan,
    job: ScheduledCase,
    contract: RunContract,
    result: CaseResultRecord,
) -> dict[str, object]:
    return {
        "schema": ABLATION_RESULT_SCHEMA,
        "plan_sha256": plan.digest,
        "job": job.to_dict(),
        "run_contract": contract.to_dict(),
        "requested_configuration": get_variant_definition(
            job.variant_id
        ).to_dict(),
        "effective_configuration": [
            {
                "stage": stage.stage.value,
                "status": stage.status.value,
                "effective_identity": _thaw(
                    stage.provenance.effective_identity
                ),
            }
            for stage in result.stages
        ],
        "case_result": result.to_dict(),
        "case_result_sha256": result.digest,
    }


def _validate_envelope(
    value: object,
    plan: AblationPlan,
    job: ScheduledCase,
    contract: RunContract,
) -> CaseResultRecord:
    data = _mapping(value, "ablation_result")
    _exact(
        data,
        {
            "schema",
            "plan_sha256",
            "job",
            "run_contract",
            "requested_configuration",
            "effective_configuration",
            "case_result",
            "case_result_sha256",
        },
        "ablation_result",
    )
    if (
        data["schema"] != ABLATION_RESULT_SCHEMA
        or data["plan_sha256"] != plan.digest
        or ScheduledCase.from_dict(data["job"]) != job
        or data["requested_configuration"]
        != get_variant_definition(job.variant_id).to_dict()
    ):
        raise AblationValidationError("result envelope identity changed")
    try:
        restored_contract = RunContract.from_dict(data["run_contract"])
        result = CaseResultRecord.from_dict(data["case_result"])
    except (ProtocolContractError, TypeError, ValueError) as exc:
        raise AblationValidationError("invalid result protocol record") from exc
    if restored_contract != contract or result.digest != data["case_result_sha256"]:
        raise AblationValidationError("result contract or digest changed")
    expected_identity = (
        plan.run_id,
        job.case.case_id,
        job.variant_id,
        plan.split,
        job.cache_mode,
        plan.case_manifest_sha256,
    )
    actual_identity = (
        result.run_id,
        result.case_id,
        result.variant_id,
        result.split,
        result.cache_mode,
        result.case_manifest_sha256,
    )
    if actual_identity != expected_identity or any(
        stage.provenance.input_sha256 != job.input_sha256
        for stage in result.stages
    ):
        raise AblationValidationError("result differs from scheduled paired input")
    effective = [
        {
            "stage": stage.stage.value,
            "status": stage.status.value,
            "effective_identity": _thaw(stage.provenance.effective_identity),
        }
        for stage in result.stages
    ]
    if data["effective_configuration"] != effective:
        raise AblationValidationError("effective configuration changed")
    return result


def _execute_ablation(
    plan: AblationPlan,
    adapters: Mapping[object, object],
    *,
    output_root: str | Path,
    resume: bool = True,
    resource_scheduler: ResourceScheduler | None = None,
    authorized_holdout: bool = False,
) -> AblationRunResult:
    """Execute jobs after the caller has selected the appropriate trust boundary.

    ``authorized_holdout`` is intentionally private implementation plumbing.
    The public :func:`execute_ablation` entry point always leaves it disabled;
    only :mod:`benchmarks.logic_pipeline.holdout_execution` enables it after
    completing its source-bound authorization and access-audit checks.
    """

    if not isinstance(plan, AblationPlan):
        raise AblationValidationError("plan must be an AblationPlan")
    if type(authorized_holdout) is not bool:
        raise AblationValidationError("authorized_holdout must be a boolean")
    if authorized_holdout and plan.split is not Split.HOLDOUT:
        raise AblationValidationError(
            "authorized holdout execution requires a holdout plan"
        )
    if plan.split is Split.HOLDOUT and not authorized_holdout:
        raise AblationValidationError(
            "generic ablation execution is forbidden for holdout; use an "
            "authorized holdout orchestrator that validates the completed "
            "pilot gate and per-contract access audits before any write or "
            "backend call"
        )
    if not isinstance(adapters, Mapping):
        raise AblationValidationError("adapters must be a mapping")
    if type(resume) is not bool:
        raise AblationValidationError("resume must be a boolean")
    if isinstance(output_root, str) and not output_root.strip():
        raise AblationValidationError("output_root must not be empty")
    if resource_scheduler is None:
        scheduler = ResourceScheduler(
            ResourcePolicy.from_resource_limits(plan.limits)
        )
    elif not isinstance(resource_scheduler, ResourceScheduler):
        raise AblationValidationError(
            "resource_scheduler must be a ResourceScheduler"
        )
    else:
        scheduler = resource_scheduler
        policy = scheduler.policy
        if (
            policy.max_workers > plan.limits.max_workers
            or policy.max_memory_bytes > plan.limits.max_memory_bytes
            or policy.max_solver_processes
            > plan.limits.max_solver_processes_per_case
        ):
            raise AblationValidationError(
                "resource scheduler policy exceeds the frozen plan limits"
            )
    receipt_start = len(scheduler.receipts)
    root = Path(output_root)
    plan_path = root / "state" / "ablation-plan.json"
    if plan_path.exists():
        if not resume:
            raise AblationValidationError(
                "existing plan cannot be used with resume disabled"
            )
        existing = AblationPlan.from_dict(_read_canonical(plan_path, "plan"))
        if existing != plan or existing.digest != plan.digest:
            raise AblationValidationError("existing plan conflicts with request")
    else:
        _write_once(plan_path, plan.to_dict())

    # The plan is the sole owner of run-contract construction.  Reusing its
    # canonical projection prevents per-executor duplicate contracts.
    contracts = plan.run_contracts
    contract_map = {
        (contract.requested_variant_id, contract.cache_mode): contract
        for contract in contracts
    }
    for contract in contracts:
        path = _contract_path(root, contract)
        if path.exists():
            try:
                existing = RunContract.from_dict(
                    _read_canonical(path, "run contract")
                )
            except (ProtocolContractError, TypeError, ValueError) as exc:
                raise AblationValidationError(
                    f"invalid existing run contract: {path}"
                ) from exc
            if existing != contract:
                raise AblationValidationError(
                    f"run contract conflicts with plan: {path}"
                )
        else:
            _write_once(path, contract.to_dict())
        scope_path = _cache_scope_path(root, contract)
        canonical_scope_root = scope_path.parent.resolve(strict=False)
        canonical_output_root = root.resolve(strict=False)
        if not canonical_scope_root.is_relative_to(canonical_output_root):
            raise AblationValidationError(
                "cache scope resolves outside the selected output root"
            )
        scope_record = {
            "schema": "ipfs-datasets.logic-pipeline-benchmark.cache-scope.v1",
            "plan_sha256": plan.digest,
            "run_id": plan.run_id,
            "variant_id": contract.requested_variant_id,
            "split": contract.split.value,
            "cache_mode": contract.cache_mode.value,
            "cache_namespace": contract.cache_namespace,
            "environment_sha256": plan.environment_sha256,
            "configuration_sha256": contract.configuration_sha256,
            "canonical_root": canonical_scope_root.as_posix(),
            "run_contract_sha256": _sha(contract.to_dict()),
        }
        if scope_path.exists():
            if _read_canonical(scope_path, "cache scope") != scope_record:
                raise AblationValidationError(
                    f"cache scope conflicts with plan: {scope_path}"
                )
        else:
            _write_once(scope_path, scope_record)

    expected_paths = {_result_path(root, job) for job in plan.jobs}
    results_root = root / "results"
    if results_root.exists():
        foreign = {
            path
            for path in results_root.rglob("*.json")
            if path not in expected_paths
        }
        if foreign:
            raise AblationValidationError(
                "foreign result records found: "
                + ", ".join(str(path) for path in sorted(foreign))
            )

    results: list[CaseResultRecord] = []
    executed: list[str] = []
    resumed: list[str] = []
    for job in plan.jobs:
        path = _result_path(root, job)
        contract = contract_map[(job.variant_id, job.cache_mode)]
        if path.exists():
            if not resume:
                raise AblationValidationError(
                    f"result exists with resume disabled: {path}"
                )
            result = _validate_envelope(
                _read_canonical(path, "result"), plan, job, contract
            )
            resumed.append(job.job_id)
        else:
            result = _execute_job(plan, job, adapters, scheduler)
            try:
                _write_once(path, _envelope(plan, job, contract, result))
                executed.append(job.job_id)
            except AblationValidationError:
                # A concurrent executor is accepted only after its exact
                # immutable record passes the same resume validation.
                result = _validate_envelope(
                    _read_canonical(path, "concurrent result"),
                    plan,
                    job,
                    contract,
                )
                resumed.append(job.job_id)
        results.append(result)
    return AblationRunResult(
        plan,
        contracts,
        tuple(results),
        tuple(executed),
        tuple(resumed),
        root,
        scheduler.receipts[receipt_start:],
    )


def execute_ablation(
    plan: AblationPlan,
    adapters: Mapping[object, object],
    *,
    output_root: str | Path,
    resume: bool = True,
    resource_scheduler: ResourceScheduler | None = None,
) -> AblationRunResult:
    """Execute non-holdout jobs or resume exact immutable evidence.

    Holdout remains fail-closed here even when a caller has assembled a
    structurally valid :class:`AblationPlan`.  The authorized holdout
    orchestrator is the sole supported execution entry point for that split.
    """

    return _execute_ablation(
        plan,
        adapters,
        output_root=output_root,
        resume=resume,
        resource_scheduler=resource_scheduler,
        authorized_holdout=False,
    )


__all__ = [
    "ABLATION_PLAN_SCHEMA",
    "ABLATION_RESULT_SCHEMA",
    "AblationCase",
    "AblationPlan",
    "AblationRunResult",
    "AblationRunnerError",
    "AblationValidationError",
    "ORDERING_ALGORITHM",
    "ResourceLimits",
    "ScheduledCase",
    "build_ablation_plan",
    "execute_ablation",
]
