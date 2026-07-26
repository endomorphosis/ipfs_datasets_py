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
import time
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from .adapters import (
    SpacyAdapter,
    StageAdapter,
    StageArtifact,
    StageInvocation,
    StageOutput,
    StageRequest,
    SymaiAdapter,
)
from .content_addressing import cid_for_bytes, cid_for_dag_json
from .cases import BenchmarkCase, ExpectedClass
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
from .cache_measurement import (
    extract_symai_cache_prime_receipt,
    extract_symai_cache_setup_telemetry,
    invoke_with_symai_cache_measurement,
)
from .contracts import (
    DEFAULT_PROTOCOL,
    DEFAULT_PROTOCOL_SHA256,
    RUN_CONTRACT_SCHEMA,
    CacheMode,
    CacheScope,
    CaseResultRecord,
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    RunContract,
    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    SemanticProjection,
    Split,
    StageName,
    StageStatus,
    TelemetryRecord,
    canonical_json,
    validate_native_kernel_receipt,
)
from .variants import (
    ALL_VARIANT_IDS,
    StagePolicy,
    VARIANT_REGISTRY,
    VARIANT_REGISTRY_SHA256,
    VariantDefinition,
    get_variant_definition,
)


ABLATION_PLAN_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.ablation-plan.v1"
)
LEGACY_ABLATION_RESULT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.ablation-result.v1"
)
ABLATION_RESULT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.ablation-result.v2"
)
ORDERING_ALGORITHM: Final = "sha256-seeded-counterbalanced-blocks-v2"
SEMANTIC_EXECUTION_PROFILE_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.semantic-execution-profile.v2"
)
SEMANTIC_V2_PROOF_SUPPRESSION_REASON: Final = (
    "semantic_v2_proof_boundary_closed_until_g210"
)
SEMANTIC_AMBIGUITY_GATE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "semantic-ambiguity-gate-decision.v2"
)
SEMANTIC_AMBIGUITY_GATE_RULE_V2: Final = (
    "strict-semantic-projection-uncertainty-v2"
)
MAX_CASE_INPUT_BYTES: Final = 64 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class AblationValidationError(ValueError):
    """Raised when plan, persistence, or resume evidence fails closed."""


class _SemanticFrontendValidationError(AblationValidationError):
    """Raised when an invoked G200 frontend emits invalid v2 evidence."""


# Descriptive compatibility name used by operators and earlier plan drafts.
AblationRunnerError = AblationValidationError


def _unix_time_ms() -> int:
    return int(time.time() * 1_000)


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

    @classmethod
    def from_benchmark_case_semantic_v2(
        cls, case: BenchmarkCase
    ) -> "AblationCase":
        """Project a reviewed case onto the source-only G200 trust boundary.

        Ground-truth labels and reviewed proof material stay on the caller's
        evaluator-side :class:`BenchmarkCase`; they are deliberately absent
        from both this scheduled case and every request derived from it.
        """

        if not isinstance(case, BenchmarkCase):
            raise AblationValidationError("case must be a BenchmarkCase")
        return cls(
            case.case_id,
            case.split,
            {"text": case.source_text},
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


def _validate_semantic_v2_plan(plan: AblationPlan) -> None:
    """Fail closed unless a plan contains only canonical source envelopes."""

    if not isinstance(plan, AblationPlan):
        raise AblationValidationError("plan must be an AblationPlan")
    for job in plan.jobs:
        value = job.case.input_data
        if (
            not isinstance(value, Mapping)
            or set(value) != {"text"}
            or not isinstance(value.get("text"), str)
            or not str(value["text"]).strip()
        ):
            raise AblationValidationError(
                "semantic protocol v2 plans must store only the canonical "
                '{"text": source_text} case envelope'
            )


def build_semantic_ablation_plan(
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
    """Build the additive G200 plan without scheduling evaluator-side fields."""

    projected = tuple(
        AblationCase.from_benchmark_case_semantic_v2(case)
        if isinstance(case, BenchmarkCase)
        else case
        for case in cases
    )
    plan = build_ablation_plan(
        run_id,
        projected,
        case_manifest_sha256=case_manifest_sha256,
        split=split,
        seed=seed,
        variant_ids=variant_ids,
        cache_modes=cache_modes,
        limits=limits,
        environment_sha256=environment_sha256,
        holdout_access_log_id=holdout_access_log_id,
    )
    _validate_semantic_v2_plan(plan)
    return plan


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
    stop_failure_code: FailureCode | None = None

    @property
    def complete(self) -> bool:
        return (
            self.stop_failure_code is None
            and len(self.results) == len(self.plan.jobs)
        )

    @property
    def executed_count(self) -> int:
        return len(self.executed_job_ids)

    @property
    def resumed_count(self) -> int:
        return len(self.resumed_job_ids)

    @property
    def result_paths(self) -> tuple[Path, ...]:
        return tuple(_result_path(self.output_root, job) for job in self.plan.jobs)


class _ProtocolStopTracker:
    """Apply frozen stop thresholds to the canonical scheduled result stream.

    Immediate incidents invalidate the entire execution.  Thresholded process
    failures stop conservatively when either the run-wide scheduled streak or
    the affected variant's own observation streak reaches the preregistered
    threshold.  A nonmatching observation resets the corresponding streak.
    """

    def __init__(self) -> None:
        self._global: tuple[FailureCode, int] | None = None
        self._by_variant: dict[str, tuple[FailureCode, int]] = {}
        self._configured = frozenset(
            condition.failure_code
            for condition in DEFAULT_PROTOCOL.stop_conditions
        )

    @staticmethod
    def _observed_failure(
        job: ScheduledCase,
        result: CaseResultRecord,
    ) -> FailureCode | None:
        input_data = job.input_data
        invalid_control = (
            isinstance(input_data, Mapping)
            and input_data.get("expected_class")
            == ExpectedClass.UNSUPPORTED.value
        )
        if invalid_control:
            kernel = next(
                (
                    stage
                    for stage in result.stages
                    if stage.stage is StageName.KERNEL
                ),
                None,
            )
            kernel_data = (
                kernel.data
                if kernel is not None
                and isinstance(kernel.data, Mapping)
                else {}
            )
            claims_raw_acceptance = bool(
                kernel is not None
                and (
                    kernel.kernel_accepted
                    or kernel_data.get("accepted") is True
                    or kernel_data.get("diagnostic_kernel_accepted") is True
                )
            )
            if not claims_raw_acceptance:
                return result.failure_code
            try:
                if result.terminal_kernel_accepted:
                    return FailureCode.INVALID_CONTROL_VERIFIED
            except ProtocolContractError:
                # A malformed positive claim is independently fatal even
                # though it cannot establish raw kernel acceptance.
                return FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
        return result.failure_code

    @staticmethod
    def _advance(
        previous: tuple[FailureCode, int] | None,
        current: FailureCode | None,
        configured: frozenset[FailureCode],
    ) -> tuple[FailureCode, int] | None:
        if current not in configured:
            return None
        if previous is not None and previous[0] is current:
            return current, previous[1] + 1
        return current, 1

    def observe(
        self,
        job: ScheduledCase,
        result: CaseResultRecord,
    ) -> FailureCode | None:
        """Return the stop code once either frozen streak reaches threshold."""

        code = self._observed_failure(job, result)
        self._global = self._advance(
            self._global,
            code,
            self._configured,
        )
        variant_streak = self._advance(
            self._by_variant.get(job.variant_id),
            code,
            self._configured,
        )
        if variant_streak is None:
            self._by_variant.pop(job.variant_id, None)
        else:
            self._by_variant[job.variant_id] = variant_streak
        counts = (
            0 if self._global is None else self._global[1],
            0 if variant_streak is None else variant_streak[1],
        )
        if (
            code is not None
            and code in self._configured
            and any(
                DEFAULT_PROTOCOL.stop_required(
                    code,
                    consecutive_occurrences=count,
                )
                for count in counts
                if count > 0
            )
        ):
            return code
        return None


def validate_ablation_evidence(
    plan: AblationPlan,
    *,
    output_root: str | Path,
    allow_legacy_results: bool = False,
) -> AblationRunResult:
    """Strictly reparse one complete persisted non-holdout execution.

    This is the read-only counterpart to :func:`execute_ablation`.  Aggregate
    benchmark receipts use it instead of trusting filenames, counts, or
    previously deserialized objects.  The function intentionally validates
    the plan, every run contract and cache scope, the exact result-file set,
    and every result envelope without importing or invoking a backend.
    Legacy v1 result envelopes are accepted only through the explicit
    compatibility switch for immutable, already-published evidence.
    """

    if not isinstance(plan, AblationPlan):
        raise AblationValidationError("plan must be an AblationPlan")
    if type(allow_legacy_results) is not bool:
        raise AblationValidationError(
            "allow_legacy_results must be a boolean"
        )
    if plan.split is Split.HOLDOUT:
        raise AblationValidationError(
            "generic persisted validation is forbidden for holdout evidence"
        )
    if isinstance(output_root, str) and not output_root.strip():
        raise AblationValidationError("output_root must not be empty")
    root = Path(output_root)
    plan_path = root / "state" / "ablation-plan.json"
    restored = AblationPlan.from_dict(_read_canonical(plan_path, "plan"))
    if restored != plan or restored.digest != plan.digest:
        raise AblationValidationError("persisted plan conflicts with request")
    semantic_protocol_cid = _read_semantic_execution_profile(root, plan)
    if semantic_protocol_cid is not None:
        _validate_semantic_v2_plan(plan)

    contracts = plan.run_contracts
    contract_map = {
        (contract.requested_variant_id, contract.cache_mode): contract
        for contract in contracts
    }
    for contract in contracts:
        contract_path = _contract_path(root, contract)
        try:
            persisted_contract = RunContract.from_dict(
                _read_canonical(contract_path, "run contract")
            )
        except (ProtocolContractError, TypeError, ValueError) as exc:
            raise AblationValidationError(
                f"invalid persisted run contract: {contract_path}"
            ) from exc
        if persisted_contract != contract:
            raise AblationValidationError(
                f"persisted run contract conflicts with plan: {contract_path}"
            )
        scope_path = _cache_scope_path(root, contract)
        scope = _mapping(_read_canonical(scope_path, "cache scope"), "cache scope")
        expected_scope_root = scope_path.parent.resolve(strict=False)
        canonical_output_root = root.resolve(strict=False)
        if not expected_scope_root.is_relative_to(canonical_output_root):
            raise AblationValidationError(
                "persisted cache scope resolves outside the selected output root"
            )
        portable_scope_root = expected_scope_root.relative_to(
            canonical_output_root
        ).as_posix()
        expected_scope = {
            "schema": "ipfs-datasets.logic-pipeline-benchmark.cache-scope.v1",
            "plan_sha256": plan.digest,
            "run_id": plan.run_id,
            "variant_id": contract.requested_variant_id,
            "split": contract.split.value,
            "cache_mode": contract.cache_mode.value,
            "cache_namespace": contract.cache_namespace,
            "environment_sha256": plan.environment_sha256,
            "configuration_sha256": contract.configuration_sha256,
            "canonical_root": portable_scope_root,
            "run_contract_sha256": _sha(contract.to_dict()),
        }
        if dict(scope) != expected_scope:
            raise AblationValidationError(
                f"persisted cache scope conflicts with plan: {scope_path}"
            )

    expected_paths = {_result_path(root, job) for job in plan.jobs}
    results_root = root / "results"
    actual_paths = (
        {path for path in results_root.rglob("*.json")}
        if results_root.exists()
        else set()
    )
    missing = expected_paths - actual_paths
    foreign = actual_paths - expected_paths
    if missing or foreign:
        raise AblationValidationError(
            "persisted result set is incomplete or foreign: "
            f"missing={len(missing)}, foreign={len(foreign)}"
        )

    results: list[CaseResultRecord] = []
    stop_tracker = _ProtocolStopTracker()
    for job in plan.jobs:
        contract = contract_map[(job.variant_id, job.cache_mode)]
        path = _result_path(root, job)
        result = _validate_envelope(
            _read_canonical(path, "result"),
            plan,
            job,
            contract,
            allow_legacy_result=allow_legacy_results,
            semantic_protocol_cid=semantic_protocol_cid,
        )
        results.append(result)
        stop_code = stop_tracker.observe(job, result)
        if stop_code is not None:
            raise AblationValidationError(
                "persisted evidence reaches a frozen protocol stop "
                f"condition: {stop_code.value}"
            )
    return AblationRunResult(
        plan=plan,
        contracts=contracts,
        results=tuple(results),
        executed_job_ids=(),
        resumed_job_ids=tuple(job.job_id for job in plan.jobs),
        output_root=root,
    )


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
        # Every frozen matrix is observational.  Pilot/development may inform
        # a later, separately frozen plan, but no in-run tuning is permitted.
        tuning_permitted=False,
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


def _semantic_execution_profile_path(root: Path) -> Path:
    return root / "state" / "semantic-execution-profile.json"


def _semantic_source_manifest_cid(plan: AblationPlan) -> str:
    cases: dict[str, str] = {}
    for job in plan.jobs:
        source_text = job.case.input_data.get("text")
        if not isinstance(source_text, str):
            raise AblationValidationError(
                "semantic source manifest requires exact source text"
            )
        source_cid = cid_for_bytes(source_text.encode("utf-8"))
        previous = cases.setdefault(job.case.case_id, source_cid)
        if previous != source_cid:
            raise AblationValidationError(
                "semantic source manifest case identity drifted"
            )
    return cid_for_dag_json(
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "semantic-source-manifest.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "split": plan.split.value,
            "cases": [
                {"case_id": case_id, "source_cid": cases[case_id]}
                for case_id in sorted(cases)
            ],
        }
    )


def _semantic_execution_profile(plan: AblationPlan) -> dict[str, object]:
    body = {
        "schema": SEMANTIC_EXECUTION_PROFILE_SCHEMA,
        "plan_sha256": plan.digest,
        "plan_cid": cid_for_dag_json(plan.to_dict()),
        "source_manifest_cid": _semantic_source_manifest_cid(plan),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "calibration_route_manifest_cid": (
            SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
        ),
        "calibration_metric_spec_cid": (
            SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
        ),
        "reviewed_target_source_cid": (
            SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
        ),
        "producer_input_fields": ["text"],
        "proof_boundary": SEMANTIC_V2_PROOF_SUPPRESSION_REASON,
        "ambiguity_gate": {
            "schema": SEMANTIC_AMBIGUITY_GATE_SCHEMA_V2,
            "rule": SEMANTIC_AMBIGUITY_GATE_RULE_V2,
        },
    }
    return {**body, "profile_cid": cid_for_dag_json(body)}


def _read_semantic_execution_profile(
    root: Path,
    plan: AblationPlan,
) -> str | None:
    path = _semantic_execution_profile_path(root)
    if not path.exists():
        return None
    profile = _mapping(
        _read_canonical(path, "semantic execution profile"),
        "semantic execution profile",
    )
    expected = _semantic_execution_profile(plan)
    if dict(profile) != expected:
        raise AblationValidationError(
            "semantic execution profile conflicts with plan or protocol"
        )
    return SEMANTIC_PROTOCOL_V2_CID


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


def _validate_semantic_v2_adapters(
    plan: AblationPlan,
    adapters: Mapping[object, object],
) -> None:
    """Reject a revision-1 frontend map before persistence or invocation."""

    frontend_stages = {
        StageName.COMPILER,
        StageName.SPACY,
        StageName.SYMAI,
    }
    for variant_id in plan.variant_ids:
        selected = _select_adapters(adapters, variant_id)
        definition = get_variant_definition(variant_id)
        for stage in definition.stages:
            if stage not in frontend_stages:
                continue
            adapter = selected.get(stage)
            if adapter is None:
                raise AblationValidationError(
                    f"semantic-v2 adapter map omits "
                    f"{variant_id}/{stage.value}"
                )
            if adapter.adapter_version != "2":
                raise AblationValidationError(
                    f"semantic-v2 requires adapter version 2 for "
                    f"{variant_id}/{stage.value}"
                )
            if isinstance(adapter, (SpacyAdapter, SymaiAdapter)):
                config = adapter.config
                if (
                    config is not None
                    and config.semantic_protocol_cid
                    != SEMANTIC_PROTOCOL_V2_CID
                ):
                    raise AblationValidationError(
                        f"{variant_id}/{stage.value} config is not bound "
                        "to the semantic-v2 protocol CID"
                    )
                if (
                    stage is StageName.SPACY
                    and isinstance(adapter, SpacyAdapter)
                    and config is not None
                ):
                    expected_mode = {
                        "current_effective": "full_model",
                        "full_model": "full_model",
                        "regex_legal": "regex_legal",
                        "blank_model": "blank_model",
                    }[definition.spacy_mode.value]
                    if config.mode.value != expected_mode:
                        raise AblationValidationError(
                            f"{variant_id}/spacy config mode "
                            f"{config.mode.value!r} conflicts with the "
                            f"frozen variant mode {expected_mode!r}"
                        )


def _validate_semantic_v2_result_frontends(
    result: CaseResultRecord,
    *,
    source_text: str,
) -> None:
    """Strictly parse every invoked frontend before result persistence."""

    for stage in result.stages:
        if stage.stage not in {
            StageName.COMPILER,
            StageName.SPACY,
            StageName.SYMAI,
        }:
            continue
        if (
            stage.provenance.effective_identity.get("graph_invoked")
            is not True
        ):
            continue
        _validate_semantic_v2_stage_record(
            stage,
            source_text=source_text,
        )


def _validate_semantic_v2_stage_record(
    stage: object,
    *,
    source_text: str,
) -> None:
    """Validate one materialized frontend record at the earliest boundary."""

    from .semantic_reassessment import (
        SemanticReassessmentError,
        validate_semantic_frontend_stage_v2,
    )

    try:
        validate_semantic_frontend_stage_v2(stage, source_text)
    except (
        ProtocolContractError,
        SemanticReassessmentError,
        TypeError,
        ValueError,
    ) as exc:
        stage_name = getattr(getattr(stage, "stage", None), "value", "frontend")
        raise _SemanticFrontendValidationError(
            f"semantic-v2 {stage_name} evidence failed strict "
            "validation"
        ) from exc


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

_RUNNER_FAILURE_CODES: Final = frozenset(
    {
        FailureCode.RESOURCE_LEASE_CANCELLATION,
        FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        FailureCode.OUT_OF_MEMORY,
        # The persisted-stop audit restamps this fatal protocol condition
        # through the same typed retained-job route.  It cannot contribute a
        # success and is rejected immediately by the stop tracker.
        FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
    }
)


_UNCERTAINTY_CUE = re.compile(
    r"(?i)\b(?:whether|may|might|could|unless|except|unclear|ambiguous|"
    r"does\s+not\s+(?:say|specify|state)|not\s+specified)\b"
)


def _frozen_invocation_order(
    definition: VariantDefinition,
) -> tuple[StageName, ...]:
    """Return the only execution order permitted by one frozen arm."""

    proof_stages = set(definition.proof_order)
    frontend = tuple(
        stage
        for stage in definition.stages
        if stage not in proof_stages | {StageName.KERNEL}
    )
    order = (
        *frontend,
        *definition.proof_order,
        *(
            (StageName.KERNEL,)
            if StageName.KERNEL in definition.stages
            else ()
        ),
    )
    if (
        len(order) != len(definition.stages)
        or set(order) != set(definition.stages)
    ):
        raise AblationValidationError(
            "registered invocation order is not a complete stage permutation"
        )
    return tuple(order)


def _ambiguity_gate_receipt(
    artifacts: Sequence[StageArtifact],
) -> dict[str, object]:
    """Return one label-blind, source-bound frontend uncertainty decision."""

    found_structured_frontend = False
    uncertainty_signals: set[str] = set()
    confidence_signals: set[str] = set()
    input_artifact_sha256s: list[str] = []
    for artifact in artifacts:
        if artifact.stage not in {StageName.COMPILER, StageName.SPACY}:
            continue
        input_artifact_sha256s.append(artifact.digest)
        if (
            not artifact.invoked
            or artifact.status is not StageStatus.SUCCESS
            or not isinstance(artifact.data, Mapping)
        ):
            uncertainty_signals.add(
                f"{artifact.stage.value}_evidence_unavailable"
            )
            continue
        data = artifact.data
        if artifact.stage is StageName.COMPILER:
            if data.get("schema") == (
                "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
            ):
                found_structured_frontend = True
                compiled = data.get("compiled_obligation")
                translation = data.get("entailment_translation")
                if isinstance(translation, Mapping):
                    confidence_signals.add(
                        "reviewed_entailment_translation_supported"
                    )
                elif isinstance(compiled, Mapping):
                    uncertainty_signals.add(
                        "reviewed_entailment_translation_unsupported"
                    )
        if artifact.stage is StageName.SPACY and data.get("schema") == (
            "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v1"
        ):
            found_structured_frontend = True
            modal_ir = data.get("modal_ir")
            normalized_text = (
                modal_ir.get("normalized_text")
                if isinstance(modal_ir, Mapping)
                else None
            )
            if isinstance(normalized_text, str) and _UNCERTAINTY_CUE.search(
                normalized_text
            ):
                uncertainty_signals.add("lexical_uncertainty_cue")
            modal_cues = data.get("modal_cues")
            if isinstance(modal_cues, (list, tuple)):
                cue_labels = {
                    str(item.get("label", item.get("cue", ""))).casefold()
                    for item in modal_cues
                    if isinstance(item, Mapping)
                }
                if len(modal_cues) > 1:
                    uncertainty_signals.add("multiple_modal_cues")
                if cue_labels & {"may", "might", "could", "can"}:
                    uncertainty_signals.add("ambiguous_modal_cue")
            formulas = (
                modal_ir.get("formulas")
                if isinstance(modal_ir, Mapping)
                else None
            )
            if isinstance(formulas, (list, tuple)) and any(
                isinstance(formula, Mapping)
                and (
                    bool(formula.get("conditions"))
                    or bool(formula.get("exceptions"))
                )
                for formula in formulas
            ):
                uncertainty_signals.add("conditional_or_exception_scope")
        queue: list[object] = [artifact.data]
        while queue:
            value = queue.pop()
            if isinstance(value, Mapping):
                if "ambiguity_detected" in value:
                    found_structured_frontend = True
                    if value["ambiguity_detected"] is True:
                        uncertainty_signals.add("explicit_ambiguity_detected")
                    elif value["ambiguity_detected"] is False:
                        confidence_signals.add("explicit_unambiguous_signal")
                for key in ("ambiguity_flags", "ambiguities"):
                    if key in value and isinstance(
                        value[key], (list, tuple)
                    ):
                        found_structured_frontend = True
                        if value[key]:
                            uncertainty_signals.add(
                                f"structured_{key}"
                            )
                queue.extend(value.values())
            elif isinstance(value, (list, tuple)):
                queue.extend(value)
    # A missing structured signal fails open so the conditional arm is not
    # silently weakened.  A successful frontend with neither an uncertainty
    # cue nor an unsupported reviewed translation closes deterministically.
    if not found_structured_frontend:
        uncertainty_signals.add("structured_frontend_signal_unavailable")
    ambiguous = bool(uncertainty_signals)
    body = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "ambiguity-gate-decision.v1"
        ),
        "decision": "invoke_symai" if ambiguous else "skip_symai",
        "ambiguity_detected": ambiguous,
        "uncertainty_signals": sorted(uncertainty_signals),
        "confidence_signals": sorted(confidence_signals),
        "input_artifact_sha256s": input_artifact_sha256s,
        "label_fields_consulted": [],
        "rule": "structured-frontend-uncertainty-v1",
    }
    return {**body, "decision_sha256": _sha(body)}


def _semantic_ambiguity_gate_receipt_v2(
    artifacts: Sequence[StageArtifact],
    *,
    source_cid: str,
) -> dict[str, object]:
    """Route only from already-validated, source-bound v2 projections."""

    projections: list[SemanticProjection] = []
    for artifact in artifacts:
        if artifact.stage not in {
            StageName.COMPILER,
            StageName.SPACY,
        }:
            continue
        if (
            not artifact.invoked
            or artifact.status is not StageStatus.SUCCESS
            or not isinstance(artifact.data, Mapping)
        ):
            continue
        raw_projection = artifact.data.get("semantic_projection")
        try:
            projection = SemanticProjection.from_dict(
                _thaw(raw_projection)
            )
        except (ProtocolContractError, TypeError, ValueError) as exc:
            raise AblationValidationError(
                "semantic ambiguity gate received an invalid projection"
            ) from exc
        if (
            projection.source_cid != source_cid
            or projection.semantic_protocol_cid
            != SEMANTIC_PROTOCOL_V2_CID
        ):
            raise AblationValidationError(
                "semantic ambiguity gate projection identity drifted"
            )
        projections.append(projection)

    uncertainty_signals: set[str] = set()
    confidence_signals: set[str] = set()
    if not projections:
        uncertainty_signals.add("semantic_projection_unavailable")
    for projection in projections:
        prefix = projection.producer_id
        if projection.ambiguity_flags:
            uncertainty_signals.add(f"{prefix}:ambiguity_flags")
        if projection.validation_errors:
            uncertainty_signals.add(f"{prefix}:validation_errors")
        if not all(projection.completeness.values()):
            uncertainty_signals.add(f"{prefix}:incomplete")
        if projection.semantic_class in {"ambiguous", "unsupported"}:
            uncertainty_signals.add(
                f"{prefix}:class_{projection.semantic_class}"
            )
        if (
            not projection.ambiguity_flags
            and not projection.validation_errors
            and all(projection.completeness.values())
            and projection.semantic_class in {"proved", "disproved"}
        ):
            confidence_signals.add(
                f"{prefix}:complete_explicit_class"
            )
    ambiguous = bool(uncertainty_signals)
    body = {
        "schema": SEMANTIC_AMBIGUITY_GATE_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "source_cid": source_cid,
        "decision": "invoke_symai" if ambiguous else "skip_symai",
        "ambiguity_detected": ambiguous,
        "uncertainty_signals": sorted(uncertainty_signals),
        "confidence_signals": sorted(confidence_signals),
        "input_projection_cids": [
            projection.projection_cid for projection in projections
        ],
        "input_semantic_content_cids": [
            projection.semantic_content_cid for projection in projections
        ],
        "label_fields_consulted": [],
        "rule": SEMANTIC_AMBIGUITY_GATE_RULE_V2,
    }
    return {**body, "decision_cid": cid_for_dag_json(body)}


def _ambiguity_decision(artifacts: Sequence[StageArtifact]) -> bool:
    """Compatibility predicate over the durable ambiguity-gate receipt."""

    return bool(_ambiguity_gate_receipt(artifacts)["ambiguity_detected"])


def _proof_candidate_ready(artifact: StageArtifact) -> bool:
    """Return whether a proof backend produced a usable unverified candidate.

    This predicate controls only the frozen one-fallback routing policy.  It
    does not confer proof authority: Hammer evidence and Leanstral drafts stay
    unverified until the independent terminal kernel accepts them.
    """

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


def _compiler_translation_unsupported(
    artifacts: Sequence[StageArtifact],
) -> bool:
    """Detect the real compiler's explicit opaque no-candidate contract.

    Legacy and injected compiler handlers predate these runtime fields.  The
    gate therefore fails open unless the successful compiler artifact exposes
    the exact compiler-output and compiled-obligation schemas together with
    explicit null translation and native-candidate fields.
    """

    compiler = next(
        (
            artifact
            for artifact in artifacts
            if artifact.stage is StageName.COMPILER
        ),
        None,
    )
    if (
        compiler is None
        or not compiler.invoked
        or compiler.status is not StageStatus.SUCCESS
        or not isinstance(compiler.data, Mapping)
    ):
        return False
    data = compiler.data
    required_fields = {
        "compiled_obligation",
        "entailment_translation",
        "native_proof_candidate",
    }
    if not required_fields.issubset(data):
        return False
    compiled = data["compiled_obligation"]
    return bool(
        data.get("schema")
        == "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
        and isinstance(compiled, Mapping)
        and compiled.get("schema")
        == "ipfs-datasets.logic-pipeline-benchmark.compiled-obligation.v1"
        and data["entailment_translation"] is None
        and data["native_proof_candidate"] is None
    )


def _compiler_native_candidate_ready(
    artifacts: Sequence[StageArtifact],
    input_data: object,
) -> bool:
    """Detect an exact source-bound compiler-native proof candidate.

    This predicate is intentionally stricter than the terminal kernel's
    compatibility surface because it may suppress a paid fallback call.  It
    recognizes only the live compiler v1 contract and binds every nested
    digest and source identifier back to the current case.  Legacy, injected,
    incomplete, or malformed artifacts fail open so Leanstral still runs.
    """

    compiler = next(
        (
            artifact
            for artifact in artifacts
            if artifact.stage is StageName.COMPILER
        ),
        None,
    )
    if (
        compiler is None
        or not compiler.invoked
        or compiler.status is not StageStatus.SUCCESS
        or not isinstance(compiler.data, Mapping)
        or not isinstance(input_data, Mapping)
        or compiler.effective_identity.get("entrypoint")
        != (
            "ipfs_datasets_py.logic.modal.codec."
            "DeterministicModalLogicCodec.encode"
        )
        or compiler.effective_identity.get("graph_invoked") is not True
        or compiler.effective_identity.get("graph_invocation_index") != 0
    ):
        return False
    data = compiler.data
    required_fields = {
        "compiled_obligation",
        "compiled_obligation_sha256",
        "entailment_translation",
        "entailment_translation_sha256",
        "native_proof_candidate",
    }
    if (
        data.get("schema")
        != "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v1"
        or not required_fields.issubset(data)
    ):
        return False
    try:
        # Import lazily to keep the ablation/runtime module boundary acyclic.
        # Reconstructing the reviewed compiler output is intentionally the
        # same source-bound check used by the independent kernel.
        from .runtime import (
            NATIVE_PROOF_CANDIDATE_SCHEMA,
            _entailment_translation,
            compile_reviewed_obligation,
        )

        expected_compiled = compile_reviewed_obligation(input_data)
        if expected_compiled is None:
            return False
        expected_translation = _entailment_translation(
            input_data,
            theorem_name=expected_compiled.theorem_name,
            obligation_sha256=expected_compiled.obligation_sha256,
            kind=expected_compiled.kind,
            logic=expected_compiled.logic,
            semantic_target=expected_compiled.semantic_target,
        )
        if (
            expected_translation is None
            or expected_translation.native_proof_text is None
        ):
            return False
        expected_candidate = {
            "schema": NATIVE_PROOF_CANDIDATE_SCHEMA,
            "translation_sha256": expected_translation.digest,
            "obligation_sha256": expected_compiled.obligation_sha256,
            "source_sha256": expected_translation.source_sha256,
            "derivation": expected_translation.shape,
            "certificate": expected_translation.native_proof_text,
            "authoritative": False,
            "requires_independent_kernel": True,
        }
    except (ImportError, ProtocolContractError, TypeError, ValueError):
        return False

    return bool(
        _thaw(data["compiled_obligation"])
        == expected_compiled.to_dict()
        and data["compiled_obligation_sha256"]
        == expected_compiled.digest
        and _thaw(data["entailment_translation"])
        == expected_translation.to_dict()
        and data["entailment_translation_sha256"]
        == expected_translation.digest
        and _thaw(data["native_proof_candidate"])
        == expected_candidate
    )


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


def _semantic_identity_binding(
    request: StageRequest,
) -> dict[str, object]:
    if request.semantic_protocol_cid is None:
        return {}
    return {
        "semantic_protocol_cid": request.semantic_protocol_cid,
        "source_cid": request.source_cid,
        "proof_context_cid": request.proof_context_cid,
    }


def _synthetic_invocation(
    stage: StageName,
    request: StageRequest,
    *,
    reason: str,
    policy_decision: Mapping[str, object] | None = None,
) -> StageInvocation:
    decision = (
        {}
        if policy_decision is None
        else {"policy_decision": _thaw(policy_decision)}
    )
    decision_identity = (
        {}
        if policy_decision is None
        else {
            "policy_decision_sha256": policy_decision.get(
                "decision_sha256"
            ),
            "policy_decision": policy_decision.get("decision"),
        }
    )
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
            **decision,
        },
        effective_identity={
            **dict(request.requested_identity),
            **_semantic_identity_binding(request),
            "invoked": False,
            "policy_reason": reason,
            "graph_invocation_index": request.invocation_index,
            "graph_invoked": False,
            "consumed_artifact_sha256": tuple(
                artifact.digest for artifact in request.upstream_artifacts
            ),
            **decision_identity,
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
    *,
    semantic_protocol_cid: str | None = None,
) -> CaseResultRecord:
    if (
        semantic_protocol_cid is not None
        and semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID
    ):
        raise AblationValidationError(
            "unsupported semantic execution protocol CID"
        )
    if semantic_protocol_cid is not None:
        _validate_semantic_v2_plan(plan)
    definition = get_variant_definition(job.variant_id)
    invocation_order = _frozen_invocation_order(definition)

    invocations: dict[StageName, StageInvocation] = {}
    artifacts: list[StageArtifact] = []
    bounded_detail = (detail.strip() or "ablation failure")[:512]
    for invocation_index, stage in enumerate(invocation_order):
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
            upstream_artifacts=tuple(artifacts),
            invocation_index=invocation_index,
            semantic_protocol_cid=semantic_protocol_cid,
        )
        reason = (
            "retained_job_failure"
            if invocation_index == 0
            else "upstream_terminal_failure"
        )
        if invocation_index == 0:
            consumed = tuple(
                artifact.digest for artifact in request.upstream_artifacts
            )
            data = {
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "policy-decision.v1"
                ),
                "stage": stage.value,
                "invoked": False,
                "reason": reason,
                "invocation_index": invocation_index,
                "consumed_artifact_sha256": list(consumed),
            }
            telemetry = TelemetryRecord(
                input_items=1,
                output_items=0,
                model_calls=0,
                bytes_in=request.input_bytes,
                resource_lane=_RESOURCE_LANE[stage],
            )
            invocation = StageInvocation(
                StageOutput(
                    status=StageStatus.FAILED,
                    data=data,
                    effective_identity={
                        **dict(request.requested_identity),
                        **_semantic_identity_binding(request),
                        "invoked": False,
                        "policy_reason": reason,
                        "graph_invocation_index": invocation_index,
                        "graph_invoked": False,
                        "consumed_artifact_sha256": consumed,
                    },
                    telemetry=telemetry,
                    failure_code=code,
                    failure_detail=bounded_detail,
                ),
                telemetry,
            )
        else:
            invocation = _synthetic_invocation(
                stage,
                request,
                reason=reason,
            )
        invocations[stage] = invocation
        artifacts.append(
            _artifact(
                stage,
                invocation,
                invocation_index=invocation_index,
                invoked=False,
                reason=reason,
            )
        )

    records = []
    canonical_upstream: tuple[str, ...] = ()
    by_stage_artifacts = tuple(artifacts)
    for stage in definition.stages:
        artifact = next(
            item for item in artifacts if item.stage is stage
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
            upstream_stage_digests=canonical_upstream,
            upstream_artifacts=by_stage_artifacts,
            invocation_index=artifact.invocation_index,
            semantic_protocol_cid=semantic_protocol_cid,
        )
        record = StageAdapter(stage).record(
            request,
            invocations[stage],
        )
        records.append(record)
        canonical_upstream = (*canonical_upstream, record.digest)
    return CaseResultRecord.from_stages(tuple(records))


def _execute_job(
    plan: AblationPlan,
    job: ScheduledCase,
    adapters: Mapping[object, object],
    scheduler: ResourceScheduler,
    *,
    semantic_protocol_cid: str | None = None,
) -> CaseResultRecord:
    if (
        semantic_protocol_cid is not None
        and semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID
    ):
        raise AblationValidationError(
            "unsupported semantic execution protocol CID"
        )
    if semantic_protocol_cid is not None:
        _validate_semantic_v2_plan(plan)
        _validate_semantic_v2_adapters(plan, adapters)
    definition = get_variant_definition(job.variant_id)
    case_deadline_unix_ms = _unix_time_ms() + max(
        1,
        math.ceil(plan.limits.case_timeout_seconds * 1_000),
    )
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
                semantic_protocol_cid=semantic_protocol_cid,
                deadline_unix_ms=case_deadline_unix_ms,
            )

        def invoke(
            stage: StageName,
            *,
            should_invoke: bool = True,
            reason: str = "scheduled",
            policy_decision: Mapping[str, object] | None = None,
        ) -> StageArtifact:
            nonlocal invocation_index
            adapter = selected.get(stage, StageAdapter(stage))
            request = request_for(stage)
            if not should_invoke:
                invocation = _synthetic_invocation(
                    stage,
                    request,
                    reason=reason,
                    policy_decision=policy_decision,
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
                remaining_case_ms = (
                    case_deadline_unix_ms - _unix_time_ms()
                )
                if remaining_case_ms <= 0:
                    raise ResourceLeaseTimeout(
                        "case deadline expired before resource lease for "
                        f"{job.job_id}"
                    )
                lease_request = ResourceLeaseRequest(
                    owner_id=f"lease-{job.ordinal}-{stage.value}",
                    resource_class=resource_class,
                    model_identity=model_identity,
                    timeout_seconds=remaining_case_ms / 1_000,
                )
                with scheduler.acquire(lease_request) as lease:
                    lease.assert_active()
                    if _unix_time_ms() >= case_deadline_unix_ms:
                        raise ResourceLeaseTimeout(
                            "case deadline expired during resource lease for "
                            f"{job.job_id}"
                        )
                    invocation = invoke_with_symai_cache_measurement(
                        adapter, request
                    )
                if policy_decision is not None:
                    output = invocation.output
                    if isinstance(output.data, Mapping):
                        if "routing_policy" in output.data:
                            raise AblationValidationError(
                                "stage output collided with routing-policy receipt"
                            )
                        output = replace(
                            output,
                            data={
                                **dict(output.data),
                                "routing_policy": _thaw(policy_decision),
                            },
                        )
                    invocation = StageInvocation(
                        output,
                        invocation.telemetry,
                    )
                identity = {
                    **dict(
                        invocation.output.effective_identity
                        or request.requested_identity
                    ),
                    **_semantic_identity_binding(request),
                    "graph_invocation_index": invocation_index,
                    "graph_invoked": True,
                    "graph_policy_reason": reason,
                    "consumed_artifact_sha256": tuple(
                        artifact.digest for artifact in artifacts
                    ),
                    **(
                        {}
                        if policy_decision is None
                        else {
                            **(
                                {
                                    "policy_decision_cid": (
                                        policy_decision.get("decision_cid")
                                    )
                                }
                                if "decision_cid" in policy_decision
                                else {
                                    "policy_decision_sha256": (
                                        policy_decision.get(
                                            "decision_sha256"
                                        )
                                    )
                                }
                            ),
                            "policy_decision": policy_decision.get(
                                "decision"
                            ),
                        }
                    ),
                }
                invocation = StageInvocation(
                    replace(
                        invocation.output,
                        effective_identity=identity,
                    ),
                    invocation.telemetry,
                )
                if (
                    semantic_protocol_cid is not None
                    and stage
                    in {
                        StageName.COMPILER,
                        StageName.SPACY,
                        StageName.SYMAI,
                    }
                ):
                    source_text = job.case.input_data.get("text")
                    if not isinstance(source_text, str):
                        raise _SemanticFrontendValidationError(
                            "semantic-v2 invocation lost source text"
                        )
                    _validate_semantic_v2_stage_record(
                        adapter.record(request, invocation),
                        source_text=source_text,
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
            if terminal_failure:
                invoke(
                    stage,
                    should_invoke=False,
                    reason="upstream_terminal_failure",
                )
                continue
            gate_receipt = (
                (
                    _semantic_ambiguity_gate_receipt_v2(
                        artifacts,
                        source_cid=cid_for_bytes(
                            str(job.case.input_data["text"]).encode("utf-8")
                        ),
                    )
                    if semantic_protocol_cid is not None
                    else _ambiguity_gate_receipt(artifacts)
                )
                if stage is StageName.SYMAI
                and definition.symai_policy
                is StagePolicy.AMBIGUITY_GATED
                else None
            )
            should_invoke = not (
                stage is StageName.SYMAI
                and definition.symai_policy is StagePolicy.AMBIGUITY_GATED
                and gate_receipt is not None
                and not gate_receipt["ambiguity_detected"]
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
                policy_decision=gate_receipt,
            )
            if artifact.status is not StageStatus.SUCCESS:
                terminal_failure = True

        semantic_v2 = semantic_protocol_cid is not None
        has_obligation = (
            False
            if semantic_v2
            else _has_obligation(job.case.input_data)
        )
        compiler_translation_unsupported = (
            _compiler_translation_unsupported(artifacts)
        )
        previous_proof: StageArtifact | None = None
        if semantic_v2:
            for stage in definition.proof_order:
                invoke(
                    stage,
                    should_invoke=False,
                    reason=SEMANTIC_V2_PROOF_SUPPRESSION_REASON,
                )
        elif terminal_failure:
            for stage in definition.proof_order:
                invoke(
                    stage,
                    should_invoke=False,
                    reason="upstream_terminal_failure",
                )
        else:
            for proof_index, stage in enumerate(definition.proof_order):
                should_invoke = has_obligation
                reason = "proof_scheduled"
                if not has_obligation:
                    reason = "no_reviewed_proof_obligation"
                elif compiler_translation_unsupported:
                    should_invoke = False
                    reason = "compiler_translation_unsupported"
                elif (
                    proof_index == 0
                    and stage is StageName.LEANSTRAL
                    and definition.leanstral_policy
                    is StagePolicy.PROOF_FAILURE_FALLBACK
                    and _compiler_native_candidate_ready(
                        artifacts, job.case.input_data
                    )
                ):
                    should_invoke = False
                    reason = "proof_fallback_suppressed"
                elif proof_index and job.variant_id != "A12":
                    should_invoke = not (
                        previous_proof is not None
                        and _proof_candidate_ready(previous_proof)
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

        if StageName.KERNEL in definition.stages:
            kernel_should_invoke = (
                not semantic_v2
                and not terminal_failure
                and not (
                    definition.proof_order and not has_obligation
                )
            )
            kernel_artifact = invoke(
                StageName.KERNEL,
                should_invoke=kernel_should_invoke,
                reason=(
                    SEMANTIC_V2_PROOF_SUPPRESSION_REASON
                    if semantic_v2
                    else (
                        "upstream_terminal_failure"
                        if terminal_failure
                        else (
                            "no_reviewed_proof_obligation"
                            if not kernel_should_invoke
                            else (
                                "legacy_diagnostic_kernel"
                                if definition.safety_diagnostic_only
                                else "independent_native_kernel"
                            )
                        )
                    )
                ),
            )
            if (
                definition.safety_diagnostic_only
                and invocations[StageName.KERNEL].output.kernel_accepted
            ):
                original = invocations[StageName.KERNEL]
                original_data = _mapping(
                    original.output.data,
                    "S1 native-kernel diagnostic receipt",
                )
                if not validate_native_kernel_receipt(
                    original_data,
                    protocol_sha256=DEFAULT_PROTOCOL_SHA256,
                    run_id=plan.run_id,
                    case_id=job.case.case_id,
                    case_manifest_sha256=plan.case_manifest_sha256,
                    variant_id=job.variant_id,
                    split=plan.split,
                    cache_mode=job.cache_mode,
                    input_sha256=job.input_sha256,
                    environment_sha256=plan.environment_sha256,
                    stage_status=original.output.status,
                    kernel_accepted=True,
                    kernel_receipt_sha256=(
                        original.output.kernel_receipt_sha256
                    ),
                    consumed_artifact_sha256s=tuple(
                        artifact.digest for artifact in artifacts[:-1]
                    ),
                    failure_code=original.output.failure_code,
                ):
                    raise AblationValidationError(
                        "S1 diagnostic kernel receipt was not accepted"
                    )
                diagnostic_receipt = _thaw(original_data)
                signed_rejection = {
                    key: diagnostic_receipt[key]
                    for key in (
                        "schema",
                        "protocol_sha256",
                        "run_id",
                        "case_id",
                        "case_manifest_sha256",
                        "variant_id",
                        "split",
                        "cache_mode",
                        "input_sha256",
                        "environment_sha256",
                        "independent",
                    )
                }
                signed_rejection.update(
                    {
                        "accepted": False,
                        "active_process_count": 0,
                        "reason": "diagnostic_only_authority_withheld",
                        "diagnostic_only": True,
                        "authority_withheld": True,
                        "diagnostic_kernel_accepted": True,
                        "diagnostic_receipt_sha256": diagnostic_receipt[
                            "receipt_sha256"
                        ],
                        "diagnostic_receipt": diagnostic_receipt,
                    }
                )
                data = {
                    **signed_rejection,
                    "receipt_sha256": _sha(signed_rejection),
                }
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
                semantic_protocol_cid=semantic_protocol_cid,
                deadline_unix_ms=case_deadline_unix_ms,
            )
            record = adapter.record(request, invocation)
            records.append(record)
            canonical_upstream = (*canonical_upstream, record.digest)
        result = CaseResultRecord.from_stages(tuple(records))
        if semantic_protocol_cid is not None:
            source_text = job.case.input_data.get("text")
            if not isinstance(source_text, str):
                raise _SemanticFrontendValidationError(
                    "semantic-v2 job lost its exact source text"
                )
            _validate_semantic_v2_result_frontends(
                result,
                source_text=source_text,
            )
    except _SemanticFrontendValidationError:
        raise
    except (ResourceLeaseTimeout, ResourceLeaseCancelled, ResourceLeaseError) as exc:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            f"resource lease failed for {job.job_id}: {type(exc).__name__}",
            semantic_protocol_cid=semantic_protocol_cid,
        )
    except Exception as exc:
        return _failure(
            plan,
            job,
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            f"runner retained {type(exc).__name__} for {job.job_id}",
            semantic_protocol_cid=semantic_protocol_cid,
        )

    setup_telemetry = tuple(
        setup
        for record in result.stages
        if (
            setup := extract_symai_cache_setup_telemetry(record)
        )
        is not None
    )
    wall_ms = sum(
        record.telemetry.wall_time_ms for record in result.stages
    ) + sum(item.wall_time_ms for item in setup_telemetry)
    peak_memory = max(
        (
            *(
                record.telemetry.peak_memory_bytes
                for record in result.stages
            ),
            *(item.peak_memory_bytes for item in setup_telemetry),
        ),
        default=0,
    )
    model_calls = sum(
        record.telemetry.model_calls for record in result.stages
    ) + sum(item.model_calls for item in setup_telemetry)
    solver_stages = sum(
        record.telemetry.resource_lane is ResourceLane.SOLVER
        for record in result.stages
    )
    if peak_memory > plan.limits.max_memory_bytes:
        return _failure(
            plan,
            job,
            FailureCode.OUT_OF_MEMORY,
            "memory limit exceeded",
            semantic_protocol_cid=semantic_protocol_cid,
        )
    if wall_ms > plan.limits.case_timeout_seconds * 1_000:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            "case timeout exceeded",
            semantic_protocol_cid=semantic_protocol_cid,
        )
    if model_calls > plan.limits.max_model_calls_per_case:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            "model-call limit exceeded",
            semantic_protocol_cid=semantic_protocol_cid,
        )
    if solver_stages > plan.limits.max_solver_processes_per_case:
        return _failure(
            plan,
            job,
            FailureCode.RESOURCE_LEASE_CANCELLATION,
            "solver-process limit exceeded",
            semantic_protocol_cid=semantic_protocol_cid,
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


def _validate_current_policy_graph(
    result: CaseResultRecord,
    *,
    plan: AblationPlan,
    job: ScheduledCase,
    ordered_artifacts: tuple[StageArtifact, ...],
    semantic_protocol_cid: str | None = None,
) -> None:
    """Recompute every frozen routing decision in a current result graph.

    Invocation markers and a valid content-addressed chain are necessary but
    not sufficient evidence: an attacker could otherwise suppress every
    backend, rehash the graph, and retain a structurally valid result.  This
    validator mirrors the frozen, label-blind routing policy in
    :func:`_execute_job` over the persisted artifacts.
    """

    definition = get_variant_definition(job.variant_id)
    records = {record.stage: record for record in result.stages}
    artifacts = {artifact.stage: artifact for artifact in ordered_artifacts}

    retained = tuple(
        artifact
        for artifact in ordered_artifacts
        if artifact.policy_reason == "retained_job_failure"
    )
    if retained:
        first = ordered_artifacts[0]
        first_record = records[first.stage]
        later = ordered_artifacts[1:]
        if (
            retained != (first,)
            or first.invoked
            or first.status is not StageStatus.FAILED
            or first_record.failure_code not in _RUNNER_FAILURE_CODES
            or result.failure_code is not first_record.failure_code
            or any(
                artifact.invoked
                or artifact.status is not StageStatus.SUCCESS
                or artifact.policy_reason != "upstream_terminal_failure"
                for artifact in later
            )
        ):
            raise AblationValidationError(
                "current result graph has a noncanonical retained runner "
                "failure route"
            )
        return

    def require(
        stage: StageName,
        *,
        invoked: bool,
        reason: str,
    ) -> StageArtifact:
        artifact = artifacts[stage]
        record = records[stage]
        if artifact.invoked is not invoked or artifact.policy_reason != reason:
            raise AblationValidationError(
                "current result graph invocation decision differs from the "
                f"frozen policy at {stage.value}"
            )
        if not invoked and record.status is not StageStatus.SUCCESS:
            raise AblationValidationError(
                "suppressed current result stage is not a successful policy "
                f"decision at {stage.value}"
            )
        return artifact

    evaluated: list[StageArtifact] = []
    proof_stages = set(definition.proof_order)
    frontend = tuple(
        stage
        for stage in definition.stages
        if stage not in proof_stages | {StageName.KERNEL}
    )
    terminal_failure = False
    for stage in frontend:
        if terminal_failure:
            artifact = require(
                stage,
                invoked=False,
                reason="upstream_terminal_failure",
            )
        else:
            gate_receipt = (
                (
                    _semantic_ambiguity_gate_receipt_v2(
                        evaluated,
                        source_cid=cid_for_bytes(
                            str(job.case.input_data["text"]).encode("utf-8")
                        ),
                    )
                    if semantic_protocol_cid is not None
                    else _ambiguity_gate_receipt(evaluated)
                )
                if stage is StageName.SYMAI
                and definition.symai_policy is StagePolicy.AMBIGUITY_GATED
                else None
            )
            should_invoke = not (
                gate_receipt is not None
                and not bool(gate_receipt["ambiguity_detected"])
            )
            reason = (
                "frontend_ambiguity_gate_closed"
                if not should_invoke
                else (
                    "frontend_ambiguity_gate_open"
                    if gate_receipt is not None
                    else "frontend_scheduled"
                )
            )
            artifact = require(
                stage,
                invoked=should_invoke,
                reason=reason,
            )
            if gate_receipt is not None:
                receipt_field = (
                    "routing_policy"
                    if should_invoke
                    else "policy_decision"
                )
                decision_identity_field = (
                    "policy_decision_cid"
                    if semantic_protocol_cid is not None
                    else "policy_decision_sha256"
                )
                decision_receipt_field = (
                    "decision_cid"
                    if semantic_protocol_cid is not None
                    else "decision_sha256"
                )
                if (
                    not isinstance(artifact.data, Mapping)
                    or _thaw(artifact.data.get(receipt_field))
                    != gate_receipt
                    or artifact.effective_identity.get(
                        decision_identity_field
                    )
                    != gate_receipt[decision_receipt_field]
                    or artifact.effective_identity.get("policy_decision")
                    != gate_receipt["decision"]
                ):
                    raise AblationValidationError(
                        "current SyMAI ambiguity gate receipt differs from "
                        "the frozen label-blind decision"
                    )
            if artifact.status is not StageStatus.SUCCESS:
                terminal_failure = True
        evaluated.append(artifact)

    semantic_v2 = semantic_protocol_cid is not None
    has_obligation = (
        False if semantic_v2 else _has_obligation(job.case.input_data)
    )
    compiler_translation_unsupported = (
        _compiler_translation_unsupported(evaluated)
    )
    previous_proof: StageArtifact | None = None
    for proof_index, stage in enumerate(definition.proof_order):
        if semantic_v2:
            artifact = require(
                stage,
                invoked=False,
                reason=SEMANTIC_V2_PROOF_SUPPRESSION_REASON,
            )
        elif terminal_failure:
            artifact = require(
                stage,
                invoked=False,
                reason="upstream_terminal_failure",
            )
        else:
            should_invoke = has_obligation
            reason = "proof_scheduled"
            if not has_obligation:
                reason = "no_reviewed_proof_obligation"
            elif compiler_translation_unsupported:
                should_invoke = False
                reason = "compiler_translation_unsupported"
            elif (
                proof_index == 0
                and stage is StageName.LEANSTRAL
                and definition.leanstral_policy
                is StagePolicy.PROOF_FAILURE_FALLBACK
                and _compiler_native_candidate_ready(
                    evaluated,
                    job.case.input_data,
                )
            ):
                should_invoke = False
                reason = "proof_fallback_suppressed"
            elif proof_index and job.variant_id != "A12":
                should_invoke = not (
                    previous_proof is not None
                    and _proof_candidate_ready(previous_proof)
                )
                reason = (
                    "proof_fallback_suppressed"
                    if not should_invoke
                    else "proof_failure_fallback"
                )
            artifact = require(
                stage,
                invoked=should_invoke,
                reason=reason,
            )
        previous_proof = artifact
        evaluated.append(artifact)

    if StageName.KERNEL in definition.stages:
        kernel_should_invoke = (
            not semantic_v2
            and not terminal_failure
            and not (definition.proof_order and not has_obligation)
        )
        require(
            StageName.KERNEL,
            invoked=kernel_should_invoke,
            reason=(
                SEMANTIC_V2_PROOF_SUPPRESSION_REASON
                if semantic_v2
                else (
                    "upstream_terminal_failure"
                    if terminal_failure
                    else (
                        "no_reviewed_proof_obligation"
                        if not kernel_should_invoke
                        else (
                            "legacy_diagnostic_kernel"
                            if definition.safety_diagnostic_only
                            else "independent_native_kernel"
                        )
                    )
                )
            ),
        )


def validate_current_result_graph(
    result: CaseResultRecord,
    *,
    plan: AblationPlan,
    job: ScheduledCase,
    semantic_protocol_cid: str | None = None,
) -> None:
    """Bind a v2 result to the complete frozen route and invocation graph."""

    if (
        semantic_protocol_cid is not None
        and semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID
    ):
        raise AblationValidationError(
            "unsupported semantic execution protocol CID"
        )
    if semantic_protocol_cid is not None:
        _validate_semantic_v2_plan(plan)
    definition = get_variant_definition(job.variant_id)
    if tuple(stage.stage for stage in result.stages) != definition.stages:
        raise AblationValidationError(
            "current result route differs from the frozen variant definition"
        )

    indexed: list[tuple[int, StageArtifact]] = []
    for stage in result.stages:
        expected_requested_identity = dict(
            definition.requested_identity(stage.stage)
        )
        if semantic_protocol_cid is not None:
            source_text = job.case.input_data["text"]
            assert isinstance(source_text, str)
            expected_requested_identity.update(
                {
                    "semantic_protocol_cid": semantic_protocol_cid,
                    "source_cid": cid_for_bytes(
                        source_text.encode("utf-8")
                    ),
                    "proof_context_cid": None,
                }
            )
        if (
            stage.provenance.requested_identity
            != expected_requested_identity
        ):
            raise AblationValidationError(
                "current result stage identity differs from the frozen "
                "variant definition"
            )
        identity = stage.provenance.effective_identity
        invoked = identity.get("graph_invoked")
        invocation_index = identity.get("graph_invocation_index")
        if (
            type(invoked) is not bool
            or isinstance(invocation_index, bool)
            or not isinstance(invocation_index, int)
            or not 0 <= invocation_index < len(result.stages)
        ):
            raise AblationValidationError(
                "current result graph invocation fields are invalid"
            )
        if (
            stage.stage is StageName.SYMAI
            and job.cache_mode is CacheMode.WARM
            and invoked
            and definition.symai_policy
            is not StagePolicy.LEGACY_DIAGNOSTIC
        ):
            try:
                cache_prime = extract_symai_cache_prime_receipt(stage)
            except ProtocolContractError as exc:
                raise AblationValidationError(
                    "current warm SyMAI stage has an invalid cache-prime "
                    "receipt"
                ) from exc
            if cache_prime is None:
                raise AblationValidationError(
                    "current warm graph-invoked non-legacy SyMAI stage "
                    "omitted its cache-prime receipt"
                )
        reason_field = (
            "graph_policy_reason" if invoked else "policy_reason"
        )
        reason = identity.get(reason_field)
        if not isinstance(reason, str) or not reason.strip():
            raise AblationValidationError(
                "current result graph policy reason is missing"
            )
        if not invoked:
            policy = stage.data
            if (
                not isinstance(policy, Mapping)
                or policy.get("schema")
                != (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "policy-decision.v1"
                )
                or policy.get("stage") != stage.stage.value
                or policy.get("invoked") is not False
                or policy.get("reason") != reason
                or policy.get("invocation_index") != invocation_index
            ):
                raise AblationValidationError(
                    "suppressed current result stage lacks its exact graph "
                    "decision receipt"
                )
        elif (
            isinstance(stage.data, Mapping)
            and stage.data.get("schema")
            == (
                "ipfs-datasets.logic-pipeline-benchmark."
                "policy-decision.v1"
            )
            and stage.data.get("invoked") is False
        ):
            raise AblationValidationError(
                "invoked current result stage contains a suppression receipt"
            )
        try:
            artifact = StageArtifact(
                stage=stage.stage,
                status=stage.status,
                data=stage.data,
                output_sha256=stage.output_sha256,
                effective_identity=identity,
                invocation_index=invocation_index,
                invoked=invoked,
                policy_reason=reason,
            )
        except ProtocolContractError as exc:
            raise AblationValidationError(
                "current result graph artifact is invalid"
            ) from exc
        indexed.append((invocation_index, artifact))

    indexed.sort(key=lambda item: item[0])
    if [index for index, _ in indexed] != list(range(len(result.stages))):
        raise AblationValidationError(
            "current result graph invocation order is incomplete"
        )
    frozen_order = _frozen_invocation_order(definition)
    if tuple(artifact.stage for _, artifact in indexed) != frozen_order:
        raise AblationValidationError(
            "current result graph differs from the frozen invocation order"
        )
    consumed: list[str] = []
    for _, artifact in indexed:
        raw_consumed = artifact.effective_identity.get(
            "consumed_artifact_sha256"
        )
        if (
            not isinstance(raw_consumed, Sequence)
            or isinstance(raw_consumed, (str, bytes, bytearray))
            or tuple(raw_consumed) != tuple(consumed)
        ):
            raise AblationValidationError(
                "current result graph artifact chain is invalid"
            )
        if not artifact.invoked:
            policy_consumed = artifact.data.get(
                "consumed_artifact_sha256"
            )
            if (
                not isinstance(policy_consumed, Sequence)
                or isinstance(
                    policy_consumed, (str, bytes, bytearray)
                )
                or tuple(policy_consumed) != tuple(consumed)
            ):
                raise AblationValidationError(
                    "suppressed current result stage receipt has an invalid "
                    "artifact chain"
                )
        consumed.append(artifact.digest)

    _validate_current_policy_graph(
        result,
        plan=plan,
        job=job,
        ordered_artifacts=tuple(artifact for _, artifact in indexed),
        semantic_protocol_cid=semantic_protocol_cid,
    )

    try:
        result.validate_provenance(
            expected_environment_sha256=plan.environment_sha256
        )
    except ProtocolContractError as exc:
        raise AblationValidationError(
            "current result provenance graph is invalid"
        ) from exc
    if semantic_protocol_cid is not None:
        source_text = job.case.input_data.get("text")
        if not isinstance(source_text, str):
            raise AblationValidationError(
                "semantic-v2 result lost its exact source text"
            )
        _validate_semantic_v2_result_frontends(
            result,
            source_text=source_text,
        )


def _validate_envelope(
    value: object,
    plan: AblationPlan,
    job: ScheduledCase,
    contract: RunContract,
    *,
    allow_legacy_result: bool = False,
    semantic_protocol_cid: str | None = None,
) -> CaseResultRecord:
    if type(allow_legacy_result) is not bool:
        raise AblationValidationError(
            "allow_legacy_result must be a boolean"
        )
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
    result_schema = data["schema"]
    if (
        result_schema == LEGACY_ABLATION_RESULT_SCHEMA
        and not allow_legacy_result
    ):
        raise AblationValidationError(
            "current validation requires an ablation-result.v2 envelope"
        )
    if (
        result_schema
        not in {LEGACY_ABLATION_RESULT_SCHEMA, ABLATION_RESULT_SCHEMA}
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
    if result_schema == ABLATION_RESULT_SCHEMA and (
        data["run_contract"] != restored_contract.to_dict()
        or data["case_result"] != result.to_dict()
    ):
        raise AblationValidationError(
            "current result envelope contains a noncanonical wire record"
        )
    if (
        result_schema == ABLATION_RESULT_SCHEMA
        and CaseResultRecord.from_stages(result.stages) != result
    ):
        raise AblationValidationError(
            "current result envelope masks its canonical terminal outcome"
        )
    if result_schema == ABLATION_RESULT_SCHEMA:
        validate_current_result_graph(
            result,
            plan=plan,
            job=job,
            semantic_protocol_cid=semantic_protocol_cid,
        )
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
    semantic_protocol_cid: str | None = None,
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
    if (
        semantic_protocol_cid is not None
        and semantic_protocol_cid != SEMANTIC_PROTOCOL_V2_CID
    ):
        raise AblationValidationError(
            "unsupported semantic execution protocol CID"
        )
    if semantic_protocol_cid is not None:
        _validate_semantic_v2_plan(plan)
        _validate_semantic_v2_adapters(plan, adapters)
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
    profile_path = _semantic_execution_profile_path(root)
    persisted_semantic_cid = _read_semantic_execution_profile(root, plan)
    if semantic_protocol_cid is None:
        if persisted_semantic_cid is not None:
            raise AblationValidationError(
                "revision-1 execution cannot resume a semantic-v2 namespace"
            )
    elif persisted_semantic_cid is None:
        if plan_path.exists():
            raise AblationValidationError(
                "semantic-v2 execution cannot adopt an existing revision-1 "
                "plan namespace"
            )
        _write_once(profile_path, _semantic_execution_profile(plan))
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
        portable_scope_root = canonical_scope_root.relative_to(
            canonical_output_root
        ).as_posix()
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
            "canonical_root": portable_scope_root,
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
    stop_tracker = _ProtocolStopTracker()
    stop_failure_code: FailureCode | None = None
    for job in plan.jobs:
        path = _result_path(root, job)
        contract = contract_map[(job.variant_id, job.cache_mode)]
        if path.exists():
            if not resume:
                raise AblationValidationError(
                    f"result exists with resume disabled: {path}"
                )
            result = _validate_envelope(
                _read_canonical(path, "result"),
                plan,
                job,
                contract,
                semantic_protocol_cid=semantic_protocol_cid,
            )
            resumed.append(job.job_id)
        else:
            result = _execute_job(
                plan,
                job,
                adapters,
                scheduler,
                semantic_protocol_cid=semantic_protocol_cid,
            )
            try:
                _write_once(path, _envelope(plan, job, contract, result))
            except AblationValidationError:
                # A concurrent executor is accepted only after its exact
                # immutable record passes the same resume validation.
                result = _validate_envelope(
                    _read_canonical(path, "concurrent result"),
                    plan,
                    job,
                    contract,
                    semantic_protocol_cid=semantic_protocol_cid,
                )
                resumed.append(job.job_id)
            else:
                result = _validate_envelope(
                    _read_canonical(path, "persisted result"),
                    plan,
                    job,
                    contract,
                    semantic_protocol_cid=semantic_protocol_cid,
                )
                executed.append(job.job_id)
        results.append(result)
        stop_failure_code = stop_tracker.observe(job, result)
        if stop_failure_code is not None:
            # The triggering immutable record is already reparsed above.  Do
            # not start, resume past, or otherwise touch a later scheduled
            # job after the frozen protocol requires termination.
            break
    return AblationRunResult(
        plan,
        contracts,
        tuple(results),
        tuple(executed),
        tuple(resumed),
        root,
        scheduler.receipts[receipt_start:],
        stop_failure_code,
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


def execute_semantic_ablation(
    plan: AblationPlan,
    adapters: Mapping[object, object],
    *,
    output_root: str | Path,
    resume: bool = True,
    resource_scheduler: ResourceScheduler | None = None,
) -> AblationRunResult:
    """Execute the source-only G200 semantic protocol.

    The additive profile binds every request to
    :data:`SEMANTIC_PROTOCOL_V2_CID`.  HAMMER, Leanstral, and the independent
    kernel remain explicit suppressed graph nodes until G210 introduces a
    separately reviewed proof-context boundary.
    """

    return _execute_ablation(
        plan,
        adapters,
        output_root=output_root,
        resume=resume,
        resource_scheduler=resource_scheduler,
        authorized_holdout=False,
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
    )


def validate_semantic_ablation_evidence(
    plan: AblationPlan,
    *,
    output_root: str | Path,
) -> AblationRunResult:
    """Reparse G200 evidence while requiring its persisted v2 profile."""

    root = Path(output_root)
    if _read_semantic_execution_profile(root, plan) is None:
        raise AblationValidationError(
            "semantic-v2 evidence requires a persisted execution profile"
        )
    return validate_ablation_evidence(plan, output_root=root)


__all__ = [
    "ABLATION_PLAN_SCHEMA",
    "ABLATION_RESULT_SCHEMA",
    "LEGACY_ABLATION_RESULT_SCHEMA",
    "SEMANTIC_AMBIGUITY_GATE_RULE_V2",
    "SEMANTIC_AMBIGUITY_GATE_SCHEMA_V2",
    "SEMANTIC_EXECUTION_PROFILE_SCHEMA",
    "SEMANTIC_V2_PROOF_SUPPRESSION_REASON",
    "AblationCase",
    "AblationPlan",
    "AblationRunResult",
    "AblationRunnerError",
    "AblationValidationError",
    "ORDERING_ALGORITHM",
    "ResourceLimits",
    "ScheduledCase",
    "build_ablation_plan",
    "build_semantic_ablation_plan",
    "execute_ablation",
    "execute_semantic_ablation",
    "validate_ablation_evidence",
    "validate_current_result_graph",
    "validate_semantic_ablation_evidence",
]
