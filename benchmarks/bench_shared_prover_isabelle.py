"""Task-sized native Isabelle, SMT, Lean and finite TLC tasks under one pressure-aware owner.

Retain every attempted trial, with selected source/executable hashes before and
after execution. This qualifies execution and accounting, not proof composition.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import sys
import threading
import time

DATASETS = Path(__file__).resolve().parents[1]
ACCELERATE = DATASETS.parent / "ipfs_accelerate"
sys.path[:0] = [str(ACCELERATE), str(DATASETS)]

from shared_prover_workloads import tseitin_target
from ipfs_accelerate_py.agent_supervisor.proof.datasets_hammer_tasks import make_datasets_smt_task
from ipfs_accelerate_py.agent_supervisor.proof.datasets_kernel_tasks import make_datasets_lean_nat_task
from ipfs_accelerate_py.agent_supervisor.proof.datasets_tla_tasks import make_datasets_tlc_counter_task
from ipfs_accelerate_py.agent_supervisor.proof.datasets_isabelle_tasks import make_datasets_isabelle_nat_task
from ipfs_accelerate_py.agent_supervisor.proof.datasets_native_bundle import execute_datasets_native_bundle, plan_datasets_native_bundle
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
from ipfs_datasets_py.logic.hammers import portfolio
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def sources():
    paths = [Path(__file__).resolve()]
    for name in (
        "shared_prover_workloads",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_hammer_tasks",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_kernel_tasks",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_tla_tasks",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_isabelle_tasks",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_native_bundle",
        "ipfs_datasets_py.logic.backends.kernel.isabelle",
        "ipfs_datasets_py.logic.external_provers.isabelle_runtime",
        "ipfs_datasets_py.logic.backends.installers.state_model_preparation",
        "ipfs_accelerate_py.agent_supervisor.proof.datasets_prover_resources",
        "ipfs_accelerate_py.agent_supervisor.proof.multi_prover_resources",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety",
        "ipfs_datasets_py.logic.hammers.portfolio",
        "ipfs_datasets_py.logic.hammers.process_lifecycle",
        "ipfs_datasets_py.logic.hammers.semantic_routing",
        "ipfs_datasets_py.logic.backends.process",
        "ipfs_datasets_py.logic.backends.kernel.lean",
        "ipfs_datasets_py.logic.backends.tla.runners",
        "ipfs_datasets_py.logic.backends.tla.compiler",
        "ipfs_datasets_py.logic.backends.installers.state_model",
    ):
        path = Path(importlib.import_module(name).__file__).resolve()
        if not (path.is_relative_to(DATASETS) or path.is_relative_to(ACCELERATE)):
            raise RuntimeError(f"wrong installed implementation: {path}")
        paths.append(path)
    return {str(path): digest(path) for path in paths}


def launchers():
    result = {}
    from ipfs_datasets_py.logic.backends import process
    from ipfs_datasets_py.logic.hammers import process_lifecycle
    from ipfs_datasets_py.logic.backends.installers import state_model
    root = state_model.expand_user_local_root()
    manifest = root / "manifests" / "tlc.json"
    with manifest.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise RuntimeError("TLC runtime manifest exceeds bound")
    selected = {name: shutil.which(name) for name in ("z3", "cvc5", "lean")}
    selected.update(prlimit_bounded=process._linux_prlimit_path(),
                    prlimit_hammer=process_lifecycle._linux_prlimit_path(),
                    tlc_manifest=str(manifest), java_tlc=json.loads(raw)["java_executable"],
                    tlc_jar=str(root / "tlc" / state_model.TLC_VERSION / "tla2tools.jar"))
    from ipfs_datasets_py.logic.backends.installers import isabelle
    isabelle_root = (isabelle.expand_user_local_root() /
                    f"{isabelle.ISABELLE_VERSION}-{isabelle.detect_platform_key()}" / isabelle.ISABELLE_VERSION)
    for name in ("bin/isabelle", "etc/settings", "etc/ISABELLE_IDENTIFIER", "etc/components", "lib/scripts/getsettings",
                 "heaps/polyml-5.9.2_arm64_32-linux/HOL", "heaps/polyml-5.9.2_arm64_32-linux/Pure",
                 "contrib/jdk-21.0.9/arm64-linux/bin/java", "contrib/polyml-5.9.2-2/arm64_32-linux/poly"):
        selected[f"isabelle/{name}"] = str(isabelle_root / name)
    for name, path in selected.items():
        result[name] = None if path is None else {
            "path": path, "resolved_path": str(Path(path).resolve()), "sha256": digest(path)}
    return result


def environment(scheduler):
    fields = ("total_cpu_slots", "total_memory_mb", "total_child_process_slots",
              "reserved_memory_mb", "proof_safety_enabled", "proof_memory_headroom_mb",
              "proof_memory_stall_percent", "proof_cpu_stall_percent", "proof_io_stall_percent",
              "proof_backoff_seconds", "lease_ttl_seconds", "poll_interval_seconds", "max_waiting_requests")
    return {"platform": platform.platform(), "python": sys.version, "python_executable": sys.executable,
            "cpu_count": os.cpu_count(), "cpu_affinity": sorted(os.sched_getaffinity(0)),
            "host_resources": asdict(collect_proof_host_resources()),
            "scheduler": {**{name: getattr(scheduler.config, name) for name in fields},
                          "state_path": str(scheduler.config.state_path),
                          "lane_reservations": {k: v.to_dict() for k, v in scheduler.config.reservations().items()}}}


def build_tasks():
    tasks = [make_datasets_isabelle_nat_task(task_id="isabelle-0", offset=41, timeout_seconds=60)]
    for number, (vertices, offset, bound) in enumerate(zip((32, 40, 48, 64), (0, 7, 41, 65535), (1, 2, 5, 16))):
        tasks.extend((
            make_datasets_smt_task(target=tseitin_target(f"smt-{number}", vertices=vertices),
                                   expected_verdict="unsat", timeout_seconds=45),
            make_datasets_lean_nat_task(task_id=f"lean-{number}", offset=offset, timeout_seconds=30),
            make_datasets_tlc_counter_task(task_id=f"tlc-{number}", counter_bound=bound,
                invariant_max=bound, timeout_seconds=30,
                dependencies=("smt-3", "lean-3", "tlc-0") if number == 3 else ()),
        ))
    return tasks


def trial(round_number, width, parent_lease=None):
    prepared_at = time.perf_counter()
    tasks = build_tasks()
    preparation = time.perf_counter() - prepared_at
    scheduler = get_global_resource_scheduler()
    supervisor = portfolio.get_process_supervisor()
    original_smt, original_bounded = supervisor.run, BoundedToolRunner.run
    active = peak = 0
    counts = {"smt": 0, "lean": 0, "tlc": 0, "isabelle": 0}
    maximum_roots = maximum_cpu = maximum_memory = maximum_process_slots = 0
    lock, stop = threading.Lock(), threading.Event()
    errors = []
    receipt = execution = None

    def counted(family, function, *args, **kwargs):
        nonlocal active, peak
        with lock:
            counts[family] += 1
            active += 1
            peak = max(peak, active)
        try:
            return function(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    def measured_smt(command, **kwargs):
        if "--version" in command or "-version" in command:
            return original_smt(command, **kwargs)
        return counted("smt", original_smt, command, **kwargs)

    def measured_bounded(self, request, **kwargs):
        if "--json" in request.argv and any(".lean" in item for item in request.argv):
            return counted("lean", original_bounded, self, request, **kwargs)
        if "tlc2.TLC" in request.argv and "-config" in request.argv:
            return counted("tlc", original_bounded, self, request, **kwargs)
        if "process_theories" in request.argv:
            return counted("isabelle", original_bounded, self, request, **kwargs)
        return original_bounded(self, request, **kwargs)

    def monitor():
        nonlocal maximum_roots, maximum_cpu, maximum_memory, maximum_process_slots
        try:
            while not stop.is_set():
                roots = [row for row in scheduler.active_leases()
                         if row["owner_pid"] == os.getpid() and not row.get("parent_lease_id")]
                maximum_roots = max(maximum_roots, len(roots))
                maximum_cpu = max(maximum_cpu, sum(row["cpu_slots"] for row in roots))
                maximum_memory = max(maximum_memory, sum(row["memory_mb"] for row in roots))
                maximum_process_slots = max(maximum_process_slots, sum(row["child_process_slots"] for row in roots))
                stop.wait(.05)
        except BaseException as exc:
            errors.append(f"monitor: {type(exc).__name__}: {exc}")

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    started = time.perf_counter()
    supervisor.run, BoundedToolRunner.run = measured_smt, measured_bounded
    try:
        monitor_thread.start()
        execution = execute_datasets_native_bundle(tasks, max_workers=width, timeout_seconds=180, parent_lease=parent_lease)
        receipt = execution.receipt
    except Exception as exc:
        errors.append(f"execution: {type(exc).__name__}: {exc}")
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        if monitor_thread.ident is not None:
            monitor_thread.join(3)
        supervisor.run, BoundedToolRunner.run = original_smt, original_bounded
    checks = {
        "all_tasks_successful": receipt is not None and len(receipt.successful_task_ids) == len(tasks),
        "native_check_counts": counts == {"smt": 8, "lean": 4, "tlc": 4, "isabelle": 1},
        "bounded_overlap": active == 0 and 1 <= peak <= width and (width == 1 or peak > 1),
        "one_owned_root": maximum_roots == 1,
        "root_cpu_envelope": execution is not None and maximum_cpu == (parent_lease.cpu_slots if parent_lease else execution.plan.budget.cpu_slots),
        "root_memory_envelope": execution is not None and maximum_memory * 1024**2 == (parent_lease.memory_mb * 1024**2 if parent_lease else execution.plan.budget.memory_bytes),
        "root_process_envelope": execution is not None and maximum_process_slots == (parent_lease.child_process_slots if parent_lease else execution.plan.budget.process_slots),
        "default_safety": execution is not None and execution.plan.proof_safety_enabled is True,
        "requested_width_fits": execution is not None and execution.plan.budget.max_portfolio_width == width,
        "monitor_stopped": not monitor_thread.is_alive(),
        "trial_leases_drained": not any(row["owner_pid"] == os.getpid()
            and (parent_lease is None or row["lease_id"] != parent_lease.lease_id) for row in scheduler.active_leases()),
    }
    if receipt is not None:
        checks["no_cache_bypass"] = not any(row.cache_bypassed_execution for row in receipt.receipts)
        checks["no_repository_authority"] = all(row.result is not None and all(
            row.result.get(key) is False for key in (
                "source_semantics_verified", "behavior_authority", "execution_authority", "completion_authority"))
            for row in receipt.receipts)
        by_id = {row.task_id: row for row in receipt.receipts}
        isabelle_receipt = by_id.get("isabelle-0")
        observed = None if isabelle_receipt is None else isabelle_receipt.result
        checks["isabelle_generated_theorem_accepted"] = (isinstance(observed, Mapping)
            and observed.get("kernel_accepted") is True and observed.get("kernel_authority") is True)
        dependencies = ("smt-3", "lean-3", "tlc-0")
        checks["dependency_order"] = (all(key in by_id for key in (*dependencies, "tlc-3"))
            and by_id["tlc-3"].started_at_ms >= max(by_id[key].finished_at_ms for key in dependencies))
    row = {"round": round_number, "workers": width, "tasks": len(tasks),
           "preparation_seconds": preparation, "execution_seconds": elapsed, "total_seconds": preparation + elapsed,
           "native_checks": counts, "peak_native_lifecycle_calls": peak,
           "supplied_parent": parent_lease is not None, "maximum_owned_roots": maximum_roots, "maximum_owned_cpu_slots": maximum_cpu,
           "maximum_owned_memory_mb": maximum_memory, "maximum_owned_process_slots": maximum_process_slots,
           "plan": None if execution is None else execution.plan.to_dict(), "checks": checks, "errors": errors,
           "receipt": None if receipt is None else receipt.to_dict(),
           "correctness_passed": not errors and all(checks.values())}
    print(f"round={round_number} workers={width} execution={elapsed:.3f} peak={peak} passed={row['correctness_passed']}",
          file=sys.stderr, flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("Choose a new output path; existing trials are retained")
    scheduler = get_global_resource_scheduler()
    if not scheduler.config.proof_safety_enabled:
        raise RuntimeError("default pressure safety must remain enabled")
    payload = {"schema": "shared-prover-isabelle-benchmark@1", "started_at_utc": datetime.now(timezone.utc).isoformat(),
               "sources_before": sources(), "launchers_before": launchers(), "environment_before": environment(scheduler),
               "configuration": {"rounds": args.rounds, "width_orders": [[1, 2, 4], [4, 1, 2], [2, 4, 1]][:args.rounds],
                   "tasks_per_trial": 13, "isabelle_offset": 41, "tseitin_vertices": [32, 40, 48, 64], "lean_offsets": [0, 7, 41, 65535],
                   "tlc_counter_bounds": [1, 2, 5, 16], "monitor_interval_seconds": .05,
                   "task_sized_default_admission": True, "shared_parent_across_widths": True, "isabelle_reservation": {"cpu_slots": 3, "process_slots": 12, "memory_mb": 2304},
                   "host_exhaustion_induced": False, "proof_composition_qualified": False},
               "trials": [], "correctness_passed": False, "status": "running",
               "measurement_limits": [
                   "Bounded authored fixtures do not qualify repository behavior or cross-family logical correspondence.",
                   "Native lifecycle overlap includes launch, monitoring and cleanup, not measured CPU occupancy.",
                   "Reservations and sampled RSS guards are not kernel-enforced aggregate memory accounting.",
                   "Selected source and launcher hashes omit transitive libraries, Lean imports and runtime executable handoffs.",
                   "Isabelle process/thread slots are scheduling estimates, not hard OS process/thread ceilings; JVM and Poly/ML run concurrently.",
                   "One Isabelle task per trial permits mixed sibling overlap; two Isabelle tasks exceed this host default process budget and serialize.",
                   "The independent runtime-preparation smoke, widest-envelope construction/admission and source/runtime hashing are outside per-trial timing; parent acquisition cost is recorded separately.",
                   "Preparation and execution are timed separately; report total costs alongside execution throughput."]}
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    save()
    try:
        prepared = time.perf_counter()
        envelope = plan_datasets_native_bundle(build_tasks(), max_workers=4, scheduler=scheduler)
        payload["shared_parent_plan"] = envelope.to_dict()
        payload["shared_parent_preparation_seconds"] = time.perf_counter() - prepared
        admitted = time.perf_counter()
        with scheduler.acquire("orchestration", cpu_slots=envelope.budget.cpu_slots,
                memory_mb=envelope.budget.memory_bytes // 1024**2,
                child_process_slots=envelope.budget.process_slots, timeout=180) as parent:
            payload["shared_parent_admission_seconds"] = time.perf_counter() - admitted
            save()
            for number, order in enumerate(payload["configuration"]["width_orders"], 1):
                for width in order:
                    attempt_start = time.perf_counter()
                    try:
                        row = trial(number, width, parent)
                    except Exception as exc:
                        row = {"round": number, "workers": width, "correctness_passed": False,
                               "elapsed_attempt_seconds": time.perf_counter() - attempt_start,
                               "errors": [f"trial: {type(exc).__name__}: {exc}"], "receipt": None}
                    payload["trials"].append(row)
                    save()
                    if not row["correctness_passed"]:
                        raise RuntimeError("trial failed; unsuccessful receipts retained")
        payload["owned_leases_drained_after_population"] = not any(
            row["owner_pid"] == os.getpid() for row in scheduler.active_leases())
        if not payload["owned_leases_drained_after_population"]:
            raise RuntimeError("owned reservations remain after the population")
        payload["sources_after"], payload["launchers_after"] = sources(), launchers()
        payload["environment_after"] = environment(scheduler)
        payload["selected_sources_unchanged"] = payload["sources_before"] == payload["sources_after"]
        payload["launchers_unchanged"] = payload["launchers_before"] == payload["launchers_after"]
        if not payload["selected_sources_unchanged"] or not payload["launchers_unchanged"]:
            raise RuntimeError("selected producer changed during benchmark")
        summary = {}
        for width in (1, 2, 4):
            selected = [row for row in payload["trials"] if row["workers"] == width]
            summary[str(width)] = {f"median_{field}": statistics.median(row[field] for row in selected)
                                  for field in ("preparation_seconds", "execution_seconds", "total_seconds")}
        for row in summary.values():
            row["execution_speedup"] = summary["1"]["median_execution_seconds"] / row["median_execution_seconds"]
            row["total_speedup"] = summary["1"]["median_total_seconds"] / row["median_total_seconds"]
        payload.update(summary=summary, status="completed", correctness_passed=True)
    except Exception as exc:
        payload.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # Failed trials also retain final identities. Recording errors are
        # explicit, never a substitute for a matching producer fingerprint.
        payload["final_recording_errors"] = []
        for key, capture in (("sources_after", sources), ("launchers_after", launchers),
                             ("environment_after", lambda: environment(scheduler))):
            try:
                payload[key] = capture()
            except Exception as exc:
                payload["final_recording_errors"].append(f"{key}: {type(exc).__name__}: {exc}")
        payload["selected_sources_unchanged"] = payload.get("sources_after") == payload["sources_before"]
        payload["launchers_unchanged"] = payload.get("launchers_after") == payload["launchers_before"]
        if (payload["final_recording_errors"] or not payload["selected_sources_unchanged"]
                or not payload["launchers_unchanged"]):
            payload.update(status="failed", correctness_passed=False)
            payload.pop("summary", None)
        payload["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({"correctness_passed": payload["correctness_passed"], "summary": payload.get("summary")}))
    if not payload["correctness_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
