"""Controlled Hyper operation budgets, queue stops and split evidence publication.

Only discovery, host samples and executor responses are synthetic. Production
V2 engines, translation, managed admission and cleanup use fresh private pools.
No native process or shared scheduler is permitted. Timings measure controlled
Python/admission paths, not native proof throughput or parallel speedup.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch

import bench_hyper_default_admission as fixtures
import bench_hyper_registry_routing as previous
from bench_smt_operation_control import MIB, ROOT, require, sha, write

ENGINES = fixtures.ENGINES
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_operation_control.py"
ENV_KEYS = ("DOTNET_PROCESSOR_COUNT", "DOTNET_gcServer", "DOTNET_GCHeapHardLimit")
CASES = (tuple((engine, "healthy", repeat) for engine in ENGINES for repeat in range(2))
    + tuple((engine, kind, 0) for kind in ("queued_timeout", "queued_cancel", "pressure_recovery") for engine in ENGINES)
    + tuple(("split", "healthy", repeat) for repeat in range(2))
    + (("split", "cumulative_timeout", 0), ("split", "split_cancel", 0)))


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def request(engine, label):
    base = fixtures.request(engine, "standalone_v2", label)
    return replace(base, bounds=replace(base.bounds, timeout_ms=1500))


class Environment:
    """Own the fixture boundaries; never install an operation scope."""

    def __init__(self, directory, kind):
        self.directory, self.kind, self.stack = directory, kind, ExitStack()
        self.pressure = False
        self.stop = threading.Event()
        self.samples, self.admissions, self.leases, self.workspaces = [], [], [], []
        self.invocations, self.lifecycle, self.discovery = [], [], []
        self.native_attempts, self.shared_attempts = [], []

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.logic.backends.hyperproperties import adapters
        from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        pressured = replace(healthy, available_memory_mb=16)
        def sample():
            pressure = self.pressure
            host = pressured if pressure else healthy
            require(len(self.samples) < 4096, "fixture sampler exceeded finite history bound")
            self.samples.append({"at_monotonic": time.monotonic(), "pressure": pressure, "host": asdict(host)})
            return host
        def deny_native(*args, **kwargs):
            self.native_attempts.append(True)
            raise AssertionError("controlled operation benchmark forbids native execution")
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(True)
            raise AssertionError("controlled operation benchmark forbids shared scheduler resolution")
        self.stack.enter_context(patch.object(subprocess, "Popen", deny_native))
        self.stack.enter_context(patch.object(os, "system", deny_native))
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny_shared))
        config = scheduler.ResourceSchedulerConfig.for_proof_host(state_path=self.directory / "private-pool.json",
            proof_resource_sampler=sample, total_cpu_slots=2, total_memory_mb=128, total_child_process_slots=4,
            proof_memory_headroom_mb=32, lane_reservations={}, auto_renew_leases=False,
            proof_backoff_seconds=.02, poll_interval_seconds=.002)
        self.owner = scheduler.GlobalResourceScheduler(config)
        self.before = self.owner.snapshot()
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", lambda: self.owner))
        executable = str(Path(sys.executable).resolve())
        def resolve(backend):
            self.discovery.append(backend.engine.value)
            return executable
        self.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", resolve))
        self.stack.enter_context(patch.object(process.shutil, "which", lambda candidate, **kwargs:
            executable if candidate == executable else None))
        acquire = self.owner.acquire
        def observe_acquire(lane, **kwargs):
            operation = current_proof_operation()
            row = {"started": time.monotonic(), "lane": str(lane),
                "operation_deadline": operation.deadline if operation else None,
                "fixture_holder": kwargs.get("request_id") == "fixture:holder",
                **{k: kwargs.get(k) for k in ("cpu_slots", "memory_mb", "child_process_slots", "timeout")}}
            self.admissions.append(row)
            try:
                lease = acquire(lane, **kwargs)
                self.leases.append(lease)
                row.update(granted=time.monotonic(), lease_id=lease.lease_id, wait_seconds=lease.wait_seconds)
                return lease
            except Exception as error:
                row.update(error_type=type(error).__name__, error=str(error), ended=time.monotonic())
                raise
        self.stack.enter_context(patch.object(self.owner, "acquire", observe_acquire))
        run = admission.ResourceAdmittedToolRunner.run
        def observe_run(runner, tool, **kwargs):
            operation = current_proof_operation()
            require(operation is not None and kwargs.get("cancellation") is operation,
                    "canonical V2 check did not forward its actual operation")
            row = {"deadline": operation.deadline, "explicit_current_operation_forwarded": True,
                "tool_request": {"argv": list(tool.argv), "limits": asdict(tool.limits),
                    "input_files": dict(tool.input_files),
                    "runtime_environment": {k: tool.environment[k] for k in ENV_KEYS if k in tool.environment}}}
            self.lifecycle.append(row)
            raw = run(runner, tool, **kwargs)
            row["result"] = raw.to_dict()
            return raw
        self.stack.enter_context(patch.object(admission.ResourceAdmittedToolRunner, "run", observe_run))
        write_inputs = process.BoundedToolRunner._write_inputs
        def observe_write(workspace, tool):
            self.workspaces.append(str(workspace))
            return write_inputs(workspace, tool)
        self.stack.enter_context(patch.object(process.BoundedToolRunner, "_write_inputs", staticmethod(observe_write)))
        def execute(executor, invocation, cancellation=None):
            engine = "autohyper" if "--explicit" in invocation.argv else "mchyper" if "-pdr" in invocation.argv else "hyperltl"
            operation = current_proof_operation()
            require(operation is not None and cancellation is not None and not cancellation.is_set(),
                    "synthetic executor lacks live operation/admission cancellation")
            state, limits = self.owner.snapshot(), invocation.limits
            require(state["active_lease_count"] == state["active_root_lease_count"] == 1
                    and state["allocated"] == {"cpu_slots": 2, "memory_mb": 128}
                    and state["allocated_child_process_slots"] == 4, "private managed reservation differs")
            require(0 < limits.timeout_seconds <= 1.5 and 0 < limits.cpu_seconds <= 1.5
                    and limits.resident_memory_bytes == 128*MIB
                    and limits.memory_bytes == (4096 if engine == "autohyper" else 2048)*MIB
                    and limits.max_output_bytes == 65536 and limits.max_workspace_bytes == 16_777_216
                    and limits.enforce_file_size_limit is (engine != "autohyper"), "managed finite profile differs")
            require("--version" not in invocation.argv and "GHCRTS" not in invocation.environment,
                    "unexpected version invocation or inherited RTS settings")
            if engine == "autohyper":
                require({k: invocation.environment.get(k) for k in ENV_KEYS} == dict(zip(ENV_KEYS, ("1", "0", "4000000"))),
                        "AutoHyper runtime controls differ")
            row = {"engine": engine, "started": time.monotonic(), "deadline": operation.deadline,
                "argv": list(invocation.argv), "limits": asdict(limits), "snapshot": state,
                "workspace": str(invocation.cwd), "synthetic_executor": True,
                "runtime_environment": {k: invocation.environment[k] for k in ENV_KEYS if k in invocation.environment},
                "input_files": {p.name: p.read_text() for p in invocation.cwd.iterdir() if p.is_file()}}
            self.invocations.append(row)
            if self.kind == "cumulative_timeout":
                row["synthetic_callback_delay_seconds"] = .23
                time.sleep(.23)
            if self.kind == "split_cancel" and len(self.invocations) == 2:
                self.stop.set()
                row["caller_cancellation_set_at"] = time.monotonic()
            row["completed"] = time.monotonic()
            return process.RawProcessResult(returncode=0, stdout=fixtures.POSITIVE[engine])
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", execute))
        return self

    def __exit__(self, *args):
        self.pressure = False
        self.after = self.owner.snapshot()
        return self.stack.__exit__(*args)


def invoke(engine, kind, repeat, req, environment):
    from ipfs_datasets_py.logic.backends import resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
    require(sys.getprofile() is None and budget.current_proof_operation() is None, "unexpected ambient profiler/operation")
    observed = {"operation_observations": [], "internal_results": [], "original_outcomes": [], "forbidden_phases": []}
    original = req.to_dict()
    def observe(frame, event, value):
        if event not in {"call", "return"}:
            return
        operation = budget.current_proof_operation()
        if frame.f_code in {adapters._operation_checkpoint.__code__, v2._operation_checkpoint.__code__} and event == "call":
            require(operation is not None, "production phase escaped engine-owned scope")
            observed["operation_observations"].append({"phase": frame.f_locals["phase"],
                "at_monotonic": time.monotonic(), "deadline": operation.deadline})
        if event == "call" and frame.f_code in {adapters.HyperpropertyBackend._tool_version.__code__,
                adapters.parse_hyper_counterexample.__code__, adapters.replay_hyper_counterexample.__code__}:
            observed["forbidden_phases"].append(frame.f_code.co_name)
        if frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            backend = frame.f_locals["self"]
            require(backend._managed_runner and type(backend._runner) is admission.ResourceAdmittedToolRunner
                    and operation is not None, "default managed runner/scope replaced")
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                observed["original_outcomes"].append(value)
        if event == "return" and frame.f_code is v2.HyperExecutionEngineV2.execute.__code__ and isinstance(value, v2.HyperExecutionResultV2):
            observed["internal_results"].append(value)
    ctor = {"cancellation": environment.stop} if kind == "queued_cancel" else {}
    if kind == "healthy" and repeat == 1:
        ctor["operation_timeout_ms"] = 1000
    api = v2.HyperExecutionEngineV2(**ctor)
    controls = ({"operation_timeout_ms": 300} if kind == "queued_timeout" else
                {"operation_timeout_ms": 400} if kind == "cumulative_timeout" else {})
    if kind in {"pressure_recovery", "split_cancel"}:
        controls["cancellation"] = environment.stop
    result = None
    interrupted = None
    started = time.monotonic()
    sys.setprofile(observe)
    try:
        if engine == "split":
            result = api.execute_split_capabilities(req.document, request_id_prefix=req.request_id,
                system_models={"mchyper": "aag 0 0 0 0 0\n"}, bounds=req.bounds, **controls)
        else:
            result = api.execute(req, **controls)
    except budget.ProofOperationInterrupted as error:
        interrupted = error
    finally:
        sys.setprofile(None)
        observed.update(elapsed_call_seconds=time.monotonic()-started,
            ambient_restored=budget.current_proof_operation() is None,
            original_request_unchanged=req.to_dict() == original)
    require(observed["ambient_restored"] and observed["original_request_unchanged"], "operation/request leaked")
    expected = (budget.ProofOperationTimeout if kind in {"queued_timeout", "cumulative_timeout"} else
                budget.ProofOperationCancelled if kind in {"queued_cancel", "split_cancel"} else None)
    require(type(interrupted) is expected if expected else interrupted is None, "typed interruption differs")
    require((result is None) is bool(expected), "stopped API returned late/partial evidence")
    observed.update(returned=result, interruption=interrupted.to_dict() if interrupted else None,
        interruption_type=type(interrupted).__name__ if interrupted else None,
        api_result_returned=result is not None,
        controls={"constructor_timeout_ms": ctor.get("operation_timeout_ms"),
            "call_timeout_ms": controls.get("operation_timeout_ms"),
            "constructor_cancellation": "cancellation" in ctor, "call_cancellation": "cancellation" in controls})
    return observed


def queued_call(engine, kind, repeat, req, environment):
    holder = None
    if kind != "pressure_recovery":
        holder = environment.owner.acquire("proof", cpu_slots=2, memory_mb=128, child_process_slots=4,
            timeout=.5, request_id="fixture:holder")
    else:
        environment.pressure = True
    box = {}
    def work():
        try:
            box["value"] = invoke(engine, kind, repeat, req, environment)
        except BaseException as error:
            box["error"] = error
    thread = threading.Thread(target=work, name="controlled-hyper-operation")
    thread.start()
    try:
        observed = None
        until = time.monotonic()+1
        while time.monotonic() < until and thread.is_alive():
            state = environment.owner.snapshot()
            if state["waiting_request_count"] == 1:
                if kind != "pressure_recovery" or state["proof_backoff"].get("reason"):
                    observed = state
                    break
            time.sleep(.002)
        require(observed is not None and not environment.invocations and not environment.workspaces,
                "did not observe durable waiter before any workspace/execution")
        require(observed["active_lease_count"] == (0 if kind == "pressure_recovery" else 1), "unexpected queued holder count")
        action_at = time.monotonic()
        if kind == "queued_cancel":
            environment.stop.set()
        elif kind == "pressure_recovery":
            require(observed["proof_backoff"]["until"] > time.time(), "pressure backoff was not active")
            environment.pressure = False
        thread.join(timeout=2)
        require(not thread.is_alive(), "operation worker exceeded finite join bound")
        if "error" in box:
            raise box["error"]
        if kind == "pressure_recovery":
            require(environment.invocations and environment.invocations[0]["started"] >= action_at,
                    "execution preceded pressure recovery")
        box["value"]["queue_observation"] = {"snapshot": observed, "action_at_monotonic": action_at,
            "action": "pressure_released" if kind == "pressure_recovery" else "cancelled" if kind == "queued_cancel" else "await_deadline",
            "worker_joined": True, "no_preparation_before_queue_observation": True}
        return box["value"]
    finally:
        environment.pressure = False
        environment.stop.set()
        if holder is not None:
            holder.release()
        thread.join(timeout=2)
        require(not thread.is_alive(), "private worker leaked")


def validate(observed, req, engine, kind, environment):
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    require(observed["operation_observations"] and not observed["forbidden_phases"], "missing scope or unexpected version/replay")
    deadlines = {p["deadline"] for p in observed["operation_observations"]}
    require(len(deadlines) == 1, "split/phase deadlines were refreshed")
    deadline = next(iter(deadlines))
    require(all(r["deadline"] == deadline for r in environment.lifecycle + environment.invocations), "native deadline differs")
    expected_calls = 0 if kind.startswith("queued_") else 2 if kind in {"cumulative_timeout", "split_cancel"} else 3 if engine == "split" else 1
    require(len(environment.invocations) == len(environment.workspaces) == expected_calls, "unexpected executor/workspace count")
    require(len(environment.lifecycle) == (1 if kind.startswith("queued_") else expected_calls), "unexpected runner count")
    returned = observed.pop("returned")
    results = list(returned.values()) if isinstance(returned, dict) else [returned] if returned else []
    if engine == "split" and returned is not None:
        require({key.value for key in returned} == set(ENGINES), "successful split lost independent engine results")
    if kind in {"cumulative_timeout", "split_cancel"}:
        require(len(observed["internal_results"]) == len(observed["original_outcomes"]) == 1 and not results,
                "interrupted split lost first completion or returned partial evidence")
    elif kind.startswith("queued_"):
        require(not observed["internal_results"] and not observed["original_outcomes"], "queued stop constructed evidence")
    else:
        require(len(observed["internal_results"]) == len(observed["original_outcomes"]) == expected_calls,
                "successful execution did not project each engine")
    for result in observed["internal_results"]:
        wire, provider = result.to_dict(), result.engine.value
        require(result.request.bounds == req.bounds and result.backend_result.bounds == req.bounds
                and result.evidence.bounds.timeout_ms == req.bounds.timeout_ms
                and result.evidence.request_digest == v2._digest_of(result.request.to_dict())
                and wire["hyperproperty_established"] and not wire["is_proved"] and not wire["is_theorem_authority"],
                "declared bounds/digest/authority changed")
        if engine != "split":
            require(result.request.to_dict() == req.to_dict() and provider == engine, "single result rebound request/engine")
        else:
            require(result.request.request_id == req.request_id+":"+provider, "split request identity differs")
        require(all(not result.evidence.establishes_other_engine(other) for other in ENGINES if other != provider),
                "result established another engine")
    for original in observed["original_outcomes"]:
        receipt, translation = original.receipt, original.translation
        require(original.result.status.value == "satisfied" and receipt.external_tool_proof
                and not receipt.authorizes_universal_proof and receipt.counterexample is None and receipt.tool_version == ""
                and receipt.timeout_seconds == req.bounds.timeout_ms/1000
                and translation is not None and translation.quantifier_order.matches_document(req.document)
                and receipt.document_digest == translation.document_digest
                and receipt.translation_digest == translation.translation_digest
                and original.request_digest == translation.document_digest, "original receipt/source binding differs")
    active_admissions = [r for r in environment.admissions if not r["fixture_holder"]]
    require(len(active_admissions) == len(environment.lifecycle) and all(r["operation_deadline"] == deadline
            and (r["cpu_slots"], r["memory_mb"], r["child_process_slots"]) == (2, 128, 4)
            and 0 < r["timeout"] <= 1.5 for r in active_admissions), "admission deadline/profile differs")
    native_gates = [row for row in observed["operation_observations"] if row["phase"] == "before hyper native execution"]
    require(len(native_gates) == len(environment.lifecycle) and all(
        0 < call["tool_request"]["limits"]["timeout_seconds"] <= deadline-gate["at_monotonic"]
        for call, gate in zip(environment.lifecycle, native_gates)), "native limit did not consume remaining operation budget")
    for index, invocation in enumerate(environment.invocations):
        lifecycle = environment.lifecycle[index]
        raw, tool = lifecycle["result"], lifecycle["tool_request"]
        require(raw["pid"] is None and raw["workspace_cleaned"] and raw["returncode"] == 0
                and raw["stdout"] == fixtures.POSITIVE[invocation["engine"]]
                and not any(raw[k] for k in ("resource_exhausted", "unavailable", "output_truncated",
                    "workspace_limit_exceeded", "process_tree_terminated")), "synthetic lifecycle differs")
        require(invocation["input_files"] == tool["input_files"] and invocation["argv"] == tool["argv"]
                and invocation["limits"]["timeout_seconds"] <= tool["limits"]["timeout_seconds"] <= 1.5,
                "admitted inputs/argv/remaining wall limit changed incorrectly")
        if index < len(observed["original_outcomes"]):
            original = observed["original_outcomes"][index]
            translation, provider = original.translation, invocation["engine"]
            executable = str(Path(sys.executable).resolve())
            expected_argv = ([executable, "-f", "property.hltl"] if provider == "hyperltl" else
                [executable, "--explicit", "system.explicit", "property.hltl"] if provider == "autohyper" else
                [executable, "-f", translation.formula_text, "system.aag", "-pdr", "-cex", "--cex_file", "counterexample.txt", "-v", "1"])
            require(tool["argv"] == expected_argv and all(tool["input_files"].get(k) == v
                for k, v in translation.auxiliary_files.items()), "default translated engine command/inputs differ")
            metadata = {key: raw[key] for key in ("cancelled", "command", "error", "output_truncated", "process_tree_terminated",
                "returncode", "resource_exhausted", "timed_out", "termination_reason", "unavailable", "workspace_cleaned", "workspace_limit_exceeded")}
            metadata.update(stdout_digest=adapters.stable_digest({"content": raw["stdout"]}),
                stderr_digest=adapters.stable_digest({"content": raw["stderr"]}))
            require(original.result.to_dict()["metadata"]["process"] == metadata, "original process lifecycle metadata differs")
        if kind == "cumulative_timeout" and index == 1:
            require(raw["timed_out"], "late native callback lost ambient timeout flag")
        elif kind == "split_cancel" and index == 1:
            require(raw["cancelled"], "late native callback lost cancellation flag")
        else:
            require(not raw["timed_out"] and not raw["cancelled"], "healthy callback unexpectedly stopped")
    if kind.startswith("queued_"):
        raw = environment.lifecycle[0]["result"]
        require(raw["pid"] is None and raw["returncode"] is None and not raw["stdout"] and raw["workspace_cleaned"],
                "queued stop executed/prepared work")
        require(raw["timed_out"] if kind == "queued_timeout" else raw["cancelled"], "queued stop flag was lost")
    observed["returned_result"] = ({k.value: value.to_dict() for k, value in returned.items()}
        if isinstance(returned, dict) else returned.to_dict() if returned else None)
    observed["internal_results"] = [result.to_dict() for result in observed["internal_results"]]
    observed["original_outcomes"] = [result.to_dict() for result in observed["original_outcomes"]]


def run_case(spec, directory):
    engine, kind, repeat = spec
    label = ":".join(map(str, spec))
    case_dir = directory / label.replace(":", "-")
    case_dir.mkdir()
    req = request("hyperltl" if engine == "split" else engine, label)
    environment = Environment(case_dir, kind)
    row = {"case": label, "engine": engine, "kind": kind, "repeat": repeat,
        "request": req.to_dict(), "status": "running"}
    started = time.monotonic()
    try:
        with environment:
            observed = (queued_call(engine, kind, repeat, req, environment) if kind.startswith("queued_") or kind == "pressure_recovery"
                else invoke(engine, kind, repeat, req, environment))
            validate(observed, req, engine, kind, environment)
            row.update(observed)
        require(environment.after["active_lease_count"] == environment.after["waiting_request_count"] == 0
                and all(lease.released for lease in environment.leases)
                and all(not Path(path).exists() for path in environment.workspaces), "private work did not drain")
        require(not environment.native_attempts and not environment.shared_attempts, "denied execution boundary crossed")
        row["status"] = "passed"
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        environment.stack.close()
        row.update(elapsed_seconds=time.monotonic()-started, admissions=environment.admissions,
            lifecycle=environment.lifecycle, invocations=environment.invocations, sample_history=environment.samples,
            discovery=environment.discovery, workspaces=environment.workspaces,
            private_config=environment.owner.config.persisted_dict() if hasattr(environment, "owner") else None,
            private_before=getattr(environment, "before", None), private_after=getattr(environment, "after", None),
            native_launch_attempts=environment.native_attempts, shared_scheduler_attempts=environment.shared_attempts,
            workspace_cleanup=all(not Path(path).exists() for path in environment.workspaces),
            leases_released=all(lease.released for lease in environment.leases))
        write(case_dir / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "hyper-operation-controlled-benchmark@1", "status": "running", "cases": [], "checks": {},
        "source_pins_before": pins(), "native_launches": 0, "shared_pool_accesses": 0, "timings": [],
        "scope": {"synthetic_executor_output": True, "synthetic_discovery": True, "synthetic_host_pressure": True,
            "private_fixture_pools": True, "default_managed_admission": True, "engine_owned_operation_scope": True,
            "injected_operation_scope": False, "native_proof_claim": False, "native_parallel_scaling_claim": False,
            "actual_host_pressure_tested": False, "native_preemption_tested": False,
            "hard_aggregate_containment_claim": False, "callback_stops_are_cooperative": True}}
    started = time.monotonic()
    try:
        for spec in CASES:
            row = run_case(spec, directory)
            result["cases"].append(row)
            write(directory / "partial.json", result)
            require(row["status"] == "passed", "controlled case failed: "+row["case"])
        for engine in (*ENGINES, "split"):
            rows = [row for row in result["cases"] if row["engine"] == engine and row["kind"] == "healthy"]
            samples = [row["elapsed_call_seconds"] for row in rows]
            result["timings"].append({"engine": engine, "scope": "Controlled synchronous API latency; synthetic executor; no speedup claim",
                "raw_samples_seconds": samples, "min_seconds": min(samples), "median_seconds": statistics.median(samples),
                "max_seconds": max(samples)})
        result["checks"].update(all19_cases_passed=len(result["cases"]) == 19,
            stopped_calls_returned_no_result=all(not row["api_result_returned"] and row["returned_result"] is None
                for row in result["cases"] if row["interruption"]),
            original_requests_unchanged=all(row["original_request_unchanged"] for row in result["cases"]),
            ambient_operations_restored=all(row["ambient_restored"] for row in result["cases"]),
            no_native_attempts=all(not row["native_launch_attempts"] for row in result["cases"]),
            no_shared_pool_attempts=all(not row["shared_scheduler_attempts"] for row in result["cases"]),
            owned_work_drained=all(row["workspace_cleanup"] and row["leases_released"] for row in result["cases"]))
        result["status"] = "passed_controlled"
    except BaseException:
        result.update(status="failed", error=traceback.format_exc())
    finally:
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        result["elapsed_seconds"] = time.monotonic()-started
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed_controlled" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
