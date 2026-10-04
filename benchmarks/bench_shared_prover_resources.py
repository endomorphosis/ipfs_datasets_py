"""Native 1/2/4-worker supervisor/SMT benchmark under the shared safe owner.

The fixture checks authored propositional assertions. Measurements establish
bounded execution/accounting and report observed throughput; no source proof,
mixed-family composition or general many-core scaling claim is made.
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

from ipfs_accelerate_py.agent_supervisor.proof.datasets_hammer_tasks import make_datasets_smt_task
from ipfs_accelerate_py.agent_supervisor.proof.datasets_prover_resources import open_datasets_prover_lease
from ipfs_accelerate_py.agent_supervisor.proof.multi_prover_resources import (
    BundleProverSupervisor, MultiProverResourceBudget,
)
from ipfs_datasets_py.logic.hammers import portfolio, semantic_routing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler


def require(value, message):
    if not value:
        raise RuntimeError(message)


def fixture_task(number, *, dependencies=()):
    text = "p and not p" if number % 2 == 0 else "p or q"
    parsed = semantic_routing.modal.parse_modal(text, semantic_routing.modal.profile_k())
    require(parsed.ok, "native fixture parse failed")
    replay = semantic_routing.modal.parse_modal(parsed.printed, semantic_routing.modal.profile_k())
    target = dict(request_id=f"observation-{number}", source_construct="authored-propositional-fixture",
        logic_family="propositional", ast_format="shared_logic", printed=parsed.printed,
        native_ast=replay.root.to_dict(), solver_names=("z3", "cvc5"))
    return make_datasets_smt_task(target=target, expected_verdict="unsat" if number % 2 == 0 else "sat",
        dependencies=dependencies, timeout_seconds=45)


def trial(number, width):
    scheduler = get_global_resource_scheduler()
    tasks = [fixture_task(n) for n in range(8)]
    tasks.extend(fixture_task(n, dependencies=tuple(task.task_id for task in tasks[:8])) for n in (8, 9))
    active = peak = calls = max_owned_roots = max_owned_cpu = max_owned_memory = 0
    guard = threading.Lock()
    stop = threading.Event()
    errors = []
    supervisor = portfolio.get_process_supervisor()
    native = supervisor.run

    def measured(*args, **kwargs):
        nonlocal active, peak, calls
        if any(flag in args[0] for flag in ("--version", "-version")):
            return native(*args, **kwargs)
        with guard:
            active += 1
            peak = max(peak, active)
            calls += 1
        try:
            return native(*args, **kwargs)
        finally:
            with guard:
                active -= 1

    def observe():
        nonlocal max_owned_roots, max_owned_cpu, max_owned_memory
        try:
            while not stop.is_set():
                roots = [row for row in scheduler.active_leases()
                    if row["owner_pid"] == os.getpid() and not row.get("parent_lease_id")]
                max_owned_roots = max(max_owned_roots, len(roots))
                max_owned_cpu = max(max_owned_cpu, sum(row["cpu_slots"] for row in roots))
                max_owned_memory = max(max_owned_memory, sum(row["memory_mb"] for row in roots))
                stop.wait(.01)
        except BaseException as error:
            errors.append(str(error))

    monitor = threading.Thread(target=observe, daemon=True)
    supervisor.run = measured
    started = time.perf_counter()
    try:
        with open_datasets_prover_lease(budget=MultiProverResourceBudget(cpu_slots=width,
                process_slots=width, thread_slots=width, max_portfolio_width=width,
                memory_bytes=width * 512 * 1024**2), timeout_seconds=120) as lease:
            monitor.start()
            receipt = BundleProverSupervisor(lease).execute(tasks)
        elapsed = time.perf_counter() - started
    finally:
        stop.set()
        if monitor.ident is not None:
            monitor.join(3)
        supervisor.run = native
    require(not errors and not monitor.is_alive(), "accounting monitor failed")
    require(len(receipt.successful_task_ids) == 10, "native task failed or was rejected")
    require(calls == 20 and active == 0 and peak <= width, "native bounded lifecycle mismatch")
    require(width == 1 or peak >= 2, "parallel native calls did not overlap")
    require(max_owned_roots == 1 and max_owned_cpu == width and max_owned_memory == width * 512,
        "shared envelope was missing, duplicated or overcommitted")
    require(not any(row["owner_pid"] == os.getpid() for row in scheduler.active_leases()), "owned lease leak")
    require(all(not row.cache_bypassed_execution for row in receipt.receipts), "unexpected execution bypass")
    for row in receipt.receipts:
        require(len(row.result["attempts"]) == 2 and row.result["all_expected_verdicts_observed"],
            "incomplete solver observation ledger")
    print(f"round={number} workers={width} seconds={elapsed:.3f} native_peak={peak}", file=sys.stderr)
    return {"round": number, "workers": width, "wall_seconds": elapsed,
        "tasks_per_second": 10 / elapsed, "solver_checks": calls,
        "peak_native_solver_lifecycle_calls": peak, "max_owned_roots": max_owned_roots,
        "max_owned_reserved_cpu": max_owned_cpu, "max_owned_reserved_memory_mb": max_owned_memory,
        "receipt": receipt.to_dict(), "correctness_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    scheduler = get_global_resource_scheduler()
    require(scheduler.config.proof_safety_enabled, "default proof resource safety must be enabled")
    trials = [trial(number, width) for number in range(1, args.rounds + 1) for width in (1, 2, 4)]
    baseline = statistics.median(row["wall_seconds"] for row in trials if row["workers"] == 1)
    summary = {}
    for width in (1, 2, 4):
        selected = [row for row in trials if row["workers"] == width]
        seconds = statistics.median(row["wall_seconds"] for row in selected)
        summary[str(width)] = {"median_wall_seconds": seconds, "tasks_per_second": 10 / seconds,
            "relative_speedup": baseline / seconds,
            "peak_native_lifecycle_calls": [row["peak_native_solver_lifecycle_calls"] for row in selected]}
    sources = [Path(__file__).resolve()]
    for name in (
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_hammer_tasks",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_prover_resources",
        "ipfs_accelerate_py.agent_supervisor.proof.multi_prover_resources",
        "ipfs_datasets_py.logic.hammers.semantic_routing",
        "ipfs_datasets_py.logic.hammers.portfolio",
        "ipfs_datasets_py.logic.hammers.process_lifecycle",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler",
    ):
        sources.append(Path(sys.modules[name].__file__).resolve())
    payload = {"schema": "shared-prover-resources-benchmark@1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
        "correctness_passed": True, "default_proof_safety_enabled": True,
        "configuration": {"rounds": args.rounds, "tasks_per_trial": 10, "solvers": ["z3", "cvc5"],
            "independent_tasks": 8, "dependent_tasks": 2, "per_solver_memory_mb": 256,
            "solver_parallelism_per_task": 1, "source_semantics_verified": False,
            "kernel_proof_verified": False, "host_exhaustion_induced": False},
        "summary": summary, "trials": trials, "scheduler_after": scheduler.snapshot(),
        "sources": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"correctness_passed": True, "summary": summary}, sort_keys=True))


if __name__ == "__main__":
    main()
