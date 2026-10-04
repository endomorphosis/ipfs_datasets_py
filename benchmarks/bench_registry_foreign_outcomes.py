"""Qualify conservative registry projection of two actual Apalache outcomes.

Two serial finite models use the default lazy registry and admitted native
transport. Only installed-tool selection is supplied through its factory. An
explicit benchmark-owned operation scope bounds Java setup and each whole case;
this is not a new production registry aggregate-budget guarantee.
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

import bench_apalache_resource_admission as previous
from bench_smt_operation_control import MIB, ROOT, require, saved, sha, write
from bench_apalache_resource_admission import OUTPUT_PATHS, RUNTIME_CONFIG


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__)}


def artifacts(valid):
    # Existing registry payload decoding uses the runner's default compiler
    # bounds and drops source maps/losses. Keep this fixture exactly decodable;
    # this benchmark does not repair or qualify richer artifact round-tripping.
    from ipfs_datasets_py.logic.backends.tla.compiler import TLACompileBounds
    return replace(previous.artifacts(valid), bounds=TLACompileBounds())


def request(valid):
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, QueryKind
    fixture = artifacts(valid)
    suffix = str(valid).lower()
    return BackendRequest(request_id="request:registry:apalache:" + suffix,
        claim_id="claim:registry:apalache:" + suffix, declaration_id="declaration:registry:apalache:" + suffix,
        claim_digest=fixture.model_digest, obligation_id="obligation:registry:apalache:" + suffix,
        obligation_digest=fixture.artifact_digest, assumption_ids=("assumption:bounded-model-check",),
        logic_family="state_transition", query_kind=QueryKind.SATISFIABILITY,
        bounds=previous.bounds("apalache"), payload={"artifacts": fixture.to_dict()}, requested_backend_id="apalache")


def phases(audit, label, provider, valid, selection, expected, *, stopped=None):
    if provider == "tlc":
        return previous.previous.validate_phases(audit, label, {"java": selection["tlc_java"], "wrapper": selection["tlc_wrapper"]},
            previous.previous.baseline.artifacts(valid), expected, stopped=stopped)
    launches, rows = previous.previous.rows_for(audit, label)
    details = [row for row in audit.requests if row["case"] in {label, label + ":constructor"}]
    require(len(launches) == len(rows) == len(details) == len(expected), "unexpected Apalache phases/lifecycles")
    fixture = artifacts(valid)
    for kind, launch, row, detail in zip(expected, launches, rows, details):
        native, request, limits = row["result"], row["request"], detail["limits"]
        if kind == "setup":
            argv = [selection["apalache_java"], *previous.previous.baseline.java_baseline.JAVA_FLAGS]
        elif kind == "model":
            argv = [selection["apalache_launcher"], "check", "--config-file=" + RUNTIME_CONFIG,
                    "--run-dir=apalache-run", "--out-dir=apalache-out", "--smt-solver=z3",
                    "--config=apalache.cfg", "--length=64", "--inv=Safety", "--no-deadlock", "BoundedCounter.tla"]
        else:
            argv = [selection["apalache_launcher"], "version"]
        require(request["argv"] == native["command"] == detail["argv"] == argv and launch["argv"][-len(argv):] == argv,
                "Apalache logical/actual command differs from reviewed argv")
        rss = (256 if kind == "setup" else 512) * MIB
        slots = 1 if kind == "setup" else 3
        require(request["memory_bytes"] == 4 * 1024**3 and request["resident_memory_bytes"] == rss
                and request["max_output_bytes"] == 65536 and 0 < request["timeout_seconds"] <= (10 if kind == "setup" else 3 if kind == "help" else 30),
                "native phase lost finite AS/RSS/output/wall bounds")
        require(0 < limits["cpu_seconds"] <= request["timeout_seconds"] and limits["enforce_file_size_limit"]
                and limits["max_file_bytes"] == (MIB if kind == "setup" else 64 * MIB)
                and limits["max_workspace_bytes"] == (MIB if kind == "setup" else 128 * MIB),
                "native phase lost finite CPU/file/workspace bounds")
        require(request["stdin_is_empty"] and request["java_option_environment_absent"], "native environment/stdin differs")
        lease = next(item for item in launch["owned_leases"] if item["lease_id"] == launch["launch_lease_id"])
        require((lease["cpu_slots"], lease["memory_mb"], lease["child_process_slots"]) == (1, rss // MIB, slots)
                and lease["parent_lease_id"] is None, "native phase lacks its actual admitted root profile")
        require(native["pid"] is not None and native["workspace_cleaned"] and not Path("/proc", str(native["pid"])).exists()
                and not any(native[k] for k in ("error", "unavailable", "resource_exhausted", "output_truncated", "workspace_limit_exceeded")),
                "native phase failed clean resource/workspace containment")
        if kind == "model":
            inputs = {"BoundedCounter.tla": fixture.model_text, "apalache.cfg": fixture.apalache_config_text,
                      RUNTIME_CONFIG: "{}\n"}
            require(detail["input_sha256"] == {name: hashlib.sha256(value.encode()).hexdigest() for name, value in inputs.items()}
                    and detail["input_bytes"] == {name: len(value.encode()) for name, value in inputs.items()}
                    and request["input_file_count"] == 3 and request["output_path_count"] == 3
                    and detail["output_paths"] == list(OUTPUT_PATHS)
                    and limits["max_input_bytes"] == max(4096, sum(len(value.encode()) for value in inputs.values())),
                    "model/source/private-runtime-config receipt differs")
        else:
            require(request["input_file_count"] == request["output_path_count"] == 0
                    and limits["max_input_bytes"] == (1024 if kind == "setup" else 4096), "identity phase has unexpected files")
        if stopped == kind:
            require((native["cancelled"] or native["timed_out"]) and native["process_tree_terminated"],
                    "live stop did not terminate its actual process")
        else:
            require(not native["cancelled"] and not native["timed_out"] and not native["process_tree_terminated"]
                    and native["returncode"] == ((0 if valid else 12) if kind == "model" else 0),
                    "native Apalache phase did not finish with its expected clean exit")
    budgets = [row for row in audit.phase_budgets if row["case"] == label]
    require(len(budgets) == len(expected) and len({row["deadline"] for row in budgets}) <= 1,
            "native phases did not share their aggregate operation deadline")
    require(all(row["request_timeout_seconds"] <= row["remaining_seconds"] + .05 for row in budgets),
            "native request widened remaining operation budget")
    return rows


def verify_projection(req, attempt, result, original, valid):
    from ipfs_datasets_py.logic.ir_core.protocols import AttemptStatus, ResultStatus, SatisfiabilityResult
    require(attempt.status is AttemptStatus.SUCCEEDED and type(result) is SatisfiabilityResult
            and result.status is ResultStatus.UNKNOWN and not result.is_theorem_proof,
            "foreign bounded result was rejected or promoted to generic authority")
    require(attempt.request_digest == result.request_digest == original.request_digest == req.digest
            and result.attempt_digest == attempt.digest and result.output_digest == attempt.output_digest
            and attempt.backend_id == result.backend_id == "apalache"
            and attempt.backend_version == result.backend_version == "matrix-declared/v1"
            and attempt.bounds == result.bounds == original.result.bounds == req.bounds,
            "registry pair lost request/attempt/backend/bounds binding")
    for field in ("claim_digest", "declaration_id", "obligation_id", "obligation_digest", "assumption_ids"):
        require(getattr(result, field) == getattr(req, field), "registry pair lost " + field)
    require(result.authority.kind is req.query_kind.authority_kind
            and result.authority.scope_digest == req.digest and result.authority.issuer == "apalache",
            "registry authority scope differs")
    typed = original.result.to_dict()
    payload = result.payload.to_dict()
    require(payload["adapter_return_type"] == type(original).__name__ == "ModelCheckOutcome"
            and payload["result_status"] == original.result.status.value == ("satisfied" if valid else "violated")
            and payload["result_authority"] == original.result.authority.value == "model_check"
            and payload["result"] == typed,
            "registry payload did not preserve the exact original bounded typed result")
    require(any("without authority upgrade" in message for message in result.diagnostics)
            and len(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) <= req.bounds.max_output_bytes,
            "foreign projection diagnostic or output budget differs")
    require(original.result.is_conclusive and original.receipt.bounded and not original.receipt.unbounded_proof
            and original.result.translation_ceiling.value == "bounded", "original checker authority is not bounded")
    return {"generic_attempt_status": attempt.status.value, "generic_result_status": result.status.value,
            "original_result_status": original.result.status.value, "original_authority": original.result.authority.value,
            "payload_exact_original_result": True, "generic_theorem_authority": False}


def run_case(valid, audit, selection, result):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import proof_operation_scope
    from ipfs_datasets_py.logic.backends.tla import runners

    label = "registry:apalache:" + str(valid).lower()
    req = request(valid)
    fixture = artifacts(valid)
    dispatch = previous.prepare_dispatch(audit, 1, label, result)
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
    projection = verify_projection(req, attempt, projected, original, valid)
    phase_rows = phases(audit, label, "apalache", valid, selection, ("setup", "model", "help"))
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
                and counterexample.source == "checker_counterexample_file" and not counterexample.states
                and any("no parseable State blocks" in note for note in counterexample.replay_notes),
                "native raw witness missing or unsupported structural replay claimed")
        values = re.findall(r"(?ms)^State\d+\s*==\s*(?:/\\\s*)?n\s*=\s*(\d+)\s*(?=\n|$)", raw)
        require(values == ["0", "1", "2"], "raw native counterexample differs from finite input")
        require(projected.payload.to_dict()["result"]["witness"]["counterexample"] == counterexample.to_dict(),
                "generic payload lost the genuine original witness")
        witness = {"path": "apalache-run/violation.tla", "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "raw_state_values": values, "parsed_state_count": 0,
            "scope": "Original raw Apalache file retained; no structural replay attestation"}
    previous.finish_dispatch(audit, dispatch, label)
    return {"case": label, "valid": valid, "phase_count": 3, "elapsed_seconds": time.monotonic() - started,
            "request": req.to_dict(), "request_digest": req.digest, "attempt": attempt.to_dict(),
            "attempt_digest": attempt.digest, "result": projected.to_dict(), "original_outcome": original.to_dict(),
            "projection_checks": projection, "raw_witness": witness, "dispatch": dispatch,
            "default_lazy_factory_used": True, "selected_delegate_count": len(created),
            "original_return_observer_restored": sys.getprofile() is old_profile,
            "factory_restored": registry._factory_constructors is old_factory,
            "aggregate_scope_owner": "benchmark", "operation_timeout_ms": req.bounds.timeout_ms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(previous.previous.runtime_baseline.base.ACCELERATE))
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "registry-foreign-outcome-benchmark@1", "status": "running", "source_pins_before": pins(),
        "runtime": saved.runtime(), "cases": [], "dispatches": [], "checks": {},
        "scope": {"registry_route": "default_backend_registry/LazyMatrixProofBackend",
            "factory_override": "Installed Apalache and Java selection, lazy_install=False only",
            "aggregate_scope_owner": "benchmark", "default_registry_aggregate_budget_claim": False,
            "native_transport_injected": False, "jvm_probe_injected": False, "installation": False,
            "tlc_execution": False, "raw_counterexample_only": True, "new_proof_cache_or_replay": False,
            "throughput_scaling_claim": False, "hard_aggregate_resource_guarantee": False}}
    owner = audit = envelope = None
    old_java = os.environ.get(previous.previous.JAVA_ENV)
    started = time.monotonic()
    try:
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = previous.previous.baseline.java_baseline.previous.install_saved_owner(directory / "saved-scheduler-config.json")
        result["shared_before"] = saved.state_summary(owner.state_path)
        result["shared_pool_compatibility"] = owner._benchmark_pool_compatibility
        selection, files, native = previous.selected_tools(directory)
        result.update(tool_selection=selection, tool_files_before=files, packaged_native_entries=native)
        os.environ[previous.previous.JAVA_ENV] = selection["apalache_java"]
        audit = previous.Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        write(directory / "fixtures.json", {str(valid).lower(): artifacts(valid).to_dict() for valid in (True, False)})
        for valid in (True, False):
            result["cases"].append(run_case(valid, audit, selection, result))
            write(directory / "partial.json", result)
        result["checks"].update(exact_two_serial_cases=len(result["cases"]) == 2,
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
            os.environ.pop(previous.previous.JAVA_ENV, None)
        else:
            os.environ[previous.previous.JAVA_ENV] = old_java
        result["elapsed_seconds"] = time.monotonic() - started
        result["source_pins_after"] = pins()
        result["checks"].update(sources_stable=result["source_pins_before"] == result["source_pins_after"],
            java_selection_environment_restored=os.environ.get(previous.previous.JAVA_ENV) == old_java)
        if "tool_files_before" in result:
            result["tool_files_after"] = {p: previous.previous.baseline.previous.tool_sha(p) for p in result["tool_files_before"]}
            result["checks"]["selected_tool_files_unchanged"] = result["tool_files_before"] == result["tool_files_after"]
        if owner is not None:
            result["shared_after"] = saved.state_summary(owner.state_path)
            result["checks"].update(shared_config_unchanged=previous.previous.baseline.java_baseline.previous._config_bytes(
                result["shared_after"]["config"]) == previous.previous.baseline.java_baseline.previous._config_bytes(envelope["config"]),
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
