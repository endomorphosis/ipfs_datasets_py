"""Qualify real Apalache scalar counterexample parsing and structural mapping.

Two serial default registry cases reuse the exact finite three-step artifacts
and native admission helpers from prior immutable qualifications. Parsed states
and raw source are descriptive evidence; this is not semantic model replay.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time
import traceback

import bench_tla_artifact_payload as previous
from bench_tla_artifact_payload import ap, artifacts
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__)}


def request(valid):
    base = previous.request(valid)
    suffix = str(valid).lower()
    return replace(base, request_id="request:counterexample-replay:" + suffix,
        claim_id="claim:counterexample-replay:" + suffix,
        declaration_id="declaration:counterexample-replay:" + suffix,
        obligation_id="obligation:counterexample-replay:" + suffix)


def verify_trace(trace, fixture):
    """Check actual scalar states and source association, not transition truth."""
    require([state.index for state in trace.states] == [1, 2, 3]
            and [state.label for state in trace.states] == ["State0", "State1", "State2"]
            and [dict(state.assignments) for state in trace.states] == [{"n": "0"}, {"n": "1"}, {"n": "2"}],
            "actual Apalache scalar states were not parsed exactly")
    require(all(state.raw in trace.raw and (state.label + " ==") in state.raw
                and "InvariantViolation" not in state.raw for state in trace.states),
            "state raw blocks lost their exact boundary/source")
    require(any(row.tla_symbol == "n" and row.source_id == "variable:counter:n" for row in fixture.source_map),
            "fixture variable source mapping changed")
    require(trace.replayed is True and len(trace.replay_notes) >= 3
            and all(any(("state " + str(state.index) + ":") in note and "n" in note
                        and "variable:counter:n" in note for note in trace.replay_notes) for state in trace.states),
            "mapped scalar trace lacks its conservative structural diagnostics")
    require("structural source-symbol mapping only; transitions and invariants were not evaluated" in trace.replay_notes
            and all("state " + str(state.index) + ": replayed mapped symbols: n" in trace.replay_notes
                    for state in trace.states), "structural replay scope or mapped-symbol notes differ")
    require(not any("unmapped" in note or "no parseable" in note for note in trace.replay_notes),
            "successful structural check contains unresolved mappings")
    return {"parsed_state_count": 3, "positive_ordinal_indexes": [1, 2, 3],
        "original_labels": ["State0", "State1", "State2"], "assignment_values": ["0", "1", "2"],
        "mapped_source_id": "variable:counter:n", "raw_state_blocks_preserved": True,
        "structural_mapping_only": True, "semantic_transition_check": False,
        "invariant_reevaluation": False, "solver_rerun": False}


def run_case(valid, audit, selection, result):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import proof_operation_scope
    from ipfs_datasets_py.logic.backends.tla import runners

    label = "counterexample-replay:apalache:" + str(valid).lower()
    req = request(valid)
    fixture = artifacts(valid)
    dispatch = ap.prepare_dispatch(audit, 1, label, result)
    audit.local.operation_label = audit.local.case = label
    audit.local.provider = "apalache"
    audit.local.control = audit.local.token = audit.local.cancel_live_probe = None
    old_factory, old_profile = registry._factory_constructors, sys.getprofile()
    require(old_profile is None, "benchmark requires no existing execution profiler")
    factories = old_factory()
    created, observed = [], []

    def selected_factory():
        backend = runners.ApalacheBackend(executable=selection["apalache_launcher"],
            java_executable=selection["apalache_java"], lazy_install=False)
        require(type(backend._runner) is ResourceAdmittedToolRunner, "default native admission was bypassed")
        created.append(backend)
        return backend

    def selected_factories():
        return {**factories, "apalache": selected_factory}

    original_run_code = runners.TLAModelCheckerBackend.run.__code__

    def observe_return(frame, event, value):
        if event == "return" and frame.f_code is original_run_code and isinstance(value, runners.ModelCheckOutcome):
            observed.append(value)

    started = time.monotonic()
    registry._factory_constructors = selected_factories
    try:
        before = len(audit.events)
        backend_registry = registry.default_backend_registry()
        wrapper = backend_registry["apalache"]
        require(type(wrapper) is registry.LazyMatrixProofBackend and not wrapper._delegate_loaded
                and len(audit.events) == before and not created, "registry discovery eagerly initialized a backend")
        sys.setprofile(observe_return)
        try:
            with proof_operation_scope(timeout_ms=req.bounds.timeout_ms):
                attempt, projected = backend_registry.run(req, backend_id="apalache")
        finally:
            sys.setprofile(old_profile)
        require(len(created) == len(observed) == 1 and wrapper._delegate is created[0]
                and sum(backend_registry[name]._delegate_loaded for name in backend_registry) == 1,
                "default lazy registry did not execute exactly one selected delegate")
    finally:
        sys.setprofile(old_profile)
        registry._factory_constructors = old_factory
    original = observed[0]
    submitted = req.payload.to_dict()["artifacts"]
    require(original.artifacts is not None and submitted == fixture.to_dict() == original.artifacts.to_dict(),
            "serialized artifact lost fields, bounds, digests, source map or losses")
    require(fixture.bounds.max_steps == 3 and len(fixture.source_map) == 2 and len(fixture.losses) == 1,
            "rich non-default artifact fixture was weakened")
    projection = previous.previous.verify_projection(req, attempt, projected, original, valid)
    phase_rows = ap.phases(audit, label, "apalache", valid, selection, ("setup", "model", "help"))
    require(original.receipt.command == tuple(phase_rows[1]["request"]["argv"])
            and original.receipt.model_digest == fixture.model_digest
            and original.receipt.artifact_digest == fixture.artifact_digest
            and original.receipt.configuration_digest == fixture.apalache_config_digest
            and original.receipt.tool_version == phase_rows[2]["result"]["stdout"].strip() == "0.58.3",
            "original native receipt lost its source/configuration/version binding")
    witness = None
    if valid:
        require(original.receipt.counterexample is None and not phase_rows[1]["result"]["output_files"],
                "valid bounded model returned a counterexample")
    else:
        raw = phase_rows[1]["result"]["output_files"].get("apalache-run/violation.tla", "")
        counterexample = original.receipt.counterexample
        require(raw and counterexample is not None and counterexample.raw == raw
                and counterexample.source == "checker_counterexample_file",
                "native raw witness or its exact source was lost")
        trace_checks = verify_trace(counterexample, fixture)
        require(all(note in original.result.diagnostics for note in counterexample.replay_notes),
                "typed result lost the original structural replay diagnostics")
        values = re.findall(r"(?ms)^State\d+\s*==\s*(?:/\\\s*)?n\s*=\s*(\d+)\s*(?=\n|$)", raw)
        require(values == ["0", "1", "2"], "raw native counterexample differs from finite input")
        require(projected.payload.to_dict()["result"]["witness"]["counterexample"] == counterexample.to_dict(),
                "generic payload lost the genuine original witness")
        witness = {"path": "apalache-run/violation.tla", "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "raw_state_values": values, "parsed_state_count": len(counterexample.states),
            "states": [state.to_dict() for state in counterexample.states],
            "replayed": counterexample.replayed, "replay_notes": list(counterexample.replay_notes),
            "structural_checks": trace_checks,
            "scope": "Parsed scalar assignments and mapped symbols only; no semantic transition/invariant attestation"}
    ap.finish_dispatch(audit, dispatch, label)
    return {"case": label, "valid": valid, "phase_count": 3, "elapsed_seconds": time.monotonic() - started,
            "request": req.to_dict(), "request_digest": req.digest, "attempt": attempt.to_dict(),
            "attempt_digest": attempt.digest, "result": projected.to_dict(), "original_outcome": original.to_dict(),
            "submitted_artifact": submitted, "decoded_artifact": original.artifacts.to_dict(),
            "complete_artifact_equal": True, "projection_checks": projection, "raw_witness": witness, "dispatch": dispatch,
            "default_lazy_factory_used": True, "selected_delegate_count": len(created),
            "original_return_observer_restored": sys.getprofile() is old_profile,
            "factory_restored": registry._factory_constructors is old_factory,
            "aggregate_scope_owner": "benchmark", "operation_timeout_ms": req.bounds.timeout_ms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ap.previous.runtime_baseline.base.ACCELERATE))
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "tla-counterexample-replay-benchmark@1", "status": "running", "source_pins_before": pins(),
        "runtime": saved.runtime(), "cases": [], "dispatches": [], "checks": {},
        "scope": {"registry_route": "default_backend_registry/LazyMatrixProofBackend",
            "factory_override": "Installed Apalache and Java selection, lazy_install=False only",
            "aggregate_scope_owner": "benchmark", "default_registry_aggregate_budget_claim": False,
            "native_transport_injected": False, "jvm_probe_injected": False, "installation": False,
            "tlc_execution": False, "raw_counterexample_and_parsed_states": True, "new_proof_cache_or_replay": False,
            "complete_serialized_artifact_preserved": True, "native_v2_execution": False,
            "source_map_structural_check": True, "semantic_counterexample_replay_claim": False, "throughput_scaling_claim": False, "hard_aggregate_resource_guarantee": False}}
    owner = audit = envelope = None
    old_java = os.environ.get(ap.previous.JAVA_ENV)
    started = time.monotonic()
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = ap.previous.baseline.java_baseline.previous.install_saved_owner(directory / "saved-scheduler-config.json")
        result["shared_before"] = saved.state_summary(owner.state_path)
        result["shared_pool_compatibility"] = owner._benchmark_pool_compatibility
        selection, files, native = ap.selected_tools(directory)
        result.update(tool_selection=selection, tool_files_before=files, packaged_native_entries=native)
        os.environ[ap.previous.JAVA_ENV] = selection["apalache_java"]
        audit = ap.Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        write(directory / "fixtures.json", {str(valid).lower(): artifacts(valid).to_dict() for valid in (True, False)})
        for valid in (True, False):
            result["cases"].append(run_case(valid, audit, selection, result))
            write(directory / "partial.json", result)
        result["checks"].update(complete_artifact_preserved=all(row["complete_artifact_equal"] for row in result["cases"]),
            exact_two_serial_cases=len(result["cases"]) == 2,
            actual_counterexample_states_preserved=result["cases"][1]["raw_witness"]["parsed_state_count"] == 3,
            conservative_structural_replay=result["cases"][1]["raw_witness"]["replayed"] is True,
            expected_real_phases=len(audit.events) == len(audit.results) == len(audit.requests) == 6,
            native_environments_sanitized=len(audit.environments) == len(audit.workspace_environments) == 6,
            owned_apalache_jvm_environments=len(audit.apalache_environments) == 4,
            exact_foreign_typed_payload=all(row["projection_checks"]["payload_exact_original_result"] for row in result["cases"]),
            observer_and_factory_restored=all(row["original_return_observer_restored"] and row["factory_restored"] for row in result["cases"]),
            no_generic_authority_promotion=all(row["result"]["status"] == "unknown" for row in result["cases"]))
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if old_java is None:
            os.environ.pop(ap.previous.JAVA_ENV, None)
        else:
            os.environ[ap.previous.JAVA_ENV] = old_java
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["checks"].update(sources_stable=result["source_pins_before"] == result["source_pins_after"],
            java_selection_environment_restored=os.environ.get(ap.previous.JAVA_ENV) == old_java)
        if "tool_files_before" in result:
            result["tool_files_after"] = {p: ap.previous.baseline.previous.tool_sha(p) for p in result["tool_files_before"]}
            result["checks"]["selected_tool_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=ap.previous.baseline.java_baseline.previous._config_bytes(
                result["shared_after"]["config"]) == ap.previous.baseline.java_baseline.previous._config_bytes(envelope["config"]),
                owned_work_drained=not result["shared_after"]["owned_active_leases"] and not result["shared_after"]["owned_waiting_requests"])
        if audit is not None:
            result.update(launches=len(audit.events), lifecycles=len(audit.results),
                native_lifecycles=sum(row["result"]["pid"] is not None for row in audit.results),
                prelaunch_lifecycles=sum(row["result"]["pid"] is None for row in audit.results),
                phase_counts=dict(Counter(row["phase"] for row in audit.phase_budgets)))
            result["audit_sha256"] = {}
            for name, value in (("launch-audit.json", audit.events), ("lifecycle-audit.json", audit.results),
                ("request-audit.json", audit.requests), ("phase-budget-audit.json", audit.phase_budgets),
                ("apalache-environment-audit.json", audit.apalache_environments)):
                write(directory / name, value)
                result["audit_sha256"][name] = sha(directory / name)
        result["child_usage"] = {key: getattr(resource.getrusage(resource.RUSAGE_CHILDREN), key) for key in ("ru_utime", "ru_stime", "ru_maxrss")}
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
