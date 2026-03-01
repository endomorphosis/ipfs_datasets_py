from __future__ import annotations

from typing import Any, Dict, Iterable, List


DEFAULT_METRIC_KEYS: List[str] = [
    "semantic_similarity_final_decoded_mean",
    "final_decoded_keyphrase_retention_mean",
    "final_decoded_enumeration_integrity_mean",
    "flogic_relation_coverage_mean",
    "hybrid_ir_success_rate",
]


DEFAULT_MIN_CANDIDATE_FLOORS: Dict[str, float] = {
    "semantic_similarity_final_decoded_mean": 0.90,
    "final_decoded_keyphrase_retention_mean": 0.75,
    "final_decoded_enumeration_integrity_mean": 0.70,
    "flogic_relation_coverage_mean": 0.50,
}


DEFAULT_MAX_INCREASE_LIMITS: Dict[str, float] = {
    "final_decoded_orphan_terminal_rate": 0.05,
    "final_decoded_relative_clause_artifact_rate": 0.05,
}


DEFAULT_GA_QUALITY_FLOORS: Dict[str, float] = {
    "semantic_similarity_final_decoded_mean": 0.92,
    "final_decoded_keyphrase_retention_mean": 0.78,
    "final_decoded_enumeration_integrity_mean": 0.70,
    "flogic_relation_coverage_mean": 0.50,
}


DEFAULT_GA_SAFETY_LIMITS: Dict[str, float] = {
    "final_decoded_orphan_terminal_rate": 0.05,
    "final_decoded_relative_clause_artifact_rate": 0.05,
}


DEFAULT_GA_LATENCY_LIMITS: Dict[str, float] = {
    "p95_latency_ms": 5000.0,
    "timeout_rate": 0.01,
    "error_rate": 0.01,
}


def build_canary_mode_decision(
    shadow_audit: Dict[str, Any],
    *,
    risk_level: str = "low",
    require_shadow_ready: bool = True,
) -> Dict[str, Any]:
    """Build canary routing decision using shadow audit and risk policy.

    Policy:
    - `high` risk always routes to baseline.
    - `medium` risk routes to hybrid only if shadow is ready and has zero failures.
    - `low` risk routes to hybrid if shadow is ready (or readiness not required).
    """
    risk = str(risk_level).strip().lower()
    if risk not in {"low", "medium", "high"}:
        raise ValueError(f"Unsupported risk_level: {risk_level}")

    summary = shadow_audit.get("summary") or {}
    shadow_ready = bool(summary.get("shadow_ready"))
    failure_count = int(summary.get("failure_count") or 0)

    route = "baseline"
    reason = "default_baseline"

    if risk == "high":
        route = "baseline"
        reason = "high_risk_profile"
    elif risk == "medium":
        if shadow_ready and failure_count == 0:
            route = "hybrid"
            reason = "medium_risk_shadow_pass"
        else:
            route = "baseline"
            reason = "medium_risk_shadow_fail"
    else:  # low
        if (not require_shadow_ready) or shadow_ready:
            route = "hybrid"
            reason = "low_risk_shadow_pass_or_not_required"
        else:
            route = "baseline"
            reason = "low_risk_shadow_fail"

    return {
        "risk_level": risk,
        "require_shadow_ready": bool(require_shadow_ready),
        "shadow_ready": shadow_ready,
        "failure_count": failure_count,
        "route": route,
        "hybrid_enabled": route == "hybrid",
        "proof_audit_required": True,
        "proof_audit_sample_size": 10 if route == "hybrid" else 0,
        "reason": reason,
    }


def build_ga_gate_assessment(
    shadow_audit: Dict[str, Any],
    canary_decision: Dict[str, Any],
    candidate_report: Dict[str, Any],
    *,
    runtime_stats: Dict[str, Any] | None = None,
    quality_floors: Dict[str, float] | None = None,
    safety_limits: Dict[str, float] | None = None,
    latency_limits: Dict[str, float] | None = None,
    require_latency_stats: bool = True,
) -> Dict[str, Any]:
    """Assess GA readiness from shadow/canary state and threshold gates."""
    qfloors = quality_floors or dict(DEFAULT_GA_QUALITY_FLOORS)
    slimits = safety_limits or dict(DEFAULT_GA_SAFETY_LIMITS)
    llimits = latency_limits or dict(DEFAULT_GA_LATENCY_LIMITS)

    summary = (candidate_report.get("summary") or {})
    shadow_summary = (shadow_audit.get("summary") or {})

    checks: List[Dict[str, Any]] = []

    shadow_ready = bool(shadow_summary.get("shadow_ready"))
    checks.append(
        {
            "type": "shadow_ready",
            "passed": shadow_ready,
            "value": shadow_ready,
            "message": "shadow audit must be ready for GA",
        }
    )

    hybrid_enabled = bool(canary_decision.get("hybrid_enabled"))
    checks.append(
        {
            "type": "canary_hybrid_enabled",
            "passed": hybrid_enabled,
            "value": hybrid_enabled,
            "message": "canary decision must enable hybrid for GA",
        }
    )

    for key, floor in sorted(qfloors.items(), key=lambda kv: kv[0]):
        value = summary.get(key)
        passed = isinstance(value, (int, float)) and float(value) >= float(floor)
        checks.append(
            {
                "type": "quality_floor",
                "metric": key,
                "value": value,
                "threshold": floor,
                "passed": bool(passed),
                "message": f"candidate[{key}] >= {floor}",
            }
        )

    for key, ceiling in sorted(slimits.items(), key=lambda kv: kv[0]):
        value = summary.get(key)
        passed = isinstance(value, (int, float)) and float(value) <= float(ceiling)
        checks.append(
            {
                "type": "safety_ceiling",
                "metric": key,
                "value": value,
                "threshold": ceiling,
                "passed": bool(passed),
                "message": f"candidate[{key}] <= {ceiling}",
            }
        )

    blocker = bool(summary.get("theorem_ingestion_blocker"))
    checks.append(
        {
            "type": "safety_blocker",
            "metric": "theorem_ingestion_blocker",
            "value": blocker,
            "passed": not blocker,
            "message": "theorem_ingestion_blocker must be false",
        }
    )

    stats = runtime_stats or {}
    has_latency_stats = all(k in stats for k in llimits)
    if require_latency_stats and not has_latency_stats:
        checks.append(
            {
                "type": "latency_stats_present",
                "passed": False,
                "message": "runtime_stats with latency/error metrics required for GA",
            }
        )
    elif (not require_latency_stats) and (not has_latency_stats):
        checks.append(
            {
                "type": "latency_stats_skipped",
                "passed": True,
                "message": "runtime stats omitted; latency checks skipped by policy",
            }
        )
    else:
        for key, ceiling in sorted(llimits.items(), key=lambda kv: kv[0]):
            value = stats.get(key)
            passed = isinstance(value, (int, float)) and float(value) <= float(ceiling)
            checks.append(
                {
                    "type": "latency_ceiling",
                    "metric": key,
                    "value": value,
                    "threshold": ceiling,
                    "passed": bool(passed),
                    "message": f"runtime_stats[{key}] <= {ceiling}",
                }
            )

    failures = [c for c in checks if not c.get("passed")]
    return {
        "summary": {
            "check_count": len(checks),
            "failure_count": len(failures),
            "ga_ready": len(failures) == 0,
        },
        "checks": checks,
    }


def _origin_counts(records: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rec in records:
        origin = str(rec.get("final_decoded_text_origin") or "none")
        counts[origin] = counts.get(origin, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def build_shadow_mode_audit(
    baseline_report: Dict[str, Any],
    candidate_report: Dict[str, Any],
    *,
    metric_keys: List[str] | None = None,
    min_candidate_floors: Dict[str, float] | None = None,
    max_increase_limits: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """Build a deterministic shadow-mode audit comparing baseline vs candidate reports."""
    metrics = metric_keys or list(DEFAULT_METRIC_KEYS)
    floors = min_candidate_floors or dict(DEFAULT_MIN_CANDIDATE_FLOORS)
    limits = max_increase_limits or dict(DEFAULT_MAX_INCREASE_LIMITS)

    base_summary = baseline_report.get("summary") or {}
    cand_summary = candidate_report.get("summary") or {}

    comparisons: List[Dict[str, Any]] = []
    checks: List[Dict[str, Any]] = []

    for key in metrics:
        b = base_summary.get(key)
        c = cand_summary.get(key)
        delta = None
        if isinstance(b, (int, float)) and isinstance(c, (int, float)):
            delta = float(c) - float(b)
        comparisons.append(
            {
                "metric": key,
                "baseline": b,
                "candidate": c,
                "delta": delta,
            }
        )

    for key, floor in sorted(floors.items(), key=lambda kv: kv[0]):
        c = cand_summary.get(key)
        passed = isinstance(c, (int, float)) and float(c) >= float(floor)
        checks.append(
            {
                "type": "candidate_floor",
                "metric": key,
                "candidate": c,
                "threshold": floor,
                "passed": bool(passed),
                "message": f"candidate[{key}] >= {floor}",
            }
        )

    for key, max_increase in sorted(limits.items(), key=lambda kv: kv[0]):
        b = base_summary.get(key)
        c = cand_summary.get(key)
        passed = False
        delta = None
        if isinstance(b, (int, float)) and isinstance(c, (int, float)):
            delta = float(c) - float(b)
            passed = delta <= float(max_increase)
        checks.append(
            {
                "type": "max_increase",
                "metric": key,
                "baseline": b,
                "candidate": c,
                "delta": delta,
                "threshold": max_increase,
                "passed": bool(passed),
                "message": f"candidate[{key}] - baseline[{key}] <= {max_increase}",
            }
        )

    segment_count_match = base_summary.get("segment_count") == cand_summary.get("segment_count")
    checks.append(
        {
            "type": "segment_count_match",
            "baseline": base_summary.get("segment_count"),
            "candidate": cand_summary.get("segment_count"),
            "passed": bool(segment_count_match),
            "message": "baseline and candidate segment_count must match",
        }
    )

    failures = [chk for chk in checks if not chk.get("passed")]

    return {
        "summary": {
            "baseline_segment_count": base_summary.get("segment_count"),
            "candidate_segment_count": cand_summary.get("segment_count"),
            "check_count": len(checks),
            "failure_count": len(failures),
            "shadow_ready": len(failures) == 0,
        },
        "comparisons": comparisons,
        "checks": checks,
        "origin_counts": {
            "baseline": _origin_counts(baseline_report.get("records") or []),
            "candidate": _origin_counts(candidate_report.get("records") or []),
        },
    }
