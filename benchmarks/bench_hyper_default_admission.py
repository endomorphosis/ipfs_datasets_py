"""Controlled HyperLTL-family admission, lifecycle gates and recovery timings.

Solver output, executable discovery and host samples are synthetic. Default
backends, finite resource admission and workspace cleanup run against fresh
private pools. Native processes and shared scheduler resolution are denied.
Timings measure this controlled admission path, not native proving or scaling.
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

import bench_tamarin_claim_binding as retained
from bench_generic_prover_admission import request as old_request
from bench_smt_operation_control import MIB, ROOT, require, sha, write

ENGINES = ("hyperltl", "autohyper", "mchyper")
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_resource_admission.py"
DEPENDENCIES = ("logic/backends/hyperproperties/adapters.py", "logic/backends/hyperproperties/execution_v2.py",
    "logic/software_verification/hyperproperties.py")
POSITIVE = {"hyperltl": "sat\n", "autohyper": "SAT\n", "mchyper": "Property proved. Time = 0.01 sec\n"}
CASES = tuple((engine, route, kind, 0) for engine in ENGINES
    for route in ("direct", "standalone_v2", *(("registry",) if engine == "hyperltl" else ()))
    for kind in ("positive", "resource_exhausted")) + tuple((engine, "direct", "capacity_refusal", 0)
    for engine in ENGINES) + tuple((engine, "direct", "pressure_recovery", repeat)
    for engine in ENGINES for repeat in range(3))


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST),
        **{str(ROOT / "ipfs_datasets_py" / p): sha(ROOT / "ipfs_datasets_py" / p) for p in DEPENDENCIES}}


def document():
    from ipfs_datasets_py.logic.software_verification.hyperproperties import (
        HyperpropertyIR, InformationFlowPolicy, ObservationKind, ObservationSpec, SecurityLevel, SelfCompositionBound)
    policy = InformationFlowPolicy(policy_id="policy:controlled-hyper", low_input_fields=("user",),
        high_input_fields=("secret",), observation_fields=("status",),
        observations=(ObservationSpec("observation:status", "status", ObservationKind.OUTPUT, SecurityLevel.LOW),))
    return HyperpropertyIR.noninterference_document(policy=policy,
        bound=SelfCompositionBound("bound:controlled-hyper", max_traces=2, max_pairs=4, max_steps=4))


def bounds():
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
    return ExecutionBounds(timeout_ms=2000, max_memory_bytes=128*MIB, max_output_bytes=65536, max_steps=4)


def request(engine, route, case):
    require(engine in ENGINES and route in {"direct", "registry", "standalone_v2"}, "unknown controlled route")
    model = "aag 0 0 0 0 0\n" if engine == "mchyper" else None
    if route == "standalone_v2":
        from ipfs_datasets_py.logic.backends.hyperproperties.execution_v2 import HyperExecutionRequestV2
        return HyperExecutionRequestV2(request_id="request:controlled-hyper:" + case,
            provider=engine, document=document(), system_model=model, bounds=bounds())
    from ipfs_datasets_py.logic.ir_core.protocols import QueryKind
    base = old_request("hyperproperty", memory_mb=128, timeout_ms=2000)
    payload = {"document": document().to_dict(), "allow_fallback": False}
    if model is not None:
        payload["system_model"] = model
    return replace(base, request_id="request:controlled-hyper:" + case, bounds=bounds(),
        query_kind=QueryKind.SATISFIABILITY, payload=payload,
        requested_backend_id="hyperltl_autohyper_mchyper" if route == "registry" else engine)


class FixtureEnvironment:
    """Explicit synthetic boundaries around the production admission path."""

    def __init__(self, path, engine, kind):
        self.path, self.engine, self.kind = path, engine, kind
        self.stack = ExitStack()
        self.pressure = False
        self.samples, self.invocations, self.lifecycle, self.admissions, self.workspaces = [], [], [], [], []
        self.leases, self.discovery, self.native_attempts, self.shared_attempts = [], [], [], []
        self.stop = threading.Event()

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.logic.backends.hyperproperties import adapters
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        self.healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        self.pressured = replace(self.healthy, available_memory_mb=16)
        def sample():
            pressure = self.pressure
            host = self.pressured if pressure else self.healthy
            require(len(self.samples) < 2048, "bounded fixture sampler exhausted")
            self.samples.append({"at_monotonic": time.monotonic(), "pressure": pressure, "host": asdict(host)})
            return host
        def deny_native(*args, **kwargs):
            self.native_attempts.append(True)
            raise AssertionError("controlled hyper benchmark forbids native process creation")
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(True)
            raise AssertionError("controlled hyper benchmark forbids shared scheduler resolution")
        self.stack.enter_context(patch.object(subprocess, "Popen", deny_native))
        self.stack.enter_context(patch.object(os, "system", deny_native))
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny_shared))
        config = scheduler.ResourceSchedulerConfig.for_proof_host(state_path=self.path,
            proof_resource_sampler=sample, total_cpu_slots=2,
            total_memory_mb=64 if self.kind == "capacity_refusal" else 128, total_child_process_slots=4,
            proof_memory_headroom_mb=32, lane_reservations={}, auto_renew_leases=False,
            proof_backoff_seconds=.02, poll_interval_seconds=.002)
        self.owner = scheduler.GlobalResourceScheduler(config)
        self.before = self.owner.snapshot()
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", lambda: self.owner))
        def resolve(backend):
            self.discovery.append(backend.engine.value)
            return str(Path(sys.executable).resolve())
        self.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", resolve))
        self.stack.enter_context(patch.object(process.shutil, "which", lambda executable, **kwargs:
            str(Path(sys.executable).resolve()) if executable == str(Path(sys.executable).resolve()) else None))
        acquire = self.owner.acquire
        def observed_acquire(lane, **kwargs):
            row = {"lane": lane, "started": time.monotonic(),
                **{key: kwargs[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "timeout")},
                "parent_lease_absent": kwargs["parent_lease"] is None,
                "cancellation_signal_present": kwargs["cancel_event"] is not None}
            self.admissions.append(row)
            try:
                lease = acquire(lane, **kwargs)
                self.leases.append(lease)
                row.update(lease_id=lease.lease_id, wait_seconds=lease.wait_seconds, granted=time.monotonic())
                return lease
            except Exception as error:
                row.update(error_type=type(error).__name__, error=str(error), ended=time.monotonic())
                raise
        self.stack.enter_context(patch.object(self.owner, "acquire", observed_acquire))
        run = admission.ResourceAdmittedToolRunner.run
        def observe_run(runner, tool, **kwargs):
            raw = run(runner, tool, **kwargs)
            self.lifecycle.append({"tool_request": {"argv": list(tool.argv), "limits": asdict(tool.limits),
                "input_files": dict(tool.input_files), "environment": dict(tool.environment)}, "result": raw.to_dict()})
            return raw
        self.stack.enter_context(patch.object(admission.ResourceAdmittedToolRunner, "run", observe_run))
        write_inputs = process.BoundedToolRunner._write_inputs
        def observe_write(workspace, tool):
            self.workspaces.append(str(workspace))
            return write_inputs(workspace, tool)
        self.stack.enter_context(patch.object(process.BoundedToolRunner, "_write_inputs", staticmethod(observe_write)))
        def execute(executor, invocation, cancellation=None):
            require(cancellation is not None and not cancellation.is_set(), "missing live admitted cancellation signal")
            snapshot = self.owner.snapshot()
            require(snapshot["active_lease_count"] == snapshot["active_root_lease_count"] == 1
                    and snapshot["allocated"] == {"cpu_slots": 2, "memory_mb": 128}
                    and snapshot["allocated_child_process_slots"] == 4, "default lease profile differs")
            limits = invocation.limits
            require(0 < limits.timeout_seconds <= 2 and 0 < limits.cpu_seconds <= 2
                    and limits.resident_memory_bytes == 128*MIB
                    and limits.memory_bytes == (4096 if self.engine == "autohyper" else 2048)*MIB
                    and limits.max_output_bytes == 65536 and limits.max_workspace_bytes == 16_777_216
                    and limits.enforce_file_size_limit is (self.engine != "autohyper"),
                    "managed finite profile or V2 bound forwarding differs")
            if self.engine == "autohyper":
                require(all(invocation.environment.get(k) == v for k, v in {
                    "DOTNET_PROCESSOR_COUNT": "1", "DOTNET_gcServer": "0", "DOTNET_GCHeapHardLimit": "4000000"}.items()),
                    "AutoHyper managed runtime controls differ")
            require("--version" not in invocation.argv, "default execution launched a hidden version phase")
            files = {str(p.relative_to(invocation.cwd)): p.read_text() for p in invocation.cwd.iterdir() if p.is_file()}
            self.invocations.append({"at_monotonic": time.monotonic(), "argv": list(invocation.argv),
                "limits": asdict(limits), "environment": dict(invocation.environment), "workspace": str(invocation.cwd),
                "input_files": files, "snapshot": snapshot, "synthetic_executor": True})
            return process.RawProcessResult(returncode=0, stdout=POSITIVE[self.engine],
                resource_exhausted=self.kind == "resource_exhausted")
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", execute))
        return self

    def __exit__(self, *args):
        self.pressure = False
        self.after = self.owner.snapshot()
        return self.stack.__exit__(*args)


def invoke(engine, route, req, environment):
    from ipfs_datasets_py.logic.backends import registry, resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    require(sys.getprofile() is None and current_proof_operation() is None, "unexpected ambient profiler/operation")
    captured, forbidden, phases = [], [], []
    def observe(frame, event, value):
        if event == "call" and frame.f_code in {adapters.HyperpropertyBackend._tool_version.__code__,
                adapters.parse_hyper_counterexample.__code__, adapters.replay_hyper_counterexample.__code__}:
            forbidden.append(frame.f_code.co_name)
        if event in {"call", "return"} and frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            selected = frame.f_locals["self"]
            require(selected.engine.value == engine and selected._managed_runner
                    and type(selected._runner) is admission.ResourceAdmittedToolRunner,
                    "wrong engine or default admitted runner was replaced")
            operation = current_proof_operation()
            phases.append({"event": event, "engine": selected.engine.value,
                "deadline": operation.deadline if operation else None})
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                captured.append(value)
    attempt = None
    sys.setprofile(observe)
    try:
        if route == "registry":
            attempt, returned = registry.default_backend_registry().run(req)
        elif route == "standalone_v2":
            returned = v2.HyperExecutionEngineV2().execute(req)
        else:
            cls = {"hyperltl": adapters.HyperLTLBackend, "autohyper": adapters.AutoHyperBackend, "mchyper": adapters.MCHyperBackend}[engine]
            returned = cls().run(req, cancellation=environment.stop if environment.kind == "pressure_recovery" else None)
    finally:
        sys.setprofile(None)
    require(current_proof_operation() is None and len(captured) == 1 and not forbidden,
            "unexpected version/replay phase or leaked operation")
    return returned, attempt, captured[0], phases


def pressure_recovery(engine, req, environment):
    box = {}
    def work():
        try:
            box["returned"] = invoke(engine, "direct", req, environment)
        except BaseException as error:
            box["error"] = error
    environment.pressure = True
    thread = threading.Thread(target=work, name="controlled-hyper-recovery")
    thread.start()
    observed = None
    try:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            state = environment.owner.snapshot()
            if state["waiting_request_count"] == 1 and state["proof_backoff"].get("reason"):
                observed = state
                break
            if not thread.is_alive():
                break
            time.sleep(.002)
        require(observed is not None and observed["active_lease_count"] == 0
                and observed["proof_backoff"]["until"] > time.time()
                and not environment.workspaces and not environment.invocations,
                "pressure did not produce an actual queued/backoff state before preparation")
        released = time.monotonic()
        environment.pressure = False
        thread.join(timeout=2)
        require(not thread.is_alive(), "private recovery worker did not complete its finite request")
        if "error" in box:
            raise box["error"]
        require(environment.invocations and environment.invocations[0]["at_monotonic"] >= released,
                "synthetic execution preceded pressure release")
        return box["returned"], {"queued_snapshot": observed, "pressure_released_at_monotonic": released,
            "worker_joined": True, "no_workspace_or_executor_before_recovery": True}
    finally:
        environment.pressure = False
        if thread.is_alive():
            environment.stop.set()
            thread.join(timeout=2)
        require(not thread.is_alive(), "owned private recovery thread leaked")


def run_case(spec, directory):
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters
    engine, route, kind, repeat = spec
    label = ":".join(map(str, spec))
    req = request(engine, route, label)
    environment = FixtureEnvironment(directory / (label.replace(":", "-") + ".json"), engine, kind)
    started = time.monotonic()
    row = {"case": label, "engine": engine, "route": route, "kind": kind, "repeat": repeat,
        "request": req.to_dict(), "status": "running"}
    try:
        with environment:
            if kind == "pressure_recovery":
                returned, row["recovery"] = pressure_recovery(engine, req, environment)
            else:
                returned = invoke(engine, route, req, environment)
            result, attempt, original, phases = returned
            wire, typed, receipt = result.to_dict(), original.result.to_dict(), original.receipt.to_dict()
            positive = kind in {"positive", "pressure_recovery"}
            require(original.result.bounds == bounds() and typed["status"] == ("satisfied" if positive else "error")
                    and typed["authority"] == "hyperproperty" and receipt["engine"] == engine
                    and receipt["external_tool_proof"] is positive and not receipt["authorizes_universal_proof"]
                    and receipt["counterexample"] is None and receipt["tool_version"] == "",
                    "resource gate, bounds, engine identity or authority differs")
            translation = original.translation
            require(translation is not None and translation.quantifier_order.matches_document(document())
                    and receipt["translation_digest"] == translation.translation_digest
                    and receipt["document_digest"] == translation.document_digest
                    and original.request_digest == (translation.document_digest if route == "standalone_v2" else req.digest),
                    "request/document/translation binding differs")
            if route == "registry":
                require(result.status.value == ("unknown" if positive else "error")
                        and attempt.status.value == ("succeeded" if positive else "failed")
                        and result.payload.to_dict()["result"] == typed
                        and attempt.request_digest == result.request_digest == req.digest
                        and result.attempt_digest == attempt.digest, "HyperLTL registry projection differs")
            elif route == "standalone_v2":
                from ipfs_datasets_py.logic.backends.hyperproperties.execution_v2 import _digest_of
                require(wire["engine"] == engine and wire["backend_result"] == typed
                        and wire["hyperproperty_established"] is positive
                        and wire["evidence"]["request_digest"] == _digest_of(req.to_dict())
                        and not wire["is_proved"] and not wire["is_theorem_authority"], "V2 promoted or misbound evidence")
                for other in ENGINES:
                    if other != engine:
                        require(not result.evidence.establishes_other_engine(other), "one engine established another's capability")
            require(len(environment.lifecycle) == len(environment.admissions) == 1, "unexpected extra execution/version/admission phase")
            lifecycle = environment.lifecycle[0]
            tool = lifecycle["tool_request"]
            executable = str(Path(sys.executable).resolve())
            expected_argv = ([executable, "-f", "property.hltl"] if engine == "hyperltl" else
                [executable, "--explicit", "system.explicit", "property.hltl"] if engine == "autohyper" else
                [executable, "-f", translation.formula_text, "system.aag", "-pdr", "-cex", "--cex_file", "counterexample.txt", "-v", "1"])
            require(tool["argv"] == expected_argv
                    and all(tool["input_files"].get(k) == v for k, v in translation.auxiliary_files.items())
                    and set(environment.discovery) == {engine}, "selected engine's default inputs/command changed")
            raw = lifecycle["result"]
            require(raw["pid"] is None and raw["workspace_cleaned"] and not any(raw[k] for k in
                ("timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded", "process_tree_terminated")),
                "unexpected controlled lifecycle failure")
            require(raw["resource_exhausted"] is (not positive), "resource exhaustion flag lost")
            expected_process = {k: raw[k] for k in ("cancelled", "command", "error", "output_truncated",
                "process_tree_terminated", "returncode", "resource_exhausted", "timed_out", "termination_reason",
                "unavailable", "workspace_cleaned", "workspace_limit_exceeded")}
            expected_process.update(stdout_digest=adapters.stable_digest({"content": raw["stdout"]}),
                stderr_digest=adapters.stable_digest({"content": raw["stderr"]}))
            require(typed["metadata"]["process"] == expected_process, "exact raw lifecycle metadata changed")
            admission = environment.admissions[0]
            require((admission["cpu_slots"], admission["memory_mb"], admission["child_process_slots"]) == (2, 128, 4)
                    and 0 < admission["timeout"] <= 2 and admission["parent_lease_absent"], "default reservation differs")
            if kind == "capacity_refusal":
                require(not environment.invocations and not environment.workspaces and not environment.leases
                        and admission.get("error_type") == "ResourceUnavailableError"
                        and raw["returncode"] is None and raw["stdout"] == "", "impossible capacity prepared/executed work")
            else:
                require(len(environment.invocations) == len(environment.workspaces) == len(environment.leases) == 1
                        and raw["returncode"] == 0 and raw["stdout"] == POSITIVE[engine]
                        and all(lease.released for lease in environment.leases)
                        and all(not Path(path).exists() for path in environment.workspaces), "owned lifecycle/workspace did not drain")
                require(environment.invocations[0]["input_files"] == lifecycle["tool_request"]["input_files"],
                        "materialized inputs differ from actual default request")
            row.update(status="passed", result=wire, original_outcome=original.to_dict(),
                attempt=attempt.to_dict() if attempt else None, operation_observations=phases)
        require(environment.after["active_lease_count"] == environment.after["waiting_request_count"] == 0,
                "private work leaked")
        require(not environment.native_attempts and not environment.shared_attempts, "controlled execution crossed a denied boundary")
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        environment.stack.close()
        row.update(elapsed_seconds=time.monotonic() - started, admission=environment.admissions,
            lifecycle=environment.lifecycle, invocations=environment.invocations, sample_history=environment.samples,
            workspaces=environment.workspaces, native_launch_attempts=environment.native_attempts,
            shared_scheduler_attempts=environment.shared_attempts, discovery=environment.discovery,
            private_config=environment.owner.config.persisted_dict() if hasattr(environment, "owner") else None,
            private_before=getattr(environment, "before", None), private_after=getattr(environment, "after", None),
            workspace_cleanup=all(not Path(path).exists() for path in environment.workspaces),
            leases_released=all(lease.released for lease in environment.leases))
        write(directory / (label.replace(":", "-") + "-result.json"), row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "hyper-default-admission-controlled-benchmark@1", "status": "running",
        "source_pins_before": pins(), "cases": [], "checks": {}, "recovery_benchmarks": [],
        "native_launches": 0, "shared_pool_accesses": 0,
        "scope": {"synthetic_executor_output": True, "synthetic_discovery": True, "synthetic_host_pressure": True,
            "private_fixture_pools": True, "default_managed_admission": True, "native_proof_claim": False,
            "actual_host_pressure_tested": False, "native_parallel_scaling_claim": False,
            "hard_aggregate_containment_claim": False, "registry_delegate": "HyperLTL only",
            "v2_request_bounds_forwarded": True, "v2_aggregate_operation_scope_claim": False}}
    started = time.monotonic()
    try:
        for spec in CASES:
            row = run_case(spec, directory)
            result["cases"].append(row)
            write(directory / "partial.json", result)
            require(row["status"] == "passed", "controlled case failed: " + row["case"])
        for engine in ENGINES:
            rows = [r for r in result["cases"] if r["engine"] == engine and r["kind"] == "pressure_recovery"]
            waits = [r["admission"][0]["wait_seconds"] for r in rows]
            result["recovery_benchmarks"].append({"engine": engine, "samples": [{"case": r["case"],
                "admission_wait_seconds": r["admission"][0]["wait_seconds"], "elapsed_seconds": r["elapsed_seconds"]} for r in rows],
                "min_wait_seconds": min(waits), "median_wait_seconds": statistics.median(waits), "max_wait_seconds": max(waits),
                "scope": "Private scheduler with controlled pressure release; no native solving"})
        result["checks"].update(all26_cases_passed=len(result["cases"]) == 26,
            all9_recovery_samples_passed=sum(len(r["samples"]) for r in result["recovery_benchmarks"]) == 9,
            no_native_launch_attempts=all(not r["native_launch_attempts"] for r in result["cases"]),
            no_shared_pool_attempts=all(not r["shared_scheduler_attempts"] for r in result["cases"]),
            owned_work_drained=all(r["workspace_cleanup"] and r["leases_released"] for r in result["cases"]))
        result["status"] = "passed_controlled"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
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
