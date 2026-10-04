"""Six real, serial ATP cases qualifying E's satisfiable exit convention.

Reuse the retained installed-ELF selection and real admission observers. Every
case uses the default registry scope and native runner; no solver output,
resource sample, operation scope, model validator or proof checker is injected.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import resource
import sys
import time
import traceback

import bench_atp_default_admission as retained
import bench_native_operation_inheritance as previous
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

selected_tools = retained.selected_tools
file_sha = retained.file_sha
NEW_TEST = ROOT / "tests/unit/logic/backends/test_eprover_exit_status.py"
CASES = (("vampire", "unsatisfiable"), ("vampire", "satisfiable"),
         ("eprover", "unsatisfiable"), ("eprover", "satisfiable"),
         ("vampire", "counter_satisfiable"), ("eprover", "counter_satisfiable"))
EXPECTED_SZS = {"unsatisfiable": "Unsatisfiable", "satisfiable": "Satisfiable",
                "counter_satisfiable": "CounterSatisfiable"}


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def request(provider, fixture):
    from ipfs_datasets_py.logic.ir_core.protocols import QueryKind
    if fixture == "counter_satisfiable":
        source, encoding, kind = "fof(goal,conjecture,p(a)).", "tptp-fof", QueryKind.THEOREM_PROOF
    else:
        require(fixture in {"unsatisfiable", "satisfiable"}, "unknown ATP fixture")
        source = "cnf(pos,axiom,p(a))." + ("\ncnf(neg,axiom,~p(a))." if fixture == "unsatisfiable" else "")
        encoding, kind = "tptp-cnf", QueryKind.SATISFIABILITY
    base = previous.old_request("fol", source, memory_mb=128, timeout_ms=5000)
    return replace(base, request_id="request:e-exit:" + provider + ":" + fixture,
        query_kind=kind, requested_backend_id=provider,
        payload={"encoding": encoding, "source": source})


def run_case(provider, fixture, paths, audit):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.atp import adapters
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = "e-exit:" + provider + ":" + fixture
    dispatch = previous.prepare(audit, label, 128)
    req = request(provider, fixture)
    require(current_proof_operation() is None, "unexpected ambient ATP scope")
    old_factories, old_profile = registry._factory_constructors, sys.getprofile()
    require(old_profile is None, "benchmark requires no existing profiler")
    factories = old_factories()
    created, outcomes, factory_scopes = [], [], []
    cls = adapters.VampireBackend if provider == "vampire" else adapters.EProverBackend
    def factory():
        operation = current_proof_operation()
        require(operation is not None, "ATP factory escaped production registry scope")
        backend = cls(executable=paths[provider])
        require(type(backend._runner) is ResourceAdmittedToolRunner and backend._proof_reconstructor is None
                and backend._countermodel_parser is None, "ATP default runner/reconstruction policy differs")
        created.append(backend)
        factory_scopes.append({"deadline": operation.deadline, "at_monotonic": time.monotonic()})
        return backend
    def observer(frame, event, value):
        if event == "return" and frame.f_code is adapters.TPTPBackend.run.__code__ and isinstance(value, adapters.ATPAdapterOutcome):
            outcomes.append(value)
    started = time.monotonic()
    registry._factory_constructors = lambda: {**factories, provider: factory}
    try:
        owner = registry.default_backend_registry()
        require(not any(owner[name]._delegate_loaded for name in owner) and not created, "ATP discovery initialized a delegate")
        sys.setprofile(observer)
        try:
            attempt, projected = owner.run(req)
        finally:
            sys.setprofile(old_profile)
        require(len(created) == len(outcomes) == len(factory_scopes) == 1
                and sum(owner[name]._delegate_loaded for name in owner) == 1, "ATP lazy route differs")
    finally:
        registry._factory_constructors = old_factories
        sys.setprofile(old_profile)
    require(current_proof_operation() is None, "ATP registry scope leaked")
    original = outcomes[0]
    native = previous.phase(audit, label, expected_memory_mb=128)
    raw = native["lifecycle"]["result"]
    combined = "\n".join(part for part in (raw["stdout"], raw["stderr"]) if part)
    raw_szs = adapters.parse_szs_status(combined).value
    require(raw_szs == EXPECTED_SZS[fixture], "actual ATP SZS disagrees with finite fixture")
    expected_exit = 1 if provider == "eprover" and fixture != "unsatisfiable" else 0
    require(type(raw["returncode"]) is int and raw["returncode"] == expected_exit, "actual ATP exit differs")
    typed = original.result.to_dict()
    require(typed["status"] == "candidate" and attempt.status.value == "succeeded"
            and projected.status.value == "unknown", "ATP terminal/candidate projection differs")
    require(projected.payload.to_dict()["result"] == typed
            and projected.payload.to_dict()["result_status"] == "candidate", "original typed ATP payload lost")
    require(original.request_digest == req.digest == attempt.request_digest == projected.request_digest
            and projected.attempt_digest == attempt.digest, "ATP request/attempt binding differs")
    payload = req.payload.to_dict()
    require(original.source_binding.source_digest == adapters.ATPSourceBinding.bind(req, payload["source"], payload["encoding"]).source_digest,
            "ATP source binding differs")
    require(typed["authority"] == "candidate" and typed["translation_ceiling"] == "advisory"
            and typed["metadata"]["szs_status"] == raw_szs
            and typed["metadata"]["process"]["returncode"] == raw["returncode"], "unverified ATP evidence gained authority or lost native exit")
    require(typed["witness"]["candidate_kind"] == ("unreconstructed_atp_proof" if fixture == "unsatisfiable" else "unvalidated_atp_model"),
            "ATP candidate kind differs")
    require(original.countermodel is None, "unexpected validated/native countermodel")
    if fixture == "unsatisfiable":
        require(original.proof_object is not None and not original.proof_object.verified
                and not original.proof_object.checker_id and original.proof_object.content == combined,
                "original unverified ATP proof output lost")
    else:
        require(original.proof_object is None, "model candidate acquired proof authority")
    require(factory_scopes[0]["deadline"] == native["request"]["deadline"], "ATP factory/native deadline differs")
    return {"case": label, "provider": provider, "fixture": fixture,
        "request": req.to_dict(), "request_digest": req.digest, "attempt": attempt.to_dict(), "attempt_digest": attempt.digest,
        "result": projected.to_dict(), "original_outcome": original.to_dict(), "native": native,
        "raw_szs_status": raw_szs, "expected_returncode": expected_exit,
        "dispatch": dispatch, "factory_scopes": factory_scopes, "elapsed_seconds": time.monotonic() - started,
        "default_runner_and_probes": True, "factory_override": "installed executable only",
        "ambient_absent_before_and_after": True, "operation_scope_owner": "production_registry",
        "observer_and_factory_restored": registry._factory_constructors is old_factories and sys.getprofile() is old_profile}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "eprover-satisfiable-exit-benchmark@1", "status": "running",
        "source_pins_before": pins(), "runtime": saved.runtime(), "cases": [], "checks": {},
        "scope": {"production_registry_scope": True, "benchmark_operation_scope_injected": False,
            "native_runner_or_probe_injected": False, "resource_sampler_injected": False,
            "installation": False, "version_probe": False, "native_v2_execution": False,
            "proof_reconstruction": False, "model_validation": False, "authority_promotion": False,
            "native_cancellation_tested": False, "parallel_scaling_claim": False, "hard_aggregate_containment": False}}
    owner = audit = None
    started = time.monotonic()
    try:
        paths, files, headers = selected_tools()
        result.update(tool_selection=paths, tool_files_before=files, tool_headers=headers)
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = install_saved_owner(directory / "saved-scheduler-config.json")
        result.update(shared_before=saved.state_summary(owner.state_path), shared_pool_compatibility=owner._benchmark_pool_compatibility)
        audit = previous.Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        for provider, fixture in CASES:
            result["cases"].append(run_case(provider, fixture, paths, audit))
            write(directory / "partial.json", result)
        result["checks"].update(six_real_atp_cases=len(result["cases"]) == 6,
            six_real_native_phases=len(audit.events) == len(audit.results) == len(audit.invocations) == 6,
            no_generic_authority_promotion=all(c["result"]["status"] == "unknown" for c in result["cases"]),
            candidate_authority_preserved=all(c["original_outcome"]["result"]["authority"] == "candidate" for c in result["cases"]),
            e_satisfiable_exits_retained=all(c["native"]["lifecycle"]["result"]["returncode"] == c["expected_returncode"] for c in result["cases"]),
            observer_and_factory_restored=all(c["observer_and_factory_restored"] for c in result["cases"]),
            no_explicit_native_cancellation=all(not r["explicit_cancellation_forwarded"] for r in audit.requests))
        result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if audit is not None:
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
            result["tool_files_after"] = {p: file_sha(p) for p in result["tool_files_before"]}
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
