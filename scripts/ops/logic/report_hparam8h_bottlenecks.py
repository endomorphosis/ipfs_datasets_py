#!/usr/bin/env python3
"""Report worker balance and likely bottlenecks for legal-IR hparam/final runs."""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        pass
    return events


def _finite_float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _summary_metric(summary: dict[str, Any], key: str, default: str = "n/a") -> str:
    value = summary.get(key)
    if value is None:
        return default
    if isinstance(value, float):
        if not math.isfinite(value):
            return default
        if abs(value) >= 1.0e11:
            return "unset"
        return f"{value:.6g}"
    return str(value)


def _distribution_cosine_similarity(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> float:
    keys = sorted(set(left) | set(right))
    if not keys:
        return math.nan
    left_values = [_finite_float(left.get(key), 0.0) for key in keys]
    right_values = [_finite_float(right.get(key), 0.0) for key in keys]
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return math.nan
    return sum(a * b for a, b in zip(left_values, right_values)) / (
        left_norm * right_norm
    )


def _learned_ir_from_metric_block(block: Mapping[str, Any]) -> dict[str, Any]:
    legal_ir_losses = (
        block.get("legal_ir_losses") if isinstance(block.get("legal_ir_losses"), dict) else {}
    )
    target_distribution = (
        block.get("legal_ir_view_distribution")
        if isinstance(block.get("legal_ir_view_distribution"), dict)
        else {}
    )
    predicted_distribution = (
        block.get("legal_ir_predicted_view_distribution")
        if isinstance(block.get("legal_ir_predicted_view_distribution"), dict)
        else {}
    )
    view_ce = _finite_float(
        legal_ir_losses.get("legal_ir_view_cross_entropy_loss"),
        math.nan,
    )
    view_entropy = _finite_float(
        legal_ir_losses.get("legal_ir_view_entropy_loss"),
        math.nan,
    )
    view_excess = _finite_float(
        legal_ir_losses.get("legal_ir_view_cross_entropy_excess_loss"),
        math.nan,
    )
    return {
        "target_count": int(block.get("legal_ir_target_count", 0) or 0),
        "view_cross_entropy_loss": view_ce,
        "view_entropy_loss": view_entropy,
        "view_cross_entropy_excess_loss": view_excess,
        "view_cosine_similarity": _distribution_cosine_similarity(
            predicted_distribution,
            target_distribution,
        ),
    }


def _projection_rejection_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = report.get("rejection_summary")
    if isinstance(summary, dict):
        return summary
    attempted_count = 0
    accepted_attempt_count = 0
    rejected_attempt_count = 0
    regression_counts: Counter[str] = Counter()
    best_rejected: dict[str, Any] = {}
    for epoch in report.get("epoch_reports", []) if isinstance(report, Mapping) else []:
        if not isinstance(epoch, Mapping):
            continue
        for candidate in epoch.get("candidate_reports", []):
            if not isinstance(candidate, Mapping):
                continue
            attempts = candidate.get("attempt_reports")
            if not isinstance(attempts, list):
                attempts = [candidate]
            for attempt in attempts:
                if not isinstance(attempt, Mapping):
                    continue
                attempted_count += 1
                if bool(attempt.get("accepted")):
                    accepted_attempt_count += 1
                    continue
                rejected_attempt_count += 1
                pareto = attempt.get("pareto_regressions")
                if isinstance(pareto, Mapping):
                    regression_counts.update(str(name) for name in pareto)
                objective_delta = _finite_float(attempt.get("objective_delta"), 0.0)
                if not best_rejected or objective_delta > _finite_float(
                    best_rejected.get("objective_delta"),
                    0.0,
                ):
                    best_rejected = {
                        "effective_learning_rate": _finite_float(
                            attempt.get("effective_learning_rate"),
                            0.0,
                        ),
                        "line_search_multiplier": _finite_float(
                            attempt.get("line_search_multiplier"),
                            0.0,
                        ),
                        "objective_delta": objective_delta,
                        "pareto_regressions": dict(pareto)
                        if isinstance(pareto, Mapping)
                        else {},
                        "update": str(attempt.get("update") or ""),
                    }
    return {
        "accepted_attempt_count": accepted_attempt_count,
        "attempted_count": attempted_count,
        "best_rejected_attempt": best_rejected,
        "pareto_regression_counts": dict(regression_counts.most_common(12)),
        "rejected_attempt_count": rejected_attempt_count,
    }


def _latest_cycle_event(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("event") == "cycle":
            return event
    return {}


def _first_metric(*values: Any, default: float = math.nan) -> float:
    for value in values:
        result = _finite_float(value, math.nan)
        if math.isfinite(result):
            return result
    return default


def _mtime_age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _run_ps() -> list[dict[str, Any]]:
    try:
        output = subprocess.check_output(
            ["ps", "-eo", "pid,ppid,pgid,stat,pcpu,pmem,args"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    rows: list[dict[str, Any]] = []
    for line in output.splitlines()[1:]:
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        pid, ppid, pgid, stat, pcpu, pmem, args = parts
        rows.append(
            {
                "pid": int(pid),
                "ppid": int(ppid),
                "pgid": int(pgid),
                "stat": stat,
                "pcpu": _finite_float(pcpu, 0.0),
                "pmem": _finite_float(pmem, 0.0),
                "args": args,
            }
        )
    return rows


def _process_snapshot(run_id: str) -> dict[str, Any]:
    rows = [
        row
        for row in _run_ps()
        if run_id in str(row.get("args", ""))
        and "report_hparam8h_bottlenecks.py" not in str(row.get("args", ""))
    ]
    counts = Counter()
    cpu = defaultdict(float)
    for row in rows:
        args = str(row["args"])
        role = "other"
        if "run_hparam_then_8h.sh" in args:
            role = "launcher"
        elif "watch_hparam8h_pipeline.sh" in args:
            role = "watchdog"
        elif "ensure_watchdog_until_verified.sh" in args:
            role = "watchdog_supervisor"
        elif "--loop-role autoencoder" in args:
            role = "autoencoder"
        elif "--loop-role codex" in args:
            role = "codex"
        elif "--loop-role paired" in args:
            role = "paired"
        counts[role] += 1
        cpu[role] += float(row["pcpu"])
    return {
        "counts": dict(counts),
        "cpu_percent": {key: round(value, 1) for key, value in sorted(cpu.items())},
        "rows": rows,
    }


def _nvidia_smi_snapshot() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return {"available": False}
    gpus = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        gpus.append(
            {
                "index": parts[0],
                "name": parts[1],
                "gpu_util_percent": _finite_float(parts[2], 0.0),
                "memory_used_mib": _finite_float(parts[3], 0.0),
                "memory_total_mib": _finite_float(parts[4], 0.0),
            }
        )
    return {"available": bool(gpus), "gpus": gpus}


def _parse_pipeline_final_run_id(pipeline_log: Path) -> str | None:
    try:
        text = pipeline_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = re.findall(r"starting final 8h run_id=([^\s]+)", text)
    return matches[-1] if matches else None


def _queue_stats(path: Path) -> dict[str, Any]:
    status_counts = Counter()
    role_counts = Counter()
    scope_counts = Counter()
    pending_by_scope = Counter()
    claimed_by_scope = Counter()
    failed_by_action = Counter()
    failed_by_reason = Counter()
    failed_by_scope = Counter()
    total = 0
    for event in _iter_jsonl(path):
        total += 1
        status = str(event.get("status") or "missing")
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        role = str(
            metadata.get("optimizer_role")
            or event.get("optimizer_role")
            or event.get("role")
            or "missing"
        )
        scope = str(metadata.get("program_synthesis_scope") or "missing")
        status_counts[status] += 1
        role_counts[role] += 1
        scope_counts[scope] += 1
        if status == "pending":
            pending_by_scope[scope] += 1
        elif status == "claimed":
            claimed_by_scope[scope] += 1
        elif status == "failed_validation":
            failed_by_scope[scope] += 1
            failed_by_action[str(event.get("action") or "missing")] += 1
            failed_by_reason[str(metadata.get("failure_reason") or "missing")] += 1
    return {
        "path": str(path),
        "exists": path.exists(),
        "total": total,
        "status_counts": dict(status_counts),
        "role_counts": dict(role_counts),
        "scope_counts": dict(scope_counts.most_common(12)),
        "pending_by_scope": dict(pending_by_scope.most_common(12)),
        "claimed_by_scope": dict(claimed_by_scope.most_common(12)),
        "failed_by_action": dict(failed_by_action.most_common(12)),
        "failed_by_reason": dict(failed_by_reason.most_common(12)),
        "failed_by_scope": dict(failed_by_scope.most_common(12)),
    }


def _trial_reports(log_dir: Path, run_id: str) -> list[dict[str, Any]]:
    reports = []
    for raw_path in sorted(glob.glob(str(log_dir / f"{run_id}-trial-*.summary"))):
        path = Path(raw_path)
        summary = _load_json(path)
        jsonl_path = path.with_suffix(".jsonl")
        cycle_durations = [
            _finite_float(event.get("duration_seconds"))
            for event in _iter_jsonl(jsonl_path)
            if event.get("event") == "cycle"
        ]
        cycle_durations = [value for value in cycle_durations if math.isfinite(value)]
        reports.append(
            {
                "run_id": summary.get("run_id") or path.stem,
                "summary_path": str(path),
                "cycles": int(summary.get("cycles", 0) or 0),
                "age_seconds": _mtime_age_seconds(path),
                "bridge_workers": int(summary.get("autoencoder_bridge_workers", 0) or 0),
                "best_validation_ce": summary.get("best_validation_ce"),
                "best_validation_cosine": summary.get("best_validation_cosine"),
                "best_validation_ir_ce": summary.get("best_validation_ir_ce"),
                "best_validation_ir_cosine": summary.get("best_validation_ir_cosine"),
                "cycle_duration_median": (
                    statistics.median(cycle_durations) if cycle_durations else None
                ),
                "cycle_duration_latest": cycle_durations[-1] if cycle_durations else None,
                "metric_failures": int(summary.get("metric_failures", 0) or 0),
            }
        )
    return reports


def _final_report(log_dir: Path, queue_dir: Path, run_id: str) -> dict[str, Any]:
    pipeline_log = log_dir / f"{run_id}.pipeline.log"
    final_run_id = _parse_pipeline_final_run_id(pipeline_log) or f"{run_id}-best-8h"
    summary_path = log_dir / f"{final_run_id}-autoencoder.summary"
    if not summary_path.exists():
        summary_path = log_dir / f"{final_run_id}.summary"
    summary = _load_json(summary_path)
    queue_path = queue_dir / f"{final_run_id}-autoencoder.jsonl"
    if not queue_path.exists():
        queue_path = queue_dir / f"{final_run_id}.jsonl"
    event_log_path = log_dir / f"{final_run_id}-autoencoder.jsonl"
    if not event_log_path.exists():
        event_log_path = log_dir / f"{final_run_id}.jsonl"
    events = _iter_jsonl(event_log_path)
    latest_cycle = _latest_cycle_event(events)
    latest_autoencoder_validation = summary.get("latest_autoencoder_validation")
    if not isinstance(latest_autoencoder_validation, dict):
        latest_autoencoder_validation = (
            latest_cycle.get("autoencoder_after_validation")
            if isinstance(latest_cycle.get("autoencoder_after_validation"), dict)
            else latest_cycle.get("after_validation")
        )
    if not isinstance(latest_autoencoder_validation, dict):
        latest_autoencoder_validation = {}
    latest_compiler_ir_validation = summary.get("latest_compiler_ir_validation")
    if not isinstance(latest_compiler_ir_validation, dict):
        latest_compiler_ir_validation = (
            latest_cycle.get("compiler_ir_validation")
            if isinstance(latest_cycle.get("compiler_ir_validation"), dict)
            else {}
        )
    latest_compiler_ir_guided_validation = summary.get(
        "latest_compiler_ir_guided_validation"
    )
    if not isinstance(latest_compiler_ir_guided_validation, dict):
        latest_compiler_ir_guided_validation = (
            latest_cycle.get("compiler_ir_guided_validation")
            if isinstance(latest_cycle.get("compiler_ir_guided_validation"), dict)
            else {}
        )
    latest_guidance_canary = summary.get("latest_compiler_ir_guidance_canary")
    if not isinstance(latest_guidance_canary, dict):
        latest_guidance_canary = (
            latest_cycle.get("compiler_ir_guidance_canary")
            if isinstance(latest_cycle.get("compiler_ir_guidance_canary"), dict)
            else {}
        )
    latest_guidance_promotion = summary.get(
        "latest_compiler_ir_guidance_promotion"
    )
    if not isinstance(latest_guidance_promotion, dict):
        latest_guidance_promotion = (
            latest_cycle.get("compiler_ir_guidance_promotion")
            if isinstance(latest_cycle.get("compiler_ir_guidance_promotion"), dict)
            else {}
        )
    latest_guidance_scope_hints = summary.get(
        "latest_compiler_ir_guidance_scope_hints"
    )
    if not isinstance(latest_guidance_scope_hints, dict):
        latest_guidance_scope_hints = (
            latest_cycle.get("compiler_ir_guidance_scope_hints")
            if isinstance(latest_cycle.get("compiler_ir_guidance_scope_hints"), dict)
            else {}
        )
    latest_guidance_distillation = summary.get(
        "latest_compiler_ir_guidance_distillation"
    )
    if not isinstance(latest_guidance_distillation, dict):
        latest_guidance_distillation = (
            latest_cycle.get("compiler_ir_guidance_distillation")
            if isinstance(latest_cycle.get("compiler_ir_guidance_distillation"), dict)
            else {}
        )
    latest_learned_ir_validation = summary.get("latest_learned_ir_validation")
    if not isinstance(latest_learned_ir_validation, dict):
        latest_learned_ir_validation = (
            latest_cycle.get("learned_ir_validation")
            if isinstance(latest_cycle.get("learned_ir_validation"), dict)
            else _learned_ir_from_metric_block(latest_autoencoder_validation)
        )
    latest_todo_generation = summary.get("latest_todo_generation")
    if not isinstance(latest_todo_generation, dict):
        latest_todo_generation = {
            "claimed": latest_cycle.get("program_synthesis_claimed_count"),
            "completed": latest_cycle.get("program_synthesis_completed_count"),
            "deduped_total": latest_cycle.get("program_synthesis_deduped_total"),
            "execution_mode": latest_cycle.get("program_synthesis_execution_mode"),
            "pending": latest_cycle.get("program_synthesis_pending_count"),
            "preinsert_deduped_count": latest_cycle.get(
                "program_synthesis_preinsert_deduped_count"
            ),
            "seeded_count": latest_cycle.get("program_synthesis_seeded_count"),
            "semantic_deduped_count": latest_cycle.get(
                "program_synthesis_semantic_deduped_count"
            ),
            "failed_validation_rescue_deduped_count": latest_cycle.get(
                "failed_validation_rescue_deduped_count"
            ),
            "failed_validation_rescue_seeded_count": latest_cycle.get(
                "failed_validation_rescue_seeded_count"
            ),
        }
    latest_feature_projection_report = summary.get("latest_feature_projection_report")
    if not isinstance(latest_feature_projection_report, dict):
        latest_feature_projection_report = (
            latest_cycle.get("feature_projection_report")
            if isinstance(latest_cycle.get("feature_projection_report"), dict)
            else {}
        )
    learned_ir_history = []
    for event in events:
        if event.get("event") != "cycle":
            continue
        learned_block = (
            event.get("learned_ir_validation")
            if isinstance(event.get("learned_ir_validation"), dict)
            else None
        )
        if learned_block is None:
            metric_block = (
                event.get("autoencoder_after_validation")
                if isinstance(event.get("autoencoder_after_validation"), dict)
                else event.get("after_validation")
            )
            learned_block = (
                _learned_ir_from_metric_block(metric_block)
                if isinstance(metric_block, dict)
                else {}
            )
        learned_ir_history.append(learned_block)
    learned_ir_ce_history = [
        _finite_float(block.get("view_cross_entropy_loss"), math.nan)
        for block in learned_ir_history
    ]
    learned_ir_ce_history = [
        value for value in learned_ir_ce_history if math.isfinite(value)
    ]
    learned_ir_cosine_history = [
        _finite_float(block.get("view_cosine_similarity"), math.nan)
        for block in learned_ir_history
    ]
    learned_ir_cosine_history = [
        value for value in learned_ir_cosine_history if math.isfinite(value)
    ]
    cycle_durations = [
        _finite_float(event.get("duration_seconds"))
        for event in events
        if event.get("event") == "cycle"
    ]
    cycle_durations = [value for value in cycle_durations if math.isfinite(value)]
    return {
        "run_id": final_run_id,
        "summary_path": str(summary_path),
        "summary_exists": bool(summary),
        "cycles": int(summary.get("cycles", 0) or 0),
        "age_seconds": _mtime_age_seconds(summary_path) if summary_path.exists() else None,
        "bridge_workers": int(summary.get("autoencoder_bridge_workers", 0) or 0),
        "best_validation_ce": summary.get("best_validation_ce"),
        "best_validation_cosine": summary.get("best_validation_cosine"),
        "best_validation_ir_ce": summary.get("best_validation_ir_ce"),
        "best_validation_ir_cosine": summary.get("best_validation_ir_cosine"),
        "best_validation_ir_guided_ce": summary.get("best_validation_ir_guided_ce"),
        "best_validation_ir_guided_ce_excess": summary.get(
            "best_validation_ir_guided_ce_excess"
        ),
        "best_validation_ir_guided_cosine": summary.get(
            "best_validation_ir_guided_cosine"
        ),
        "best_validation_ir_source_copy_loss": summary.get(
            "best_validation_ir_source_copy_loss"
        ),
        "best_validation_learned_ir_view_ce": summary.get(
            "best_validation_learned_ir_view_ce"
        )
        if summary.get("best_validation_learned_ir_view_ce") is not None
        else (min(learned_ir_ce_history) if learned_ir_ce_history else math.nan),
        "best_validation_learned_ir_view_cosine": summary.get(
            "best_validation_learned_ir_view_cosine"
        )
        if summary.get("best_validation_learned_ir_view_cosine") is not None
        else (
            max(learned_ir_cosine_history)
            if learned_ir_cosine_history
            else math.nan
        ),
        "latest_validation_ce": _first_metric(
            summary.get("latest_validation_ce"),
            latest_autoencoder_validation.get("cross_entropy_loss"),
        ),
        "latest_validation_cosine": _first_metric(
            summary.get("latest_validation_cosine"),
            latest_autoencoder_validation.get("cosine_similarity"),
        ),
        "latest_validation_reconstruction": _first_metric(
            summary.get("latest_validation_reconstruction"),
            latest_autoencoder_validation.get("reconstruction_loss"),
        ),
        "latest_validation_ce_excess": _first_metric(
            latest_autoencoder_validation.get("cross_entropy_excess_loss"),
        ),
        "latest_validation_ce_delta": _first_metric(
            summary.get("latest_validation_ce_delta"),
            latest_cycle.get("validation_cross_entropy_delta"),
        ),
        "latest_validation_cosine_delta": _first_metric(
            summary.get("latest_validation_cosine_delta"),
            latest_cycle.get("validation_cosine_delta"),
        ),
        "latest_compiler_ir_ce": _first_metric(
            summary.get("latest_compiler_ir_ce"),
            latest_compiler_ir_validation.get("cross_entropy_loss"),
        ),
        "latest_compiler_ir_ce_excess": _first_metric(
            summary.get("latest_compiler_ir_ce_excess"),
            latest_compiler_ir_validation.get("cross_entropy_excess_loss"),
        ),
        "latest_compiler_ir_cosine": _first_metric(
            summary.get("latest_compiler_ir_cosine"),
            latest_compiler_ir_validation.get("cosine_similarity"),
        ),
        "latest_compiler_ir_source_copy_loss": _first_metric(
            summary.get("latest_compiler_ir_source_copy_loss"),
            latest_compiler_ir_validation.get("source_copy_loss"),
        ),
        "latest_compiler_ir_source_copy_reward_hack_penalty": _first_metric(
            latest_compiler_ir_validation.get("source_copy_reward_hack_penalty"),
        ),
        "latest_compiler_ir_guided_applied_count": int(
            latest_compiler_ir_guided_validation.get(
                "autoencoder_guidance_applied_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guided_empty_count": int(
            latest_compiler_ir_guided_validation.get(
                "autoencoder_guidance_empty_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guided_failures": int(
            latest_compiler_ir_guided_validation.get(
                "autoencoder_guidance_failures",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guided_produced_count": int(
            latest_compiler_ir_guided_validation.get(
                "autoencoder_guidance_produced_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guided_requested_count": int(
            latest_compiler_ir_guided_validation.get(
                "autoencoder_guidance_requested_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guided_unapplied_count": int(
            latest_compiler_ir_guided_validation.get(
                "autoencoder_guidance_unapplied_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guided_ce": _first_metric(
            summary.get("latest_compiler_ir_guided_ce"),
            latest_compiler_ir_guided_validation.get("cross_entropy_loss"),
        ),
        "latest_compiler_ir_guided_ce_excess": _first_metric(
            summary.get("latest_compiler_ir_guided_ce_excess"),
            latest_compiler_ir_guided_validation.get("cross_entropy_excess_loss"),
        ),
        "latest_compiler_ir_guided_cosine": _first_metric(
            summary.get("latest_compiler_ir_guided_cosine"),
            latest_compiler_ir_guided_validation.get("cosine_similarity"),
        ),
        "latest_compiler_ir_guided_copy_hack_penalty": _first_metric(
            summary.get(
                "latest_compiler_ir_guided_source_copy_reward_hack_penalty"
            ),
            latest_compiler_ir_guided_validation.get(
                "source_copy_reward_hack_penalty"
            ),
        ),
        "latest_compiler_ir_guidance_ce_delta": _first_metric(
            summary.get("latest_compiler_ir_guidance_ce_delta"),
            latest_guidance_canary.get("ce_delta"),
            latest_cycle.get("compiler_ir_guidance_ce_delta"),
        ),
        "latest_compiler_ir_guidance_cosine_delta": _first_metric(
            summary.get("latest_compiler_ir_guidance_cosine_delta"),
            latest_guidance_canary.get("cosine_delta"),
            latest_cycle.get("compiler_ir_guidance_cosine_delta"),
        ),
        "latest_compiler_ir_guidance_copy_hack_delta": _first_metric(
            summary.get("latest_compiler_ir_guidance_copy_hack_delta"),
            latest_guidance_canary.get("copy_hack_delta"),
            latest_cycle.get("compiler_ir_guidance_copy_hack_delta"),
        ),
        "latest_compiler_ir_guidance_quality_gate": str(
            summary.get("latest_compiler_ir_guidance_quality_gate")
            or latest_guidance_canary.get("quality_gate")
            or "n/a"
        ),
        "latest_compiler_ir_guidance_promotion_allowed": bool(
            summary.get("latest_compiler_ir_guidance_promotion_allowed")
            if summary.get("latest_compiler_ir_guidance_promotion_allowed")
            is not None
            else latest_guidance_promotion.get("promotion_allowed", False)
        ),
        "latest_compiler_ir_guidance_promotion_block_reason": str(
            summary.get("latest_compiler_ir_guidance_promotion_block_reason")
            or latest_guidance_promotion.get("promotion_block_reason")
            or "n/a"
        ),
        "latest_compiler_ir_guidance_distillation_path": str(
            summary.get("latest_compiler_ir_guidance_distillation_path")
            or ""
        ),
        "latest_compiler_ir_guidance_distillation_deduped_count": int(
            summary.get("latest_compiler_ir_guidance_distillation_deduped_count")
            or latest_cycle.get(
                "compiler_ir_guidance_distillation_deduped_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guidance_distillation_seeded_count": int(
            summary.get("latest_compiler_ir_guidance_distillation_seeded_count")
            or latest_cycle.get(
                "compiler_ir_guidance_distillation_seeded_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guidance_distillation": latest_guidance_distillation,
        "latest_compiler_ir_guidance_scope_hints": latest_guidance_scope_hints,
        "latest_compiler_ir_guided_family_ce_excess": _first_metric(
            latest_compiler_ir_guided_validation.get(
                "guidance_family_cross_entropy_excess_loss"
            ),
        ),
        "latest_compiler_ir_guided_frame_boost_count": _first_metric(
            latest_compiler_ir_guided_validation.get(
                "compiler_guidance_frame_boost_count"
            ),
        ),
        "latest_compiler_ir_guided_frame_changed_count": int(
            latest_compiler_ir_guided_validation.get(
                "compiler_guidance_frame_changed_count",
                0,
            )
            or 0
        ),
        "latest_compiler_ir_guidance_feature_groups": (
            latest_compiler_ir_guided_validation.get(
                "compiler_guidance_feature_groups",
                {},
            )
            if isinstance(
                latest_compiler_ir_guided_validation.get(
                    "compiler_guidance_feature_groups"
                ),
                dict,
            )
            else {}
        ),
        "latest_compiler_ir_guidance_surface_features": (
            latest_compiler_ir_guided_validation.get(
                "compiler_guidance_surface_features",
                {},
            )
            if isinstance(
                latest_compiler_ir_guided_validation.get(
                    "compiler_guidance_surface_features"
                ),
                dict,
            )
            else {}
        ),
        "latest_compiler_ir_guidance_todo_routes": (
            latest_compiler_ir_guided_validation.get(
                "compiler_guidance_todo_routes",
                {},
            )
            if isinstance(
                latest_compiler_ir_guided_validation.get(
                    "compiler_guidance_todo_routes"
                ),
                dict,
            )
            else {}
        ),
        "latest_learned_ir_view_ce": _first_metric(
            summary.get("latest_learned_ir_view_ce"),
            latest_learned_ir_validation.get("view_cross_entropy_loss"),
        ),
        "latest_learned_ir_view_ce_excess": _first_metric(
            latest_learned_ir_validation.get("view_cross_entropy_excess_loss"),
        ),
        "latest_learned_ir_view_cosine": _first_metric(
            summary.get("latest_learned_ir_view_cosine"),
            latest_learned_ir_validation.get("view_cosine_similarity"),
        ),
        "learning_rate_plateau_streak": int(
            summary.get("learning_rate_plateau_streak", 0) or 0
        ),
        "latest_feature_projection_accepted_epochs": int(
            latest_feature_projection_report.get("accepted_epochs", 0)
            or 0
        ),
        "latest_feature_projection_rejection_summary": _projection_rejection_summary(
            latest_feature_projection_report
        ),
        "program_synthesis_pending": int(summary.get("program_synthesis_pending", 0) or 0),
        "program_synthesis_claimed": int(summary.get("program_synthesis_claimed", 0) or 0),
        "program_synthesis_completed": int(summary.get("program_synthesis_completed", 0) or 0),
        "program_synthesis_seeded": int(summary.get("program_synthesis_seeded", 0) or 0),
        "program_synthesis_preinsert_deduped": int(
            summary.get("program_synthesis_preinsert_deduped", 0) or 0
        ),
        "program_synthesis_semantic_deduped": int(
            summary.get("program_synthesis_semantic_deduped", 0) or 0
        ),
        "program_synthesis_deduped_total": int(
            summary.get("program_synthesis_deduped_total", 0) or 0
        ),
        "latest_program_synthesis_seeded_count": int(
            latest_todo_generation.get("seeded_count") or 0
        ),
        "latest_program_synthesis_preinsert_deduped_count": int(
            latest_todo_generation.get("preinsert_deduped_count") or 0
        ),
        "latest_program_synthesis_semantic_deduped_count": int(
            latest_todo_generation.get("semantic_deduped_count") or 0
        ),
        "latest_failed_validation_rescue_seeded_count": int(
            summary.get("latest_failed_validation_rescue_seeded_count")
            or latest_todo_generation.get("failed_validation_rescue_seeded_count")
            or latest_cycle.get("failed_validation_rescue_seeded_count")
            or 0
        ),
        "latest_failed_validation_rescue_deduped_count": int(
            summary.get("latest_failed_validation_rescue_deduped_count")
            or latest_todo_generation.get("failed_validation_rescue_deduped_count")
            or latest_cycle.get("failed_validation_rescue_deduped_count")
            or 0
        ),
        "latest_todo_generation": latest_todo_generation,
        "latest_queue_counts": summary.get("latest_queue_counts", {}),
        "latest_role_queue_counts": summary.get("latest_role_queue_counts", {}),
        "cycle_duration_median": (
            statistics.median(cycle_durations) if cycle_durations else None
        ),
        "cycle_duration_latest": cycle_durations[-1] if cycle_durations else None,
        "queue": _queue_stats(queue_path),
    }


def _recommendation(
    *,
    trials: list[dict[str, Any]],
    final: dict[str, Any],
    processes: dict[str, Any],
    gpu: dict[str, Any],
    production: bool,
) -> list[str]:
    counts = processes.get("counts", {})
    codex_count = int(counts.get("codex", 0) or 0)
    auto_count = int(counts.get("autoencoder", 0) or 0)
    lines: list[str] = []

    if trials and not final.get("summary_exists"):
        active_cycles = [int(item["cycles"]) for item in trials]
        zero_cycle = sum(1 for value in active_cycles if value == 0)
        lines.append(
            "Current phase looks like hyperparameter sweep: Codex workers should be 0."
        )
        if zero_cycle:
            lines.append(
                f"{zero_cycle}/{len(trials)} trials have not finished a first cycle yet; "
                "the sweep is autoencoder/data/bridge bound, not Codex bound."
            )
        lines.append(
            "For DGX Spark CUDA sweeps, start with 1 trial; try 2 only if GPU utilization "
            "stays below about 60% and memory headroom is large."
        )
    elif final.get("summary_exists"):
        queue = final.get("queue", {})
        pending = int(final.get("program_synthesis_pending", 0) or 0)
        claimed = int(final.get("program_synthesis_claimed", 0) or 0)
        completed = int(final.get("program_synthesis_completed", 0) or 0)
        latest_seeded = int(final.get("latest_program_synthesis_seeded_count", 0) or 0)
        latest_preinsert_deduped = int(
            final.get("latest_program_synthesis_preinsert_deduped_count", 0) or 0
        )
        plateau_streak = int(final.get("learning_rate_plateau_streak", 0) or 0)
        accepted_epochs = int(
            final.get("latest_feature_projection_accepted_epochs", 0) or 0
        )
        cycle_latest = final.get("cycle_duration_latest")
        if pending == 0 and claimed == 0:
            lines.append(
                "Final loop has no Codex backlog; extra Codex workers would idle. "
                "The autoencoder/TODO producer is the bottleneck."
            )
        elif pending > max(4, codex_count * 2):
            lines.append(
                "Queue backlog exceeds active Codex capacity; Codex/apply/validation is likely "
                "the bottleneck, so add Codex workers by hot scope."
            )
        elif claimed > pending and completed == 0:
            lines.append(
                "Many tasks are claimed but not completed; apply/validation or long Codex calls "
                "are likely the bottleneck."
            )
        else:
            lines.append(
                "Queue depth is roughly matched to Codex capacity; keep Codex workers demand-weighted."
            )
        if latest_seeded > 0 and latest_preinsert_deduped >= latest_seeded and pending <= max(5, codex_count):
            lines.append(
                "TODO producer is active, but visible backlog can stay flat because current-cycle "
                "dedupe plus Codex consumption is matching or exceeding seeding."
            )
        latest_ce_delta = _finite_float(final.get("latest_validation_ce_delta"), math.nan)
        if plateau_streak > 0 and math.isfinite(latest_ce_delta) and latest_ce_delta <= 0.0:
            lines.append(
                f"Validation CE is plateaued on the latest canary cycle "
                f"(delta={latest_ce_delta:.6g}, accepted_epochs={accepted_epochs})."
            )
        rejection_summary = final.get("latest_feature_projection_rejection_summary")
        if accepted_epochs == 0 and isinstance(rejection_summary, dict):
            regression_counts = rejection_summary.get("pareto_regression_counts")
            if isinstance(regression_counts, dict) and regression_counts:
                top_regressions = ", ".join(
                    f"{name}={count}"
                    for name, count in list(regression_counts.items())[:4]
                )
                lines.append(
                    "Projection guard rejected all feature updates; dominant "
                    f"regression guards: {top_regressions}."
                )
            best_rejected = rejection_summary.get("best_rejected_attempt")
            if isinstance(best_rejected, dict) and best_rejected:
                lines.append(
                    "Best rejected projection attempt: "
                    f"update={best_rejected.get('update', 'n/a')} "
                    f"lr={_finite_float(best_rejected.get('effective_learning_rate'), 0.0):.6g} "
                    f"objective_delta={_finite_float(best_rejected.get('objective_delta'), 0.0):.6g}."
                )
        guidance_applied = int(
            final.get("latest_compiler_ir_guided_applied_count", 0) or 0
        )
        guidance_requested = int(
            final.get("latest_compiler_ir_guided_requested_count", 0) or 0
        )
        guidance_produced = int(
            final.get("latest_compiler_ir_guided_produced_count", 0) or 0
        )
        guidance_failures = int(
            final.get("latest_compiler_ir_guided_failures", 0) or 0
        )
        guidance_ce_delta = _finite_float(
            final.get("latest_compiler_ir_guidance_ce_delta"),
            math.nan,
        )
        guidance_cosine_delta = _finite_float(
            final.get("latest_compiler_ir_guidance_cosine_delta"),
            math.nan,
        )
        if guidance_requested > 0 and guidance_applied == 0:
            lines.append(
                "Autoencoder guidance was requested but did not apply; inspect "
                f"produced={guidance_produced}, failures={guidance_failures}, "
                "and codec guidance-summary filtering before tuning guidance metrics."
            )
        if guidance_applied > 0:
            guidance_gate = str(
                final.get("latest_compiler_ir_guidance_quality_gate") or ""
            )
            if guidance_gate == "fail":
                lines.append(
                    "Autoencoder guidance quality gate is failing; keep guidance in canary "
                    "mode until CE/cosine/copy-hack deltas recover."
                )
            if (
                math.isfinite(guidance_ce_delta)
                and math.isfinite(guidance_cosine_delta)
                and guidance_ce_delta <= 0.0
                and guidance_cosine_delta <= 0.0
            ):
                lines.append(
                    "Autoencoder guidance is not yet improving deterministic compiler IR; "
                    "prioritize decompiler slot consumption and feature distillation."
                )
            elif (
                (math.isfinite(guidance_ce_delta) and guidance_ce_delta > 0.0)
                or (
                    math.isfinite(guidance_cosine_delta)
                    and guidance_cosine_delta > 0.0
                )
            ):
                lines.append(
                    "Autoencoder guidance is improving at least one compiler metric; "
                    "promote those guided slots into deterministic parser/decompiler rules."
                )
            promotion_allowed = bool(
                final.get("latest_compiler_ir_guidance_promotion_allowed")
            )
            promotion_reason = str(
                final.get("latest_compiler_ir_guidance_promotion_block_reason")
                or ""
            )
            if promotion_allowed:
                lines.append(
                    "Guidance promotion gate is open; use the distillation artifact as "
                    "the reviewed source for deterministic compiler/decompiler rules."
                )
                seeded = int(
                    final.get(
                        "latest_compiler_ir_guidance_distillation_seeded_count",
                        0,
                    )
                    or 0
                )
                if seeded > 0:
                    lines.append(
                        f"Guidance distillation seeded {seeded} Codex TODOs this cycle; "
                        "watch whether those scopes reduce guided CE/cosine residuals."
                    )
            elif promotion_reason and promotion_reason != "n/a":
                lines.append(
                    f"Guidance promotion remains blocked ({promotion_reason}); keep "
                    "learned slots in canary mode."
                )
            scope_hints = final.get("latest_compiler_ir_guidance_scope_hints")
            if isinstance(scope_hints, dict) and scope_hints.get("scope_counts"):
                hot_guidance = ", ".join(
                    f"{scope}={count}"
                    for scope, count in scope_hints["scope_counts"].items()
                )
                lines.append(
                    f"Learned guidance is pointing at Codex scopes: {hot_guidance}. "
                    "Rebalance scoped workers there when queue hot scopes agree."
                )
        if isinstance(cycle_latest, (float, int)) and cycle_latest > 600:
            lines.append(
                f"Latest autoencoder cycle is long ({cycle_latest:.1f}s); optimize bridge/prover/data "
                "parallelism before adding more final trainers."
            )
        if queue.get("pending_by_scope"):
            hot = ", ".join(
                f"{scope}={count}" for scope, count in queue["pending_by_scope"].items()
            )
            lines.append(f"Hot pending scopes: {hot}.")
        failed_count = int(queue.get("status_counts", {}).get("failed_validation", 0) or 0)
        if failed_count > 0:
            failed_scopes = queue.get("failed_by_scope", {})
            hot_failed = ", ".join(
                f"{scope}={count}" for scope, count in failed_scopes.items()
            )
            suffix = f" Hot failed scopes: {hot_failed}." if hot_failed else ""
            rescue_seeded = int(
                final.get("latest_failed_validation_rescue_seeded_count", 0) or 0
            )
            rescue_deduped = int(
                final.get("latest_failed_validation_rescue_deduped_count", 0) or 0
            )
            lines.append(
                f"{failed_count} failed-validation TODOs need rescue or retirement before "
                f"worker utilization stats are trustworthy.{suffix}"
            )
            if rescue_seeded > 0:
                lines.append(
                    f"Failed-validation rescue seeded {rescue_seeded} repair TODOs "
                    "this cycle; route Codex workers to those scopes before adding "
                    "more generic workers."
                )
            elif rescue_deduped > 0:
                lines.append(
                    "Failed-validation rescue is merging new failed evidence into "
                    "existing repair TODOs; prioritize completing those rescue tasks."
                )

    if production:
        lines.append(
            "Production writer recommendation: keep 1 canonical autoencoder trainer; scale "
            "bridge workers and Codex consumers around it."
        )
        lines.append(
            "DGX Spark starting point: final autoencoder=1, final bridge workers=8, "
            "Codex workers=14 demand-weighted."
        )

    if gpu.get("available"):
        utils = [float(item.get("gpu_util_percent", 0.0)) for item in gpu.get("gpus", [])]
        if utils and max(utils) < 50.0 and auto_count <= 1:
            lines.append(
                "GPU utilization is low; prefer larger batches/more bridge workers or a second "
                "isolated sweep trial before adding another production trainer."
            )
    else:
        lines.append("No nvidia-smi GPU telemetry available in this environment.")

    return lines


def _print_report(report: dict[str, Any]) -> None:
    print(f"Run: {report['run_id']}")
    print(f"Phase: {report['phase']}")
    print(f"Process counts: {report['processes']['counts']}")
    print(f"CPU by role: {report['processes']['cpu_percent']}")
    print()
    if report["trials"]:
        print("Sweep trials:")
        for trial in report["trials"]:
            age = trial["age_seconds"]
            age_text = "n/a" if age is None else f"{age:.0f}s"
            latest = trial["cycle_duration_latest"]
            latest_text = "n/a" if latest is None else f"{latest:.1f}s"
            print(
                f"- {trial['run_id']}: cycles={trial['cycles']} "
                f"bridge_workers={trial['bridge_workers']} latest_cycle={latest_text} "
                f"best_ce={_summary_metric(trial, 'best_validation_ce')} "
                f"best_cos={_summary_metric(trial, 'best_validation_cosine')} "
                f"best_ir_ce={_summary_metric(trial, 'best_validation_ir_ce')} "
                f"best_ir_cos={_summary_metric(trial, 'best_validation_ir_cosine')} "
                f"summary_age={age_text}"
            )
        print()
    final = report["final"]
    if final.get("summary_exists"):
        print("Final autoencoder:")
        latest = final["cycle_duration_latest"]
        latest_text = "n/a" if latest is None else f"{latest:.1f}s"
        print(
            f"- {final['run_id']}: cycles={final['cycles']} "
            f"bridge_workers={final['bridge_workers']} latest_cycle={latest_text} "
            f"pending={final['program_synthesis_pending']} "
            f"claimed={final['program_synthesis_claimed']} "
            f"completed={final['program_synthesis_completed']}"
        )
        print(
            "  autoencoder_validation="
            f"best_ce={_summary_metric(final, 'best_validation_ce')} "
            f"latest_ce={_summary_metric(final, 'latest_validation_ce')} "
            f"latest_ce_excess={_summary_metric(final, 'latest_validation_ce_excess')} "
            f"ce_delta={_summary_metric(final, 'latest_validation_ce_delta')} "
            f"best_cos={_summary_metric(final, 'best_validation_cosine')} "
            f"latest_cos={_summary_metric(final, 'latest_validation_cosine')} "
            f"cos_delta={_summary_metric(final, 'latest_validation_cosine_delta')}"
        )
        print(
            "  deterministic_compiler_ir="
            f"best_ce={_summary_metric(final, 'best_validation_ir_ce')} "
            f"latest_ce={_summary_metric(final, 'latest_compiler_ir_ce')} "
            f"latest_ce_excess={_summary_metric(final, 'latest_compiler_ir_ce_excess')} "
            f"best_cos={_summary_metric(final, 'best_validation_ir_cosine')} "
            f"latest_cos={_summary_metric(final, 'latest_compiler_ir_cosine')} "
            f"source_copy_loss={_summary_metric(final, 'latest_compiler_ir_source_copy_loss')} "
            "copy_hack_penalty="
            f"{_summary_metric(final, 'latest_compiler_ir_source_copy_reward_hack_penalty')}"
        )
        print(
            "  guided_compiler_ir="
            f"requested={final['latest_compiler_ir_guided_requested_count']} "
            f"produced={final['latest_compiler_ir_guided_produced_count']} "
            f"applied={final['latest_compiler_ir_guided_applied_count']} "
            f"empty={final['latest_compiler_ir_guided_empty_count']} "
            f"failures={final['latest_compiler_ir_guided_failures']} "
            f"unapplied={final['latest_compiler_ir_guided_unapplied_count']} "
            f"best_ce={_summary_metric(final, 'best_validation_ir_guided_ce')} "
            f"latest_ce={_summary_metric(final, 'latest_compiler_ir_guided_ce')} "
            "best_ce_excess="
            f"{_summary_metric(final, 'best_validation_ir_guided_ce_excess')} "
            f"latest_ce_excess={_summary_metric(final, 'latest_compiler_ir_guided_ce_excess')} "
            f"best_cos={_summary_metric(final, 'best_validation_ir_guided_cosine')} "
            f"latest_cos={_summary_metric(final, 'latest_compiler_ir_guided_cosine')} "
            f"copy_hack_penalty={_summary_metric(final, 'latest_compiler_ir_guided_copy_hack_penalty')} "
            f"ce_delta={_summary_metric(final, 'latest_compiler_ir_guidance_ce_delta')} "
            f"cos_delta={_summary_metric(final, 'latest_compiler_ir_guidance_cosine_delta')} "
            f"copy_hack_delta={_summary_metric(final, 'latest_compiler_ir_guidance_copy_hack_delta')} "
            f"quality_gate={final['latest_compiler_ir_guidance_quality_gate']} "
            "promotion="
            f"{'allowed' if final['latest_compiler_ir_guidance_promotion_allowed'] else 'blocked'} "
            "promotion_reason="
            f"{final['latest_compiler_ir_guidance_promotion_block_reason']} "
            "distill_seeded="
            f"{final['latest_compiler_ir_guidance_distillation_seeded_count']} "
            "distill_deduped="
            f"{final['latest_compiler_ir_guidance_distillation_deduped_count']} "
            "guidance_family_ce_excess="
            f"{_summary_metric(final, 'latest_compiler_ir_guided_family_ce_excess')} "
            f"frame_boosts={_summary_metric(final, 'latest_compiler_ir_guided_frame_boost_count')} "
            f"frame_changes={final['latest_compiler_ir_guided_frame_changed_count']}"
        )
        if final["latest_compiler_ir_guidance_surface_features"]:
            print(
                "  guidance_surface_features="
                f"{final['latest_compiler_ir_guidance_surface_features']}"
            )
        if final["latest_compiler_ir_guidance_todo_routes"]:
            print(
                "  guidance_todo_routes="
                f"{final['latest_compiler_ir_guidance_todo_routes']}"
            )
        scope_hints = final.get("latest_compiler_ir_guidance_scope_hints")
        if isinstance(scope_hints, dict) and scope_hints.get("scope_counts"):
            print(f"  guidance_scope_hints={scope_hints['scope_counts']}")
        distillation_path = final.get(
            "latest_compiler_ir_guidance_distillation_path"
        )
        if distillation_path:
            print(f"  guidance_distillation_artifact={distillation_path}")
        print(
            "  learned_ir_view="
            f"best_ce={_summary_metric(final, 'best_validation_learned_ir_view_ce')} "
            f"latest_ce={_summary_metric(final, 'latest_learned_ir_view_ce')} "
            f"latest_ce_excess={_summary_metric(final, 'latest_learned_ir_view_ce_excess')} "
            f"best_cos={_summary_metric(final, 'best_validation_learned_ir_view_cosine')} "
            f"latest_cos={_summary_metric(final, 'latest_learned_ir_view_cosine')}"
        )
        print(
            "  todo_generation="
            f"latest_seeded={final['latest_program_synthesis_seeded_count']} "
            f"latest_preinsert_deduped={final['latest_program_synthesis_preinsert_deduped_count']} "
            f"latest_semantic_deduped={final['latest_program_synthesis_semantic_deduped_count']} "
            "failed_rescue_seeded="
            f"{final['latest_failed_validation_rescue_seeded_count']} "
            "failed_rescue_deduped="
            f"{final['latest_failed_validation_rescue_deduped_count']} "
            f"total_seeded={final['program_synthesis_seeded']} "
            f"total_deduped={final['program_synthesis_deduped_total']} "
            f"accepted_epochs={final['latest_feature_projection_accepted_epochs']} "
            f"plateau_streak={final['learning_rate_plateau_streak']}"
        )
        rejection_summary = final.get("latest_feature_projection_rejection_summary")
        if isinstance(rejection_summary, dict) and rejection_summary.get(
            "attempted_count"
        ):
            print(
                "  projection_rejections="
                f"attempted={rejection_summary.get('attempted_count', 0)} "
                f"accepted_attempts={rejection_summary.get('accepted_attempt_count', 0)} "
                f"rejected={rejection_summary.get('rejected_attempt_count', 0)} "
                f"pareto={rejection_summary.get('pareto_regression_counts', {})} "
                f"best_rejected={rejection_summary.get('best_rejected_attempt', {})}"
            )
        print(f"  queue_status={final['queue']['status_counts']}")
        print(f"  pending_by_scope={final['queue']['pending_by_scope']}")
        if final["queue"].get("failed_by_scope"):
            print(f"  failed_by_scope={final['queue']['failed_by_scope']}")
        if final["queue"].get("failed_by_action"):
            print(f"  failed_by_action={final['queue']['failed_by_action']}")
        if final["queue"].get("failed_by_reason"):
            print(f"  failed_by_reason={final['queue']['failed_by_reason']}")
        print()
    gpu = report["gpu"]
    if gpu.get("available"):
        print("GPU:")
        for item in gpu.get("gpus", []):
            print(
                f"- GPU {item['index']} {item['name']}: util={item['gpu_util_percent']}% "
                f"mem={item['memory_used_mib']}/{item['memory_total_mib']} MiB"
            )
        print()
    print("Recommendation:")
    for line in report["recommendation"]:
        print(f"- {line}")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    log_dir = root / "workspace" / "test-logs"
    queue_dir = root / "workspace" / "todo-queues"
    trials = _trial_reports(log_dir, args.run_id)
    final = _final_report(log_dir, queue_dir, args.run_id)
    processes = _process_snapshot(args.run_id)
    gpu = _nvidia_smi_snapshot()
    phase = "final" if final.get("summary_exists") else ("sweep" if trials else "unknown")
    report = {
        "run_id": args.run_id,
        "phase": phase,
        "trials": trials,
        "final": final,
        "processes": {
            "counts": processes["counts"],
            "cpu_percent": processes["cpu_percent"],
        },
        "gpu": gpu,
    }
    report["recommendation"] = _recommendation(
        trials=trials,
        final=final,
        processes=processes,
        gpu=gpu,
        production=bool(args.production),
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="Base run id, e.g. legal-ir-hparam8h-restart6-...")
    parser.add_argument(
        "--root",
        default=os.getcwd(),
        help="Repository root containing workspace/test-logs and workspace/todo-queues.",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Include production DGX Spark worker recommendations.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args(argv)
    report = build_report(args)
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
