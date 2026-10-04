"""Native aggregate SMT deadline/cancellation qualification with real admission.

Successful fixtures reuse the prior consumer harness without running its main.
Stop controls observe actual process and semantic completion boundaries; they
never substitute solver responses, scheduler pressure, or execution results.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import statistics
import sys
import threading
import time
import traceback

import bench_smt_consumer_admission as previous
from bench_smt_consumer_admission import MIB, ROOT, bounds, obligation, require, saved, sha, write

DISABLED_RECOVERY_REFERENCE_SHA256 = "6924810e337a00cc32eadad4b3a2902e9cb9be3a17dcde7b2457157413c5f128"
_DISABLED_RECOVERY_FIELDS = {
    "proof_recovery_enabled": False, "proof_recovery_samples": 2,
    "proof_recovery_grants": 4, "proof_recovery_interval_seconds": 0.25,
}


def _config_bytes(value):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceConfigurationError
    if type(value) is not dict:
        raise ResourceConfigurationError("benchmark requires an exact configuration object")
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ResourceConfigurationError("benchmark configuration must be finite inert JSON") from error


def pinned_config(value, state_path):
    """Retain only the reviewed, disabled foreign recovery metadata.

    The reviewed source is a retained evidence file, never an imported policy.
    Every ordinary scheduling method and the real host sampler stay local.
    Canonical comparisons preserve JSON types instead of treating False as 0.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    encoded = _config_bytes(value)
    owned = json.loads(encoded)
    if owned.get("proof_safety_enabled") is not True:
        raise scheduler.ResourceConfigurationError("benchmark requires enabled proof safety")
    present = set(owned) & set(_DISABLED_RECOVERY_FIELDS)
    extras = {}
    if present:
        if present != set(_DISABLED_RECOVERY_FIELDS):
            raise scheduler.ResourceConfigurationError("benchmark refuses partial recovery metadata")
        extras = {key: owned.pop(key) for key in _DISABLED_RECOVERY_FIELDS}
        if any(type(extras[key]) is not type(expected) or extras[key] != expected
               for key, expected in _DISABLED_RECOVERY_FIELDS.items()):
            raise scheduler.ResourceConfigurationError("benchmark only accepts exact reviewed disabled recovery metadata")

    class RetainingConfig(scheduler.ResourceSchedulerConfig):
        def persisted_dict(self):
            return {**super().persisted_dict(), **extras}

    try:
        config = RetainingConfig(state_path=state_path, **owned)
        config.validate()
    except (TypeError, ValueError) as error:
        raise scheduler.ResourceConfigurationError("benchmark cannot represent the complete saved configuration") from error
    if _config_bytes(config.persisted_dict()) != encoded:
        raise scheduler.ResourceConfigurationError("benchmark requires exact complete configuration round-trip")
    return config, {
        "mode": "reviewed_disabled_recovery_metadata" if extras else "native_config",
        "retained_disabled_fields": dict(extras), "config_sha256": hashlib.sha256(encoded).hexdigest(),
        "reviewed_external_source_sha256": DISABLED_RECOVERY_REFERENCE_SHA256 if extras else None,
        "production_recovery_policy_imported": False,
    }


def guarded_owner(config, expected_config):
    """Refuse recreation, policy activation, or typed config drift in every lock."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    expected = _config_bytes(expected_config)

    class ExistingPoolScheduler(scheduler.GlobalResourceScheduler):
        def _new_state(self):
            raise scheduler.ResourceConfigurationError("benchmark refuses missing or empty shared state recreation")

        def _validate_state_configuration(self, state, *, allow_reconfigure=False):
            if (_config_bytes(state.get("config")) != expected
                    or _config_bytes(self.config.persisted_dict()) != expected):
                raise scheduler.ResourceConfigurationError("benchmark refuses complete shared configuration drift")
            recovery = state.get("proof_recovery", {})
            if type(recovery) is not dict or recovery:
                raise scheduler.ResourceConfigurationError("benchmark refuses active or malformed foreign proof recovery")
            super()._validate_state_configuration(state, allow_reconfigure=False)

    return ExistingPoolScheduler(config)


def install_saved_owner(path):
    """Attach to the exact saved pool without resetting or widening its policy."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    envelope = saved.read_json(path)
    require(envelope["schema"] == saved.PIN_SCHEMA, "unknown saved configuration pin")
    state_path = Path(envelope["state_path"]).resolve()
    current = saved.state_summary(state_path)
    require(_config_bytes(current["config"]) == _config_bytes(envelope["config"]),
            "shared configuration changed after pinning")
    require(envelope.get("allow_foreign_work") is True or
            (not current["active_leases"] and not current["waiting_requests"]),
            "this saved pin does not allow existing shared work")
    config, compatibility = pinned_config(envelope["config"], state_path)
    owner = guarded_owner(config, envelope["config"])
    require(not saved.base.own_leases(owner), "qualification must start without owned leases")
    require(_config_bytes(saved.state_summary(state_path)["config"]) == _config_bytes(envelope["config"]),
            "benchmark installation changed the captured configuration")
    owner._benchmark_pool_compatibility = compatibility
    scheduler.default_resource_scheduler_config = lambda: config
    with scheduler._GLOBAL_SCHEDULERS_LOCK:
        scheduler._GLOBAL_SCHEDULERS[str(owner.state_path)] = owner
    require(scheduler.get_global_resource_scheduler() is owner, "default resource owner differs")
    return owner, envelope


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__),
            str(ROOT / "ipfs_datasets_py/logic/backends/smt/operation_budget.py"):
                sha(ROOT / "ipfs_datasets_py/logic/backends/smt/operation_budget.py")}


class OperationAudit(previous.Audit):
    """Delegate native execution unchanged and observe actual completion stops."""

    def __init__(self, owner):
        super().__init__(owner)
        self.native_starts = []
        self.triggers = []
        self.completed_peers = []
        self.completed_reports = []

    def install_observers(self):
        super().install_observers()
        from ipfs_datasets_py.logic.backends.process import SubprocessExecutor
        from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
        from ipfs_datasets_py.logic.backends.smt.differential import SmtDifferentialVerifier

        initialize = SubprocessExecutor.__init__

        def observed_initialize(executor, *args, **kwargs):
            initialize(executor, *args, **kwargs)
            popen = executor._popen

            def observed_popen(*args, **kwargs):
                process = popen(*args, **kwargs)
                control = getattr(self.local, "live_control", None)
                if control is not None:
                    # The audit event precedes Popen. This observation runs
                    # after the real constructor returned an actual live PID.
                    require(process.pid is not None and process.poll() is None
                            and Path("/proc", str(process.pid)).is_dir(),
                            "slow-control process was not observed alive")
                    self.local.live_control = None
                    label = getattr(self.local, "case", "setup")
                    record = {"case": label, "pid": process.pid,
                              "at_monotonic": time.monotonic(), "observed_live": True}
                    with self.lock:
                        self.native_starts.append(record)
                    if control["kind"] == "cancelled":
                        def cancel_started_process():
                            with self.lock:
                                self.triggers.append({"case": label, "kind": "cancelled",
                                    "boundary": "live_pid_plus_50ms", "pid": process.pid,
                                    "at_monotonic": time.monotonic()})
                            control["token"].cancel()
                        timer = threading.Timer(0.05, cancel_started_process)
                        timer.daemon = True
                        self.local.cancel_timer = timer
                        timer.start()
                return process
            executor._popen = observed_popen

        SubprocessExecutor.__init__ = observed_initialize
        run_compilation = Z3SoftwareVerificationBackend.run_compilation

        def observed_peer(backend, *args, **kwargs):
            outcome = run_compilation(backend, *args, **kwargs)
            token = getattr(self.local, "cancel_after_peer", None)
            if token is not None:
                self.local.cancel_after_peer = None
                require(outcome.backend_id == "z3" and outcome.result.status.value == "proved"
                        and bool(outcome.solver_version) and bool(outcome.unsat_core),
                        "first-peer control did not complete a real positive native peer")
                with self.lock:
                    self.completed_peers.append({"case": self.local.case, "outcome": outcome.to_dict()})
                    self.triggers.append({"case": self.local.case, "kind": "cancelled",
                        "boundary": "completed_first_peer", "at_monotonic": time.monotonic()})
                token.cancel()
            return outcome

        Z3SoftwareVerificationBackend.run_compilation = observed_peer
        report = SmtDifferentialVerifier._report

        def observed_report(verifier, *args, **kwargs):
            result = report(verifier, *args, **kwargs)
            control = getattr(self.local, "cancel_after_report", None)
            if control is not None:
                self.local.cancel_after_report = None
                previous._check_report(result, control["valid"])
                with self.lock:
                    self.completed_reports.append({"case": self.local.case, "report": result.to_dict()})
                    self.triggers.append({"case": self.local.case, "kind": "cancelled",
                        "boundary": "completed_first_pipeline_differential_report",
                        "at_monotonic": time.monotonic()})
                control["token"].cancel()
            return result

        SmtDifferentialVerifier._report = observed_report


def slow_obligation(pigeons=18):
    """A bounded Boolean CNF fixture whose unsatisfiability is intentionally hard."""
    from ipfs_datasets_py.logic.backends.smt.compiler import (
        BOOL_SORT, SmtFunDecl, SmtNamedAssertion, SmtObligation,
        SmtQueryMode, SmtTerm, SmtTermKind, term_false, term_symbol,
    )
    require(type(pigeons) is int and 3 <= pigeons <= 18, "bounded pigeonhole dimensions required")
    holes = pigeons - 1
    atom = lambda i, j: term_symbol(f"p{i}_{j}")
    clauses = [SmtNamedAssertion(name=f"occupies_{i}", formula=SmtTerm(
        SmtTermKind.OR, arguments=tuple(atom(i, j) for j in range(holes)))) for i in range(pigeons)]
    for j in range(holes):
        for i in range(pigeons):
            for k in range(i + 1, pigeons):
                clauses.append(SmtNamedAssertion(name=f"exclusive_{j}_{i}_{k}", formula=SmtTerm(
                    SmtTermKind.OR, arguments=(SmtTerm(SmtTermKind.NOT, arguments=(atom(i, j),)),
                                               SmtTerm(SmtTermKind.NOT, arguments=(atom(k, j),))))))
    return SmtObligation(obligation_id="obligation:operation-control:pigeonholes",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION, features=("verification_conditions",),
        goal=term_false(), assumptions=tuple(clauses), logic="QF_UF",
        functions=tuple(SmtFunDecl(name=f"p{i}_{j}", range=BOOL_SORT, is_const=True)
                        for i in range(pigeons) for j in range(holes)),
        request_model=True, request_unsat_core=True,
        property_ids=("property:operation-control:pigeonholes",))


def _stopped_call(callback, *, expected_kind):
    from ipfs_datasets_py.logic.backends.smt.operation_budget import (
        ProofOperationInterrupted, ProofOperationTimeout, ProofOperationCancelled,
    )
    started = time.monotonic()
    try:
        value = callback()
    except ProofOperationInterrupted as error:
        expected_type = ProofOperationCancelled if expected_kind == "cancelled" else ProofOperationTimeout
        require(isinstance(error, expected_type), "operation raised the wrong typed stop")
        elapsed = time.monotonic() - started
        require(elapsed < 10, "tiny native control exceeded its bounded observation window")
        return {"exception_type": type(error).__name__, "exception": error.to_dict(),
                "elapsed_seconds": elapsed, "returned_result": False}
    raise AssertionError("interrupted operation returned a result: " + repr(value)[:1000])


def _control_rows(audit, label):
    with audit.lock:
        return ([row for row in audit.events if row["case"] == label],
                [row for row in audit.results if row["case"] == label])


def _drained(audit):
    state = saved.state_summary(audit.owner.state_path)
    require(state["owned_active_leases"] == state["owned_waiting_requests"] == 0,
            "native control leaked owned work")
    return state


def slow_control(audit, compilation, *, cancelled):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.smt import run_z3_cvc5_differential
    label = "control:live-cancellation" if cancelled else "control:aggregate-deadline"
    audit.local.case = label
    token = CancellationToken()
    audit.local.live_control = {"kind": "cancelled" if cancelled else "timeout", "token": token}
    budget_ms = 5000 if cancelled else 1500
    try:
        result = _stopped_call(lambda: run_z3_cvc5_differential(compilation,
            bounds=bounds(timeout_ms=5000, max_steps=1_000_000_000,
                          max_memory_bytes=256 * MIB, max_output_bytes=MIB),
            operation_timeout_ms=budget_ms, cancellation=token),
            expected_kind="cancelled" if cancelled else "timeout")
    finally:
        timer = getattr(audit.local, "cancel_timer", None)
        if timer is not None:
            timer.cancel()
            timer.join(1)
            audit.local.cancel_timer = None
        audit.local.live_control = None
    launches, phases = _control_rows(audit, label)
    starts = [row for row in audit.native_starts if row["case"] == label]
    require(len(launches) == len(phases) == len(starts) == 1,
            "slow stop launched an artifact, version, or second peer")
    row, start = phases[0], starts[0]
    process, request = row["result"], row["request"]
    require(request["terminal_command"] == "(check-sat)" and "-in" in request["argv"],
            "slow control did not stop inside the first Z3 verdict")
    require(process["pid"] == start["pid"] and process["process_tree_terminated"]
            and process["workspace_cleaned"] and not Path("/proc", str(start["pid"])).exists(),
            "slow-control native process/tree/workspace did not drain")
    require(process["cancelled"] if cancelled else process["timed_out"] or process["cancelled"],
            "native lifecycle did not report interruption")
    require(not any(process[key] for key in ("resource_exhausted", "output_truncated", "workspace_limit_exceeded")),
            "slow control stopped for an unrelated resource failure")
    require(0 < request["timeout_seconds"] <= budget_ms / 1000,
            "aggregate budget was not inherited by the native request")
    require(request["memory_bytes"] == request["resident_memory_bytes"] == 256 * MIB,
            "slow control lost its finite memory limits")
    if cancelled:
        triggers = [row for row in audit.triggers if row["case"] == label]
        require(len(triggers) == 1 and token.is_set()
                and triggers[0]["at_monotonic"] >= start["at_monotonic"] + 0.045,
                "cancellation did not follow the actual live PID observation")
    result.update(case=label, expected_kind="cancelled" if cancelled else "timeout",
        operation_timeout_ms=budget_ms, phase_count=1, launch_count=1,
        native_start=start, shared_after=_drained(audit), no_followup_launch=True)
    return result


def completed_peer_control(audit):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.smt import run_z3_cvc5_differential
    label = "control:completed-first-peer"
    audit.local.case = label
    token = CancellationToken()
    audit.local.cancel_after_peer = token
    try:
        result = _stopped_call(lambda: run_z3_cvc5_differential(obligation(True), bounds=bounds(),
            operation_timeout_ms=5000, cancellation=token), expected_kind="cancelled")
    finally:
        audit.local.cancel_after_peer = None
    launches, phases = _control_rows(audit, label)
    require(len(launches) == len(phases) == 3 and token.is_set(),
            "completed-first-peer cancellation did not prevent the second peer")
    require([row["request"]["terminal_command"] for row in phases] == ["(check-sat)", "(get-unsat-core)", ""],
            "completed peer lost its full native query/core/version lifecycle")
    completed = [row for row in audit.completed_peers if row["case"] == label]
    require(len(completed) == 1, "first peer was not actually completed before cancellation")
    for row in phases:
        process, request = row["result"], row["request"]
        require(process["returncode"] == 0 and process["workspace_cleaned"]
                and not any(process[key] for key in ("cancelled", "timed_out", "unavailable",
                    "resource_exhausted", "output_truncated", "workspace_limit_exceeded",
                    "process_tree_terminated", "error")),
                "completed peer unexpectedly stopped inside a native phase")
        require(request["memory_bytes"] == request["resident_memory_bytes"] == 128 * MIB
                and 0 < request["timeout_seconds"] <= 5
                and 0 < request["max_output_bytes"] <= 65536,
                "completed peer lost its finite phase limits")
    result.update(case=label, expected_kind="cancelled", phase_count=3, launch_count=3,
        completed_peer=completed[0]["outcome"], shared_after=_drained(audit), no_second_peer_launch=True)
    return result


def pipeline_control(audit, *, valid):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.software_verification import SourceToVerificationPipeline
    from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
    label = "control:pipeline-after-first:" + ("proved" if valid else "disproved")
    source = ("def increment(x: int) -> int:\n    return " + ("x + 1" if valid else "x")
              + "\n\ndef other(y: int) -> int:\n    return y + 1\n")
    contracts = [ContractSpec("increment", postconditions=("result == x + 1",)),
                 ContractSpec("other", postconditions=("result == y + 1",))]
    arguments = {"path": "operation_increment.py", "language": "python", "contracts": contracts,
                 "revision": "benchmark:aggregate-operation-control"}
    preview = SourceToVerificationPipeline(bounds=bounds(), include_supervisor_evidence=False,
        execute_solvers=False).run(source, **arguments)
    require(preview.status.value == "success" and len(preview.obligation_results) == 2,
            "pipeline control requires two genuine source-bound obligations")
    token = CancellationToken()
    audit.local.case = label
    audit.local.cancel_after_report = {"token": token, "valid": valid}
    try:
        result = _stopped_call(lambda: SourceToVerificationPipeline(bounds=bounds(),
            include_supervisor_evidence=False, operation_timeout_ms=5000, cancellation=token).run(
                source, **arguments), expected_kind="cancelled")
    finally:
        audit.local.cancel_after_report = None
    phase_count = previous._check_phases(audit, label, "source_pipeline", valid)
    completed = [row for row in audit.completed_reports if row["case"] == label]
    require(phase_count == 6 and len(completed) == 1 and token.is_set(),
            "pipeline cancellation did not stop after the first complete obligation")
    require(completed[0]["report"]["obligation_id"] == preview.obligation_results[0].smt_obligation.obligation_id,
            "pipeline completion trigger did not bind the first source obligation")
    result.update(case=label, expected_kind="cancelled", phase_count=6, launch_count=6,
        completed_report=completed[0]["report"], source=source, contracts=[contract.to_dict() for contract in contracts],
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        planned_obligation_ids=[item.smt_obligation.obligation_id for item in preview.obligation_results],
        shared_after=_drained(audit), no_later_obligation_launch=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = pins()
    write(directory / "command.json", {"argv": sys.argv, "cwd": str(Path.cwd()),
        "environment": {key: os.environ.get(key) for key in (
            "PYTHONPATH", "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "IPFS_TEST_PROOF_REUSE_MODE")}})
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = install_saved_owner(directory / "saved-scheduler-config.json")
    except BaseException:
        failure = {"schema": "smt-operation-control-benchmark@1", "status": "failed",
            "failure_stage": "shared_pool_initialization", "error": traceback.format_exc(),
            "source_pins_before": before, "source_pins_after": pins(),
            "launches": 0, "lifecycles": 0, "native_execution_started": False,
            "shared_pool_compatibility": {"mode": "refused"}}
        write(directory / "result.json", failure)
        raise
    audit = OperationAudit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "smt-operation-control-benchmark@1", "status": "running",
        "source_pins_before": before, "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
        "runs": [], "controls": [], "checks": {},
        "shared_pool_compatibility": owner._benchmark_pool_compatibility,
        "scope": "Cooperative whole-operation stops plus admitted native process termination; no hard aggregate memory containment"}
    started = time.monotonic()
    try:
        result["executables"] = {}
        for name in ("z3", "cvc5"):
            path = shutil.which(name)
            require(path is not None, "required native solver is not installed: " + name)
            result["executables"][name] = {"path": path, "sha256": sha(path)}
        cases = [(kind, "differential", valid) for kind in (
            "public_differential", "verification_api", "source_pipeline") for valid in (True, False)]
        cases += [("classical", solver, valid) for solver in ("z3", "cvc5") for valid in (True, False)]
        for workers in previous.WORKERS:
            for repeat in range(previous.REPEATS):
                batch_started = time.monotonic()
                label = f"parallel:{workers}:{repeat}"
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    rows = list(pool.map(lambda item: previous.case(*item, audit, label), cases))
                require(sum(row["phase_count"] for row in rows) == 44, "successful batch lost native phases")
                result["runs"].append({"workers": workers, "repeat": repeat,
                    "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
                write(directory / "partial.json", result)
        audit.local.case = "parent"
        with owner.acquire("validation", cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=5) as parent:
            with ThreadPoolExecutor(max_workers=2) as pool:
                result["nested_cases"] = list(pool.map(lambda item: previous.case(*item, audit, "nested", parent=parent),
                    (("public_differential", "differential", True), ("source_pipeline", "differential", False))))
            nested = [event for event in audit.events if event["case"].startswith("nested:")]
            result["checks"]["native_children_bound_to_actual_parent"] = len(nested) == 12 and all(
                any(row["lease_id"] == event["launch_lease_id"] and row.get("parent_lease_id") == parent.lease_id
                    for row in event["owned_leases"]) for event in nested)
            state = saved.read_json(owner.state_path, 4 * MIB)
            own = [row for row in state["leases"].values() if row["owner_pid"] == os.getpid()]
            result["checks"]["children_drained_before_parent_release"] = len(own) == 1 and own[0]["lease_id"] == parent.lease_id
        from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
        from ipfs_datasets_py.logic.software_contracts.codebase_smt_protocol import split_smt_script
        slow = slow_obligation()
        compiled = SoftwareVerificationSMTCompiler().compile(slow)
        base, model, core = split_smt_script(compiled.script.source)
        require(model and core and base.endswith("(check-sat)\n"), "slow fixture left the existing closed native profile")
        write(directory / "slow-fixture.json", {"obligation": slow.to_dict(), "compilation": compiled.to_dict()})
        result["slow_fixture"] = {"file": "slow-fixture.json", "sha256": sha(directory / "slow-fixture.json"),
            "source_bytes": len(compiled.script.source.encode()), "assumptions": len(slow.assumptions),
            "variables": len(slow.functions), "script_digest": compiled.script.digest}
        result["controls"].append(slow_control(audit, compiled, cancelled=True))
        result["controls"].append(slow_control(audit, compiled, cancelled=False))
        result["controls"].append(completed_peer_control(audit))
        for valid in (True, False):
            result["controls"].append(pipeline_control(audit, valid=valid))
        result["median_seconds"] = {str(n): statistics.median(
            run["elapsed_seconds"] for run in result["runs"] if run["workers"] == n) for n in previous.WORKERS}
        result["checks"].update(
            all_60_successful_batch_cases=sum(len(run["cases"]) for run in result["runs"]) == 60,
            all_264_batch_native_phases=sum(row["phase_count"] for run in result["runs"] for row in run["cases"]) == 264,
            all_five_typed_stops_withhold_results=len(result["controls"]) == 5
                and all(control["returned_result"] is False for control in result["controls"]),
            exactly_17_control_native_phases=sum(control["phase_count"] for control in result["controls"]) == 17,
            all_293_launches_have_lifecycles=len(audit.events) == len(audit.results) == 293,
            concurrent_owned_roots_observed=max(sum(not row.get("parent_lease_id") for row in event["owned_leases"])
                for event in audit.events if event["case"].startswith("parallel:")) >= 2,
            installed_executables_unchanged=all(sha(value["path"]) == value["sha256"] for value in result["executables"].values()))
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
        raise
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["shared_after"] = saved.state_summary(owner.state_path)
        result["checks"].update(sources_stable=result["source_pins_after"] == before,
            shared_config_unchanged=result["shared_after"]["config"] == envelope["config"],
            owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                 for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["memory_observation_scope"] = "Largest reaped child in Linux KiB; not aggregate peak RSS"
        for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                            ("control-audit.json", {"native_starts": audit.native_starts, "triggers": audit.triggers,
                                "completed_peers": audit.completed_peers, "completed_reports": audit.completed_reports})):
            write(directory / name, value)
            result[name + "_sha256"] = sha(directory / name)
        result.update(launches=len(audit.events), lifecycles=len(audit.results))
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "aggregate native operation-control qualification failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "median_seconds")}))


if __name__ == "__main__":
    main()
