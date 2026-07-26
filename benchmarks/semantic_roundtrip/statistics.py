"""Repeat scheduling and paired statistics for semantic round-trip results.

This module is deliberately an analysis-only boundary.  It consumes sealed
``MatrixCoordinateRecord`` values and never imports or calls a constructor,
realizer, validator, model service, or cache.

The two important units are kept explicit:

* repeats are averaged within a case before cases are macro-averaged; and
* confidence intervals resample those whole case means, never individual
  repeats or rules.

Consequently, a fast failure, an easy case with many rules, or an arm with
more successful repeats cannot acquire extra weight.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json

from .contracts import ComponentStatus, ContractError
from .matrix import MatrixCoordinateRecord


ROUND_TRIP_PAIRED_STATISTICS_INTERFACE: Final = (
    "RoundTripPairedStatistics@1"
)
MIN_UNCACHED_MODEL_REPEATS: Final = 5
DEFAULT_BOOTSTRAP_SAMPLES: Final = 10_000
DEFAULT_CONFIDENCE_LEVEL: Final = 0.95
MAX_BOOTSTRAP_SAMPLES: Final = 1_000_000

_LOSS_METRICS: Final = ("forward", "cycle", "end_to_end")
_EXACT_RULE_METRICS: Final = (
    "exact_rule_f1",
    "exact_ir_rate",
    "exact_ir_nonvacuous_rate",
)
_FACET_METRICS: Final = (
    "modality_survival",
    "conditions_survival",
    "exceptions_survival",
    "temporal_survival",
)
_COVERAGE_METRICS: Final = (
    "success_rate",
    "failure_rate",
    "full_coverage_rate",
    "selection_eligible_rate",
)
_COST_METRICS: Final = (
    "model_calls",
    "retries",
    "input_tokens",
    "output_tokens",
    "wall_time_seconds",
    "estimated_cost",
)
_METRIC_GROUPS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "losses": _LOSS_METRICS,
        "exact_rule": _EXACT_RULE_METRICS,
        "facets": _FACET_METRICS,
        "coverage": _COVERAGE_METRICS,
        "cost": _COST_METRICS,
    }
)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a nonblank string")
    return value


def _nonnegative_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} must be a nonnegative integer")
    return value


def _optional_nonnegative_number(
    value: object, field_name: str
) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ContractError(
            f"{field_name} must be a finite nonnegative number or None"
        )
    return float(value)


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ContractError("cannot average an empty population")
    return math.fsum(values) / len(values)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 12)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _quantile(values: Sequence[float], probability: float) -> float:
    """Return a deterministic linear (R-7) sample quantile."""

    if not values:
        raise ContractError("cannot take a quantile of an empty population")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return (
        ordered[lower]
        + (ordered[upper] - ordered[lower]) * fraction
    )


def _derived_seed(seed: int, *parts: str) -> int:
    encoded = json.dumps(
        [seed, *parts],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


@dataclass(frozen=True, slots=True)
class CostMetrics:
    """Operational measurements kept separate from semantic quality.

    ``None`` means the measurement was not supplied.  Missing cost evidence is
    never silently converted to zero or removed from its missingness count.
    """

    model_calls: int | None = None
    retries: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    wall_time_seconds: float | None = None
    estimated_cost: float | None = None

    def __post_init__(self) -> None:
        for name in ("model_calls", "retries", "input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None:
                _nonnegative_integer(value, name)
        for name in ("wall_time_seconds", "estimated_cost"):
            object.__setattr__(
                self,
                name,
                _optional_nonnegative_number(getattr(self, name), name),
            )

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            name: getattr(self, name)
            for name in _COST_METRICS
        }


@dataclass(frozen=True, slots=True)
class ScheduledBlock:
    """Outcome-independent order for one case/repeat block."""

    case_id: str
    repeat_index: int
    arm_order: tuple[str, ...]
    cache_namespaces: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _nonnegative_integer(self.repeat_index, "repeat_index")
        if not self.arm_order or len(set(self.arm_order)) != len(
            self.arm_order
        ):
            raise ContractError("arm_order must contain unique arm ids")
        for arm_id in self.arm_order:
            _identifier(arm_id, "arm_order[]")
        if len(self.cache_namespaces) != len(self.arm_order):
            raise ContractError(
                "cache_namespaces must align one-to-one with arm_order"
            )
        if len(set(self.cache_namespaces)) != len(self.cache_namespaces):
            raise ContractError("cache namespaces must be unique within a block")
        for namespace in self.cache_namespaces:
            _identifier(namespace, "cache_namespaces[]")

    def cache_namespace_for(self, arm_id: str) -> str:
        try:
            return self.cache_namespaces[self.arm_order.index(arm_id)]
        except ValueError as exc:
            raise ContractError(f"arm {arm_id!r} is not in this block") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "repeat_index": self.repeat_index,
            "arm_order": list(self.arm_order),
            "coordinates": [
                {
                    "arm_id": arm_id,
                    "cache_mode": "uncached",
                    "cache_namespace": namespace,
                }
                for arm_id, namespace in zip(
                    self.arm_order,
                    self.cache_namespaces,
                    strict=True,
                )
            ],
        }


@dataclass(frozen=True, slots=True)
class RepeatSchedule:
    """A reproducible counterbalanced schedule frozen before outcomes exist."""

    case_ids: tuple[str, ...]
    arm_ids: tuple[str, ...]
    model_arm_ids: tuple[str, ...]
    repeat_count: int
    seed: int
    blocks: tuple[ScheduledBlock, ...]
    interface: str = ROUND_TRIP_PAIRED_STATISTICS_INTERFACE

    def __post_init__(self) -> None:
        if self.interface != ROUND_TRIP_PAIRED_STATISTICS_INTERFACE:
            raise ContractError("unsupported paired-statistics interface")
        if not self.case_ids or len(set(self.case_ids)) != len(self.case_ids):
            raise ContractError("case_ids must be nonempty and unique")
        if not self.arm_ids or len(set(self.arm_ids)) != len(self.arm_ids):
            raise ContractError("arm_ids must be nonempty and unique")
        for value in self.case_ids:
            _identifier(value, "case_ids[]")
        for value in self.arm_ids:
            _identifier(value, "arm_ids[]")
        if len(set(self.model_arm_ids)) != len(self.model_arm_ids):
            raise ContractError("model_arm_ids must be unique")
        if not set(self.model_arm_ids).issubset(self.arm_ids):
            raise ContractError("model_arm_ids must be a subset of arm_ids")
        _nonnegative_integer(self.repeat_count, "repeat_count")
        if self.repeat_count < 1:
            raise ContractError("repeat_count must be positive")
        if (
            self.model_arm_ids
            and self.repeat_count < MIN_UNCACHED_MODEL_REPEATS
        ):
            raise ContractError(
                "model-backed arms require at least "
                f"{MIN_UNCACHED_MODEL_REPEATS} uncached repeats"
            )
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise ContractError("seed must be a nonnegative integer")
        expected = len(self.case_ids) * self.repeat_count
        if len(self.blocks) != expected:
            raise ContractError("schedule must contain every case/repeat block")
        expected_keys = {
            (case_id, repeat_index)
            for case_id in self.case_ids
            for repeat_index in range(self.repeat_count)
        }
        actual_keys = {
            (block.case_id, block.repeat_index) for block in self.blocks
        }
        if actual_keys != expected_keys or len(actual_keys) != len(self.blocks):
            raise ContractError(
                "schedule blocks must cover each case/repeat exactly once"
            )
        expected_arms = set(self.arm_ids)
        namespaces: list[str] = []
        for block in self.blocks:
            if set(block.arm_order) != expected_arms:
                raise ContractError("every block must schedule every arm")
            namespaces.extend(block.cache_namespaces)
        if len(namespaces) != len(set(namespaces)):
            raise ContractError(
                "every scheduled coordinate needs a unique cache namespace"
            )
        counts = self.position_counts
        for position in range(len(self.arm_ids)):
            position_values = [
                counts[arm_id][position] for arm_id in self.arm_ids
            ]
            if max(position_values) - min(position_values) > 1:
                raise ContractError(
                    "arm order is not counterbalanced by ordinal position"
                )

    @property
    def position_counts(self) -> Mapping[str, tuple[int, ...]]:
        counts = {
            arm_id: [0] * len(self.arm_ids) for arm_id in self.arm_ids
        }
        for block in self.blocks:
            for position, arm_id in enumerate(block.arm_order):
                counts[arm_id][position] += 1
        return MappingProxyType(
            {arm_id: tuple(values) for arm_id, values in counts.items()}
        )

    def block(self, case_id: str, repeat_index: int) -> ScheduledBlock:
        for item in self.blocks:
            if (
                item.case_id == case_id
                and item.repeat_index == repeat_index
            ):
                return item
        raise ContractError(
            f"no scheduled block for {(case_id, repeat_index)!r}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "seed": self.seed,
            "repeat_count": self.repeat_count,
            "minimum_uncached_model_repeats": MIN_UNCACHED_MODEL_REPEATS,
            "case_ids": list(self.case_ids),
            "arm_ids": list(self.arm_ids),
            "model_arm_ids": list(self.model_arm_ids),
            "cache_policy": (
                "unique_uncached_namespace_per_scheduled_coordinate"
            ),
            "ordering_policy": (
                "seeded_outcome_independent_counterbalanced_blocks"
            ),
            "maximum_ordinal_position_count_imbalance": 1,
            "position_counts": {
                arm_id: list(values)
                for arm_id, values in self.position_counts.items()
            },
            "blocks": [block.to_dict() for block in self.blocks],
        }


def make_repeat_schedule(
    case_ids: Sequence[str],
    arm_ids: Sequence[str],
    *,
    repeat_count: int,
    seed: int,
    model_arm_ids: Iterable[str] | None = None,
) -> RepeatSchedule:
    """Build a seeded schedule whose ordinal imbalance is at most one.

    A randomized base order is rotated across blocks.  Rotation is what
    guarantees positional balance; randomizing the base order and rotation
    sequence makes the planned order seed-dependent without observing any
    result.
    """

    if isinstance(case_ids, (str, bytes, bytearray)):
        raise ContractError("case_ids must be a sequence of identifiers")
    if isinstance(arm_ids, (str, bytes, bytearray)):
        raise ContractError("arm_ids must be a sequence of identifiers")
    if isinstance(model_arm_ids, (str, bytes, bytearray)):
        raise ContractError(
            "model_arm_ids must be an iterable of identifiers"
        )
    try:
        cases = tuple(case_ids)
        arms = tuple(arm_ids)
        model_arms = tuple(
            arms if model_arm_ids is None else model_arm_ids
        )
    except TypeError as exc:
        raise ContractError(
            "case_ids, arm_ids, and model_arm_ids must be iterable"
        ) from exc
    if not cases or not arms:
        # Let RepeatSchedule provide the stable public error messages.
        return RepeatSchedule(
            cases,
            arms,
            model_arms,
            repeat_count,
            seed,
            (),
        )
    if (
        isinstance(repeat_count, bool)
        or not isinstance(repeat_count, int)
        or repeat_count < 1
    ):
        raise ContractError("repeat_count must be positive")
    if (
        model_arms
        and repeat_count < MIN_UNCACHED_MODEL_REPEATS
    ):
        raise ContractError(
            "model-backed arms require at least "
            f"{MIN_UNCACHED_MODEL_REPEATS} uncached repeats"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ContractError("seed must be a nonnegative integer")

    rng = random.Random(seed)
    base = list(arms)
    rng.shuffle(base)
    offsets: list[int] = []
    block_count = len(cases) * repeat_count
    while len(offsets) < block_count:
        cycle = list(range(len(arms)))
        rng.shuffle(cycle)
        offsets.extend(cycle)

    blocks: list[ScheduledBlock] = []
    block_index = 0
    for case_id in cases:
        for repeat_index in range(repeat_count):
            offset = offsets[block_index]
            order = tuple(base[offset:] + base[:offset])
            namespaces = tuple(
                "srt-uncached-"
                + hashlib.sha256(
                    json.dumps(
                        [
                            ROUND_TRIP_PAIRED_STATISTICS_INTERFACE,
                            seed,
                            case_id,
                            repeat_index,
                            arm_id,
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                for arm_id in order
            )
            blocks.append(
                ScheduledBlock(
                    case_id=case_id,
                    repeat_index=repeat_index,
                    arm_order=order,
                    cache_namespaces=namespaces,
                )
            )
            block_index += 1
    return RepeatSchedule(
        case_ids=cases,
        arm_ids=arms,
        model_arm_ids=model_arms,
        repeat_count=repeat_count,
        seed=seed,
        blocks=tuple(blocks),
    )


# Descriptive aliases make the scheduling primitive easy to discover.
balanced_repeat_schedule = make_repeat_schedule
schedule_balanced_repeats = make_repeat_schedule


@dataclass(frozen=True, slots=True)
class RoundTripObservation:
    """One sealed case/repeat/arm result plus separate cost evidence."""

    coordinate: MatrixCoordinateRecord
    repeat_index: int
    cache_mode: str
    cache_namespace: str
    cost: CostMetrics = field(default_factory=CostMetrics)

    def __post_init__(self) -> None:
        if not isinstance(self.coordinate, MatrixCoordinateRecord):
            raise ContractError(
                "coordinate must be an immutable MatrixCoordinateRecord"
            )
        _nonnegative_integer(self.repeat_index, "repeat_index")
        if self.cache_mode not in {"uncached", "not_applicable"}:
            raise ContractError(
                "cache_mode must be 'uncached' or 'not_applicable'"
            )
        _identifier(self.cache_namespace, "cache_namespace")
        if not isinstance(self.cost, CostMetrics):
            raise ContractError("cost must be CostMetrics")

    @property
    def case_id(self) -> str:
        return self.coordinate.case_id

    @property
    def arm_id(self) -> str:
        return self.coordinate.cell_id

    @classmethod
    def from_schedule(
        cls,
        coordinate: MatrixCoordinateRecord,
        schedule: RepeatSchedule,
        repeat_index: int,
        *,
        cost: CostMetrics | None = None,
    ) -> "RoundTripObservation":
        block = schedule.block(coordinate.case_id, repeat_index)
        return cls(
            coordinate=coordinate,
            repeat_index=repeat_index,
            cache_mode=(
                "uncached"
                if coordinate.cell_id in schedule.model_arm_ids
                else "not_applicable"
            ),
            cache_namespace=block.cache_namespace_for(coordinate.cell_id),
            cost=cost or CostMetrics(),
        )


@dataclass(frozen=True, slots=True)
class PairedStatisticsReport:
    """Immutable analysis result with semantic, coverage, and cost axes."""

    seed: int
    bootstrap_samples: int
    confidence_level: float
    arm_summaries: Mapping[str, object]
    paired_comparisons: Mapping[str, object]
    model_repeat_validation: Mapping[str, object]
    observation_manifest: tuple[Mapping[str, object], ...]
    interface: str = ROUND_TRIP_PAIRED_STATISTICS_INTERFACE

    def __post_init__(self) -> None:
        if self.interface != ROUND_TRIP_PAIRED_STATISTICS_INTERFACE:
            raise ContractError("unsupported paired-statistics interface")
        object.__setattr__(self, "arm_summaries", _freeze(self.arm_summaries))
        object.__setattr__(
            self, "paired_comparisons", _freeze(self.paired_comparisons)
        )
        object.__setattr__(
            self,
            "model_repeat_validation",
            _freeze(self.model_repeat_validation),
        )
        object.__setattr__(
            self,
            "observation_manifest",
            _freeze(self.observation_manifest),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "analysis_policy": {
                "aggregation_order": "repeats_within_case_then_macro_cases",
                "failure_loss": 1.0,
                "bootstrap_unit": "case_cluster",
                "cost_folded_into_semantic_loss": False,
            },
            "seed": self.seed,
            "bootstrap_samples": self.bootstrap_samples,
            "confidence_level": self.confidence_level,
            "input_coordinate_count": len(self.observation_manifest),
            "observation_manifest": _thaw(self.observation_manifest),
            "model_repeat_validation": _thaw(
                self.model_repeat_validation
            ),
            "arm_summaries": _thaw(self.arm_summaries),
            "paired_comparisons": _thaw(self.paired_comparisons),
        }

    @property
    def report_cid(self) -> str:
        return cid_for_dag_json(self._payload())

    @property
    def cid(self) -> str:
        return self.report_cid

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "report_cid": self.report_cid}


def _record_metrics(
    observation: RoundTripObservation,
) -> dict[str, dict[str, float | None]]:
    record = observation.coordinate
    failed = record.status is ComponentStatus.FAILED
    losses = {
        "forward": (
            1.0 if failed else float(record.result.forward_loss)
        ),
        "cycle": 1.0 if failed else float(record.result.cycle_loss),
        "end_to_end": (
            1.0 if failed else float(record.result.end_to_end_loss)
        ),
    }
    # A failed coordinate is scored fail-closed even if a malformed external
    # record attempted to retain an optimistic numeric loss.
    if failed and any(value != 1.0 for value in losses.values()):
        raise ContractError("terminal failures must retain loss one")

    diagnostics = record.diagnostics
    gates_value = diagnostics.get("gates")
    gates = gates_value if isinstance(gates_value, Mapping) else {}
    comparisons_value = diagnostics.get("semantic_comparisons")
    comparisons = (
        comparisons_value
        if isinstance(comparisons_value, Mapping)
        else {}
    )
    end_value = comparisons.get("end_to_end_gold_to_l2")
    end_comparison = end_value if isinstance(end_value, Mapping) else {}
    facets_value = end_comparison.get("facet_survival")
    facets = facets_value if isinstance(facets_value, Mapping) else {}

    exact_rule = {
        "exact_rule_f1": (
            0.0
            if failed
            else float(end_comparison.get("exact_rule_f1", 0.0))
        ),
        "exact_ir_rate": (
            0.0 if failed else float(bool(end_comparison.get("exact_ir")))
        ),
        "exact_ir_nonvacuous_rate": (
            0.0
            if failed
            else float(bool(end_comparison.get("exact_ir_nonvacuous")))
        ),
    }
    facet_metrics = {
        f"{name}_survival": (
            0.0 if failed else float(facets.get(name, 0.0))
        )
        for name in ("modality", "conditions", "exceptions", "temporal")
    }
    coverage = {
        "success_rate": float(not failed),
        "failure_rate": float(failed),
        "full_coverage_rate": float(
            bool(gates.get("full_coverage", False))
        ),
        "selection_eligible_rate": float(
            bool(gates.get("selection_eligible", False))
        ),
    }
    return {
        "losses": losses,
        "exact_rule": exact_rule,
        "facets": facet_metrics,
        "coverage": coverage,
        "cost": {
            name: (
                None
                if getattr(observation.cost, name) is None
                else float(getattr(observation.cost, name))
            )
            for name in _COST_METRICS
        },
    }


def _case_means(
    observations: Sequence[RoundTripObservation],
) -> dict[str, dict[str, dict[str, float | None]]]:
    by_case: dict[str, list[RoundTripObservation]] = {}
    for observation in observations:
        by_case.setdefault(observation.case_id, []).append(observation)

    result: dict[str, dict[str, dict[str, float | None]]] = {}
    for case_id in sorted(by_case):
        repeats = sorted(
            by_case[case_id], key=lambda item: item.repeat_index
        )
        extracted = [_record_metrics(item) for item in repeats]
        groups: dict[str, dict[str, float | None]] = {}
        for group, metric_names in _METRIC_GROUPS.items():
            groups[group] = {}
            for metric_name in metric_names:
                values = [
                    item[group][metric_name] for item in extracted
                ]
                # Cost evidence must cover every scheduled repeat.  Semantic,
                # exact-rule, facet, and coverage values are always fail-closed
                # numeric measurements.
                groups[group][metric_name] = (
                    None
                    if any(value is None for value in values)
                    else _mean(
                        [float(value) for value in values if value is not None]
                    )
                )
        groups["counts"] = {
            "scheduled_repeats": float(len(repeats)),
            "successful_repeats": float(
                sum(
                    item.coordinate.status is ComponentStatus.SUCCESS
                    for item in repeats
                )
            ),
            "failed_repeats": float(
                sum(
                    item.coordinate.status is ComponentStatus.FAILED
                    for item in repeats
                )
            ),
        }
        result[case_id] = groups
    return result


def _metric_summary(
    case_metrics: Mapping[str, Mapping[str, Mapping[str, float | None]]],
    group: str,
    metric_name: str,
) -> dict[str, object]:
    values = [
        groups[group][metric_name] for groups in case_metrics.values()
    ]
    measured = [float(value) for value in values if value is not None]
    missing_case_ids = [
        case_id
        for case_id, groups in case_metrics.items()
        if groups[group][metric_name] is None
    ]
    return {
        "mean": (
            _rounded(_mean(measured))
            if len(measured) == len(values) and measured
            else None
        ),
        "scheduled_case_count": len(values),
        "measured_case_count": len(measured),
        "missing_case_count": len(missing_case_ids),
        "missing_case_ids": missing_case_ids,
    }


def _arm_summary(
    arm_id: str,
    observations: Sequence[RoundTripObservation],
) -> dict[str, object]:
    cases = _case_means(observations)
    metrics = {
        group: {
            metric_name: _metric_summary(
                cases, group, metric_name
            )
            for metric_name in metric_names
        }
        for group, metric_names in _METRIC_GROUPS.items()
    }
    cost_totals: dict[str, object] = {}
    for metric_name in _COST_METRICS:
        values = [
            getattr(observation.cost, metric_name)
            for observation in observations
        ]
        measured = [float(value) for value in values if value is not None]
        cost_totals[metric_name] = {
            "total": (
                _rounded(math.fsum(measured))
                if len(measured) == len(values)
                else None
            ),
            "measured_coordinate_count": len(measured),
            "missing_coordinate_count": len(values) - len(measured),
        }
    return {
        "arm_id": arm_id,
        "scheduled_case_count": len(cases),
        "scheduled_coordinate_count": len(observations),
        "success_count": sum(
            item.coordinate.status is ComponentStatus.SUCCESS
            for item in observations
        ),
        "failure_count": sum(
            item.coordinate.status is ComponentStatus.FAILED
            for item in observations
        ),
        "denominator_policy": (
            "all_scheduled_repeats_including_failures"
        ),
        "aggregation_order": "repeats_within_case_then_macro_cases",
        "per_case": {
            case_id: {
                group: {
                    name: _rounded(value)
                    for name, value in values.items()
                }
                for group, values in groups.items()
            }
            for case_id, groups in cases.items()
        },
        "metrics": metrics,
        "cost_totals": cost_totals,
    }


def _bootstrap_delta(
    deltas: Sequence[float],
    *,
    seed: int,
    bootstrap_samples: int,
    confidence_level: float,
) -> tuple[float, float]:
    if not deltas:
        raise ContractError("paired bootstrap requires at least one case")
    rng = random.Random(seed)
    sample_count = len(deltas)
    draws = [
        _mean([deltas[rng.randrange(sample_count)] for _ in deltas])
        for _ in range(bootstrap_samples)
    ]
    tail = (1.0 - confidence_level) / 2.0
    return _quantile(draws, tail), _quantile(draws, 1.0 - tail)


def _paired_metric(
    baseline_cases: Mapping[
        str, Mapping[str, Mapping[str, float | None]]
    ],
    candidate_cases: Mapping[
        str, Mapping[str, Mapping[str, float | None]]
    ],
    *,
    baseline_arm_id: str,
    candidate_arm_id: str,
    group: str,
    metric_name: str,
    seed: int,
    bootstrap_samples: int,
    confidence_level: float,
) -> dict[str, object]:
    case_ids = sorted(baseline_cases)
    measured: list[tuple[str, float, float]] = []
    missing: list[str] = []
    for case_id in case_ids:
        baseline = baseline_cases[case_id][group][metric_name]
        candidate = candidate_cases[case_id][group][metric_name]
        if baseline is None or candidate is None:
            missing.append(case_id)
        else:
            measured.append((case_id, float(baseline), float(candidate)))
    deltas = [candidate - baseline for _, baseline, candidate in measured]
    if measured:
        low, high = _bootstrap_delta(
            deltas,
            seed=_derived_seed(
                seed,
                baseline_arm_id,
                candidate_arm_id,
                group,
                metric_name,
            ),
            bootstrap_samples=bootstrap_samples,
            confidence_level=confidence_level,
        )
        baseline_mean = _mean([item[1] for item in measured])
        candidate_mean = _mean([item[2] for item in measured])
        delta = _mean(deltas)
    else:
        low = high = baseline_mean = candidate_mean = delta = None
    return {
        "baseline_mean": _rounded(baseline_mean),
        "candidate_mean": _rounded(candidate_mean),
        "candidate_minus_baseline": _rounded(delta),
        "paired_case_count": len(measured),
        "scheduled_case_count": len(case_ids),
        "missing_case_count": len(missing),
        "missing_case_ids": missing,
        "confidence_interval": {
            "method": "seeded_percentile_case_cluster_bootstrap",
            "confidence_level": confidence_level,
            "bootstrap_samples": bootstrap_samples,
            "low": _rounded(low),
            "high": _rounded(high),
            "resampling_unit": "case_after_within_case_repeat_aggregation",
        },
        "case_deltas": {
            case_id: _rounded(candidate - baseline)
            for case_id, baseline, candidate in measured
        },
    }


class RoundTripPairedStatistics:
    """Analyze repeated immutable matrix results without invoking components."""

    interface: Final = ROUND_TRIP_PAIRED_STATISTICS_INTERFACE

    def __init__(
        self,
        *,
        seed: int = 17_291,
        bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
        confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ContractError("seed must be a nonnegative integer")
        if (
            isinstance(bootstrap_samples, bool)
            or not isinstance(bootstrap_samples, int)
            or not 1 <= bootstrap_samples <= MAX_BOOTSTRAP_SAMPLES
        ):
            raise ContractError(
                "bootstrap_samples must be an integer from 1 to "
                f"{MAX_BOOTSTRAP_SAMPLES}"
            )
        if (
            isinstance(confidence_level, bool)
            or not isinstance(confidence_level, (int, float))
            or not math.isfinite(float(confidence_level))
            or not 0.0 < float(confidence_level) < 1.0
        ):
            raise ContractError(
                "confidence_level must be a finite number between zero and one"
            )
        self.seed = seed
        self.bootstrap_samples = bootstrap_samples
        self.confidence_level = float(confidence_level)

    @property
    def identity(self) -> str:
        return self.interface

    def analyze(
        self,
        observations: Iterable[RoundTripObservation],
        *,
        baseline_arm_id: str,
        candidate_arm_ids: Iterable[str] | None = None,
        model_arm_ids: Iterable[str] = (),
    ) -> PairedStatisticsReport:
        """Return per-case-first summaries and paired case-bootstrap deltas."""

        if isinstance(observations, (str, bytes, bytearray)):
            raise ContractError(
                "observations must contain RoundTripObservation values"
            )
        if isinstance(candidate_arm_ids, (str, bytes, bytearray)):
            raise ContractError(
                "candidate_arm_ids must be an iterable of arm ids"
            )
        if isinstance(model_arm_ids, (str, bytes, bytearray)):
            raise ContractError(
                "model_arm_ids must be an iterable of arm ids"
            )
        rows = tuple(observations)
        if not rows:
            raise ContractError("observations must be nonempty")
        if any(not isinstance(row, RoundTripObservation) for row in rows):
            raise ContractError(
                "observations must contain RoundTripObservation values"
            )
        keys = [
            (row.case_id, row.repeat_index, row.arm_id) for row in rows
        ]
        if len(keys) != len(set(keys)):
            raise ContractError(
                "case/repeat/arm observations must be unique"
            )
        cache_namespaces = [row.cache_namespace for row in rows]
        if len(cache_namespaces) != len(set(cache_namespaces)):
            raise ContractError(
                "cache namespaces must be unique across scheduled coordinates"
            )

        by_arm: dict[str, list[RoundTripObservation]] = {}
        for row in rows:
            by_arm.setdefault(row.arm_id, []).append(row)
        _identifier(baseline_arm_id, "baseline_arm_id")
        if baseline_arm_id not in by_arm:
            raise ContractError("baseline_arm_id has no observations")
        selected_candidates = tuple(
            sorted(set(by_arm) - {baseline_arm_id})
            if candidate_arm_ids is None
            else candidate_arm_ids
        )
        if len(set(selected_candidates)) != len(selected_candidates):
            raise ContractError("candidate_arm_ids must be unique")
        for arm_id in selected_candidates:
            if arm_id == baseline_arm_id or arm_id not in by_arm:
                raise ContractError(
                    f"candidate arm {arm_id!r} is unavailable or is baseline"
                )

        baseline_cases = {row.case_id for row in by_arm[baseline_arm_id]}
        for arm_id in selected_candidates:
            candidate_cases = {row.case_id for row in by_arm[arm_id]}
            if candidate_cases != baseline_cases:
                raise ContractError(
                    "paired arms must contain exactly the same case ids"
                )

        model_arms = tuple(model_arm_ids)
        if len(set(model_arms)) != len(model_arms):
            raise ContractError("model_arm_ids must be unique")
        unknown_model_arms = set(model_arms) - set(by_arm)
        if unknown_model_arms:
            raise ContractError(
                f"model arms have no observations: {sorted(unknown_model_arms)!r}"
            )
        repeat_details: dict[str, object] = {}
        for arm_id in model_arms:
            arm_rows = by_arm[arm_id]
            per_case: dict[str, int] = {}
            for case_id in sorted({row.case_id for row in arm_rows}):
                case_rows = [
                    row for row in arm_rows if row.case_id == case_id
                ]
                count = len(case_rows)
                if count < MIN_UNCACHED_MODEL_REPEATS:
                    raise ContractError(
                        f"model arm {arm_id!r} case {case_id!r} requires at "
                        f"least {MIN_UNCACHED_MODEL_REPEATS} repeats"
                    )
                if any(row.cache_mode != "uncached" for row in case_rows):
                    raise ContractError(
                        "every model-backed repeat must be marked uncached"
                    )
                per_case[case_id] = count
            repeat_details[arm_id] = {
                "minimum_required": MIN_UNCACHED_MODEL_REPEATS,
                "all_uncached": True,
                "repeat_count_by_case": per_case,
            }

        case_means_by_arm = {
            arm_id: _case_means(arm_rows)
            for arm_id, arm_rows in by_arm.items()
        }
        summaries = {
            arm_id: _arm_summary(arm_id, by_arm[arm_id])
            for arm_id in sorted(by_arm)
        }
        comparisons: dict[str, object] = {}
        for candidate_arm_id in selected_candidates:
            comparison_id = f"{candidate_arm_id}__vs__{baseline_arm_id}"
            comparisons[comparison_id] = {
                "baseline_arm_id": baseline_arm_id,
                "candidate_arm_id": candidate_arm_id,
                "delta_direction": "candidate_minus_baseline",
                "bootstrap_unit": "case_cluster",
                "metrics": {
                    group: {
                        metric_name: _paired_metric(
                            case_means_by_arm[baseline_arm_id],
                            case_means_by_arm[candidate_arm_id],
                            baseline_arm_id=baseline_arm_id,
                            candidate_arm_id=candidate_arm_id,
                            group=group,
                            metric_name=metric_name,
                            seed=self.seed,
                            bootstrap_samples=self.bootstrap_samples,
                            confidence_level=self.confidence_level,
                        )
                        for metric_name in metric_names
                    }
                    for group, metric_names in _METRIC_GROUPS.items()
                },
            }

        return PairedStatisticsReport(
            seed=self.seed,
            bootstrap_samples=self.bootstrap_samples,
            confidence_level=self.confidence_level,
            arm_summaries=summaries,
            paired_comparisons=comparisons,
            model_repeat_validation={
                "minimum_uncached_model_repeats": (
                    MIN_UNCACHED_MODEL_REPEATS
                ),
                "validated_model_arm_ids": list(model_arms),
                "arms": repeat_details,
            },
            observation_manifest=tuple(
                {
                    "case_id": row.case_id,
                    "arm_id": row.arm_id,
                    "repeat_index": row.repeat_index,
                    "coordinate_record_cid": row.coordinate.record_cid,
                    "status": row.coordinate.status.value,
                    "failure_reason": (
                        None
                        if row.coordinate.result.failure_reason is None
                        else row.coordinate.result.failure_reason.value
                    ),
                    "cache_mode": row.cache_mode,
                    "cache_namespace": row.cache_namespace,
                    "cost": row.cost.to_dict(),
                }
                for row in sorted(
                    rows,
                    key=lambda item: (
                        item.case_id,
                        item.repeat_index,
                        item.arm_id,
                    ),
                )
            ),
        )


def analyze_paired_round_trips(
    observations: Iterable[RoundTripObservation],
    *,
    baseline_arm_id: str,
    candidate_arm_ids: Iterable[str] | None = None,
    model_arm_ids: Iterable[str] = (),
    seed: int = 17_291,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> PairedStatisticsReport:
    """Functional wrapper around :class:`RoundTripPairedStatistics`."""

    return RoundTripPairedStatistics(
        seed=seed,
        bootstrap_samples=bootstrap_samples,
        confidence_level=confidence_level,
    ).analyze(
        observations,
        baseline_arm_id=baseline_arm_id,
        candidate_arm_ids=candidate_arm_ids,
        model_arm_ids=model_arm_ids,
    )


__all__ = [
    "ROUND_TRIP_PAIRED_STATISTICS_INTERFACE",
    "MIN_UNCACHED_MODEL_REPEATS",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_CONFIDENCE_LEVEL",
    "MAX_BOOTSTRAP_SAMPLES",
    "CostMetrics",
    "ScheduledBlock",
    "RepeatSchedule",
    "make_repeat_schedule",
    "balanced_repeat_schedule",
    "schedule_balanced_repeats",
    "RoundTripObservation",
    "PairedStatisticsReport",
    "RoundTripPairedStatistics",
    "analyze_paired_round_trips",
]
