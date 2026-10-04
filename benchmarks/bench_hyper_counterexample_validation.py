"""Controlled Hyper counterexample parsing and context-bound structural replay.

Discovery, executor responses and healthy host samples are explicit fixtures.
Default managed runners, private admission, translation, parsers and projections
remain production code. No native solver, shared pool or real host load is used.
Structural replay does not establish model membership or temporal validity.
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
import time
import traceback
from unittest.mock import patch

import bench_hyper_default_admission as fixtures
import bench_hyper_operation_control as previous
from bench_smt_operation_control import MIB, ROOT, require, sha, write

ENGINES = fixtures.ENGINES
ROUTES = ("direct", "registry", "standalone_v2")
KINDS = ("valid", "malformed", "equal_observations", "unequal_low_inputs")
CASES = tuple((engine, route, kind) for engine in ENGINES for route in ROUTES for kind in KINDS)
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_counterexample_validation.py"
VIOLATED = {"hyperltl": "unsat\n", "autohyper": "UNSAT\n", "mchyper": "Counterexample found. Safety violation.\n"}
ENV_KEYS = ("DOTNET_PROCESSOR_COUNT", "DOTNET_gcServer", "DOTNET_GCHeapHardLimit")


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def document():
    from ipfs_datasets_py.logic.software_verification.hyperproperties import HyperpropertyIR
    base = fixtures.document()
    return HyperpropertyIR.noninterference_document(
        policy=replace(base.information_flow_policy, subject_fields=("tenant",)), bound=base.self_composition_bound)


def request(engine, route, label):
    doc = document()
    base = fixtures.request(engine, "standalone_v2" if route == "standalone_v2" else "direct", label)
    bounds = replace(base.bounds, timeout_ms=1500)
    if route == "standalone_v2":
        return replace(base, document=doc, bounds=bounds)
    return replace(base, payload={**base.payload.to_dict(), "document": doc.to_dict()},
        requested_backend_id=engine, bounds=bounds)


def output(engine, kind):
    second_low = "bob" if kind == "unequal_low_inputs" else "alice"
    second_obs = "ok" if kind == "equal_observations" else "leak"
    body = ("TRACE pi1:\n  public.user = alice\n  subject.tenant = tenant_a\n  obs.status = ok\n"
        f"TRACE pi2:\n  public.user = {second_low}\n  subject.tenant = tenant_a\n  obs.status = {second_obs}\n")
    if kind != "equal_observations":
        body += "DIFF field=status left=ok right=leak\n"
    malformed_kind = None
    if kind == "malformed":
        malformed_kind = {"hyperltl": "unknown_trace_label", "autohyper": "duplicate_assignment", "mchyper": "conflicting_difference"}[engine]
        if engine == "hyperltl":
            body = body.replace("TRACE pi2:", "TRACE undeclared:")
        elif engine == "autohyper":
            body = body.replace("  public.user = alice\n", "  public.user = alice\n  public.user = alice\n", 1)
        else:
            body = body.replace("DIFF field=status left=ok right=leak", "DIFF field=status left=leak right=ok")
    return VIOLATED[engine]+body, malformed_kind


class Environment:
    def __init__(self, path, engine, stdout):
        self.path, self.engine, self.stdout, self.stack = path, engine, stdout, ExitStack()
        self.samples, self.admissions, self.leases, self.workspaces = [], [], [], []
        self.invocations, self.lifecycle, self.discovery = [], [], []
        self.native_attempts, self.shared_attempts = [], []

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.logic.backends.hyperproperties import adapters
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        def sample():
            require(len(self.samples) < 256, "bounded healthy sample history exceeded")
            self.samples.append({"at_monotonic": time.monotonic(), "host": asdict(healthy)})
            return healthy
        def deny_native(*args, **kwargs):
            self.native_attempts.append(True)
            raise AssertionError("controlled counterexample benchmark forbids native execution")
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(True)
            raise AssertionError("controlled counterexample benchmark forbids shared scheduler resolution")
        self.stack.enter_context(patch.object(subprocess, "Popen", deny_native))
        self.stack.enter_context(patch.object(os, "system", deny_native))
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny_shared))
        self.owner = scheduler.GlobalResourceScheduler(scheduler.ResourceSchedulerConfig.for_proof_host(
            state_path=self.path, proof_resource_sampler=sample, total_cpu_slots=2, total_memory_mb=128,
            total_child_process_slots=4, proof_memory_headroom_mb=32, lane_reservations={}, auto_renew_leases=False))
        self.before = self.owner.snapshot()
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", lambda: self.owner))
        executable = str(Path(sys.executable).resolve())
        def resolve(backend):
            self.discovery.append(backend.engine.value)
            return executable
        self.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", resolve))
        self.stack.enter_context(patch.object(process.shutil, "which", lambda candidate, **kwargs: executable if candidate == executable else None))
        acquire = self.owner.acquire
        def observe_acquire(lane, **kwargs):
            row = {"started": time.monotonic(), "lane": str(lane),
                **{key: kwargs[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "timeout")}}
            self.admissions.append(row)
            lease = acquire(lane, **kwargs)
            self.leases.append(lease)
            row.update(lease_id=lease.lease_id, wait_seconds=lease.wait_seconds, granted=time.monotonic())
            return lease
        self.stack.enter_context(patch.object(self.owner, "acquire", observe_acquire))
        run = admission.ResourceAdmittedToolRunner.run
        def observe_run(runner, tool, **kwargs):
            row = {"tool_request": {"argv": list(tool.argv), "limits": asdict(tool.limits),
                "input_files": dict(tool.input_files), "runtime_environment": {k: tool.environment[k] for k in ENV_KEYS if k in tool.environment}}}
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
            require(cancellation is not None and not cancellation.is_set(), "admitted execution lacks live cancellation")
            state, limits = self.owner.snapshot(), invocation.limits
            require(state["active_lease_count"] == state["active_root_lease_count"] == 1
                and state["allocated"] == {"cpu_slots": 2, "memory_mb": 128}
                and state["allocated_child_process_slots"] == 4, "default private reservation differs")
            require(0 < limits.timeout_seconds <= 1.5 and 0 < limits.cpu_seconds <= 1.5
                and limits.resident_memory_bytes == 128*MIB
                and limits.memory_bytes == (4096 if self.engine == "autohyper" else 2048)*MIB
                and limits.max_output_bytes == 65536 and limits.max_workspace_bytes == 16_777_216
                and limits.enforce_file_size_limit is (self.engine != "autohyper"), "finite managed profile differs")
            require("--version" not in invocation.argv and "GHCRTS" not in invocation.environment, "hidden version/RTS execution")
            if self.engine == "autohyper":
                require({k: invocation.environment.get(k) for k in ENV_KEYS} == dict(zip(ENV_KEYS, ("1", "0", "4000000"))),
                    "AutoHyper runtime controls differ")
            self.invocations.append({"started": time.monotonic(), "argv": list(invocation.argv), "limits": asdict(limits),
                "snapshot": state, "workspace": str(invocation.cwd), "synthetic_executor": True,
                "runtime_environment": {k: invocation.environment[k] for k in ENV_KEYS if k in invocation.environment},
                "input_files": {p.name: p.read_text() for p in invocation.cwd.iterdir() if p.is_file()}})
            return process.RawProcessResult(returncode=0, stdout=self.stdout)
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", execute))
        return self

    def __exit__(self, *args):
        self.after = self.owner.snapshot()
        return self.stack.__exit__(*args)


def invoke(engine, route, req):
    from ipfs_datasets_py.logic.backends import registry, resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    require(sys.getprofile() is None and current_proof_operation() is None, "unexpected ambient observer/operation")
    captured, timings, phases, forbidden, started_calls = [], [], [], [], {}
    semantic = {adapters.parse_hyper_counterexample.__code__: "parse", adapters.replay_hyper_counterexample.__code__: "replay",
        adapters.HyperCounterexampleTrace.to_witness_bundle.__code__: "bundle"}
    def observe(frame, event, value):
        if event not in {"call", "return"}:
            return
        if frame.f_code is adapters.HyperpropertyBackend._tool_version.__code__ and event == "call":
            forbidden.append("version")
        if frame.f_code in semantic:
            if event == "call":
                started_calls[id(frame)] = (time.monotonic(), {key: (context_value.to_dict() if hasattr(context_value, "to_dict") else context_value)
                    for key in ("formula_id", "observation_map", "quantifier_order") if (context_value := frame.f_locals.get(key)) is not None})
            else:
                phase_started, context = started_calls.pop(id(frame))
                timings.append({"phase": semantic[frame.f_code], "elapsed_seconds": time.monotonic()-phase_started,
                    "returned_none": value is None, "replayed": getattr(value, "replayed", None), "context": context})
        if frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            backend, operation = frame.f_locals["self"], current_proof_operation()
            require(backend.engine.value == engine and backend._managed_runner and type(backend._runner) is admission.ResourceAdmittedToolRunner,
                "selected default engine/runner differs")
            require((operation is None) is (route == "direct"), "route's production operation scope differs")
            phases.append({"event": event, "deadline": operation.deadline if operation else None})
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                captured.append(value)
    original_wire = req.to_dict()
    sys.setprofile(observe)
    started = time.monotonic()
    attempt = None
    try:
        if route == "registry":
            attempt, returned = registry.default_backend_registry().run(req)
        elif route == "standalone_v2":
            returned = v2.HyperExecutionEngineV2().execute(req)
        else:
            cls = {"hyperltl": adapters.HyperLTLBackend, "autohyper": adapters.AutoHyperBackend, "mchyper": adapters.MCHyperBackend}[engine]
            returned = cls().run(req)
    finally:
        sys.setprofile(None)
    require(current_proof_operation() is None and req.to_dict() == original_wire and len(captured) == 1
        and not forbidden and not started_calls, "leaked operation, changed request or incomplete semantic observation")
    expected_context = {"formula_id": document().formula.formula_id,
        "observation_map": adapters.ObservationMap.from_document(document()).to_dict(),
        "quantifier_order": adapters.QuantifierOrder.from_document(document()).to_dict()}
    require(timings and all(row["context"] == expected_context for row in timings),
        "parser/replay/bundle did not receive actual request context")
    return returned, attempt, captured[0], {"elapsed_call_seconds": time.monotonic()-started,
        "semantic_timings": timings, "operation_observations": phases, "original_request_unchanged": True, "ambient_restored": True}


def validate(req, engine, route, kind, returned, attempt, original, environment):
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    typed, receipt, translation = original.result.to_dict(), original.receipt.to_dict(), original.translation
    counterexample = original.receipt.counterexample
    witness = original.result.witness.to_dict()
    valid = kind == "valid"
    require(typed["status"] == receipt["status"] == "violated" and typed["authority"] == "hyperproperty"
        and original.result.bounds == req.bounds and receipt["engine"] == engine
        and not receipt["authorizes_universal_proof"] and receipt["tool_version"] == ""
        and receipt["timeout_seconds"] == 1.5, "engine verdict, declared bound or authority changed")
    require(translation is not None and translation.quantifier_order.matches_document(document())
        and receipt["translation_digest"] == translation.translation_digest
        and receipt["document_digest"] == translation.document_digest
        and original.request_digest == (translation.document_digest if route == "standalone_v2" else req.digest), "source/request binding differs")
    if kind == "malformed":
        require(counterexample is None and "counterexample" not in witness, "malformed trace became a counterexample")
    else:
        require(counterexample is not None and counterexample.replayed is valid
            and counterexample.formula_id == document().formula.formula_id
            and counterexample.observation_policy_id == document().information_flow_policy.policy_id,
            "structural replay or context binding differs")
        require(len(counterexample.traces) == 2 and all(set(trace.public_inputs) == {"user"}
            and set(trace.observations) == {"status"} and set(trace.subject) == {"tenant"} for trace in counterexample.traces),
            "trace fields do not exactly cover declared context")
        left, right = counterexample.traces
        require(tuple(trace.variable_id for trace in counterexample.traces) == translation.quantifier_order.variable_ids
            and tuple(trace.trace_id for trace in counterexample.traces) == ("trace:pi1", "trace:pi2")
            and dict(left.public_inputs) == {"user": "alice"}
            and dict(right.public_inputs) == {"user": "bob" if kind == "unequal_low_inputs" else "alice"}
            and dict(left.subject) == dict(right.subject) == {"tenant": "tenant_a"}
            and dict(left.observations) == {"status": "ok"}
            and dict(right.observations) == {"status": "ok" if kind == "equal_observations" else "leak"}
            and len(counterexample.differences) == (0 if kind == "equal_observations" else 1)
            and witness["counterexample"] == counterexample.to_dict(), "parsed values, real differences or witness changed")
    require(("witness_bundle" in witness) is valid, "invalid structure gained a witness bundle")
    if valid:
        bundle = witness["witness_bundle"]
        require(bundle["role"] == "counterexample" and bundle["formula_id"] == document().formula.formula_id
            and len(bundle["traces"]) == 2 and len(bundle["differences"]) == 1, "valid structural bundle differs")
    if route == "registry":
        require(attempt.backend_id == returned.backend_id == engine and attempt.status.value == "succeeded"
            and returned.status.value == "unknown" and returned.payload.to_dict()["result"] == typed
            and attempt.request_digest == returned.request_digest == req.digest and returned.attempt_digest == attempt.digest,
            "generic registry acquired counterexample/theorem authority or lost original projection")
    elif route == "standalone_v2":
        wire = returned.to_dict()
        require(wire["engine"] == engine and wire["backend_result"] == typed and wire["disposition"] == "violated"
            and returned.evidence.request_digest == v2._digest_of(req.to_dict()) and returned.request.to_dict() == req.to_dict()
            and returned.evidence.witness.replayed is valid and not wire["is_proved"] and not wire["is_theorem_authority"],
            "V2 lost actual request binding or promoted invalid replay")
        require(all(not returned.evidence.establishes_other_engine(other) for other in ENGINES if other != engine),
            "V2 transferred capability between engines")
    require(len(environment.lifecycle) == len(environment.invocations) == len(environment.admissions) == len(environment.workspaces) == 1
        and set(environment.discovery) == {engine}, "unexpected engine/version/admission execution")
    call, invocation = environment.lifecycle[0], environment.invocations[0]
    raw, tool = call["result"], call["tool_request"]
    require(raw["pid"] is None and raw["returncode"] == 0 and raw["stdout"] == environment.stdout and raw["workspace_cleaned"]
        and not any(raw[key] for key in ("timed_out", "cancelled", "unavailable", "resource_exhausted", "output_truncated",
            "workspace_limit_exceeded", "process_tree_terminated")), "raw synthetic lifecycle differs")
    metadata = {key: raw[key] for key in ("cancelled", "command", "error", "output_truncated", "process_tree_terminated",
        "returncode", "resource_exhausted", "timed_out", "termination_reason", "unavailable", "workspace_cleaned", "workspace_limit_exceeded")}
    metadata.update(stdout_digest=adapters.stable_digest({"content": raw["stdout"]}), stderr_digest=adapters.stable_digest({"content": raw["stderr"]}))
    require(typed["metadata"]["process"] == metadata, "typed process metadata changed raw lifecycle")
    executable = str(Path(sys.executable).resolve())
    expected_argv = ([executable, "-f", "property.hltl"] if engine == "hyperltl" else
        [executable, "--explicit", "system.explicit", "property.hltl"] if engine == "autohyper" else
        [executable, "-f", translation.formula_text, "system.aag", "-pdr", "-cex", "--cex_file", "counterexample.txt", "-v", "1"])
    require(tool["argv"] == invocation["argv"] == expected_argv and tool["input_files"] == invocation["input_files"]
        and all(tool["input_files"].get(key) == value for key, value in translation.auxiliary_files.items()), "translated argv/inputs differ")
    require(tuple(environment.admissions[0][key] for key in ("cpu_slots", "memory_mb", "child_process_slots")) == (2, 128, 4),
        "resource reservation changed")


def run_case(spec, directory):
    engine, route, kind = spec
    label = ":".join(spec)
    case_dir = directory / label.replace(":", "-")
    case_dir.mkdir()
    req = request(engine, route, label)
    stdout, malformed_kind = output(engine, kind)
    environment = Environment(case_dir / "private-pool.json", engine, stdout)
    row = {"case": label, "engine": engine, "route": route, "kind": kind, "request": req.to_dict(),
        "synthetic_stdout": stdout, "malformed_kind": malformed_kind, "status": "running"}
    started = time.monotonic()
    try:
        with environment:
            returned, attempt, original, observations = invoke(engine, route, req)
            row.update(observations, returned_result=returned.to_dict(), original_outcome=original.to_dict(),
                attempt=attempt.to_dict() if attempt else None)
            validate(req, engine, route, kind, returned, attempt, original, environment)
        require(environment.after["active_lease_count"] == environment.after["waiting_request_count"] == 0
            and all(lease.released for lease in environment.leases) and all(not Path(p).exists() for p in environment.workspaces),
            "private leases/workspaces did not drain")
        require(not environment.native_attempts and not environment.shared_attempts, "denied boundary crossed")
        row["status"] = "passed"
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        environment.stack.close()
        row.update(elapsed_seconds=time.monotonic()-started, admissions=environment.admissions, lifecycle=environment.lifecycle,
            invocations=environment.invocations, sample_history=environment.samples, discovery=environment.discovery,
            workspaces=environment.workspaces, native_launch_attempts=environment.native_attempts,
            shared_scheduler_attempts=environment.shared_attempts,
            private_config=environment.owner.config.persisted_dict() if hasattr(environment, "owner") else None,
            private_before=getattr(environment, "before", None), private_after=getattr(environment, "after", None),
            workspace_cleanup=all(not Path(p).exists() for p in environment.workspaces),
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
    result = {"schema": "hyper-counterexample-controlled-benchmark@1", "status": "running", "cases": [], "checks": {},
        "source_pins_before": pins(), "native_launches": 0, "shared_pool_accesses": 0, "semantic_timings": [],
        "scope": {"synthetic_executor_output": True, "synthetic_discovery": True, "synthetic_healthy_host_samples": True,
            "private_fixture_pools": True, "default_managed_admission": True, "native_model_membership_tested": False,
            "native_temporal_replay_tested": False, "native_proof_claim": False, "native_parallel_scaling_claim": False,
            "actual_host_pressure_tested": False, "structural_replay_only": True, "high_inputs_in_trace_fixtures": False}}
    started = time.monotonic()
    try:
        for spec in CASES:
            row = run_case(spec, directory)
            result["cases"].append(row)
            write(directory / "partial.json", result)
            require(row["status"] == "passed", "controlled case failed: "+row["case"])
        for phase in ("parse", "replay", "bundle"):
            samples = [timing["elapsed_seconds"] for row in result["cases"] for timing in row["semantic_timings"] if timing["phase"] == phase]
            require(samples, "missing semantic phase observations: "+phase)
            result["semantic_timings"].append({"phase": phase, "samples_seconds": samples, "count": len(samples),
                "min_seconds": min(samples), "median_seconds": statistics.median(samples), "max_seconds": max(samples),
                "scope": "Observed tiny controlled fixtures across routes; mixed calls, not a scaling/throughput benchmark"})
        result["checks"].update(all36_cases_passed=len(result["cases"]) == 36,
            only9_valid_cases_have_bundles=sum("witness_bundle" in row["original_outcome"]["result"]["witness"] for row in result["cases"]) == 9,
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
