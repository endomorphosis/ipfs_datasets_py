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
from typing import Any


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
    total = 0
    for event in _iter_jsonl(path):
        total += 1
        status = str(event.get("status") or "missing")
        role = str(event.get("optimizer_role") or event.get("role") or "missing")
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        scope = str(metadata.get("program_synthesis_scope") or "missing")
        status_counts[status] += 1
        role_counts[role] += 1
        scope_counts[scope] += 1
        if status == "pending":
            pending_by_scope[scope] += 1
        elif status == "claimed":
            claimed_by_scope[scope] += 1
    return {
        "path": str(path),
        "exists": path.exists(),
        "total": total,
        "status_counts": dict(status_counts),
        "role_counts": dict(role_counts),
        "scope_counts": dict(scope_counts.most_common(12)),
        "pending_by_scope": dict(pending_by_scope.most_common(12)),
        "claimed_by_scope": dict(claimed_by_scope.most_common(12)),
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
    events = _iter_jsonl(log_dir / f"{final_run_id}-autoencoder.jsonl")
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
        "program_synthesis_pending": int(summary.get("program_synthesis_pending", 0) or 0),
        "program_synthesis_claimed": int(summary.get("program_synthesis_claimed", 0) or 0),
        "program_synthesis_completed": int(summary.get("program_synthesis_completed", 0) or 0),
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
        print(f"  queue_status={final['queue']['status_counts']}")
        print(f"  pending_by_scope={final['queue']['pending_by_scope']}")
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
