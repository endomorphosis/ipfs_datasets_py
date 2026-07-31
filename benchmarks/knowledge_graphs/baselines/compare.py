"""Baseline comparison and SLO regression gates (KGP-030).

Enforces:

* zero correctness / security errors
* unexplained p95 latency regression > 10% blocks release
* unexplained throughput regression > 10% blocks release
* optional recovery / resource bound checks declared on the baseline
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .catalog import (
    CORRECTNESS_ERROR_MAX,
    REGRESSION_RATIO_LIMIT,
    SECURITY_ERROR_MAX,
    load_baseline,
)
from .ratify import extract_metrics_from_receipt

JSONDict = Dict[str, Any]


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """One metric compared against a labelled baseline."""

    name: str
    baseline_value: float
    candidate_value: float
    direction: str
    ratio: float
    regression_ratio: float
    limit: float
    exceeds_limit: bool
    bound: Optional[float] = None
    exceeds_bound: bool = False
    explanation: Optional[str] = None

    def to_json_dict(self) -> JSONDict:
        return {
            "name": self.name,
            "baseline_value": self.baseline_value,
            "candidate_value": self.candidate_value,
            "direction": self.direction,
            "ratio": self.ratio,
            "regression_ratio": self.regression_ratio,
            "limit": self.limit,
            "exceeds_limit": self.exceeds_limit,
            "bound": self.bound,
            "exceeds_bound": self.exceeds_bound,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """Pass/fail decision for a single gate."""

    name: str
    passed: bool
    detail: str
    blocking: bool = True

    def to_json_dict(self) -> JSONDict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "blocking": self.blocking,
        }


@dataclass
class ComparisonResult:
    """Full comparison of a candidate run against a labelled baseline."""

    profile: str
    environment_label: str
    passed: bool
    gates: List[GateVerdict] = field(default_factory=list)
    deltas: List[MetricDelta] = field(default_factory=list)
    correctness_errors: int = 0
    security_errors: int = 0
    explanations: List[str] = field(default_factory=list)
    baseline_id: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def blocking_failures(self) -> List[GateVerdict]:
        return [g for g in self.gates if g.blocking and not g.passed]

    def to_json_dict(self) -> JSONDict:
        return {
            "profile": self.profile,
            "environment_label": self.environment_label,
            "passed": self.passed,
            "baseline_id": self.baseline_id,
            "correctness_errors": self.correctness_errors,
            "security_errors": self.security_errors,
            "gates": [g.to_json_dict() for g in self.gates],
            "deltas": [d.to_json_dict() for d in self.deltas],
            "explanations": list(self.explanations),
            "warnings": list(self.warnings),
            "blocking_failures": [g.to_json_dict() for g in self.blocking_failures],
        }


def unexplained_regression(
    baseline_value: float,
    candidate_value: float,
    *,
    higher_is_worse: bool,
    limit: float = REGRESSION_RATIO_LIMIT,
    explanation: Optional[str] = None,
) -> Optional[float]:
    """Return the regression ratio when it exceeds *limit* and is unexplained.

    For ``higher_is_worse`` (latency): regression when candidate > baseline.
    For lower-is-worse inverted (throughput, higher_is_worse=False): regression
    when candidate < baseline.

    A non-empty *explanation* marks the regression as explained and returns
    ``None`` (does not block). Absolute zero baselines are treated as no
    relative comparison (returns ``None``).
    """
    if baseline_value == 0:
        return None
    if higher_is_worse:
        # latency: worse when larger
        if candidate_value <= baseline_value:
            return None
        ratio = (candidate_value - baseline_value) / abs(baseline_value)
    else:
        # throughput: worse when smaller
        if candidate_value >= baseline_value:
            return None
        ratio = (baseline_value - candidate_value) / abs(baseline_value)
    if ratio > limit and not (explanation and str(explanation).strip()):
        return float(ratio)
    return None


def _metric_delta(
    name: str,
    *,
    baseline_value: float,
    candidate_value: float,
    direction: str,
    limit: float,
    bound: Optional[float] = None,
    explanation: Optional[str] = None,
) -> MetricDelta:
    higher_is_worse = direction == "lower_is_better"
    if baseline_value == 0:
        ratio = 0.0 if candidate_value == 0 else float("inf")
        reg = 0.0
    elif higher_is_worse:
        ratio = candidate_value / baseline_value
        reg = max(0.0, (candidate_value - baseline_value) / abs(baseline_value))
    else:
        ratio = candidate_value / baseline_value
        reg = max(0.0, (baseline_value - candidate_value) / abs(baseline_value))

    exceeds_limit = (
        unexplained_regression(
            baseline_value,
            candidate_value,
            higher_is_worse=higher_is_worse,
            limit=limit,
            explanation=explanation,
        )
        is not None
    )
    exceeds_bound = False
    if bound is not None:
        if higher_is_worse:
            exceeds_bound = candidate_value > bound
        else:
            exceeds_bound = candidate_value < bound
    return MetricDelta(
        name=name,
        baseline_value=float(baseline_value),
        candidate_value=float(candidate_value),
        direction=direction,
        ratio=float(ratio) if ratio != float("inf") else float("inf"),
        regression_ratio=float(reg),
        limit=float(limit),
        exceeds_limit=exceeds_limit,
        bound=float(bound) if bound is not None else None,
        exceeds_bound=exceeds_bound,
        explanation=explanation,
    )


def compare_metrics(
    baseline_metrics: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    regression_limit: float = REGRESSION_RATIO_LIMIT,
    explanations: Optional[Mapping[str, str]] = None,
    check_bounds: bool = True,
) -> List[MetricDelta]:
    """Compare candidate scalar metrics against baseline metric summaries.

    *baseline_metrics* maps metric name → summary dict with at least
    ``median`` and preferably ``bound`` / ``direction``.
    *candidate_metrics* maps metric name → numeric value (or summary with
    ``median``).
    """
    explanations = dict(explanations or {})
    deltas: List[MetricDelta] = []
    for name, bsum in baseline_metrics.items():
        if not isinstance(bsum, Mapping):
            continue
        if "median" not in bsum and "mean" not in bsum:
            continue
        baseline_value = float(bsum.get("median", bsum.get("mean", 0.0)))
        direction = str(bsum.get("direction") or (
            "higher_is_better" if name == "ops_per_s" else "lower_is_better"
        ))
        bound = bsum.get("bound")
        if bound is not None:
            bound = float(bound)
        raw = candidate_metrics.get(name)
        if raw is None:
            continue
        if isinstance(raw, Mapping):
            candidate_value = float(raw.get("median", raw.get("mean", raw.get("value", 0.0))))
        else:
            candidate_value = float(raw)
        # Regression gate applies to p95 and throughput per plan.
        limit = regression_limit if name in ("p95_ms", "ops_per_s") else float("inf")
        deltas.append(
            _metric_delta(
                name,
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                direction=direction,
                limit=limit,
                bound=bound if check_bounds else None,
                explanation=explanations.get(name),
            )
        )
    return deltas


def compare_to_baseline(
    baseline: Mapping[str, Any],
    candidate_metrics: Mapping[str, Any],
    *,
    correctness_errors: int = 0,
    security_errors: int = 0,
    status: str = "success",
    explanations: Optional[Mapping[str, str]] = None,
    check_bounds: bool = True,
    require_environment_match: bool = False,
    candidate_environment_label: Optional[str] = None,
) -> ComparisonResult:
    """Full gate evaluation of candidate metrics against a baseline document."""
    profile = str(baseline.get("profile") or "")
    env_label = str(baseline.get("environment_label") or "")
    baseline_id = str(baseline.get("baseline_id") or "")
    gates_cfg = baseline.get("gates") if isinstance(baseline.get("gates"), Mapping) else {}
    regression_limit = float(
        gates_cfg.get("p95_regression_max_ratio")
        or gates_cfg.get("regression_ratio_limit")
        or REGRESSION_RATIO_LIMIT
    )
    thr_limit = float(
        gates_cfg.get("throughput_regression_max_ratio") or regression_limit
    )
    corr_max = int(gates_cfg.get("correctness_errors_max", CORRECTNESS_ERROR_MAX))
    sec_max = int(gates_cfg.get("security_errors_max", SECURITY_ERROR_MAX))

    result = ComparisonResult(
        profile=profile,
        environment_label=env_label,
        passed=True,
        correctness_errors=int(correctness_errors),
        security_errors=int(security_errors),
        explanations=list((explanations or {}).values()),
        baseline_id=baseline_id,
    )

    # Environment label check (advisory unless required).
    if (
        require_environment_match
        and candidate_environment_label is not None
        and candidate_environment_label != env_label
    ):
        result.gates.append(
            GateVerdict(
                name="environment_label",
                passed=False,
                detail=(
                    f"candidate environment_label={candidate_environment_label!r} "
                    f"!= baseline {env_label!r}"
                ),
                blocking=True,
            )
        )
    elif (
        candidate_environment_label is not None
        and candidate_environment_label != env_label
    ):
        result.warnings.append(
            f"environment_label mismatch: candidate={candidate_environment_label!r} "
            f"baseline={env_label!r}; absolute bounds are not portable"
        )

    # Correctness / security hard gates.
    corr_ok = correctness_errors <= corr_max
    result.gates.append(
        GateVerdict(
            name="correctness_errors",
            passed=corr_ok,
            detail=f"correctness_errors={correctness_errors} max={corr_max}",
            blocking=True,
        )
    )
    sec_ok = security_errors <= sec_max
    result.gates.append(
        GateVerdict(
            name="security_errors",
            passed=sec_ok,
            detail=f"security_errors={security_errors} max={sec_max}",
            blocking=True,
        )
    )

    # Run status.
    status_ok = status == "success"
    result.gates.append(
        GateVerdict(
            name="run_status",
            passed=status_ok,
            detail=f"status={status!r}",
            blocking=True,
        )
    )

    baseline_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), Mapping) else {}
    # Apply distinct limits for p95 vs throughput via explanations + per-delta.
    deltas = compare_metrics(
        baseline_metrics,
        candidate_metrics,
        regression_limit=regression_limit,
        explanations=explanations,
        check_bounds=check_bounds,
    )
    # Re-apply throughput-specific limit if different.
    adjusted: List[MetricDelta] = []
    for d in deltas:
        if d.name == "ops_per_s" and thr_limit != regression_limit:
            adjusted.append(
                _metric_delta(
                    d.name,
                    baseline_value=d.baseline_value,
                    candidate_value=d.candidate_value,
                    direction=d.direction,
                    limit=thr_limit,
                    bound=d.bound,
                    explanation=d.explanation,
                )
            )
        else:
            adjusted.append(d)
    result.deltas = adjusted

    for d in adjusted:
        if d.name in ("p95_ms", "ops_per_s") and d.exceeds_limit:
            result.gates.append(
                GateVerdict(
                    name=f"regression_{d.name}",
                    passed=False,
                    detail=(
                        f"{d.name} regression {d.regression_ratio:.1%} exceeds "
                        f"limit {d.limit:.0%} "
                        f"(baseline={d.baseline_value:.6g}, candidate={d.candidate_value:.6g})"
                    ),
                    blocking=True,
                )
            )
        elif d.name in ("p95_ms", "ops_per_s"):
            result.gates.append(
                GateVerdict(
                    name=f"regression_{d.name}",
                    passed=True,
                    detail=(
                        f"{d.name} regression {d.regression_ratio:.1%} within "
                        f"limit {d.limit:.0%}"
                    ),
                    blocking=True,
                )
            )
        if d.exceeds_bound and check_bounds:
            result.gates.append(
                GateVerdict(
                    name=f"bound_{d.name}",
                    passed=False,
                    detail=(
                        f"{d.name}={d.candidate_value:.6g} outside bound "
                        f"{d.bound:.6g} ({d.direction})"
                    ),
                    blocking=True,
                )
            )

    result.passed = all(g.passed for g in result.gates if g.blocking)
    return result


def compare_receipt_to_baseline(
    receipt: Mapping[str, Any],
    baseline: Optional[Mapping[str, Any]] = None,
    *,
    profile: Optional[str] = None,
    environment_label: Optional[str] = None,
    explanations: Optional[Mapping[str, str]] = None,
    check_bounds: bool = True,
    security_errors: int = 0,
) -> ComparisonResult:
    """Compare a load-receipt document to a labelled baseline.

    Correctness errors are taken from ``receipt["error"]["count"]`` and any
    cell-level correctness markers in ``results``. Security errors must be
    supplied explicitly (receipts do not currently emit a dedicated counter);
    any non-zero value fails the gate.
    """
    if baseline is None:
        prof = profile
        if prof is None:
            cfg = receipt.get("config") if isinstance(receipt.get("config"), Mapping) else {}
            pblock = cfg.get("profile") if isinstance(cfg.get("profile"), Mapping) else {}
            prof = pblock.get("name") or cfg.get("profile_name")
        if not prof:
            raise ValueError("profile is required when baseline is not provided")
        baseline = load_baseline(str(prof), environment_label=environment_label)

    metrics = extract_metrics_from_receipt(receipt)
    err = receipt.get("error") if isinstance(receipt.get("error"), Mapping) else {}
    correctness = int(err.get("count") or 0)
    # Treat hard seed failures on python cells as correctness errors too.
    for cell in receipt.get("results") or []:
        if not isinstance(cell, Mapping):
            continue
        if cell.get("surface") == "python" and cell.get("seed_status") == "error":
            correctness += 1
        if cell.get("recovery_ok") is False and cell.get("surface") == "python":
            correctness += 1

    status = str(receipt.get("status") or "unknown")
    return compare_to_baseline(
        baseline,
        metrics,
        correctness_errors=correctness,
        security_errors=security_errors,
        status=status,
        explanations=explanations,
        check_bounds=check_bounds,
        candidate_environment_label=environment_label,
    )
