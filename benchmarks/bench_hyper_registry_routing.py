"""Controlled independent Hyper registry routing and bounded queue progress.

Native processes and shared scheduler resolution are denied. Executable
discovery, tool outputs and host samples are explicit fixtures; registry
factories, admitted runners and evidence projection are production defaults.
Timing observations do not measure native solver throughput or speedup.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch

import bench_hyper_default_admission as previous
from bench_smt_operation_control import MIB, ROOT, require, sha, write

ENGINES = previous.ENGINES
LEGACY = "hyperltl_autohyper_mchyper"
SELECTORS = ("request_id", "explicit_empty", "matching")
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_registry_routing.py"
EXTRA_PINS = ("ipfs_datasets_py/logic/conformance/matrix.py",
    "ipfs_datasets_py/logic/conformance/claim_runtime_audit.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_capabilities.py",
    "tests/unit/logic/families/test_provider_catalog.py")


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST),
        **{str(ROOT / p): sha(ROOT / p) for p in EXTRA_PINS}}


def request(engine, label, target=None):
    base = previous.request(engine, "direct", label)
    return replace(base, bounds=replace(base.bounds, timeout_ms=3000),
        requested_backend_id=engine if target is None else target)


class Fixtures:
    def __init__(self, directory):
        self.directory, self.stack, self.local = directory, ExitStack(), threading.local()
        self.samples, self.discovery, self.invocations, self.lifecycle, self.admissions, self.workspaces = [], [], [], [], [], []
        self.native_attempts, self.shared_attempts, self.leases = [], [], []
        self.gate = threading.Event()
        self.block_concurrent = False
        self.lock = threading.Lock()

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.logic.backends.hyperproperties import adapters
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        def sample():
            self.samples.append({"at_monotonic": time.monotonic(), "host": asdict(healthy)})
            return healthy
        def deny_native(*args, **kwargs):
            self.native_attempts.append(True)
            raise AssertionError("controlled routing benchmark forbids native execution")
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(True)
            raise AssertionError("controlled routing benchmark forbids shared scheduler resolution")
        self.stack.enter_context(patch.object(subprocess, "Popen", deny_native))
        self.stack.enter_context(patch.object(os, "system", deny_native))
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny_shared))
        config = scheduler.ResourceSchedulerConfig.for_proof_host(state_path=self.directory / "private-pool.json",
            proof_resource_sampler=sample, total_cpu_slots=4, total_memory_mb=256, total_child_process_slots=8,
            proof_memory_headroom_mb=32, lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.002)
        self.owner = scheduler.GlobalResourceScheduler(config)
        self.before = self.owner.snapshot()
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", lambda: self.owner))
        def resolve(backend):
            self.discovery.append({"case": self.local.case, "engine": backend.engine.value})
            return "" if self.local.kind == "unavailable" else str(Path(sys.executable).resolve())
        self.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", resolve))
        self.stack.enter_context(patch.object(process.shutil, "which", lambda executable, **kwargs:
            str(Path(sys.executable).resolve()) if executable == str(Path(sys.executable).resolve()) else None))
        acquire = self.owner.acquire
        def observed_acquire(lane, **kwargs):
            row = {"case": self.local.case, "lane": lane, "started": time.monotonic(),
                **{key: kwargs[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "timeout")}}
            self.admissions.append(row)
            lease = acquire(lane, **kwargs)
            self.leases.append(lease)
            row.update(granted=time.monotonic(), lease_id=lease.lease_id, wait_seconds=lease.wait_seconds)
            return lease
        self.stack.enter_context(patch.object(self.owner, "acquire", observed_acquire))
        run = admission.ResourceAdmittedToolRunner.run
        def observed_run(runner, tool, **kwargs):
            raw = run(runner, tool, **kwargs)
            self.lifecycle.append({"case": self.local.case, "result": raw.to_dict(),
                "tool_request": {"argv": list(tool.argv), "limits": asdict(tool.limits),
                    "input_files": dict(tool.input_files), "environment": dict(tool.environment)}})
            return raw
        self.stack.enter_context(patch.object(admission.ResourceAdmittedToolRunner, "run", observed_run))
        write_inputs = process.BoundedToolRunner._write_inputs
        def observed_write(workspace, tool):
            self.workspaces.append({"case": self.local.case, "path": str(workspace)})
            return write_inputs(workspace, tool)
        self.stack.enter_context(patch.object(process.BoundedToolRunner, "_write_inputs", staticmethod(observed_write)))
        def execute(executor, invocation, cancellation=None):
            engine = "autohyper" if "--explicit" in invocation.argv else "mchyper" if "-pdr" in invocation.argv else "hyperltl"
            require(engine == self.local.engine and cancellation is not None and not cancellation.is_set(),
                    "selected engine or live cancellation signal differs")
            state = self.owner.snapshot()
            require(state["allocated"]["cpu_slots"] <= 4 and state["allocated"]["memory_mb"] <= 256
                    and state["allocated_child_process_slots"] <= 8, "private capacity overspent")
            limits = invocation.limits
            require(0 < limits.timeout_seconds <= 3 and 0 < limits.cpu_seconds <= 3
                    and limits.resident_memory_bytes == 128*MIB
                    and limits.memory_bytes == (4096 if engine == "autohyper" else 2048)*MIB
                    and limits.max_output_bytes == 65536 and limits.max_workspace_bytes == 16_777_216
                    and limits.enforce_file_size_limit is (engine != "autohyper"),
                    "finite managed profile differs")
            if engine == "autohyper":
                require(all(invocation.environment.get(k) == v for k, v in {
                    "DOTNET_PROCESSOR_COUNT": "1", "DOTNET_gcServer": "0", "DOTNET_GCHeapHardLimit": "4000000"}.items()),
                    "selected AutoHyper runtime controls differ")
            record = {"case": self.local.case, "engine": engine, "started": time.monotonic(),
                "argv": list(invocation.argv), "limits": asdict(limits), "environment": dict(invocation.environment),
                "workspace": str(invocation.cwd), "snapshot": state,
                "input_files": {p.name: p.read_text() for p in invocation.cwd.iterdir() if p.is_file()}}
            with self.lock:
                self.invocations.append(record)
            if self.block_concurrent:
                require(self.gate.wait(timeout=2), "concurrent fixture release was not observed")
            require(not cancellation.is_set(), "controlled job exceeded its operation")
            record["completed"] = time.monotonic()
            return process.RawProcessResult(returncode=0, stdout=previous.POSITIVE[engine],
                resource_exhausted=self.local.kind == "resource_failure")
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", execute))
        return self

    def __exit__(self, *args):
        self.gate.set()
        self.after = self.owner.snapshot()
        return self.stack.__exit__(*args)


def loaded(owner):
    return [key for key in owner if owner[key]._delegate_loaded]


def run_case(owner, fixtures, engine, selector="request_id", kind="positive", target=None, label=None):
    from ipfs_datasets_py.logic.backends import registry, resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = label or ":".join((engine, selector, kind))
    fixtures.local.case, fixtures.local.engine, fixtures.local.kind = label, engine, kind
    req = request(engine, label, target)
    if selector == "explicit_empty":
        req = replace(req, requested_backend_id="")
    argument = {} if selector == "request_id" else {"backend_id": engine if selector == "explicit_empty" else req.requested_backend_id}
    original_request = req.to_dict()
    before = loaded(owner)
    captured, phases = [], []
    def observe(frame, event, value):
        if event in {"call", "return"} and frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            backend = frame.f_locals["self"]
            operation = current_proof_operation()
            require(backend.engine.value == engine and backend._managed_runner
                    and type(backend._runner) is admission.ResourceAdmittedToolRunner and operation is not None,
                    "registry selected a peer or bypassed default admission/scope")
            phases.append({"event": event, "engine": engine, "deadline": operation.deadline})
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                captured.append(value)
    require(sys.getprofile() is None and current_proof_operation() is None, "unexpected ambient state")
    started = time.monotonic()
    sys.setprofile(observe)
    try:
        attempt, result = owner.run(req, **argument)
    finally:
        sys.setprofile(None)
    require(current_proof_operation() is None and req.to_dict() == original_request,
            "registry operation leaked or request selector was rewritten")
    canonical = LEGACY if target in {"", LEGACY} else engine
    require(result.backend_id == attempt.backend_id == canonical
            and attempt.request_digest == result.request_digest == req.digest
            and result.attempt_digest == attempt.digest and result.bounds == attempt.bounds == req.bounds,
            "registry selector/request/attempt binding differs")
    discovery = [r for r in fixtures.discovery if r["case"] == label]
    require(discovery and {r["engine"] for r in discovery} == {engine}, "selected engine fell through to a peer")
    rows = [r for r in fixtures.lifecycle if r["case"] == label]
    if kind == "unavailable":
        require(not captured and not rows and attempt.status.value == "unavailable" and result.status.value == "unknown",
                "unavailable selected engine executed or gained evidence")
        original = None
    else:
        require(len(captured) == len(rows) == 1, "selected engine did not execute exactly once")
        original = captured[0]
        typed, receipt = original.result.to_dict(), original.receipt.to_dict()
        positive = kind != "resource_failure"
        require(typed["backend_id"] == receipt["engine"] == engine
                and typed["status"] == ("satisfied" if positive else "error")
                and receipt["external_tool_proof"] is positive and not receipt["authorizes_universal_proof"]
                and receipt["counterexample"] is None and receipt["tool_version"] == ""
                and original.request_digest == req.digest and original.result.bounds == req.bounds,
                "typed engine identity, bounds or authority changed")
        require(result.payload.to_dict()["result"] == typed
                and result.status.value == ("unknown" if positive else "error")
                and attempt.status.value == ("succeeded" if positive else "failed"), "typed/generic projection differs")
        require(len(phases) == 2 and phases[0]["deadline"] == phases[1]["deadline"], "registry operation deadline changed")
        raw = rows[0]["result"]
        require(raw["returncode"] == 0 and raw["pid"] is None and raw["stdout"] == previous.POSITIVE[engine]
                and raw["resource_exhausted"] is (not positive) and raw["workspace_cleaned"], "synthetic lifecycle differs")
        require(not any(raw[k] for k in ("timed_out", "cancelled", "unavailable", "output_truncated",
            "workspace_limit_exceeded", "process_tree_terminated", "error")), "unexpected controlled interruption")
        metadata = {k: raw[k] for k in ("cancelled", "command", "error", "output_truncated", "process_tree_terminated",
            "returncode", "resource_exhausted", "timed_out", "termination_reason", "unavailable", "workspace_cleaned", "workspace_limit_exceeded")}
        metadata.update(stdout_digest=adapters.stable_digest({"content": raw["stdout"]}),
            stderr_digest=adapters.stable_digest({"content": raw["stderr"]}))
        require(typed["metadata"]["process"] == metadata, "selected engine lifecycle metadata changed")
        invocations = [r for r in fixtures.invocations if r["case"] == label]
        admissions = [r for r in fixtures.admissions if r["case"] == label]
        require(len(invocations) == len(admissions) == 1
                and invocations[0]["input_files"] == rows[0]["tool_request"]["input_files"]
                and (admissions[0]["cpu_slots"], admissions[0]["memory_mb"], admissions[0]["child_process_slots"]) == (2, 128, 4)
                and 0 < admissions[0]["timeout"] <= 3, "selected engine request/admission profile differs")
    return {"case": label, "engine": engine, "selector": selector, "kind": kind,
        "request": req.to_dict(), "selector_arguments": argument, "attempt": attempt.to_dict(),
        "result": result.to_dict(), "original_outcome": original.to_dict() if original else None,
        "loaded_before": before, "loaded_after": loaded(owner), "discovery": discovery,
        "admission": [r for r in fixtures.admissions if r["case"] == label],
        "lifecycle": rows, "invocations": [r for r in fixtures.invocations if r["case"] == label],
        "operation_observations": phases, "elapsed_seconds": time.monotonic() - started, "status": "passed"}


def mismatch_case(fixtures, engine, other):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    owner = registry.default_backend_registry()
    label = engine + ":conflict:" + other
    fixtures.local.case, fixtures.local.engine, fixtures.local.kind = label, engine, "conflict"
    req = request(engine, label)
    try:
        owner.run(req, backend_id=other)
    except registry.BackendRegistryError as error:
        reason = str(error)
    else:
        raise AssertionError("mismatched selectors were not rejected")
    require(not loaded(owner) and not any(r["case"] == label for r in fixtures.discovery)
            and current_proof_operation() is None, "selector conflict initialized or probed a delegate")
    return {"case": label, "engine": engine, "kind": "selector_conflict", "request": req.to_dict(),
        "explicit_selector": other, "error": reason, "loaded_after": [], "status": "passed"}


def concurrent_cases(fixtures):
    from ipfs_datasets_py.logic.backends import registry
    owner = registry.default_backend_registry()
    require(not loaded(owner), "shared registry discovery initialized delegates")
    fixtures.block_concurrent = True
    values, errors, threads = {}, {}, []
    def worker(engine):
        try:
            values[engine] = run_case(owner, fixtures, engine, label="concurrent:" + engine)
        except BaseException:
            errors[engine] = traceback.format_exc()
    started = time.monotonic()
    try:
        for engine in ENGINES:
            thread = threading.Thread(target=worker, args=(engine,), name="controlled-registry-" + engine)
            threads.append(thread)
            thread.start()
        queued = None
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            snapshot = fixtures.owner.snapshot()
            live = [r for r in fixtures.invocations if r["case"].startswith("concurrent:")]
            if len(live) == 2 and snapshot["active_lease_count"] == 2 and snapshot["waiting_request_count"] == 1:
                queued = snapshot
                break
            if errors:
                break
            time.sleep(.002)
        require(queued is not None and queued["allocated"] == {"cpu_slots": 4, "memory_mb": 256}
                and queued["allocated_child_process_slots"] == 8, "third job did not queue behind two finite leases")
        released = time.monotonic()
        fixtures.gate.set()
        for thread in threads:
            thread.join(timeout=3)
        require(not any(t.is_alive() for t in threads) and not errors and set(values) == set(ENGINES),
                "shared-registry controlled workers failed: " + json.dumps(errors))
        invocations = [r for r in fixtures.invocations if r["case"].startswith("concurrent:")]
        require(len(invocations) == 3 and sum(r["started"] < released for r in invocations) == 2
                and sorted(loaded(owner)) == sorted(ENGINES), "queued engine was omitted, or a peer delegate initialized")
        return [values[e] for e in ENGINES], {"queued_snapshot": queued, "release_at_monotonic": released,
            "elapsed_seconds": time.monotonic() - started, "loaded_delegates": loaded(owner),
            "all_threads_joined": True, "scope": "Controlled queue observation, not native parallel speedup"}
    finally:
        fixtures.gate.set()
        for thread in threads:
            thread.join(timeout=3)
        fixtures.block_concurrent = False
        require(not any(t.is_alive() for t in threads), "owned concurrent worker leaked")


def main():
    from ipfs_datasets_py.logic.backends import registry
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "benchmark_sha256": sha(__file__), "cwd": str(Path.cwd())})
    result = {"schema": "hyper-registry-routing-controlled-benchmark@1", "status": "running",
        "source_pins_before": pins(), "cases": [], "checks": {}, "native_launches": 0, "shared_pool_accesses": 0,
        "scope": {"synthetic_output_discovery_pressure": True, "private_pool": True,
            "production_registry_factories_and_runners": True, "native_proof_claim": False,
            "native_speedup_claim": False, "hard_aggregate_containment_claim": False}}
    fixtures, started = Fixtures(directory), time.monotonic()
    try:
        with fixtures:
            result["private_config"], result["private_before"] = fixtures.owner.config.persisted_dict(), fixtures.before
            for engine in ENGINES:
                for selector in SELECTORS:
                    for kind in ("positive", "resource_failure"):
                        owner = registry.default_backend_registry()
                        require(not loaded(owner), "new registry discovery initialized delegates")
                        row = run_case(owner, fixtures, engine, selector, kind)
                        require(row["loaded_after"] == [engine], "single-engine route initialized extra delegates")
                        result["cases"].append(row)
                result["cases"].append(mismatch_case(fixtures, engine, ENGINES[(ENGINES.index(engine)+1)%3]))
                owner = registry.default_backend_registry()
                row = run_case(owner, fixtures, engine, kind="unavailable")
                require(row["loaded_after"] == [engine], "unavailable engine fell through to peers")
                result["cases"].append(row)
            for target in (LEGACY, ""):
                owner = registry.default_backend_registry()
                row = run_case(owner, fixtures, "hyperltl", target=target,
                    label="compatibility:" + ("legacy" if target else "default"))
                require(row["loaded_after"] == [LEGACY], "compatibility route changed its original delegate")
                result["cases"].append(row)
            rows, result["concurrency"] = concurrent_cases(fixtures)
            result["cases"].extend(rows)
        result["private_after"] = fixtures.after
        result["checks"].update(all29_cases_passed=len(result["cases"]) == 29,
            no_native_or_shared_attempts=not fixtures.native_attempts and not fixtures.shared_attempts,
            owned_work_drained=fixtures.after["active_lease_count"] == fixtures.after["waiting_request_count"] == 0,
            all_leases_released=all(lease.released for lease in fixtures.leases),
            all_workspaces_removed=all(not Path(row["path"]).exists() for row in fixtures.workspaces))
        result["status"] = "passed_controlled"
    except BaseException:
        result["status"], result["error"] = "failed", traceback.format_exc()
    finally:
        fixtures.stack.close()
        result["audit_sha256"] = {}
        for name in ("samples", "discovery", "invocations", "lifecycle", "admissions", "workspaces", "native_attempts", "shared_attempts"):
            path = directory / (name + ".json")
            write(path, getattr(fixtures, name))
            result["audit_sha256"][path.name] = sha(path)
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        result["elapsed_seconds"] = time.monotonic() - started
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed_controlled" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
