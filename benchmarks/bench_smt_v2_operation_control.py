"""Qualify real V2 SMT execution, replay, and aggregate operation stops.

Default engines execute installed solvers in both pinned and hermetic modes;
no fixture runner is injected. Observers delegate actual process/evidence work.
The saved shared pool, real pressure sampler, and prior harnesses stay unchanged.
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
import sys
import time
import traceback

import bench_smt_operation_control as previous
from bench_smt_operation_control import MIB, ROOT, bounds, obligation, require, saved, sha, write

WORKERS = (1, 2, 4)


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__)}


class V2Audit(previous.OperationAudit):
    """Observe real semantic boundaries without replacing their return values."""

    def __init__(self, owner):
        super().__init__(owner)
        self.v2_boundaries = []

    def install_observers(self):
        super().install_observers()
        from ipfs_datasets_py.logic.backends.smt.execution_v2 import (
            SmtExecutionEngineV2, SmtProviderEvidenceV2,
        )
        immediate = SmtExecutionEngineV2._immediate_replay

        def observed_immediate(engine, *args, **kwargs):
            token = getattr(self.local, "cancel_before_immediate", None)
            if token is not None:
                self.local.cancel_before_immediate = None
                require(kwargs["primary"].result.status.value == "proved",
                        "automatic replay control has no completed native theorem")
                with self.lock:
                    self.v2_boundaries.append({"case": self.local.case,
                        "boundary": "before_automatic_replay",
                        "obligation_digest": kwargs["obligation_digest"],
                        "script_digest": kwargs["script_digest"]})
                    self.triggers.append({"case": self.local.case, "kind": "cancelled",
                        "boundary": "before_automatic_replay", "at_monotonic": time.monotonic()})
                token.cancel()
            return immediate(engine, *args, **kwargs)

        SmtExecutionEngineV2._immediate_replay = observed_immediate
        validate = SmtProviderEvidenceV2.__post_init__

        def observed_evidence(evidence):
            validate(evidence)
            token = getattr(self.local, "cancel_after_evidence", None)
            if token is not None:
                self.local.cancel_after_evidence = None
                require(evidence.disposition.value == "disproved" and evidence.model.present
                        and evidence.proof_established is False,
                        "evidence control lacks a real validated counterexample receipt")
                with self.lock:
                    self.v2_boundaries.append({"case": self.local.case,
                        "boundary": "after_validated_evidence", "evidence": evidence.to_dict()})
                    self.triggers.append({"case": self.local.case, "kind": "cancelled",
                        "boundary": "after_validated_evidence", "at_monotonic": time.monotonic()})
                token.cancel()

        SmtProviderEvidenceV2.__post_init__ = observed_evidence


def request(label, provider, mode, valid, *, fixture=None, selected_bounds=None):
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import SmtExecutionRequestV2
    return SmtExecutionRequestV2(request_id="req:v2:" + label,
        obligation=obligation(valid) if fixture is None else fixture,
        provider=provider, mode=mode, bounds=selected_bounds or bounds(),
        source_ref_ids=("source:benchmark:arithmetic-fixture",))


def _providers(provider, mode):
    sequence = ["z3", "cvc5"] if provider == "differential" else [provider]
    if mode == "hermetic_fixture":
        sequence.append("cvc5" if provider == "cvc5" else "z3")
    return sequence


def _check_phases(audit, label, providers, valid):
    launches, phases = previous._control_rows(audit, label)
    require(len(launches) == len(phases) == 3 * len(providers),
            "V2 native phase count differs for " + label)
    expected = ["(check-sat)", "(get-unsat-core)" if valid else "(get-model)", ""]
    for index, provider in enumerate(providers):
        group = phases[index * 3:index * 3 + 3]
        require([row["request"]["terminal_command"] for row in group] == expected,
                "V2 native query/artifact/version order differs")
        require(all(("-in" in row["request"]["argv"] if provider == "z3"
                     else "--lang=smt2" in row["request"]["argv"])
                    for row in group[:2]), "V2 phase used the wrong solver")
        for row in group:
            native, limits = row["result"], row["request"]
            require(native["pid"] is not None and native["returncode"] == 0
                    and native["workspace_cleaned"], "V2 phase did not complete and clean up")
            require(not any(native[key] for key in (
                "cancelled", "timed_out", "unavailable", "resource_exhausted", "output_truncated",
                "workspace_limit_exceeded", "process_tree_terminated", "error")),
                "V2 phase has an unsafe native lifecycle result")
            require(limits["memory_bytes"] == limits["resident_memory_bytes"] == 128 * MIB
                    and 0 < limits["timeout_seconds"] <= 5
                    and 0 < limits["max_output_bytes"] <= 65536,
                    "V2 phase lost finite native limits")
        require(group[0]["request"]["stdin_sha256"] == phases[0]["request"]["stdin_sha256"]
                and group[1]["request"]["stdin_sha256"] == phases[1]["request"]["stdin_sha256"],
                "V2 peers/replays used different query or artifact bytes")
    return len(phases)


def _check_execution(outcome, req, valid):
    from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import _digest_of
    compilation = SoftwareVerificationSMTCompiler().compile(req.obligation)
    evidence = outcome.evidence
    require(outcome.request is req and evidence.request_id == req.request_id
            and evidence.request_digest == _digest_of(req.to_dict())
            and evidence.obligation_digest == req.obligation_digest
            and evidence.source_ref_ids == req.source_ref_ids,
            "V2 evidence lost its exact request/obligation/source binding")
    require(evidence.compilation_id == compilation.compilation_id
            and evidence.obligation_id == compilation.obligation_id
            and evidence.script_digest == compilation.script.digest
            and evidence.translation_receipt_id == compilation.receipt.receipt_id,
            "V2 evidence lost its canonical compilation and translation receipt")
    require(evidence.disposition.value == ("proved" if valid else "disproved")
            and evidence.solver_verdict == ("unsat" if valid else "sat")
            and evidence.result_status.value == ("proved" if valid else "disproved")
            and outcome.backend_result.status.value == evidence.result_status.value,
            "V2 returned the wrong mathematical result")
    require(evidence.provider is req.provider and evidence.mode is req.mode
            and evidence.solver_backend_id == ("cvc5" if req.provider.value == "cvc5" else "z3")
            and bool(evidence.solver_version), "V2 evidence lost actual provider/version")
    require(evidence.result_authority.value == "theorem" and evidence.translation_ceiling.value == "bounded"
            and evidence.theorem_established and evidence.satisfiability_established
            and evidence.proof_established is False and not evidence.proof.present,
            "V2 evidence exceeded or lost its existing theorem-by-negation ceiling")
    require(evidence.model.present is (not valid) and evidence.unsat_core.present is valid,
            "V2 evidence lost its applicable native artifact")
    if valid:
        require(bool(evidence.unsat_core.atoms) and bool(evidence.unsat_core.digest),
                "V2 unsat core lacks bound atoms/digest")
    else:
        require("define-fun" in evidence.model.text_excerpt and bool(evidence.model.digest),
                "V2 counterexample lacks a bound native model")
    if req.provider.value == "differential":
        previous.previous._check_report(outcome.differential_report, valid, expected_obligation=req.obligation)
        require(evidence.differential.agreement, "V2 differential binding lost agreement")
    else:
        require(outcome.differential_report is None and evidence.differential is None,
                "single-provider V2 result invented differential evidence")
    if req.mode.value == "hermetic_fixture":
        _check_replay(evidence.replay, outcome)
    else:
        require(evidence.replay is None, "pinned V2 execution unexpectedly added automatic replay")


def _check_replay(receipt, outcome):
    evidence = outcome.evidence
    require(receipt is not None and receipt.matched and receipt.replay_claimed
            and receipt.request_id == outcome.request.request_id
            and receipt.obligation_digest == evidence.obligation_digest
            and receipt.script_digest == evidence.script_digest
            and receipt.original_disposition is evidence.disposition
            and receipt.replayed_disposition is evidence.disposition
            and receipt.original_verdict == receipt.replayed_verdict == evidence.solver_verdict,
            "V2 replay lacks exact same-obligation/script/verdict binding")


def case(provider, mode, valid, audit, label, *, parent=None):
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import SmtExecutionEngineV2
    identifier = label + ":" + provider + ":" + mode + ":" + str(valid)
    audit.local.case = identifier
    req = request(identifier, provider, mode, valid)
    backends = {}
    if parent is not None:
        from ipfs_datasets_py.logic.backends.z3 import Z3SoftwareVerificationBackend
        from ipfs_datasets_py.logic.backends.cvc5 import CVC5SoftwareVerificationBackend
        backends = {"z3": Z3SoftwareVerificationBackend(parent_lease=parent),
                    "cvc5": CVC5SoftwareVerificationBackend(parent_lease=parent)}
    engine = SmtExecutionEngineV2(**backends)
    started = time.monotonic()
    outcome = engine.execute(req)
    _check_execution(outcome, req, valid)
    original = outcome.to_dict()
    replay = engine.replay(outcome)
    _check_replay(replay, outcome)
    require(outcome.to_dict() == original, "explicit replay mutated original evidence")
    phases = _check_phases(audit, identifier, _providers(provider, mode) * 2, valid)
    return {"case": identifier, "provider": provider, "mode": mode, "valid": valid,
        "elapsed_seconds": time.monotonic() - started, "phase_count": phases,
        "default_aggregate_timeout_ms": req.bounds.timeout_ms,
        "fixture": req.obligation.to_dict(), "outcome": original, "explicit_replay": replay.to_dict()}


def _no_later_launch(audit, label):
    launches, _ = previous._control_rows(audit, label)
    triggers = [row for row in audit.triggers if row["case"] == label]
    require(len(triggers) == 1 and all(row["at_monotonic"] <= triggers[0]["at_monotonic"] for row in launches),
            "V2 launched native work after its cancellation trigger")
    return triggers[0]


def slow_control(audit, compilation, *, cancelled):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import SmtExecutionEngineV2
    label = "control:v2:live-cancellation" if cancelled else "control:v2:aggregate-deadline"
    audit.local.case = label
    token = CancellationToken()
    audit.local.live_control = {"kind": "cancelled" if cancelled else "timeout", "token": token}
    budget_ms = 5000 if cancelled else 1500
    req = request(label, "differential", "hermetic_fixture", True, fixture=compilation,
        selected_bounds=bounds(timeout_ms=5000, max_steps=1_000_000_000,
                               max_memory_bytes=256 * MIB, max_output_bytes=MIB))
    try:
        result = previous._stopped_call(lambda: SmtExecutionEngineV2().execute(req,
            operation_timeout_ms=budget_ms, cancellation=token),
            expected_kind="cancelled" if cancelled else "timeout")
    finally:
        timer = getattr(audit.local, "cancel_timer", None)
        if timer is not None:
            timer.cancel()
            timer.join(1)
            audit.local.cancel_timer = None
        audit.local.live_control = None
    launches, phases = previous._control_rows(audit, label)
    starts = [row for row in audit.native_starts if row["case"] == label]
    require(len(launches) == len(phases) == len(starts) == 1,
            "V2 live stop launched artifacts, version, peer, or replay")
    native, limits, start = phases[0]["result"], phases[0]["request"], starts[0]
    require(limits["terminal_command"] == "(check-sat)" and "-in" in limits["argv"]
            and native["pid"] == start["pid"] and native["process_tree_terminated"]
            and native["workspace_cleaned"] and not Path("/proc", str(start["pid"])).exists(),
            "V2 live first verdict did not terminate its native process/tree/workspace")
    require(native["cancelled"] if cancelled else native["cancelled"] or native["timed_out"],
            "V2 lifecycle did not reflect native interruption")
    require(not any(native[key] for key in ("resource_exhausted", "output_truncated", "workspace_limit_exceeded"))
            and limits["memory_bytes"] == limits["resident_memory_bytes"] == 256 * MIB
            and 0 < limits["timeout_seconds"] <= budget_ms / 1000,
            "V2 stop lost native bounds or failed from unrelated resource exhaustion")
    if cancelled:
        trigger = _no_later_launch(audit, label)
        require(token.is_set() and trigger["at_monotonic"] >= start["at_monotonic"] + 0.045,
                "V2 cancellation did not follow an actual live PID by 50ms")
        result["trigger"] = trigger
    result.update(case=label, expected_kind="cancelled" if cancelled else "timeout",
        operation_timeout_ms=budget_ms, phase_count=1, launch_count=1,
        native_start=start, no_followup_launch=True, shared_after=previous._drained(audit))
    return result


def boundary_control(audit, boundary):
    from ipfs_datasets_py.logic.backends.process import CancellationToken
    from ipfs_datasets_py.logic.backends.smt.execution_v2 import SmtExecutionEngineV2
    choices = {
        "between_peers": ("differential", "pinned_solver", True, "cancel_after_peer"),
        "before_automatic_replay": ("z3", "hermetic_fixture", True, "cancel_before_immediate"),
        "during_explicit_replay": ("differential", "pinned_solver", True, "cancel_after_peer"),
        "after_evidence": ("z3", "pinned_solver", False, "cancel_after_evidence"),
    }
    provider, mode, valid, hook = choices[boundary]
    label = "control:v2:" + boundary
    req = request(label, provider, mode, valid)
    engine = SmtExecutionEngineV2()
    setup_phases = 0
    original = None
    if boundary == "during_explicit_replay":
        audit.local.case = label + ":original"
        original = engine.execute(req)
        _check_execution(original, req, valid)
        setup_phases = _check_phases(audit, audit.local.case, _providers(provider, mode), valid)
    audit.local.case = label
    token = CancellationToken()
    setattr(audit.local, hook, token)
    try:
        result = previous._stopped_call(
            (lambda: engine.replay(original, cancellation=token)) if original is not None
            else (lambda: engine.execute(req, cancellation=token)), expected_kind="cancelled")
    finally:
        setattr(audit.local, hook, None)
    phases = _check_phases(audit, label, ["z3"], valid)
    trigger = _no_later_launch(audit, label)
    require(token.is_set(), "V2 boundary token was never cancelled")
    result.update(case=label, boundary=boundary, expected_kind="cancelled", trigger=trigger,
        phase_count=phases + setup_phases, interrupted_call_phase_count=phases,
        setup_phase_count=setup_phases, launch_count=phases + setup_phases,
        no_followup_launch=True, shared_after=previous._drained(audit))
    if original is not None:
        _check_execution(original, req, valid)
        result["original_result"] = original.to_dict()
        result["returned_replay_receipt"] = False
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
        previous.saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = previous.install_saved_owner(directory / "saved-scheduler-config.json")
    except BaseException:
        write(directory / "result.json", {"schema": "smt-v2-operation-control-benchmark@1", "status": "failed",
            "failure_stage": "shared_pool_initialization", "error": traceback.format_exc(),
            "source_pins_before": before, "source_pins_after": pins(),
            "launches": 0, "lifecycles": 0, "native_execution_started": False,
            "shared_pool_compatibility": {"mode": "refused"}})
        raise
    audit = V2Audit(owner)
    audit.install_observers()
    sys.addaudithook(audit.observe)
    result = {"schema": "smt-v2-operation-control-benchmark@1", "status": "running",
        "source_pins_before": before, "runtime": saved.runtime(), "shared_before": saved.state_summary(owner.state_path),
        "runs": [], "controls": [], "checks": {}, "shared_pool_compatibility": owner._benchmark_pool_compatibility,
        "scope": "Default live V2 backends including automatic/explicit replay; cooperative aggregate stops; finite per-phase limits",
        "mode_scope": "hermetic_fixture is the existing mode label; these default engines execute actual installed solvers"}
    started = time.monotonic()
    try:
        result["executables"] = {}
        for name in ("z3", "cvc5"):
            path = shutil.which(name)
            require(path is not None, "required native solver is not installed: " + name)
            result["executables"][name] = {"path": path, "sha256": sha(path)}
        cases = [(provider, mode, valid) for provider in ("z3", "cvc5", "differential")
                 for mode in ("pinned_solver", "hermetic_fixture") for valid in (True, False)]
        for workers in WORKERS:
            batch_started = time.monotonic()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(lambda item: case(*item, audit, f"parallel:{workers}:0"), cases))
            require(sum(row["phase_count"] for row in rows) == 132, "V2 successful batch lost native phases")
            result["runs"].append({"workers": workers, "repeat": 0,
                "elapsed_seconds": time.monotonic() - batch_started, "cases": rows})
            write(directory / "partial.json", result)
        audit.local.case = "parent"
        with owner.acquire("validation", cpu_slots=2, memory_mb=256, child_process_slots=2, timeout=5) as parent:
            with ThreadPoolExecutor(max_workers=2) as pool:
                result["nested_cases"] = list(pool.map(lambda item: case(*item, audit, "nested", parent=parent),
                    (("differential", "hermetic_fixture", True), ("cvc5", "hermetic_fixture", False))))
            nested = [event for event in audit.events if event["case"].startswith("nested:")]
            result["checks"]["all_30_nested_launches_bound_to_actual_parent_including_replay"] = len(nested) == 30 and all(
                any(row["lease_id"] == event["launch_lease_id"] and row.get("parent_lease_id") == parent.lease_id
                    for row in event["owned_leases"]) for event in nested)
            state = saved.read_json(owner.state_path, 4 * MIB)
            own = [row for row in state["leases"].values() if row["owner_pid"] == os.getpid()]
            result["checks"]["native_children_drained_before_parent_release"] = len(own) == 1 and own[0]["lease_id"] == parent.lease_id
        from ipfs_datasets_py.logic.backends.smt.compiler import SoftwareVerificationSMTCompiler
        from ipfs_datasets_py.logic.software_contracts.codebase_smt_protocol import split_smt_script
        slow = previous.slow_obligation()
        compilation = SoftwareVerificationSMTCompiler().compile(slow)
        base, model, core = split_smt_script(compilation.script.source)
        require(model and core and base.endswith("(check-sat)\n"), "slow V2 fixture left the closed native profile")
        write(directory / "slow-fixture.json", {"obligation": slow.to_dict(), "compilation": compilation.to_dict()})
        result["slow_fixture"] = {"file": "slow-fixture.json", "sha256": sha(directory / "slow-fixture.json"),
            "source_bytes": len(compilation.script.source.encode()), "assumptions": len(slow.assumptions),
            "variables": len(slow.functions), "script_digest": compilation.script.digest}
        for cancelled in (True, False):
            result["controls"].append(slow_control(audit, compilation, cancelled=cancelled))
        for boundary in ("between_peers", "before_automatic_replay", "during_explicit_replay", "after_evidence"):
            result["controls"].append(boundary_control(audit, boundary))
        result["elapsed_seconds_by_workers"] = {str(run["workers"]): run["elapsed_seconds"] for run in result["runs"]}
        result["checks"].update(
            all_36_native_execution_and_explicit_replay_cases=sum(len(run["cases"]) for run in result["runs"]) == 36,
            all_396_successful_native_phases=sum(row["phase_count"] for run in result["runs"] for row in run["cases"]) == 396,
            all_six_typed_stops_withhold_results=len(result["controls"]) == 6
                and all(row["returned_result"] is False for row in result["controls"]),
            exactly_20_control_phases_including_original_replay_setup=sum(row["phase_count"] for row in result["controls"]) == 20,
            all_446_launches_have_lifecycles=len(audit.events) == len(audit.results) == 446,
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
            shared_config_unchanged=previous._config_bytes(result["shared_after"]["config"]) == previous._config_bytes(envelope["config"]),
            owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key)
                                 for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        result["memory_observation_scope"] = "Largest reaped child in Linux KiB; not aggregate peak RSS"
        for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                            ("control-audit.json", {"native_starts": audit.native_starts, "triggers": audit.triggers,
                                "completed_peers": audit.completed_peers, "v2_boundaries": audit.v2_boundaries})):
            write(directory / name, value)
            result[name + "_sha256"] = sha(directory / name)
        result.update(launches=len(audit.events), lifecycles=len(audit.results))
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    require(result["status"] == "passed", "V2 aggregate native operation-control qualification failed")
    print(json.dumps({key: result[key] for key in ("status", "checks", "launches", "elapsed_seconds_by_workers")}))


if __name__ == "__main__":
    main()
