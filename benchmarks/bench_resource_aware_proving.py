"""Bounded real-solver throughput and admission-backoff benchmark.

Run with PYTHONPATH=. python benchmarks/bench_resource_aware_proving.py --out DIR.
SAT/UNSAT checks are solver outcomes, not kernel-verified theorem counts.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import platform
import statistics
import shutil
import threading
import time

import psutil

from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy, TranslationRecord, TranslationStatus, TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy
from ipfs_datasets_py.logic.hammers.portfolio import (
    PortfolioAttemptSpec, SolverPortfolio, run_bounded_solver_process,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig, get_global_resource_scheduler,
)


def pigeonhole(job: int) -> tuple[TranslationRecord, str]:
    """Alternate satisfiable bijections and impossible pigeonhole placements."""
    holes = 5
    pigeons = holes + job % 2
    lines = ["(set-logic QF_UF)"]
    for p in range(pigeons):
        for h in range(holes):
            lines.append(f"(declare-fun p{p}h{h} () Bool)")
        lines.append("(assert (or " + " ".join(f"p{p}h{h}" for h in range(holes)) + "))")
    for h in range(holes):
        for p in range(pigeons):
            for q in range(p):
                lines.append(f"(assert (not (and p{p}h{h} p{q}h{h})))")
    return TranslationRecord(
        translation_id=f"pigeonhole-{job}", request_id=f"job-{job}",
        target=TranslationTarget.SMTLIB, status=TranslationStatus.SUPPORTED,
        source_construct="generated_boolean_pigeonhole", translated_text="\n".join(lines),
    ), "unsat" if job % 2 else "sat"


def run_trial(scheduler, solvers, workers: int, jobs: int) -> dict:
    policy = PortfolioPolicy(
        hammer_policy=HammerPolicy(allowed_solvers=solvers, timeout_seconds=3, memory_mb=256),
        max_parallel_processes=len(solvers), cancel_on_first_conclusive=False,
    )
    portfolio = SolverPortfolio(policy, resource_scheduler=scheduler, resource_wait_timeout_seconds=10)
    # Warm version probes and executable discovery outside the timed region.
    translation, _ = pigeonhole(0)
    warmup = portfolio.run("warmup", [PortfolioAttemptSpec(translation=translation, solver_name=s) for s in solvers])
    samples = []
    stop = threading.Event()
    process = psutil.Process()
    def monitor():
        while not stop.is_set():
            snapshot = scheduler.snapshot()
            children = process.children(recursive=True)
            rss = process.memory_info().rss
            for child in children:
                try:
                    rss += child.memory_info().rss
                except psutil.Error:
                    pass
            samples.append((snapshot["allocated"]["cpu_slots"], snapshot["allocated"]["memory_mb"], rss))
            stop.wait(0.05)
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    def execute(job):
        translation, expected = pigeonhole(job)
        started = time.perf_counter()
        result = portfolio.run(f"job-{job}", [PortfolioAttemptSpec(translation=translation, solver_name=s) for s in solvers])
        verdicts = [record.verdict.value for record in result.attempts]
        if result.denied or len(verdicts) != len(solvers) or any(v != expected for v in verdicts):
            raise AssertionError(f"job {job}: expected {expected}, got {verdicts}, denied={result.denied}")
        return {"latency_seconds": time.perf_counter() - started, "expected": expected,
                "solver_seconds": [record.wall_time_seconds for record in result.attempts]}
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(execute, range(jobs)))
        elapsed = time.perf_counter() - started
    finally:
        stop.set()
        thread.join(2)
    final = scheduler.snapshot()
    if final["active_lease_count"] or final["waiting_request_count"]:
        raise AssertionError("resource leases or waiters leaked")
    return {"workers": workers, "jobs": jobs, "solver_checks": jobs * len(solvers),
            "wall_seconds": elapsed, "jobs_per_second": jobs / elapsed,
            "median_job_seconds": statistics.median(r["latency_seconds"] for r in results),
            "max_job_seconds": max(r["latency_seconds"] for r in results),
            "peak_reserved_cpu_slots": max((s[0] for s in samples), default=0),
            "peak_reserved_memory_mb": max((s[1] for s in samples), default=0),
            "sampled_peak_process_tree_rss_mb": max((s[2] for s in samples), default=0) / 1024**2,
            "sample_interval_seconds": 0.05, "results": results, "leases_remaining": 0,
            "solver_versions": {record.solver_name: record.solver_version for record in warmup.attempts}}


def run_pressure_probe(path: Path, solver: str, pressure: str) -> dict:
    """Inject external pressure readings, then execute an actual solver."""
    active = threading.Event()
    launches = []
    def sample():
        host = collect_proof_host_resources()
        if active.is_set():
            if pressure == "memory":
                return replace(host, available_memory_mb=0)
            return replace(host, **{f"{pressure}_stall_percent": 100.0})
        return host
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=path, proof_resource_sampler=sample,
    ))
    policy = PortfolioPolicy(hammer_policy=HammerPolicy(allowed_solvers=[solver], timeout_seconds=3, memory_mb=256))
    def runner(*args, **kwargs):
        launches.append(time.perf_counter())
        return run_bounded_solver_process(*args, **kwargs)
    portfolio = SolverPortfolio(policy, resource_scheduler=scheduler, process_runner=runner,
                                resource_wait_timeout_seconds=10)
    active.set()
    started = time.perf_counter()
    translation, expected = pigeonhole(0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(portfolio.run, "pressure", [PortfolioAttemptSpec(translation=translation, solver_name=solver)])
        deadline = time.monotonic() + 3
        while not scheduler.snapshot()["proof_backoff"] and time.monotonic() < deadline:
            time.sleep(0.01)
        backoff = scheduler.snapshot()["proof_backoff"]
        if not backoff or launches:
            active.clear()
            raise AssertionError("pressure did not prevent solver launch")
        cleared = time.perf_counter()
        active.clear()
        result = future.result(timeout=10)
    if result.attempts[0].verdict.value != expected or not launches:
        raise AssertionError("solver did not recover after pressure cleared")
    recovered_after = launches[0] - cleared
    if recovered_after < scheduler.config.proof_backoff_seconds - 0.1:
        raise AssertionError("solver launched before cooldown elapsed")
    snapshot = scheduler.snapshot()
    if snapshot["active_lease_count"] or snapshot["waiting_request_count"]:
        raise AssertionError("pressure probe leaked resources")
    return {"pressure": pressure, "pressure_source": "injected telemetry; real solver subprocess",
            "backoff_reason": backoff["reason"], "cooldown_seconds": scheduler.config.proof_backoff_seconds,
            "recovery_after_clear_seconds": recovered_after, "elapsed_seconds": time.perf_counter() - started,
            "launches_during_pressure": 0, "verdict": expected, "leases_remaining": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 2 <= args.jobs <= 32 or not 1 <= args.repeats <= 5:
        parser.error("bounded run requires 2..32 jobs and 1..5 repeats")
    args.out.mkdir(parents=True, exist_ok=True)
    state = args.out / "scheduler.json"
    os.environ["IPFS_DATASETS_RESOURCE_SCHEDULER_PATH"] = str(state.resolve())
    os.environ.pop("IPFS_DATASETS_PROOF_RESOURCE_SAFETY", None)
    scheduler = get_global_resource_scheduler()
    solvers = [s for s in ("z3", "cvc5") if shutil.which(s)]
    if not solvers:
        parser.error("requires at least one installed Z3 or CVC5 executable")
    host = collect_proof_host_resources()
    trials = []
    # Rotate order to reduce the bias of always timing serial execution first.
    for repeat in range(args.repeats):
        for width in ([1, 2, 4][repeat % 3:] + [1, 2, 4][:repeat % 3]):
            trial = run_trial(scheduler, solvers, width, args.jobs)
            trial["repeat"] = repeat
            trials.append(trial)
            print(json.dumps({k: v for k, v in trial.items() if k != "results"}), flush=True)
    summary = []
    serial = statistics.median(t["jobs_per_second"] for t in trials if t["workers"] == 1)
    for width in (1, 2, 4):
        rows = [t for t in trials if t["workers"] == width]
        throughput = statistics.median(t["jobs_per_second"] for t in rows)
        summary.append({"workers": width, "median_jobs_per_second": throughput,
                        "speedup_over_serial": throughput / serial,
                        "peak_rss_mb": max(t["sampled_peak_process_tree_rss_mb"] for t in rows)})
    pressures = [run_pressure_probe(args.out / f"{kind}-pressure-state.json", solvers[0], kind)
                 for kind in ("cpu", "memory", "io")]
    report = {"schema": "resource-aware-proving-benchmark-v1", "unix_time": time.time(),
              "platform": platform.platform(), "python": platform.python_version(),
              "host": asdict(host), "scheduler_config": scheduler.config.persisted_dict(),
              "solvers": {s: {"path": shutil.which(s), "version": trials[0]["solver_versions"].get(s)} for s in solvers}, "trials": trials,
              "summary": summary, "pressure_probes": pressures,
              "scope": "real SMT solver execution; no kernel reconstruction or multi-family scaling claim"}
    (args.out / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# Resource-aware proving benchmark", "", report["scope"], "",
             "| Concurrent portfolios | Median jobs/s | Speedup | Sampled peak RSS MiB |",
             "|---:|---:|---:|---:|"]
    lines += [f"| {r['workers']} | {r['median_jobs_per_second']:.2f} | {r['speedup_over_serial']:.2f}x | {r['peak_rss_mb']:.1f} |" for r in summary]
    lines += ["", "Each job runs every installed SMT solver with cancellation disabled and checks the expected SAT/UNSAT result.",
              "Peak RSS includes the Python harness and its children; 50 ms sampling can miss short-lived peaks.",
              "Small pigeonhole problems emphasize process and scheduling overhead rather than difficult proof search.", "",
              "| Injected pressure | Backoff reason | Recovery after clear (s) | Launches under pressure |",
              "|---|---|---:|---:|"]
    lines += [f"| {r['pressure']} | {r['backoff_reason']} | {r['recovery_after_clear_seconds']:.3f} | 0 |" for r in pressures]
    lines += ["", "All trials and pressure probes completed with zero active leases or waiters.",
              "Injected pressure validates the controller without imposing real external load.",
              "Raw timings, environment, resource policy, and individual results are in benchmark.json."]
    (args.out / "benchmark.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
