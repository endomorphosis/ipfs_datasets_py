from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


DEFAULT_MIN_GAIN_THRESHOLD = 0.0
DEFAULT_MAX_MODALITY_REGRESSION = 0.0
DEFAULT_MODALITY_FLOOR = 0.85


_BENCHMARK_METRICS = (
    ("semantic_similarity_final_decoded_mean", "higher"),
    ("final_decoded_keyphrase_retention_mean", "higher"),
    ("final_decoded_enumeration_integrity_mean", "higher"),
    ("flogic_relation_coverage_mean", "higher"),
    ("hybrid_ir_success_rate", "higher"),
    ("hybrid_ir_success_count", "higher"),
    ("final_decoded_orphan_terminal_rate", "lower"),
    ("final_decoded_relative_clause_artifact_rate", "lower"),
    ("final_decoded_orphan_terminal_count_total", "lower"),
    ("final_decoded_relative_clause_artifact_count_total", "lower"),
)


def build_optimizer_onoff_benchmark(
    optimizer_off_report: Dict[str, Any],
    optimizer_on_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Build deterministic optimizer on/off benchmark comparison payload."""
    off_summary = optimizer_off_report.get("summary") or {}
    on_summary = optimizer_on_report.get("summary") or {}

    comparisons: List[Dict[str, Any]] = []
    improvements = 0
    regressions = 0
    equals = 0
    missing = 0

    for metric, direction in _BENCHMARK_METRICS:
        off_v = _as_float(off_summary.get(metric))
        on_v = _as_float(on_summary.get(metric))
        delta = None if off_v is None or on_v is None else on_v - off_v

        if delta is None:
            status = "missing"
            missing += 1
        elif delta == 0.0:
            status = "equal"
            equals += 1
        elif direction == "higher":
            status = "improved" if delta > 0 else "regressed"
            if status == "improved":
                improvements += 1
            else:
                regressions += 1
        else:
            status = "improved" if delta < 0 else "regressed"
            if status == "improved":
                improvements += 1
            else:
                regressions += 1

        comparisons.append(
            {
                "metric": metric,
                "direction": direction,
                "optimizer_off": off_v,
                "optimizer_on": on_v,
                "delta": delta,
                "status": status,
            }
        )

    semantic_gain = None
    off_sem = _as_float(off_summary.get("semantic_similarity_final_decoded_mean"))
    on_sem = _as_float(on_summary.get("semantic_similarity_final_decoded_mean"))
    if off_sem is not None and on_sem is not None:
        semantic_gain = on_sem - off_sem

    payload = {
        "optimizer_off_summary": off_summary,
        "optimizer_on_summary": on_summary,
        "comparisons": comparisons,
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]

    return {
        "summary": {
            "benchmark_id": f"opt_bench_{digest}",
            "improvement_count": improvements,
            "regression_count": regressions,
            "equal_count": equals,
            "missing_count": missing,
            "metric_count": len(comparisons),
            "net_score": improvements - regressions,
            "semantic_gain": semantic_gain,
        },
        "comparisons": comparisons,
    }


def build_optimizer_chain_plan(
    acceptance_decision: Dict[str, Any],
    *,
    post_parse_default: bool = True,
    post_compile_default: bool = True,
) -> Dict[str, Any]:
    """Build stage-level optimizer orchestration plan.

    Stage mapping:
    - `post_parse`: focused retry, encoder-quality retry
    - `post_compile`: fragment merging, LLM KG enrichment, decoder pass
    """
    summary = acceptance_decision.get("summary") or {}
    accepted = bool(summary.get("accepted"))

    # Conservative fallback: keep post-parse diagnostics active, disable
    # post-compile mutation-heavy stages when policy rejects.
    post_parse_enabled = bool(post_parse_default)
    post_compile_enabled = bool(post_compile_default) and accepted

    checks = acceptance_decision.get("checks") or []
    failing_modalities = sorted(
        {
            str(c.get("modality"))
            for c in checks
            if not c.get("passed") and c.get("modality") is not None
        }
    )

    return {
        "summary": {
            "accepted": accepted,
            "post_parse_enabled": post_parse_enabled,
            "post_compile_enabled": post_compile_enabled,
        },
        "stages": {
            "post_parse": {
                "enabled": post_parse_enabled,
                "optimizers": [
                    "focused_retry_optimizer",
                    "encoder_quality_retry",
                ],
            },
            "post_compile": {
                "enabled": post_compile_enabled,
                "optimizers": [
                    "fragment_merging",
                    "llm_kg_enrichment",
                    "llm_decoder_pass",
                ],
            },
        },
        "env": {
            "ENABLE_POST_PARSE_OPTIMIZERS": "1" if post_parse_enabled else "0",
            "ENABLE_POST_COMPILE_OPTIMIZERS": "1" if post_compile_enabled else "0",
        },
        "notes": {
            "failing_modalities": failing_modalities,
            "policy": "optimizer_chain_v1",
            "reason": (
                "policy_accepted"
                if accepted
                else "policy_rejected_post_compile_disabled"
            ),
        },
    }


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def build_optimizer_acceptance_decision(
    baseline_report: Dict[str, Any],
    candidate_report: Dict[str, Any],
    *,
    min_gain_threshold: float = DEFAULT_MIN_GAIN_THRESHOLD,
    max_modality_regression: float = DEFAULT_MAX_MODALITY_REGRESSION,
    default_modality_floor: float = DEFAULT_MODALITY_FLOOR,
) -> Dict[str, Any]:
    """Apply optimizer acceptance policy with semantic-floor guards.

    Acceptance rule:
    - global gain >= min_gain_threshold
    - each modality delta >= -max_modality_regression
    - each candidate modality score >= floor
    """
    base_summary = baseline_report.get("summary") or {}
    cand_summary = candidate_report.get("summary") or {}

    base_global = _as_float(base_summary.get("semantic_similarity_final_decoded_mean"))
    cand_global = _as_float(cand_summary.get("semantic_similarity_final_decoded_mean"))
    global_gain = None if base_global is None or cand_global is None else cand_global - base_global

    checks: List[Dict[str, Any]] = []

    global_pass = global_gain is not None and global_gain >= float(min_gain_threshold)
    checks.append(
        {
            "type": "global_gain",
            "baseline": base_global,
            "candidate": cand_global,
            "gain": global_gain,
            "threshold": float(min_gain_threshold),
            "passed": bool(global_pass),
            "message": f"candidate_global_gain >= {float(min_gain_threshold)}",
        }
    )

    base_mod = dict(base_summary.get("semantic_similarity_by_modality") or {})
    cand_mod = dict(cand_summary.get("semantic_similarity_by_modality") or {})
    floors = dict(cand_summary.get("semantic_similarity_floors") or {})

    modalities = sorted(set(base_mod.keys()) | set(cand_mod.keys()))
    for mod in modalities:
        b = _as_float(base_mod.get(mod))
        c = _as_float(cand_mod.get(mod))
        delta = None if b is None or c is None else c - b
        no_regression_pass = delta is not None and delta >= -float(max_modality_regression)
        checks.append(
            {
                "type": "modality_regression",
                "modality": mod,
                "baseline": b,
                "candidate": c,
                "delta": delta,
                "threshold": -float(max_modality_regression),
                "passed": bool(no_regression_pass),
                "message": f"candidate[{mod}] - baseline[{mod}] >= {-float(max_modality_regression)}",
            }
        )

        floor = _as_float(floors.get(mod))
        if floor is None:
            floor = float(default_modality_floor)
        floor_pass = c is not None and c >= float(floor)
        checks.append(
            {
                "type": "modality_floor",
                "modality": mod,
                "candidate": c,
                "threshold": float(floor),
                "passed": bool(floor_pass),
                "message": f"candidate[{mod}] >= {float(floor)}",
            }
        )

    failures = [c for c in checks if not c.get("passed")]

    payload = {
        "baseline_global": base_global,
        "candidate_global": cand_global,
        "global_gain": global_gain,
        "min_gain_threshold": float(min_gain_threshold),
        "max_modality_regression": float(max_modality_regression),
        "default_modality_floor": float(default_modality_floor),
        "checks": checks,
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]

    return {
        "summary": {
            "decision_id": f"opt_{digest}",
            "accepted": len(failures) == 0,
            "check_count": len(checks),
            "failure_count": len(failures),
            "global_gain": global_gain,
        },
        "checks": checks,
        "audit_record": {
            "policy": "optimizer_acceptance_v1",
            "decision": "accepted" if len(failures) == 0 else "rejected",
            "reason_count": len(failures),
        },
    }
