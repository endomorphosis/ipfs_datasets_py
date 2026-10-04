"""Bounded CPU-bearing native SMT trials through the shared supervisor owner.

Measure target preparation separately from execution. No historical observation
or model cache bypasses Z3/CVC5; every task checks the deterministic odd-charge
Tseitin fixture with both installed native solvers under default pressure policy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time

DATASETS = Path(__file__).resolve().parents[1]
ACCELERATE = DATASETS.parent / "ipfs_accelerate"
sys.path[:0] = [str(ACCELERATE), str(DATASETS)]

from shared_prover_workloads import tseitin_target
from ipfs_accelerate_py.agent_supervisor.proof.datasets_hammer_tasks import make_datasets_smt_task
from ipfs_accelerate_py.agent_supervisor.proof.datasets_prover_resources import open_datasets_prover_lease
from ipfs_accelerate_py.agent_supervisor.proof.multi_prover_resources import BundleProverSupervisor, MultiProverResourceBudget
from ipfs_datasets_py.logic.hammers import portfolio
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def trial(round_number, width, count, vertices):
    prepared_at = time.perf_counter()
    jobs = [make_datasets_smt_task(target=tseitin_target(f"tseitin-{n}", vertices=vertices),
        expected_verdict="unsat", timeout_seconds=45) for n in range(count)]
    preparation_seconds = time.perf_counter() - prepared_at
    scheduler = get_global_resource_scheduler()
    native_owner = portfolio.get_process_supervisor()
    native = native_owner.run
    original_fsync = os.fsync
    lock, stop = threading.Lock(), threading.Event()
    active = peak = calls = fsync_calls = 0
    fsync_seconds = 0.0
    maximum_roots = maximum_cpu = maximum_memory = 0
    errors = []

    def measured(command, **kwargs):
        nonlocal active, peak, calls
        if any(flag in command for flag in ("--version", "-version")):
            return native(command, **kwargs)
        with lock:
            active += 1
            calls += 1
            peak = max(peak, active)
        try:
            return native(command, **kwargs)
        finally:
            with lock:
                active -= 1

    def measured_fsync(fd):
        nonlocal fsync_calls, fsync_seconds
        started = time.perf_counter()
        try:
            return original_fsync(fd)
        finally:
            with lock:
                fsync_calls += 1
                fsync_seconds += time.perf_counter() - started

    def monitor():
        nonlocal maximum_roots, maximum_cpu, maximum_memory
        try:
            while not stop.is_set():
                roots = [row for row in scheduler.active_leases()
                         if row["owner_pid"] == os.getpid() and not row.get("parent_lease_id")]
                maximum_roots = max(maximum_roots, len(roots))
                maximum_cpu = max(maximum_cpu, sum(row["cpu_slots"] for row in roots))
                maximum_memory = max(maximum_memory, sum(row["memory_mb"] for row in roots))
                stop.wait(.05)
        except BaseException as error:
            errors.append(repr(error))

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    started = time.perf_counter()
    native_owner.run, os.fsync = measured, measured_fsync
    try:
        with open_datasets_prover_lease(budget=MultiProverResourceBudget(cpu_slots=width,
                thread_slots=width, process_slots=width, max_portfolio_width=width,
                memory_bytes=width * 512 * 1024**2), timeout_seconds=180) as owner:
            monitor_thread.start()
            receipt = BundleProverSupervisor(owner).execute(jobs)
        execution_seconds = time.perf_counter() - started
    finally:
        stop.set()
        if monitor_thread.ident is not None:
            monitor_thread.join(3)
        native_owner.run, os.fsync = native, original_fsync
    require(not errors and not monitor_thread.is_alive(), "accounting monitor failed")
    require(len(receipt.successful_task_ids) == count, "native task failed or was refused")
    require(calls == 2 * count and not active and 1 <= peak <= width, "native lifecycle bounds failed")
    require(width == 1 or peak > 1, "no parallel native work observed")
    require(maximum_roots == 1 and maximum_cpu == width and maximum_memory == width * 512,
            "shared root ownership mismatch")
    require(not any(row["owner_pid"] == os.getpid() for row in scheduler.active_leases()), "owned lease leak")
    for row in receipt.receipts:
        require(not row.cache_bypassed_execution and len(row.result["attempts"]) == 2,
                "missing or execution-bypassed observation")
        require(row.result["all_expected_verdicts_observed"] and not row.result["proof_authority"],
                "unexpected semantic authority or verdict")
    print(f"round={round_number} width={width} prepare={preparation_seconds:.3f} "
          f"execute={execution_seconds:.3f} peak={peak}", file=sys.stderr)
    return {"round": round_number, "workers": width, "tasks": count,
        "preparation_seconds": preparation_seconds, "execution_seconds": execution_seconds,
        "total_seconds": preparation_seconds + execution_seconds,
        "peak_native_lifecycle_calls": peak, "solver_checks": calls,
        "parent_python_fsync_calls": fsync_calls, "parent_python_fsync_seconds": fsync_seconds,
        "maximum_owned_roots": maximum_roots, "maximum_owned_cpu_slots": maximum_cpu,
        "maximum_owned_memory_mb": maximum_memory, "receipt": receipt.to_dict(), "correctness_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--tasks", type=int, choices=(4, 8), default=8)
    parser.add_argument("--vertices", type=int, choices=(48, 64), default=64)
    args = parser.parse_args()
    scheduler = get_global_resource_scheduler()
    require(scheduler.config.proof_safety_enabled, "default safety disabled")
    # Rotate width order to reduce a fixed cold-start/order advantage.
    orders = ((1, 2, 4), (4, 1, 2), (2, 4, 1))
    trials = [trial(number + 1, width, args.tasks, args.vertices)
              for number in range(args.rounds) for width in orders[number]]
    baseline = statistics.median(row["execution_seconds"] for row in trials if row["workers"] == 1)
    summary = {}
    for width in (1, 2, 4):
        selected = [row for row in trials if row["workers"] == width]
        seconds = statistics.median(row["execution_seconds"] for row in selected)
        summary[str(width)] = {"median_execution_seconds": seconds,
            "median_preparation_seconds": statistics.median(row["preparation_seconds"] for row in selected),
            "median_total_seconds": statistics.median(row["total_seconds"] for row in selected),
            "execution_relative_speedup": baseline / seconds, "tasks_per_second": args.tasks / seconds,
            "peak_native_lifecycle_calls": [row["peak_native_lifecycle_calls"] for row in selected]}
    sources = {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name in ("shared_prover_workloads", "ipfs_accelerate_py.agent_supervisor.proof.datasets_hammer_tasks",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_prover_resources",
        "ipfs_accelerate_py.agent_supervisor.proof.multi_prover_resources",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler",
        "ipfs_datasets_py.logic.hammers.portfolio", "ipfs_datasets_py.logic.hammers.process_lifecycle",
        "ipfs_datasets_py.logic.hammers.semantic_routing"):
        path = Path(sys.modules[name].__file__).resolve()
        require(path.is_relative_to(DATASETS) or path.is_relative_to(ACCELERATE), "wrong installed implementation")
        sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {"schema": "shared-prover-scaling-benchmark@1", "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": {"rounds": args.rounds, "workers": [1, 2, 4], "tasks_per_trial": args.tasks,
            "workload": "odd-charge-tseitin-cnf", "vertices": args.vertices, "seed": 1729 + args.vertices,
            "native_memory_mb": 256, "task_timeout_seconds": 45, "monitor_interval_seconds": .05,
            "default_safety_enabled": True, "native_solvers": ["z3", "cvc5"], "expected_verdict": "unsat",
            "proof_authority": False, "source_semantics_verified": False},
        "summary": summary, "trials": trials, "sources": sources, "correctness_passed": True,
        "measurement_limits": ["Native lifecycle overlap includes process monitoring and cleanup, not measured CPU occupancy.",
            "Per-attempt CPU/RSS fields originate from process-global child usage deltas and are not summed as independent usage.",
            "Parent fsync durations can overlap other work; they are not a partition of wall time.",
            "Preparation and execution are both timed; execution includes checked target replay and live admission."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"correctness_passed": True, "summary": summary}))


if __name__ == "__main__":
    main()
