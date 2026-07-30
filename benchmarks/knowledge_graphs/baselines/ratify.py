"""Build and validate labelled baseline documents (KGP-030)."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .catalog import (
    BASELINE_SCHEMA,
    BASELINE_SCHEMA_VERSION,
    CORRECTNESS_ERROR_MAX,
    REGRESSION_RATIO_LIMIT,
    REQUIRED_BASELINE_KEYS,
    REQUIRED_METRIC_KEYS,
    SECURITY_ERROR_MAX,
)
from .methodology import (
    MetricSummary,
    aggregate_samples,
    validate_methodology,
    validate_metric_summary,
)

JSONDict = Dict[str, Any]


def extract_metrics_from_receipt(receipt: Mapping[str, Any]) -> JSONDict:
    """Pull comparable scalar metrics out of a load receipt."""
    hist = receipt.get("latency_histogram") if isinstance(receipt.get("latency_histogram"), Mapping) else {}
    thr = receipt.get("throughput") if isinstance(receipt.get("throughput"), Mapping) else {}
    rec = receipt.get("recovery") if isinstance(receipt.get("recovery"), Mapping) else {}
    resources = receipt.get("resources") if isinstance(receipt.get("resources"), Mapping) else {}
    return {
        "p50_ms": float(hist.get("p50_ms") or 0.0),
        "p95_ms": float(hist.get("p95_ms") or 0.0),
        "p99_ms": float(hist.get("p99_ms") or 0.0),
        "ops_per_s": float(thr.get("ops_per_s") or 0.0),
        "operations": float(thr.get("operations") or 0.0),
        "elapsed_s": float(thr.get("elapsed_s") or receipt.get("elapsed_s") or 0.0),
        "recovery_ms_mean": float(rec.get("ms_mean") or 0.0),
        "max_rss_bytes": float(resources.get("max_rss_bytes") or 0.0),
        "rss_bytes_end": float(resources.get("rss_bytes_end") or 0.0),
        "open_fds_end": float(
            (resources.get("end") or {}).get("open_fds")
            if isinstance(resources.get("end"), Mapping)
            else resources.get("open_fds_end") or 0.0
        ),
        "heap_bytes_end": float(resources.get("heap_bytes_end") or 0.0),
    }


def _digest(body: Mapping[str, Any]) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_baseline_document(
    *,
    profile: str,
    environment_label: str,
    environment: Mapping[str, Any],
    methodology: Mapping[str, Any],
    metric_summaries: Mapping[str, MetricSummary | Mapping[str, Any]],
    seed: int,
    shape: Optional[Mapping[str, Any]] = None,
    shape_fingerprint: Optional[str] = None,
    status: str = "ratified",
    ratification_method: str = "multi_sample_measurement",
    notes: str = "",
    gates: Optional[Mapping[str, Any]] = None,
    profile_config: Optional[Mapping[str, Any]] = None,
    baseline_id: Optional[str] = None,
    ratified_at: Optional[float] = None,
    task_id: str = "KGP-030",
) -> JSONDict:
    """Assemble a versioned, environment-labelled baseline document."""
    metrics: JSONDict = {}
    for name, summary in metric_summaries.items():
        if isinstance(summary, MetricSummary):
            metrics[name] = summary.to_json_dict()
        else:
            metrics[name] = dict(summary)

    gate_block = {
        "correctness_errors_max": CORRECTNESS_ERROR_MAX,
        "security_errors_max": SECURITY_ERROR_MAX,
        "p95_regression_max_ratio": REGRESSION_RATIO_LIMIT,
        "throughput_regression_max_ratio": REGRESSION_RATIO_LIMIT,
        "block_unexplained_p95_regression": True,
        "block_unexplained_throughput_regression": True,
        "require_zero_correctness_errors": True,
        "require_zero_security_errors": True,
    }
    if gates:
        gate_block.update(dict(gates))

    bid = baseline_id or f"kg-bl-{profile}-{environment_label}-{uuid.uuid4().hex[:10]}"
    body: JSONDict = {
        "schema": BASELINE_SCHEMA,
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_id": bid,
        "task_id": task_id,
        "profile": profile,
        "environment_label": environment_label,
        "environment": dict(environment),
        "methodology": dict(methodology),
        "metrics": metrics,
        "gates": gate_block,
        "status": status,
        "ratification_method": ratification_method,
        "ratified_at": float(ratified_at if ratified_at is not None else time.time()),
        "seed": int(seed),
        "shape": dict(shape or {}),
        "shape_fingerprint": shape_fingerprint,
        "profile_config": dict(profile_config or {}),
        "notes": notes,
    }
    body["digest"] = _digest({k: v for k, v in body.items() if k != "digest"})
    return body


def ratify_profile_runs(
    *,
    profile: str,
    environment_label: str,
    environment: Mapping[str, Any],
    run_metrics: Sequence[Mapping[str, Any]],
    methodology: Mapping[str, Any],
    seed: int,
    shape: Optional[Mapping[str, Any]] = None,
    shape_fingerprint: Optional[str] = None,
    status: str = "ratified",
    ratification_method: str = "multi_sample_measurement",
    notes: str = "",
    profile_config: Optional[Mapping[str, Any]] = None,
    k_stdev: float = 3.0,
    margin_ratio: float = 0.25,
) -> JSONDict:
    """Ratify a baseline from repeated run metric dicts.

    Each entry in *run_metrics* is a flat mapping produced by
    :func:`extract_metrics_from_receipt` (or equivalent).
    """
    if not run_metrics:
        raise ValueError("run_metrics must be non-empty")

    def _col(key: str) -> List[float]:
        return [float(r[key]) for r in run_metrics if key in r]

    lower_keys = (
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "recovery_ms_mean",
        "max_rss_bytes",
        "rss_bytes_end",
        "open_fds_end",
        "heap_bytes_end",
        "elapsed_s",
    )
    higher_keys = ("ops_per_s",)

    summaries: Dict[str, MetricSummary] = {}
    for key in lower_keys:
        vals = _col(key)
        if not vals:
            continue
        # Absolute floors tuned per unit class.
        floor = 0.05 if key.endswith("_ms") else (1024 * 1024 if "bytes" in key else 0.0)
        summaries[key] = aggregate_samples(
            vals,
            direction="lower_is_better",
            k_stdev=k_stdev,
            margin_ratio=margin_ratio,
            absolute_floor=floor,
        )
    for key in higher_keys:
        vals = _col(key)
        if not vals:
            continue
        summaries[key] = aggregate_samples(
            vals,
            direction="higher_is_better",
            k_stdev=k_stdev,
            margin_ratio=margin_ratio,
            absolute_floor=0.0,
        )

    return build_baseline_document(
        profile=profile,
        environment_label=environment_label,
        environment=environment,
        methodology=methodology,
        metric_summaries=summaries,
        seed=seed,
        shape=shape,
        shape_fingerprint=shape_fingerprint,
        status=status,
        ratification_method=ratification_method,
        notes=notes,
        profile_config=profile_config,
    )


def validate_baseline_document(data: Mapping[str, Any]) -> List[str]:
    """Return validation problems for a baseline document (empty = ok)."""
    problems: List[str] = []
    if not isinstance(data, Mapping):
        return ["baseline must be a mapping"]
    for key in REQUIRED_BASELINE_KEYS:
        if key not in data:
            problems.append(f"missing required key: {key}")
    if data.get("schema") != BASELINE_SCHEMA:
        problems.append(
            f"schema must be {BASELINE_SCHEMA!r}, got {data.get('schema')!r}"
        )
    if data.get("schema_version") != BASELINE_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {BASELINE_SCHEMA_VERSION}, "
            f"got {data.get('schema_version')!r}"
        )
    if not data.get("environment_label"):
        problems.append("environment_label must be non-empty")
    if not data.get("profile"):
        problems.append("profile must be non-empty")
    if data.get("status") not in (
        "ratified",
        "provisional",
        "environment_gated",
        "deprecated",
    ):
        problems.append(
            f"status must be ratified|provisional|environment_gated|deprecated, "
            f"got {data.get('status')!r}"
        )

    problems.extend(validate_methodology(data.get("methodology") or {}))

    metrics = data.get("metrics")
    if not isinstance(metrics, Mapping):
        problems.append("metrics must be a mapping")
    else:
        for key in REQUIRED_METRIC_KEYS:
            if key not in metrics:
                problems.append(f"metrics missing required key: {key}")
            else:
                problems.extend(validate_metric_summary(key, metrics[key]))
        # Ensure directions are consistent for gate metrics.
        p95 = metrics.get("p95_ms")
        if isinstance(p95, Mapping) and p95.get("direction") not in (
            None,
            "lower_is_better",
        ):
            problems.append("metrics.p95_ms.direction must be lower_is_better")
        thr = metrics.get("ops_per_s")
        if isinstance(thr, Mapping) and thr.get("direction") not in (
            None,
            "higher_is_better",
        ):
            problems.append("metrics.ops_per_s.direction must be higher_is_better")

    gates = data.get("gates")
    if not isinstance(gates, Mapping):
        problems.append("gates must be a mapping")
    else:
        for key in (
            "correctness_errors_max",
            "security_errors_max",
            "p95_regression_max_ratio",
            "throughput_regression_max_ratio",
        ):
            if key not in gates:
                problems.append(f"gates missing required key: {key}")
        if gates.get("correctness_errors_max") not in (0, 0.0):
            problems.append("gates.correctness_errors_max must be 0")
        if gates.get("security_errors_max") not in (0, 0.0):
            problems.append("gates.security_errors_max must be 0")
        for ratio_key in (
            "p95_regression_max_ratio",
            "throughput_regression_max_ratio",
        ):
            if ratio_key in gates:
                try:
                    r = float(gates[ratio_key])
                except (TypeError, ValueError):
                    problems.append(f"gates.{ratio_key} must be numeric")
                else:
                    if r > REGRESSION_RATIO_LIMIT + 1e-9:
                        problems.append(
                            f"gates.{ratio_key}={r} exceeds plan limit "
                            f"{REGRESSION_RATIO_LIMIT}"
                        )
    return problems
