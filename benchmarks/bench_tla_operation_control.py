"""Bounded actual TLC operation controls through public state execution V2.

The unchanged finite launcher, admission guard and process observers are reused
without running earlier benchmark mains. Real setup/model boundaries trigger
caller cancellation; one real compile result is deliberately held until its
operation deadline. No returned solver output or proof evidence is fabricated.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time
import traceback

import bench_source_mirroring_compatibility as runtime_baseline
import bench_tla_outcome_integrity as baseline
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write

WORKERS = (1, 2, 4)
CONTROLS = ("pre_setup_cancel", "live_setup_cancel", "after_setup_cancel", "compile_deadline",
            "live_model_cancel", "live_model_deadline", "after_model_cancel")
JAVA_ENV = "IPFS_DATASETS_PY_JAVA_EXECUTABLE"


def pins():
    paths = [Path(__file__), ROOT / "ipfs_datasets_py/logic/backends/tla/execution_v2.py",
             ROOT / "ipfs_datasets_py/logic/backends/tla/compiler.py",
             ROOT / "ipfs_datasets_py/logic/software_verification/state.py",
             ROOT / "ipfs_datasets_py/logic/software_verification/transitions.py"]
    return {**runtime_baseline.pins(), **{str(path.resolve()): sha(path) for path in paths}}


def document():
    """Small typed real compiler input; the deadline case never launches it."""
    from ipfs_datasets_py.logic.software_verification.state import (
        Boundedness, FiniteDomainBound, PredicateRole, StatePredicate, StateSchema, StateTypeKind, StateVariable)
    from ipfs_datasets_py.logic.software_verification.transitions import Action, ActionFrame, StateTransitionIR, TransitionRelation
    schema = StateSchema((StateVariable("var:n", "n", StateTypeKind.INTEGER, Boundedness.FINITE,
                         domain_bound=FiniteDomainBound("bound:n", lower=0, upper=3)),))
    return StateTransitionIR(schema=schema, predicates=(
        StatePredicate("pred:init", PredicateRole.INITIAL, "n = 0", expression={"var:n": 0}, subject_variable_ids=("var:n",)),
        StatePredicate("pred:next", PredicateRole.NEXT, "n' = 1", expression={"var:n": 1}, subject_variable_ids=("var:n",)),
        StatePredicate("pred:inv", PredicateRole.INVARIANT, "n \\in 0..3", subject_variable_ids=("var:n",))),
        actions=(Action("action:set", "Set", ActionFrame(reads=("var:n",), writes=("var:n",)), next_predicate_id="pred:next"),),
        transitions=(TransitionRelation("relation:set", "action", "Set", action_ids=("action:set",)),),
        metadata={"purpose": "bounded operation compiler checkpoint"})


def deadline_artifacts():
    """Finite counter with per-state arithmetic work under the short deadline.

    Every reachable n is nonnegative and each quantified k is positive, so the
    added invariant is true. Its state-dependent evaluations slow exploration
    instead of requiring a larger stored graph to reach the deadline.
    """
    value = baseline.artifacts(True)
    text = ("---- MODULE BoundedCounter ----\nEXTENDS Integers\nVARIABLE n\n"
            "Init == n = 0\nNext == n < 100000000 /\\ n' = n + 1\n"
            "Spec == Init /\\ [][Next]_n\n"
            "Safety == n \\in 0..100000000 /\\ \\A k \\in 1..10000 : n + k >= n\n====\n")
    return replace(value, model_text=text, bounds=replace(value.bounds, max_steps=100000001,
        max_integer_span=100000001), source_document_id="benchmark:deadline-bounded-counter")


class OperationAudit(baseline.OutcomeAudit):
    def __init__(self, owner):
        super().__init__(owner)
        self.boundaries = []
        self.phase_budgets = []

    def install_observers(self):
        super().install_observers()
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        from ipfs_datasets_py.logic.backends.process import SubprocessExecutor
        from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
        from ipfs_datasets_py.logic.backends.tla.compiler import TLACompiler
        run = ResourceAdmittedToolRunner.run

        @wraps(run)
        def observed_run(runner, request, **kwargs):
            label = self.local.operation_label
            kind = "setup" if request.argv[-1] == "-version" else "model" if request.input_files else "help"
            previous = getattr(self.local, "case", label)
            self.local.case = label + ":constructor" if kind == "setup" else label
            operation = current_proof_operation()
            require(operation is not None, "TLA native phase escaped its aggregate operation")
            remaining = operation.checkpoint("benchmark phase observation")
            self.local.phase = kind
            with self.lock:
                self.phase_budgets.append({"case": label, "phase": kind, "at_monotonic": time.monotonic(),
                    "deadline": operation.deadline, "remaining_seconds": remaining,
                    "request_timeout_seconds": request.limits.timeout_seconds})
            control = getattr(self.local, "control", None)
            token = getattr(self.local, "token", None)
            if (control == "live_setup_cancel" and kind == "setup") or (control == "live_model_cancel" and kind == "model"):
                self.local.cancel_live_probe = token
            try:
                result = run(runner, request, **kwargs)
                if (control == "after_setup_cancel" and kind == "setup") or (control == "after_model_cancel" and kind == "model"):
                    token.cancel()
                    with self.lock:
                        self.boundaries.append({"case": label, "kind": "after_actual_completed_" + kind,
                            "pid": result.pid, "returncode": result.returncode, "workspace_cleaned": result.workspace_cleaned,
                            "at_monotonic": time.monotonic()})
                return result
            finally:
                self.local.case = previous
                self.local.cancel_live_probe = None

        ResourceAdmittedToolRunner.run = observed_run
        initialize = SubprocessExecutor.__init__

        @wraps(initialize)
        def observed_initialize(executor, *args, **kwargs):
            initialize(executor, *args, **kwargs)
            popen = executor._popen

            def observed_popen(*args, **kwargs):
                process = popen(*args, **kwargs)
                if getattr(self.local, "control", None) == "live_model_deadline" and self.local.phase == "model":
                    operation = current_proof_operation()
                    with self.lock:
                        self.boundaries.append({"case": self.local.operation_label, "kind": "actual_live_model_before_deadline",
                            "pid": process.pid, "observed_live": process.poll() is None and Path("/proc", str(process.pid)).is_dir(),
                            "at_monotonic": time.monotonic(), "deadline": operation.deadline})
                return process
            executor._popen = observed_popen

        SubprocessExecutor.__init__ = observed_initialize
        compile_document = TLACompiler.compile

        @wraps(compile_document)
        def observed_compile(compiler, *args, **kwargs):
            artifacts = compile_document(compiler, *args, **kwargs)
            if getattr(self.local, "control", None) == "compile_deadline":
                operation = current_proof_operation()
                require(operation is not None and artifacts.model_text and artifacts.artifact_digest,
                        "deadline checkpoint did not follow genuine compilation")
                remaining = operation.deadline - time.monotonic()
                require(0 < remaining < 2, "cooperative compiler-delay control lost its finite budget")
                before = time.monotonic()
                threading.Event().wait(remaining + .025)
                with self.lock:
                    self.boundaries.append({"case": self.local.operation_label, "kind": "after_real_compile_deadline",
                        "artifact_digest": artifacts.artifact_digest, "artifacts": artifacts.to_dict(),
                        "delay_started_monotonic": before, "at_monotonic": time.monotonic(), "deadline": operation.deadline,
                        "in_process_observer_delay_only": True})
            return artifacts

        TLACompiler.compile = observed_compile


def engine(selection):
    from ipfs_datasets_py.logic.backends.tla.execution_v2 import StateExecutionEngineV2

    def selected_finder(name):
        require(name == "tlc", "TLC-only execution attempted another provider's setup")
        return selection["wrapper"]

    return StateExecutionEngineV2(which=selected_finder, lazy_install=False)


def execute(route, audit, selection, label, fixture, *, control=None, token=None, timeout=None, compiled_document=False):
    from ipfs_datasets_py.logic.backends.tla.execution_v2 import StateExecutionRequestV2, execute_tlc
    audit.local.operation_label = audit.local.case = label
    audit.local.control, audit.local.token = control, token
    before = len([row for row in audit.events if row["case"].startswith(label)])
    backend = engine(selection)
    require(len([row for row in audit.events if row["case"].startswith(label)]) == before,
            "public V2 engine construction eagerly launched provider setup")
    bounds = baseline.bounded_request().bounds
    source = {"document": document()} if compiled_document else {"artifacts": fixture}
    controls = {}
    if token is not None:
        controls["cancellation"] = token
    if timeout is not None:
        controls["operation_timeout_ms"] = timeout
    try:
        if route == "engine":
            request = StateExecutionRequestV2(request_id="req:" + label, provider="tlc", module_name="BoundedCounter",
                bounds=bounds, **source)
            return backend.execute(request, **controls)
        return execute_tlc(engine=backend, request_id="req:" + label, module_name="BoundedCounter",
                           bounds=bounds, **source, **controls)
    finally:
        audit.local.control = audit.local.token = audit.local.cancel_live_probe = None


def rows_for(audit, label):
    return ([row for row in audit.events if row["case"] in {label, label + ":constructor"}],
            [row for row in audit.results if row["case"] in {label, label + ":constructor"}])


def validate_phases(audit, label, selection, fixture, expected, *, stopped=None):
    launches, rows = rows_for(audit, label)
    details = [row for row in audit.requests if row["case"] in {label, label + ":constructor"}]
    require(len(launches) == len(rows) == len(details) == len(expected), "unexpected phase starts/lifecycles")
    for kind, launch, row, detail in zip(expected, launches, rows, details):
        native, request = row["result"], row["request"]
        if kind == "setup":
            argv = [selection["java"], *baseline.java_baseline.JAVA_FLAGS]
        elif kind == "model":
            argv = [selection["wrapper"], "-workers", "1", "-config", "BoundedCounter.cfg", "BoundedCounter.tla"]
        else:
            argv = [selection["wrapper"], "-help"]
        require(request["argv"] == native["command"] == detail["argv"] == argv and launch["argv"][-len(argv):] == argv,
                "native setup/model/help command differs from reviewed selection")
        require(native["pid"] is not None and native["workspace_cleaned"] and not Path("/proc", str(native["pid"])).exists()
                and not any(native[key] for key in ("unavailable", "resource_exhausted", "output_truncated",
                    "workspace_limit_exceeded", "error")), "TLC phase failed resource/identity/cleanup checks")
        require(request["memory_bytes"] == 4 * 1024**3 and request["resident_memory_bytes"] == 256 * MIB
                and request["max_output_bytes"] == baseline.OUTPUT_BYTES
                and 0 < request["timeout_seconds"] <= (10 if kind == "setup" else 3 if kind == "help" else 15)
                and request["stdin_is_empty"] and request["java_option_environment_absent"],
                "native phase lost reviewed finite JVM profile")
        limits = detail["limits"]
        require(0 < limits["cpu_seconds"] <= request["timeout_seconds"]
                and limits["enforce_file_size_limit"] is True
                and limits["max_file_bytes"] == (MIB if kind == "setup" else None)
                and limits["max_workspace_bytes"] == (MIB if kind == "setup" else 16 * MIB),
                "native CPU/workspace or inherited finite file cap differs")
        lease = next(item for item in launch["owned_leases"] if item["lease_id"] == launch["launch_lease_id"])
        require((lease["cpu_slots"], lease["memory_mb"], lease["child_process_slots"]) == (1, 256, 1)
                and lease["parent_lease_id"] is None, "phase lost actual default one-slot root ownership")
        if kind == "model":
            require(detail["input_sha256"] == {"BoundedCounter.tla": hashlib.sha256(fixture.model_text.encode()).hexdigest(),
                "BoundedCounter.cfg": hashlib.sha256(fixture.tlc_config_text.encode()).hexdigest()}, "model bytes differ")
            require(request["input_file_count"] == 2 and request["output_path_count"] == 3
                    and detail["limits"]["max_workspace_bytes"] == 16 * MIB
                    and detail["limits"]["max_input_bytes"] == max(4096, len(fixture.model_text.encode()) + len(fixture.tlc_config_text.encode())),
                    "model workspace/input bounds differ")
        else:
            require(request["input_file_count"] == request["output_path_count"] == 0
                    and limits["max_input_bytes"] == (1024 if kind == "setup" else 4096),
                    "identity phase received model input or lost its input cap")
        require(detail["output_paths"] == (["counterexample.tla", "violation.tla", "example.tla"] if kind == "model" else []),
                "native declared output paths differ")
        interrupted = stopped == kind
        if interrupted:
            require((native["cancelled"] or native["timed_out"]) and native["process_tree_terminated"],
                    "native stop did not terminate actual bounded process")
        else:
            require(not native["cancelled"] and not native["timed_out"] and not native["process_tree_terminated"]
                    and native["returncode"] in ({0, 12} if kind == "model" else {1} if kind == "help" else {0}),
                    "completed native phase did not remain clean")
    budgets = [row for row in audit.phase_budgets if row["case"] == label]
    require(len(budgets) == len(expected), "missing aggregate phase-budget observation")
    require(len({row["deadline"] for row in budgets}) <= 1, "setup/model/help did not share one absolute deadline")
    # An admitted runner may tighten the native request further while waiting.
    require(all(row["request_timeout_seconds"] <= row["remaining_seconds"] + .05 for row in budgets),
            "phase request expanded the aggregate remaining deadline")
    return rows


def baseline_case(route, valid, audit, selection, label):
    from ipfs_datasets_py.logic.backends.tla.execution_v2 import BackendRequest, FrozenMap, QueryKind, StateExecutionRequestV2, _digest_of
    fixture = baseline.artifacts(valid)
    started = time.monotonic()
    result = execute(route, audit, selection, label, fixture)
    rows = validate_phases(audit, label, selection, fixture, ("setup", "model", "help"))
    require(result.outcome is not None and result.result.status.value == ("satisfied" if valid else "violated")
            and result.disposition.value == ("satisfied" if valid else "counterexample"), "public V2 model disposition differs")
    evidence = result.evidence.to_dict()
    require(result.provider.value == "tlc" and evidence["model_check_established"] is True
            and evidence["theorem_established"] is False, "V2 evidence crossed bounded-model authority")
    outcome = result.outcome
    request = StateExecutionRequestV2(request_id="req:" + label, provider="tlc", module_name="BoundedCounter",
        bounds=baseline.bounded_request().bounds, artifacts=fixture)
    digest = _digest_of(request.to_dict())
    backend_request = BackendRequest(request_id=request.request_id, claim_id=f"claim:state:{request.request_id}",
        declaration_id=f"declaration:state:{request.request_id}", claim_digest=digest,
        obligation_id=f"obligation:state:{request.request_id}", obligation_digest=digest,
        assumption_ids=("assumption:bounded-model-check",), logic_family="state_transition",
        query_kind=QueryKind.SATISFIABILITY, bounds=request.bounds,
        payload=FrozenMap({"module_name": fixture.module_name, "provider": "tlc"}), requested_backend_id="tlc")
    require(outcome.receipt.model_digest == fixture.model_digest and outcome.receipt.artifact_digest == fixture.artifact_digest
            and outcome.receipt.configuration_digest == fixture.tlc_config_digest and outcome.receipt.bounded
            and not outcome.receipt.unbounded_proof and result.request_digest == result.evidence.request_digest == digest
            and outcome.request_digest == backend_request.digest,
            "V2 outcome lost source/config/request bindings")
    require(rows[1]["result"]["returncode"] == (0 if valid else 12), "TLC model exit status differs")
    if valid:
        require("4 distinct states found" in rows[1]["result"]["stdout"] and outcome.receipt.counterexample is None,
                "tiny valid state space did not complete")
    else:
        require(outcome.receipt.counterexample is not None
                and [state.assignments.get("n") for state in outcome.receipt.counterexample.states] == ["0", "1", "2"],
                "real invalid fixture lost counterexample")
    return {"case": label, "route": route, "valid": valid, "phase_count": 3,
            "elapsed_seconds": time.monotonic() - started, "result": result.to_dict()}


def control_case(kind, audit, selection):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled, ProofOperationTimeout
    label = "control:" + kind
    token = CancellationToken()
    if kind == "pre_setup_cancel":
        token.cancel()
    timeout = 1500 if kind == "compile_deadline" else 1200 if kind == "live_model_deadline" else 5000
    fixture = deadline_artifacts() if kind == "live_model_deadline" else baseline.artifacts(False)
    started = time.monotonic()
    expected_error = ProofOperationTimeout if kind.endswith("deadline") else ProofOperationCancelled
    try:
        execute("helper", audit, selection, label, fixture, control=kind, token=token, timeout=timeout,
                compiled_document=kind == "compile_deadline")
    except expected_error as error:
        failure = {"type": type(error).__name__, **error.to_dict()}
    else:
        raise AssertionError("interrupted aggregate operation published a result")
    expected = () if kind == "pre_setup_cancel" else ("setup",) if kind in {
        "live_setup_cancel", "after_setup_cancel", "compile_deadline"} else ("setup", "model")
    stopped = "setup" if kind == "live_setup_cancel" else "model" if kind in {"live_model_cancel", "live_model_deadline"} else None
    rows = validate_phases(audit, label, selection, fixture, expected, stopped=stopped)
    boundaries = [row for row in audit.boundaries if row["case"] == label]
    triggers = [row for row in audit.triggers if row["case"] in {label, label + ":constructor"}]
    if kind in {"live_setup_cancel", "live_model_cancel"}:
        require(len(triggers) == 1 and triggers[0]["observed_live"]
                and triggers[0]["pid"] == rows[-1]["result"]["pid"], "cancellation lacked real live Popen observation")
    elif kind == "live_model_deadline":
        require(len(boundaries) == 1 and boundaries[0]["observed_live"]
                and boundaries[0]["at_monotonic"] < boundaries[0]["deadline"]
                and boundaries[0]["pid"] == rows[-1]["result"]["pid"], "deadline lacked actual live model process")
    elif kind == "compile_deadline":
        require(len(boundaries) == 1 and boundaries[0]["at_monotonic"] > boundaries[0]["deadline"]
                and boundaries[0]["artifacts"]["model_text"], "compiler deadline was not observed after true compilation")
    elif kind in {"after_setup_cancel", "after_model_cancel"}:
        require(len(boundaries) == 1 and boundaries[0]["workspace_cleaned"]
                and boundaries[0]["returncode"] == (0 if kind == "after_setup_cancel" else 12),
                "boundary cancellation did not follow genuine completed native work")
    elapsed = time.monotonic() - started
    require(elapsed < 10, "bounded stop control exceeded cleanup envelope")
    baseline.java_baseline.previous._drained(audit)
    return {"case": label, "kind": kind, "phase_count": len(expected), "phases": list(expected),
        "interruption": failure, "operation_timeout_ms": timeout, "elapsed_seconds": elapsed,
        "boundaries": boundaries, "live_triggers": triggers, "result_published": False,
        "deadline_native_flag_scope": "native polling may report cancellation or timeout; typed outer timeout is authoritative"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(runtime_baseline.base.ACCELERATE))
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "tla-operation-control-benchmark@1", "status": "running", "source_pins_before": pins(),
        "runs": [], "controls": [], "checks": {}, "runtime": saved.runtime(),
        "scope": {"public_v2_selected_tlc_setup": True, "new_apalache_processes": 0, "installation": False,
            "in_process_callbacks_cooperative": True, "scaling_claim": False,
            "memory": "per-process AS bound and sampled process-tree RSS; no kernel aggregate memory cap"}}
    previous_java = os.environ.get(JAVA_ENV)
    owner = audit = envelope = None
    started = time.monotonic()
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = baseline.java_baseline.previous.install_saved_owner(directory / "saved-scheduler-config.json")
        result["shared_before"] = saved.state_summary(owner.state_path)
        result["shared_pool_compatibility"] = owner._benchmark_pool_compatibility
        selection, tool_before = baseline.selected_tools()
        launcher = directory / "tlc-memory-aware"
        launcher.write_text(baseline.launcher_body(selection))
        launcher.chmod(0o700)
        selection["wrapper"] = str(launcher)
        tool_before[str(launcher)] = baseline.previous.tool_sha(launcher)
        result.update(tool_selection=selection, tool_files_before=tool_before,
            wrapper_profile={"java_flags": list(baseline.JAVA_FLAGS), "heap_bytes": 128 * MIB,
                "direct_exec_no_helper_forks": True, "java_tmpdir_from_private_workspace": True},
            selection_environment={JAVA_ENV: selection["java"]})
        os.environ[JAVA_ENV] = selection["java"]
        audit = OperationAudit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        write(directory / "fixtures.json", {"valid": baseline.artifacts(True).to_dict(),
            "invalid": baseline.artifacts(False).to_dict(), "deadline": deadline_artifacts().to_dict(),
            "compiler_input": document().to_dict()})
        for workers in WORKERS:
            batch_started = time.monotonic()
            jobs = (("engine", True), ("engine", False), ("helper", True), ("helper", False))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(lambda job: baseline_case(job[0], job[1], audit, selection,
                    f"parallel:{workers}:{job[0]}:{job[1]}"), jobs))
            result["runs"].append({"workers": workers, "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
            write(directory / "partial.json", result)
        for kind in CONTROLS:
            result["controls"].append(control_case(kind, audit, selection))
        result["checks"].update(twelve_public_v2_success_cases=sum(len(row["cases"]) for row in result["runs"]) == 12,
            seven_operation_stop_controls=len(result["controls"]) == 7,
            forty_five_real_phases=len(audit.events) == len(audit.results) == len(audit.requests) == 45,
            all_native_environments_sanitized=len(audit.environments) == len(audit.workspace_environments) == 45,
            overlapping_admitted_roots_observed=max(sum(not lease["parent_lease_id"] for lease in row["owned_leases"])
                for row in audit.events if row["case"].startswith("parallel:")) >= 2)
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if previous_java is None:
            os.environ.pop(JAVA_ENV, None)
        else:
            os.environ[JAVA_ENV] = previous_java
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["checks"].update(sources_stable=result["source_pins_before"] == result["source_pins_after"],
            java_selection_environment_restored=os.environ.get(JAVA_ENV) == previous_java)
        if "tool_files_before" in result:
            result["tool_files_after"] = {path: baseline.previous.tool_sha(path) for path in result["tool_files_before"]}
            result["checks"]["selected_tool_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=baseline.java_baseline.previous._config_bytes(
                result["shared_after"]["config"]) == baseline.java_baseline.previous._config_bytes(envelope["config"]),
                owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        if audit is not None:
            result.update(launches=len(audit.events), lifecycles=len(audit.results),
                native_lifecycles=sum(row["result"]["pid"] is not None for row in audit.results),
                prelaunch_lifecycles=sum(row["result"]["pid"] is None for row in audit.results))
            result["phase_counts"] = dict(Counter(row["phase"] for row in audit.phase_budgets))
            result["audit_sha256"] = {}
            for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                ("request-audit.json", audit.requests), ("control-audit.json", {"boundaries": audit.boundaries,
                    "triggers": audit.triggers, "phase_budgets": audit.phase_budgets})):
                write(directory / name, value)
                result["audit_sha256"][name] = sha(directory / name)
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                 for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
