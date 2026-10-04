"""Tiny real-Python-process qualification of sampled live workspace limits.

All native processes belong to this benchmark. At most two jobs run concurrently
under an explicit private admitted pool. Host samples are healthy fixtures; no
shared pool, solver, installer, disk-quota or many-core claim is involved. File
writes are finite (at most 32 KiB per job); sampled logical bytes may overshoot.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from unittest.mock import patch

import bench_hyper_counterexample_validation as previous
from bench_smt_operation_control import MIB, ROOT, require, sha, write

NEW_TEST = ROOT / "tests/unit/logic/backends/test_process_workspace_guard.py"
WORKSPACE_BYTES = 8192
SERIAL = ("healthy", "exact", "single_overrun", "aggregate_overrun", "sticky_delete", "descendant_writer", "cancel", "quick_overrun")
WAVES = (("exact", "single_overrun"), ("aggregate_overrun", "sticky_delete"))
OVERRUN = {"single_overrun", "aggregate_overrun", "sticky_delete", "descendant_writer", "quick_overrun"}


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def program(kind, concurrent=False):
    prelude = "import json, os, pathlib, signal, subprocess, sys, time\n"
    prelude += "def birth(pid):\n return int(pathlib.Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19])\n"
    prelude += "print('SAT', flush=True)\n"
    if concurrent:
        prelude += "time.sleep(.25)\n"
    if kind == "sticky_delete":
        prelude += ("def stop(signum, frame):\n"
            " for p in pathlib.Path('.').glob('payload*'):\n  p.unlink()\n"
            " print('DELETED_ON_TERM', flush=True)\n sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n")
    if kind == "descendant_writer":
        child = "import pathlib,time;pathlib.Path('payload-child').write_bytes(b'x'*32768);time.sleep(2)"
        return prelude + f"child=subprocess.Popen([sys.executable,'-I','-B','-c',{child!r}])\n" + (
            "print('DESCENDANT '+json.dumps({'pid':child.pid,'birth_ticks':birth(child.pid)}),flush=True)\n"
            "child.wait(timeout=2.5)\n")
    sizes = (4096, 4096, 4096) if kind == "aggregate_overrun" else ({
        "healthy": 1024, "exact": 8192, "cancel": 4096}.get(kind, 32768),)
    for index, size in enumerate(sizes):
        prelude += f"pathlib.Path('payload-{index}').write_bytes(b'x'*{size})\n"
    if kind != "quick_overrun":
        prelude += f"time.sleep({.25 if kind in {'healthy', 'exact'} else 2})\n"
    return prelude


def identity(pid):
    try:
        fields = Path("/proc", str(pid), "stat").read_text().rsplit(")", 1)[1].split()
        return {"birth_ticks": int(fields[19]), "state": fields[0]}
    except (OSError, ValueError, IndexError):
        return None


class Audit:
    """Observe actual production launch and workspace scans without replacing them."""

    def __init__(self, directory):
        self.directory, self.stack, self.local = directory, ExitStack(), threading.local()
        self.lock = threading.Lock()
        self.samples, self.admissions, self.leases, self.workspaces = [], [], [], []
        self.invocations, self.launches, self.scans, self.shared_attempts = [], [], [], []
        self.children, self.max_live_roots = {}, 0
        self.ready, self.cancel_tokens = {}, {}

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        def sample():
            with self.lock:
                require(len(self.samples) < 4096, "finite sampler history exceeded")
                self.samples.append({"at_monotonic": time.monotonic(), "host": asdict(healthy)})
            return healthy
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(True)
            raise AssertionError("workspace benchmark forbids shared scheduler resolution")
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny_shared))
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", deny_shared))
        self.owner = scheduler.GlobalResourceScheduler(scheduler.ResourceSchedulerConfig.for_proof_host(
            state_path=self.directory / "private-pool.json", proof_resource_sampler=sample,
            total_cpu_slots=2, total_memory_mb=256, total_child_process_slots=4,
            proof_memory_headroom_mb=32, lane_reservations={}, auto_renew_leases=False))
        self.before = self.owner.snapshot()
        acquire = self.owner.acquire
        def observe_acquire(lane, **kwargs):
            row = {"case": self.local.case, "started": time.monotonic(), "lane": str(lane),
                **{key: kwargs[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "timeout")}}
            self.admissions.append(row)
            lease = acquire(lane, **kwargs)
            self.leases.append(lease)
            row.update(lease_id=lease.lease_id, granted=time.monotonic(), wait_seconds=lease.wait_seconds)
            return lease
        self.stack.enter_context(patch.object(self.owner, "acquire", observe_acquire))
        write_inputs = process.BoundedToolRunner._write_inputs
        def observe_write(workspace, request):
            self.workspaces.append({"case": self.local.case, "path": str(workspace)})
            return write_inputs(workspace, request)
        self.stack.enter_context(patch.object(process.BoundedToolRunner, "_write_inputs", staticmethod(observe_write)))
        initialize = process.SubprocessExecutor.__init__
        def observe_initialize(executor, *args, **kwargs):
            initialize(executor, *args, **kwargs)
            popen = executor._popen
            def observe_popen(*args, **kwargs):
                expected = [str(self.prlimit), "--core=0:0", "--cpu=1:1", f"--as={256*MIB}:{256*MIB}", "--", *self.local.expected_argv]
                require(list(args[0]) == expected and kwargs.get("shell") is False
                    and kwargs.get("start_new_session") is True, "unexpected native launcher/profile")
                before_launch_snapshot = self.owner.snapshot()
                child = popen(*args, **kwargs)
                row = {"case": self.local.case, "pid": child.pid, "started": time.monotonic(),
                    "identity": identity(child.pid), "observed_live": child.poll() is None,
                    "argv": list(args[0]), "workspace": kwargs["cwd"]}
                with self.lock:
                    self.children[self.local.case] = child
                    self.launches.append(row)
                    live = sum(p.poll() is None for p in self.children.values())
                    self.max_live_roots = max(self.max_live_roots, live)
                    row["live_owned_roots"] = live
                row["before_launch_snapshot"] = before_launch_snapshot
                return child
            executor._popen = observe_popen
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "__init__", observe_initialize))
        execute = process.SubprocessExecutor.execute
        def observe_execute(executor, invocation, cancellation=None):
            state = self.owner.snapshot()
            require(0 < state["allocated"]["cpu_slots"] <= 2 and 0 < state["allocated"]["memory_mb"] <= 256
                and 0 < state["allocated_child_process_slots"] <= 4, "private resource capacity overspent")
            row = {"case": self.local.case, "started": time.monotonic(), "argv": list(invocation.argv),
                "limits": asdict(invocation.limits), "workspace": str(invocation.cwd), "snapshot": state}
            self.invocations.append(row)
            self.local.executing = True
            try:
                raw = execute(executor, invocation, cancellation)
                row["raw_process"] = {key: getattr(raw, key) for key in ("pid", "returncode", "timed_out", "cancelled",
                    "workspace_limit_exceeded", "resource_exhausted", "process_tree_terminated", "error", "elapsed_seconds")}
                return raw
            finally:
                row["completed"] = time.monotonic()
                self.local.executing = False
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", observe_execute))
        inspect = process._inspect_workspace
        def observe_inspect(workspace, limits, **kwargs):
            snapshot = inspect(workspace, limits, **kwargs)
            label = self.local.case
            child = self.children.get(label)
            row = {"case": label, "at_monotonic": time.monotonic(), "workspace": str(workspace),
                "during_executor": getattr(self.local, "executing", False),
                "owned_root_live": child is not None and child.poll() is None,
                **{key: getattr(snapshot, key) for key in ("bytes_used", "entries", "limit_exceeded", "error", "interrupted")}}
            self.scans.append(row)
            if label in self.ready and row["owned_root_live"] and snapshot.bytes_used >= 4096:
                self.ready[label].set()
            return snapshot
        self.stack.enter_context(patch.object(process, "_inspect_workspace", observe_inspect))
        return self

    def __exit__(self, *args):
        self.after = self.owner.snapshot()
        return self.stack.__exit__(*args)


def run_case(kind, label, audit, concurrent=False):
    from ipfs_datasets_py.logic.backends import process, resource_admission as admission
    audit.local.case = label
    script = program(kind, concurrent)
    limits = process.ToolRunLimits(timeout_seconds=3, termination_grace_seconds=.2, cpu_seconds=1,
        memory_bytes=256*MIB, resident_memory_bytes=128*MIB, max_output_bytes=4096,
        max_input_bytes=1024, max_workspace_bytes=WORKSPACE_BYTES, enforce_file_size_limit=False)
    require(limits.max_workspace_entries == 16384 and limits.max_workspace_depth == 64, "default workspace complexity caps differ")
    request = process.ToolRunRequest(argv=(str(Path(sys.executable).resolve()), "-I", "-B", "-c", script), limits=limits)
    audit.local.expected_argv = list(request.argv)
    runner = admission.ResourceAdmittedToolRunner(scheduler=audit.owner, cpu_slots=1, child_process_slots=2,
        workspace_root=audit.directory / "workspaces")
    token = threading.Event()
    audit.cancel_tokens[label] = token
    controller = None
    controller_state = {}
    if kind == "cancel":
        audit.ready[label] = threading.Event()
        def cancel_after_observed_write():
            controller_state["ready_observed"] = audit.ready[label].wait(timeout=2)
            if controller_state["ready_observed"]:
                controller_state["cancelled_at_monotonic"] = time.monotonic()
                token.set()
        controller = threading.Thread(target=cancel_after_observed_write, name="workspace-guard-cancel")
        controller.start()
    row = {"case": label, "kind": kind, "concurrent_wave": concurrent, "status": "running",
        "request": {"argv": list(request.argv), "limits": asdict(limits), "input_files": {}, "output_paths": []},
        "program_sha256": hashlib.sha256(script.encode()).hexdigest()}
    started = time.monotonic()
    try:
        result = runner.run(request, cancellation=token)
        row.update(result=result.to_dict(), tool_result_ok=result.ok)
        if controller is not None:
            controller.join(timeout=2)
            require(not controller.is_alive() and controller_state.get("ready_observed"), "finite cancellation controller did not observe owned write")
        launches = [entry for entry in audit.launches if entry["case"] == label]
        invocations = [entry for entry in audit.invocations if entry["case"] == label]
        scans = [entry for entry in audit.scans if entry["case"] == label]
        workspaces = [entry["path"] for entry in audit.workspaces if entry["case"] == label]
        require(len(launches) == len(invocations) == len(workspaces) == 1 and launches[0]["observed_live"]
            and result.pid == launches[0]["pid"] and result.workspace_cleaned
            and not Path(workspaces[0]).exists() and identity(result.pid) is None,
            "owned root/workspace was not launched once and fully reaped")
        require(result.stdout.startswith("SAT\n") and not result.timed_out and not result.unavailable and not result.output_truncated,
            "unexpected transport failure or missing solver-like marker")
        require(not any(scan["error"] for scan in scans)
            and all(not scan["interrupted"] or kind == "cancel" for scan in scans),
            "workspace scanner failed or had an unexpected interruption")
        if kind in OVERRUN:
            require(result.workspace_limit_exceeded and result.resource_exhausted and not result.ok and not result.cancelled,
                "solver-like output crossed workspace resource failure")
            require(any(scan["limit_exceeded"] and scan["bytes_used"] > WORKSPACE_BYTES for scan in scans),
                "overrun lacks an actual bounded logical-byte scan")
            if kind != "quick_overrun":
                require(result.process_tree_terminated and any(scan["owned_root_live"] and scan["limit_exceeded"] for scan in scans),
                    "sleeping writer was not stopped by the live guard")
        elif kind == "cancel":
            require(result.cancelled and result.process_tree_terminated and not result.ok
                and not result.workspace_limit_exceeded, "caller cancellation became success/workspace overrun")
        else:
            require(result.ok and result.returncode == 0 and not result.workspace_limit_exceeded and not result.resource_exhausted,
                "healthy/exact-bound workspace was rejected")
            require(max(scan["bytes_used"] for scan in scans) == (8192 if kind == "exact" else 1024),
                "healthy logical-byte observation differs")
        if kind == "sticky_delete":
            require(result.returncode == 0 and "DELETED_ON_TERM" in result.stdout
                and any(scan["bytes_used"] == 0 and not scan["during_executor"] for scan in scans),
                "deleting SIGTERM handler did not test sticky failure after successful exit")
        descendants = []
        for line in result.stdout.splitlines():
            if line.startswith("DESCENDANT "):
                observed = json.loads(line.removeprefix("DESCENDANT "))
                now = identity(observed["pid"])
                require(now is None or now["birth_ticks"] != observed["birth_ticks"] or now["state"] == "Z",
                    "owned descendant remained live after cleanup")
                descendants.append({**observed, "after": now, "matching_identity_live": False})
        require(len(descendants) == (1 if kind == "descendant_writer" else 0), "owned descendant evidence differs")
        invocation = invocations[0]
        require(invocation["argv"] == list(request.argv) and 0 < invocation["limits"]["timeout_seconds"] <= 3
            and all(invocation["limits"][key] == asdict(limits)[key] for key in asdict(limits) if key != "timeout_seconds"),
            "actual invocation limits differ from admitted request")
        row.update(status="passed", descendants=descendants, root_identity_after=None)
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        token.set()
        if controller is not None:
            controller.join(timeout=2)
        row.update(elapsed_seconds=time.monotonic()-started, cancellation_controller=controller_state,
            launches=[entry for entry in audit.launches if entry["case"] == label],
            invocations=[entry for entry in audit.invocations if entry["case"] == label],
            scans=[entry for entry in audit.scans if entry["case"] == label],
            admissions=[entry for entry in audit.admissions if entry["case"] == label],
            workspaces=[entry["path"] for entry in audit.workspaces if entry["case"] == label])
        row["max_sampled_logical_bytes"] = max((scan["bytes_used"] for scan in row["scans"]), default=0)
        row["sampled_logical_overshoot_bytes"] = max(0, row["max_sampled_logical_bytes"]-WORKSPACE_BYTES)
        write(audit.directory / (label+".json"), row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    require(sys.platform.startswith("linux") and Path("/proc/self/stat").is_file(), "qualification requires reviewed Linux process ownership")
    prlimit = next((path.resolve() for path in (Path("/usr/bin/prlimit"), Path("/bin/prlimit"))
        if path.is_file() and os.access(path, os.X_OK)), Path("/missing/prlimit"))
    tool_paths = (Path(sys.executable).resolve(), prlimit)
    tool_files = {str(path): sha(path) for path in tool_paths}
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "process-workspace-guard-benchmark@1", "status": "running", "cases": [], "checks": {},
        "source_pins_before": pins(), "tool_files_before": tool_files, "waves": [],
        "scope": {"real_python_processes": True, "max_concurrent_job_roots": 2, "synthetic_healthy_host_samples": True,
            "private_fixture_pool": True, "explicit_resource_admitted_runners": True, "solver_execution": False,
            "actual_host_pressure_tested": False, "disk_quota_claim": False, "hard_disk_containment_claim": False,
            "many_core_scaling_claim": False, "sample_interval_seconds": .1,
            "byte_measure": "bounded sampled regular-file logical bytes; may overshoot; not physical disk usage",
            "max_payload_bytes_per_job": 32768, "scheduled_payload_bytes_total": 242688}}
    audit = Audit(directory)
    audit.prlimit = prlimit
    started = time.monotonic()
    try:
        with audit:
            for kind in SERIAL:
                row = run_case(kind, "serial-"+kind, audit)
                result["cases"].append(row)
                write(directory / "partial.json", result)
                require(row["status"] == "passed", "serial workspace case failed: "+kind)
            for index, kinds in enumerate(WAVES):
                wave_started = time.monotonic()
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="workspace-guard") as pool:
                    pending = [pool.submit(run_case, kind, f"wave{index}-{kind}", audit, True) for kind in kinds]
                    rows = [future.result(timeout=5) for future in pending]
                result["cases"].extend(rows)
                result["waves"].append({"wave": index, "cases": [row["case"] for row in rows],
                    "elapsed_seconds": time.monotonic()-wave_started,
                    "two_live_owned_roots_observed": any(launch["live_owned_roots"] == 2 for row in rows for launch in row["launches"])})
                write(directory / "partial.json", result)
                require(all(row["status"] == "passed" for row in rows), "concurrent workspace case failed")
                require(result["waves"][-1]["two_live_owned_roots_observed"], "concurrent wave lacked two observed live roots")
            require(audit.max_live_roots == 2, "two owned roots were not observed concurrently")
        result["checks"].update(all12_cases_passed=len(result["cases"]) == 12,
            root_launches12=len(audit.launches) == 12, one_owned_descendant=sum(len(row["descendants"]) for row in result["cases"]) == 1,
            observed_two_root_concurrency=audit.max_live_roots == 2,
            shared_pool_untouched=not audit.shared_attempts,
            private_work_drained=audit.after["active_lease_count"] == audit.after["waiting_request_count"] == 0,
            all_leases_released=all(lease.released for lease in audit.leases),
            all_workspaces_removed=all(not Path(row["path"]).exists() for row in audit.workspaces))
        result["status"] = "passed_real_processes"
    except BaseException:
        result.update(status="failed", error=traceback.format_exc())
    finally:
        audit.stack.close()
        result.update(source_pins_after=pins(), tool_files_after={str(path): sha(path) for path in tool_paths},
            elapsed_seconds=time.monotonic()-started, native_root_launches=len(audit.launches),
            native_descendant_processes_observed=sum(len(row.get("descendants", [])) for row in result["cases"]),
            max_observed_live_roots=audit.max_live_roots, shared_scheduler_attempts=audit.shared_attempts,
            sample_history=audit.samples, private_config=audit.owner.config.persisted_dict() if hasattr(audit, "owner") else None,
            private_before=getattr(audit, "before", None), private_after=getattr(audit, "after", None))
        result["checks"].update(sources_stable=result["source_pins_before"] == result["source_pins_after"],
            tools_stable=result["tool_files_before"] == result["tool_files_after"])
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed_real_processes" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
