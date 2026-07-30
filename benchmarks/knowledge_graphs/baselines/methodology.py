"""Warmup / repetition / variance helpers for labelled baselines (KGP-030)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .catalog import REQUIRED_METHODOLOGY_KEYS, REQUIRED_METRIC_SUMMARY_KEYS

JSONDict = Dict[str, Any]

# Supported variance models recorded on baseline methodology blocks.
VARIANCE_MODELS = (
    "sample_std",  # sample standard deviation (n-1) across repetitions
    "population_std",
    "range",
)

# How absolute bounds are derived from multi-sample summaries.
BOUND_POLICIES = (
    # ceiling = median + max(k * stdev, margin_ratio * median, floor)
    "median_plus_k_stdev",
    # floor for higher-is-better metrics (throughput)
    "median_minus_k_stdev",
    "max_sample",
    "min_sample",
    "explicit",
)


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """Multi-sample summary for one metric."""

    samples: Tuple[float, ...]
    mean: float
    median: float
    stdev: float
    min: float
    max: float
    n: int
    cv: float
    bound: float
    direction: str  # "lower_is_better" | "higher_is_better"
    bound_policy: str = "median_plus_k_stdev"

    def to_json_dict(self) -> JSONDict:
        return {
            "samples": list(self.samples),
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "min": self.min,
            "max": self.max,
            "n": self.n,
            "cv": self.cv,
            "bound": self.bound,
            "direction": self.direction,
            "bound_policy": self.bound_policy,
        }


def aggregate_samples(
    values: Sequence[float],
    *,
    direction: str = "lower_is_better",
    k_stdev: float = 3.0,
    margin_ratio: float = 0.25,
    absolute_floor: float = 0.0,
    bound_policy: str = "median_plus_k_stdev",
    explicit_bound: Optional[float] = None,
) -> MetricSummary:
    """Aggregate repeated samples into a summary with a ratified bound.

    Parameters
    ----------
    direction:
        ``lower_is_better`` for latency / recovery / RSS;
        ``higher_is_better`` for throughput.
    k_stdev:
        Multiplier on sample stdev when forming the bound.
    margin_ratio:
        Minimum relative margin around the median.
    absolute_floor:
        Absolute minimum margin (same units as the metric).
    """
    if not values:
        raise ValueError("values must be non-empty")
    if direction not in ("lower_is_better", "higher_is_better"):
        raise ValueError(f"unknown direction {direction!r}")
    samples = tuple(float(v) for v in values)
    n = len(samples)
    mean = float(statistics.mean(samples))
    med = float(statistics.median(samples))
    stdev = float(statistics.stdev(samples)) if n > 1 else 0.0
    mn = float(min(samples))
    mx = float(max(samples))
    cv = (stdev / mean) if mean else 0.0
    bound = bound_from_summary(
        median=med,
        stdev=stdev,
        sample_max=mx,
        sample_min=mn,
        direction=direction,
        k_stdev=k_stdev,
        margin_ratio=margin_ratio,
        absolute_floor=absolute_floor,
        bound_policy=bound_policy,
        explicit_bound=explicit_bound,
    )
    return MetricSummary(
        samples=samples,
        mean=mean,
        median=med,
        stdev=stdev,
        min=mn,
        max=mx,
        n=n,
        cv=cv,
        bound=bound,
        direction=direction,
        bound_policy=bound_policy,
    )


def bound_from_summary(
    *,
    median: float,
    stdev: float,
    sample_max: float,
    sample_min: float,
    direction: str,
    k_stdev: float = 3.0,
    margin_ratio: float = 0.25,
    absolute_floor: float = 0.0,
    bound_policy: str = "median_plus_k_stdev",
    explicit_bound: Optional[float] = None,
) -> float:
    """Compute a single numeric bound from summary statistics."""
    if bound_policy == "explicit":
        if explicit_bound is None:
            raise ValueError("explicit_bound required for bound_policy=explicit")
        return float(explicit_bound)
    if bound_policy == "max_sample":
        return float(sample_max)
    if bound_policy == "min_sample":
        return float(sample_min)

    margin = max(k_stdev * stdev, margin_ratio * abs(median), absolute_floor)
    if direction == "lower_is_better":
        # Ceiling.
        if bound_policy in ("median_plus_k_stdev", "median_minus_k_stdev"):
            return float(median + margin)
        raise ValueError(f"unsupported bound_policy {bound_policy!r}")
    # higher_is_better → floor
    if bound_policy in ("median_plus_k_stdev", "median_minus_k_stdev"):
        return float(max(0.0, median - margin))
    raise ValueError(f"unsupported bound_policy {bound_policy!r}")


def validate_methodology(methodology: Mapping[str, Any]) -> List[str]:
    """Return validation problems for a methodology block (empty = ok)."""
    problems: List[str] = []
    if not isinstance(methodology, Mapping):
        return ["methodology must be a mapping"]
    for key in REQUIRED_METHODOLOGY_KEYS:
        if key not in methodology:
            problems.append(f"methodology missing required key: {key}")
    if "warmup_runs" in methodology:
        wr = methodology["warmup_runs"]
        if not isinstance(wr, int) or wr < 0:
            problems.append("methodology.warmup_runs must be int >= 0")
    if "repetitions" in methodology:
        reps = methodology["repetitions"]
        if not isinstance(reps, int) or reps < 1:
            problems.append("methodology.repetitions must be int >= 1")
    if "warmup_operations" in methodology:
        wo = methodology["warmup_operations"]
        if not isinstance(wo, int) or wo < 0:
            problems.append("methodology.warmup_operations must be int >= 0")
    vm = methodology.get("variance_model")
    if vm is not None and vm not in VARIANCE_MODELS:
        problems.append(
            f"methodology.variance_model must be one of {VARIANCE_MODELS}, got {vm!r}"
        )
    for list_key in ("surfaces", "storage_profiles"):
        if list_key in methodology and not isinstance(methodology[list_key], list):
            problems.append(f"methodology.{list_key} must be a list")
    return problems


def validate_metric_summary(
    name: str, summary: Mapping[str, Any]
) -> List[str]:
    """Return validation problems for one metric summary mapping."""
    problems: List[str] = []
    if not isinstance(summary, Mapping):
        return [f"metrics.{name} must be a mapping"]
    for key in REQUIRED_METRIC_SUMMARY_KEYS:
        if key not in summary:
            problems.append(f"metrics.{name} missing required key: {key}")
    if "n" in summary:
        n = summary["n"]
        if not isinstance(n, int) or n < 1:
            problems.append(f"metrics.{name}.n must be int >= 1")
        samples = summary.get("samples")
        if isinstance(samples, list) and len(samples) != n:
            problems.append(
                f"metrics.{name}.samples length {len(samples)} != n {n}"
            )
    if "direction" in summary and summary["direction"] not in (
        "lower_is_better",
        "higher_is_better",
    ):
        problems.append(
            f"metrics.{name}.direction must be lower_is_better or higher_is_better"
        )
    for numeric in ("median", "mean", "stdev", "bound"):
        if numeric in summary and not isinstance(summary[numeric], (int, float)):
            problems.append(f"metrics.{name}.{numeric} must be numeric")
    return problems


def discard_warmup(
    samples: Sequence[Mapping[str, Any]],
    *,
    warmup_runs: int,
) -> List[Mapping[str, Any]]:
    """Drop the first *warmup_runs* samples (process-level warmups)."""
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be >= 0")
    if warmup_runs >= len(samples):
        raise ValueError(
            f"warmup_runs={warmup_runs} leaves no measured samples "
            f"(total={len(samples)})"
        )
    return list(samples[warmup_runs:])
