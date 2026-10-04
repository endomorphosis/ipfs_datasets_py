"""Actual Lean/Rocq registry calls and owned Python ambient-stop transport smoke.

No operation scope, solver output, resource sample, admission or executor is
substituted. Native executable selection is the only kernel factory override.
The two Python cases qualify transport interruption, not solver cancellation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time
import traceback

import bench_registry_operation_budget as previous
from bench_generic_prover_admission import LaunchAudit, request as old_request
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

KERNEL_FILES = ("logic/backends/kernel/lean.py", "logic/backends/kernel/rocq.py",
                "logic/backends/kernel/wasm.py", "logic/families/models.py")
SLEEP_SOURCE = "import time; print('transport-child-started', flush=True); time.sleep(10)"


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__),
        **{str(ROOT / "ipfs_datasets_py" / p): sha(ROOT / "ipfs_datasets_py" / p) for p in KERNEL_FILES}}


def selected_tools():
    retained = ROOT / "workspace/generic-prover-admission-qualification-20261003/native-final/result.json"
    old = json.loads(retained.read_text())["installed_files"]
    paths = {name: old[name]["path"] for name in ("lean", "rocq")}
    for name, path in paths.items():
        require(Path(path).is_file() and os.access(path, os.X_OK) and sha(path) == old[name]["sha256"],
                "reviewed installed " + name + " changed or is absent")
    # Bind the explicit executable in the reviewed local launcher, not PATH lookup.
    launcher = Path(paths["rocq"]).read_text()
    target = Path(paths["rocq"]).parents[1] / "opam/ipfs-datasets-coq/bin/rocq"
    require("exec " + str(target) + ' repl "$@"' in launcher and target.is_file()
            and sha(target) == "1528f5b9402743109ffe798ac53fbdb080037d339bd4682cf5663d06052d391f",
            "reviewed Rocq launcher target differs")
    paths.update(rocq_target=str(target), python=str(Path(sys.executable).resolve()))
    return paths, {path: sha(path) for path in paths.values()}, {"source": str(retained), "sha256": sha(retained)}


def kernel_request(provider, valid):
    rhs = "2" if valid else "3"
    source = ("theorem admission_demo : (1 : Nat) + 1 = " + rhs + " := by decide\n" if provider == "lean"
              else "Theorem admission_demo : 1 + 1 = " + rhs + ".\nProof. reflexivity. Qed.\n")
    value = old_request("lean4" if provider == "lean" else "rocq", source,
                        memory_mb=512 if provider == "lean" else 1024)
    label = provider + ":" + str(valid).lower()
    return replace(value, request_id="request:native-inheritance:" + label,
                   requested_backend_id=provider)


def transport_request(kind):
    value = old_request("first_order", "transport-only", memory_mb=128,
                        timeout_ms=1000 if kind == "timeout" else 3000)
    return replace(value, request_id="request:transport-inheritance:" + kind,
                   requested_backend_id="transport-smoke")


def drained(audit):
    state = saved.state_summary(audit.owner.state_path)
    require(not state["owned_active_leases"] and not state["owned_waiting_requests"], "owned work did not drain")
    return state


def prepare(audit, label, memory_mb):
    drained(audit)
    snapshot = audit.owner.snapshot()
    available = dict(snapshot["available"])
    for lane, row in snapshot["lanes"].items():
        if lane != "validation":
            for key in ("cpu_slots", "memory_mb"):
                available[key] -= max(0, row["reservation"][key] - row["allocated"][key])
    require(available["cpu_slots"] >= 1 and available["memory_mb"] >= memory_mb
            and available["child_process_slots"] >= 1, "no shared capacity for finite serial profile")
    audit.local.case = label
    audit.local.cancel_token = None
    return {"snapshot": snapshot, "available_after_other_lane_reservations": available,
            "required": {"cpu_slots": 1, "memory_mb": memory_mb, "child_process_slots": 1},
            "scope": "Advisory serial dispatch only; admission rechecks live pressure and capacity"}


class Audit(LaunchAudit):
    """Read-only request/invocation observations around actual admitted execution."""

    def __init__(self, owner):
        super().__init__(owner)
        self.requests, self.invocations, self.live, self.timers = [], [], [], []

    def install_observers(self):
        super().install_observers()
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        from ipfs_datasets_py.logic.backends.process import SubprocessExecutor
        from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
        run = ResourceAdmittedToolRunner.run

        def observed_run(runner, request, **kwargs):
            operation = current_proof_operation()
            require(operation is not None, "native request escaped registry operation")
            require(kwargs.get("cancellation") is None, "caller explicitly forwarded native cancellation")
            self.requests.append({"case": self.local.case, "at_monotonic": time.monotonic(),
                "deadline": operation.deadline, "argv": list(request.argv), "limits": asdict(request.limits),
                "input_files": dict(request.input_files), "environment": dict(request.environment),
                "explicit_cancellation_forwarded": False})
            return run(runner, request, **kwargs)

        ResourceAdmittedToolRunner.run = observed_run
        execute = SubprocessExecutor.execute

        def observed_execute(executor, invocation, cancellation=None):
            operation = current_proof_operation()
            require(operation is not None and cancellation is not None, "executor lacks inherited stop signal")
            now = time.monotonic()
            remaining = operation.deadline - now
            require(0 < invocation.limits.timeout_seconds <= remaining + .05,
                    "executor wall budget exceeds remaining registry deadline")
            require(invocation.limits.cpu_seconds is not None and
                    0 < invocation.limits.cpu_seconds <= remaining + .05,
                    "explicit CPU ceiling exceeds remaining registry deadline")
            self.invocations.append({"case": self.local.case, "at_monotonic": now,
                "deadline": operation.deadline, "remaining_seconds": remaining,
                "argv": list(invocation.argv), "limits": asdict(invocation.limits),
                "workspace": str(invocation.cwd), "environment": dict(invocation.environment),
                "inherited_signal_present": True})
            return execute(executor, invocation, cancellation)

        SubprocessExecutor.execute = observed_execute
        initialize = SubprocessExecutor.__init__

        def observed_initialize(executor, *args, **kwargs):
            initialize(executor, *args, **kwargs)
            popen = executor._popen
            def observed_popen(*args, **kwargs):
                child = popen(*args, **kwargs)
                operation = current_proof_operation()
                row = {"case": self.local.case, "pid": child.pid, "at_monotonic": time.monotonic(),
                    "deadline": operation.deadline, "observed_live": child.poll() is None}
                self.live.append(row)
                token = getattr(self.local, "cancel_token", None)
                if token is not None:
                    require(row["observed_live"], "transport cancellation target already exited")
                    def cancel_owned_operation():
                        row["cancel_requested_at_monotonic"] = time.monotonic()
                        row["live_at_cancel"] = child.poll() is None
                        token.cancel()
                    timer = threading.Timer(.15, cancel_owned_operation)
                    timer.daemon = True
                    self.timers.append(timer)
                    timer.start()
                return child
            executor._popen = observed_popen
        SubprocessExecutor.__init__ = observed_initialize


def phase(audit, label, *, expected_memory_mb, stopped=None):
    def single(rows):
        selected = [r for r in rows if r["case"] == label]
        require(len(selected) == 1, "case must have one real native lifecycle: " + label)
        return selected[0]
    launch, lifecycle, request, invocation, live = map(single,
        (audit.events, audit.results, audit.requests, audit.invocations, audit.live))
    result = lifecycle["result"]
    lease = next(r for r in launch["owned_leases"] if r["lease_id"] == launch["launch_lease_id"])
    require((lease["cpu_slots"], lease["memory_mb"], lease["child_process_slots"], lease["parent_lease_id"])
            == (1, expected_memory_mb, 1, None), "native lease profile differs")
    require(request["deadline"] == invocation["deadline"] == live["deadline"], "native deadline changed")
    require(result["pid"] == live["pid"] and result["pid"] is not None and result["workspace_cleaned"]
            and not Path(invocation["workspace"]).exists() and not Path("/proc", str(result["pid"])).exists(),
            "owned native PID or workspace did not clean up")
    require(not any(result[k] for k in ("unavailable", "resource_exhausted", "output_truncated", "workspace_limit_exceeded")),
            "native phase exceeded unexpected bounds")
    if stopped:
        require(result["timed_out" if stopped == "timeout" else "cancelled"] and result["process_tree_terminated"]
                and live["observed_live"] and result["elapsed_seconds"] < 5,
                "owned transport did not stop under ambient operation")
        if stopped == "cancelled":
            require(live.get("live_at_cancel") is True and live.get("cancel_requested_at_monotonic"),
                    "cancellation did not follow observed live child")
    else:
        require(not any(result[k] for k in ("error", "cancelled", "timed_out", "process_tree_terminated")),
                "real kernel phase was interrupted")
    drained(audit)
    return {"launch": launch, "lifecycle": lifecycle, "request": request, "invocation": invocation, "live": live}


def kernel_case(provider, valid, paths, audit):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.kernel import lean, rocq
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = "kernel:" + provider + ":" + str(valid).lower()
    dispatch = prepare(audit, label, 512 if provider == "lean" else 1024)
    req = kernel_request(provider, valid)
    require(current_proof_operation() is None, "unexpected ambient kernel scope")
    backend_type = lean.LeanKernelBackend if provider == "lean" else rocq.RocqKernelBackend
    outcome_type = lean.LeanKernelOutcome if provider == "lean" else rocq.RocqKernelOutcome
    old_factories, old_profile = registry._factory_constructors, sys.getprofile()
    require(old_profile is None, "preexisting profiler")
    factories = old_factories()
    created, outcomes, factory_scopes = [], [], []
    def factory():
        operation = current_proof_operation()
        require(operation is not None, "kernel construction escaped registry scope")
        backend = backend_type(executable=paths[provider])
        require(type(backend._runner) is ResourceAdmittedToolRunner, "kernel default admission bypassed")
        created.append(backend)
        factory_scopes.append({"deadline": operation.deadline, "at_monotonic": time.monotonic()})
        return backend
    def observer(frame, event, value):
        if event == "return" and frame.f_code is backend_type.run.__code__ and isinstance(value, outcome_type):
            outcomes.append(value)
    started = time.monotonic()
    registry._factory_constructors = lambda: {**factories, provider: factory}
    try:
        owner = registry.default_backend_registry()
        require(not any(owner[name]._delegate_loaded for name in owner) and not created, "discovery constructed a delegate")
        sys.setprofile(observer)
        try:
            attempt, result = owner.run(req)
        finally:
            sys.setprofile(old_profile)
        require(len(created) == len(outcomes) == len(factory_scopes) == 1, "kernel delegate/return differs")
        require(sum(owner[name]._delegate_loaded for name in owner) == 1, "multiple kernel delegates loaded")
    finally:
        registry._factory_constructors = old_factories
        sys.setprofile(old_profile)
    require(current_proof_operation() is None, "kernel registry scope leaked")
    original = outcomes[0]
    record = phase(audit, label, expected_memory_mb=512 if provider == "lean" else 1024)
    require(factory_scopes[0]["deadline"] == record["request"]["deadline"], "factory/native budget differs")
    typed = original.result.to_dict()
    require(result.status.value == ("unknown" if valid else "error")
            and attempt.status.value == ("succeeded" if valid else "failed")
            and result.payload.to_dict()["result"] == typed
            and result.payload.to_dict()["result_status"] == ("proved" if valid else "error")
            and typed["authority"] == "theorem" and original.receipt.accepted is valid,
            "kernel typed evidence lost or generic authority promoted")
    require(original.request_digest == req.digest == attempt.request_digest == result.request_digest
            and result.attempt_digest == attempt.digest, "request/attempt binding differs")
    process = record["lifecycle"]["result"]
    require(process["returncode"] == 0 if valid else process["returncode"] != 0
            and bool(process["stdout"] or process["stderr"]), "native kernel exit/diagnostic differs")
    return {"case": label, "provider": provider, "valid": valid, "request": req.to_dict(),
        "request_digest": req.digest, "attempt": attempt.to_dict(), "attempt_digest": attempt.digest,
        "result": result.to_dict(), "original_outcome": original.to_dict(), "native": record,
        "factory_scopes": factory_scopes, "dispatch": dispatch, "elapsed_seconds": time.monotonic() - started,
        "default_runner_and_probes": True, "factory_override": "installed executable only",
        "ambient_absent_before_and_after": True, "operation_scope_owner": "production_registry",
        "observer_and_factory_restored": registry._factory_constructors is old_factories and sys.getprofile() is old_profile}


def transport_case(kind, paths, audit):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.process import CancellationToken, ToolRunLimits, ToolRunRequest
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    from ipfs_datasets_py.logic.ir_core.protocols import BackendCapabilities, QueryKind
    label = "transport:" + kind
    dispatch = prepare(audit, label, 128)
    req = transport_request(kind)
    require(current_proof_operation() is None, "unexpected ambient transport scope")
    token = CancellationToken() if kind == "cancelled" else None
    audit.local.cancel_token = token
    captured = []
    runner = ResourceAdmittedToolRunner()
    def compile_request(request):
        return registry.CompiledBackendRequest(request.digest, "transport-smoke", "transport-only")
    def execute(compiled, request):
        raw = runner.run(ToolRunRequest(argv=(paths["python"], "-c", SLEEP_SOURCE), limits=ToolRunLimits(
            timeout_seconds=10, cpu_seconds=2, memory_bytes=128*MIB,
            max_output_bytes=4096, max_input_bytes=1024, max_workspace_bytes=MIB, max_file_bytes=MIB)))
        captured.append(raw)
        return registry.BackendRunnerOutput(stdout=raw.stdout, stderr=raw.stderr, returncode=raw.returncode)
    backend = registry.CallableProofBackend(backend_id="transport-smoke", backend_version="transport-only/v1",
        capabilities=BackendCapabilities(logic_families=("first_order",), query_kinds=(QueryKind.THEOREM_PROOF,)),
        compiler=compile_request, runner=execute, availability_probe=lambda: True)
    started = time.monotonic()
    try:
        attempt, result = registry.ProofBackendRegistry((backend,)).run(req, cancellation=token)
    finally:
        for timer in audit.timers:
            timer.cancel()
            timer.join(timeout=1)
            require(not timer.is_alive(), "owned cancellation timer did not drain")
        audit.local.cancel_token = None
    require(current_proof_operation() is None and len(captured) == 1, "transport scope/result differs")
    record = phase(audit, label, expected_memory_mb=128, stopped=kind)
    require(attempt.status.value == ("timed_out" if kind == "timeout" else "cancelled")
            and result.status.value == "unknown" and not result.is_theorem_proof
            and result.request_digest == req.digest == attempt.request_digest
            and result.attempt_digest == attempt.digest, "transport stop leaked conclusive evidence")
    return {"case": label, "kind": kind, "scope": "owned Python transport interruption only; no solver cancellation claim",
        "request": req.to_dict(), "request_digest": req.digest, "attempt": attempt.to_dict(),
        "attempt_digest": attempt.digest, "result": result.to_dict(), "native": record,
        "dispatch": dispatch, "elapsed_seconds": time.monotonic() - started,
        "operation_scope_owner": "production_registry", "explicit_runner_cancellation_forwarded": False,
        "ambient_absent_before_and_after": True, "solver_output_injected": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "native-operation-inheritance-benchmark@1", "status": "running",
        "source_pins_before": pins(), "runtime": saved.runtime(), "kernel_cases": [], "transport_cases": [], "checks": {},
        "scope": {"production_registry_scope": True, "benchmark_operation_scope_injected": False,
            "native_runner_or_probe_injected": False, "resource_sampler_injected": False,
            "real_kernel_cancellation_tested": False, "python_transport_smoke": True,
            "installation": False, "parallel_scaling_claim": False, "hard_aggregate_containment": False,
            "atp_proverif_tamarin_included": False}}
    owner = audit = None
    started = time.monotonic()
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = install_saved_owner(directory / "saved-scheduler-config.json")
        result.update(shared_before=saved.state_summary(owner.state_path), shared_pool_compatibility=owner._benchmark_pool_compatibility)
        paths, files, provenance = selected_tools()
        result.update(tool_selection=paths, tool_files_before=files, tool_selection_provenance=provenance)
        audit = Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        for provider in ("lean", "rocq"):
            for valid in (True, False):
                result["kernel_cases"].append(kernel_case(provider, valid, paths, audit))
                write(directory / "partial.json", result)
        for kind in ("timeout", "cancelled"):
            result["transport_cases"].append(transport_case(kind, paths, audit))
            write(directory / "partial.json", result)
        result["checks"].update(four_real_kernel_cases=len(result["kernel_cases"]) == 4,
            two_transport_stop_controls=len(result["transport_cases"]) == 2,
            six_real_native_phases=len(audit.events) == len(audit.results) == len(audit.invocations) == 6,
            no_generic_authority_promotion=all(c["result"]["status"] in {"unknown", "error"} for c in result["kernel_cases"] + result["transport_cases"]),
            observer_and_factory_restored=all(c["observer_and_factory_restored"] for c in result["kernel_cases"]),
            no_explicit_native_cancellation=all(not r["explicit_cancellation_forwarded"] for r in audit.requests))
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if audit is not None:
            for timer in audit.timers:
                timer.cancel()
                timer.join(timeout=1)
            result["audit_sha256"] = {}
            for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                    ("request-audit.json", audit.requests), ("invocation-audit.json", audit.invocations), ("live-process-audit.json", audit.live)):
                write(directory / name, value)
                result["audit_sha256"][name] = sha(directory / name)
            result["launches"] = len(audit.events)
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=result["shared_before"]["config"] == result["shared_after"]["config"],
                owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        if "tool_files_before" in result:
            result["tool_files_after"] = {p: sha(p) for p in result["tool_files_before"]}
            result["checks"]["selected_tools_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        result["elapsed_seconds"] = time.monotonic() - started
        result["child_usage"] = {k: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), k) for k in ("ru_utime", "ru_stime", "ru_maxrss")}
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
