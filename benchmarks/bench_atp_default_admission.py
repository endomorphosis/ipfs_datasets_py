"""Four real installed ATP cases through default registry resource admission.

Tiny CNF satisfiable/unsatisfiable inputs exercise canonical Vampire/E commands.
Raw SZS evidence stays candidate-only; no reconstruction or native V2 is claimed.
No tools are installed and no pressure samples, native outputs or runners are
substituted. Factories only select exact installed executable paths.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import resource
import struct
import sys
import time
import traceback

import bench_native_operation_inheritance as previous
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

ATP_FILES = ("logic/backends/atp/adapters.py", "logic/backends/atp/execution_v2.py",
             "logic/parsers/tptp.py", "logic/parsers/tptp_v2.py")
INSTALL = Path("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers")
TOOLS = {
    "vampire": ("vampire-5.0.1-linux-aarch64/vampire", "765c5aa84bf7333e3ed6e7936a5f44eec832777c00ac0ab5ee3b0aadf65c44de"),
    "eprover": ("eprover-3.2.5/bin/eprover", "a5748ba4a6421b5b0198fa008fb58d1410292d52b302e9d5ab48c5961f3834c1"),
}


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__),
        **{str(ROOT / "ipfs_datasets_py" / p): sha(ROOT / "ipfs_datasets_py" / p) for p in ATP_FILES}}


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(MIB):
            value.update(block)
    return value.hexdigest()


def selected_tools():
    require(os.uname().machine == "aarch64", "selected installed ATP targets require aarch64")
    paths, files, headers = {}, {}, {}
    for provider, (relative, expected) in TOOLS.items():
        path = INSTALL / relative
        require(path.is_file() and os.access(path, os.X_OK) and file_sha(path) == expected,
                "selected installed ATP binary missing or changed: " + provider)
        with path.open("rb") as stream:
            header = stream.read(64)
        require(header[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", header, 18)[0] == 183,
                "selected target is not reviewed ELF64 little-endian AArch64")
        paths[provider] = str(path)
        files[str(path)] = expected
        headers[provider] = {"elf_class": 64, "byte_order": "little", "machine": 183,
            "selected_binary_sha256": expected, "version_probed": False}
    return paths, files, headers


def request(provider, satisfiable):
    from ipfs_datasets_py.logic.ir_core.protocols import QueryKind
    source = "cnf(pos,axiom,p(a))." + ("" if satisfiable else "\ncnf(neg,axiom,~p(a)).")
    base = previous.old_request("fol", source, memory_mb=128, timeout_ms=5000)
    return replace(base, request_id="request:atp-admission:" + provider + ":" + str(satisfiable).lower(),
        query_kind=QueryKind.SATISFIABILITY, requested_backend_id=provider,
        payload={"encoding": "tptp-cnf", "source": source})


def run_case(provider, satisfiable, paths, audit):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.atp import adapters
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = "atp:" + provider + ":" + ("satisfiable" if satisfiable else "unsatisfiable")
    dispatch = previous.prepare(audit, label, 128)
    req = request(provider, satisfiable)
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
    require(raw_szs == ("Satisfiable" if satisfiable else "Unsatisfiable"), "actual ATP SZS disagrees with finite CNF fixture")
    # E reports a satisfiable clause set with exit 1. The existing adapter treats
    # all nonzero exits as operational errors before parsing SZS. Retain that gap.
    expected_error = provider == "eprover" and satisfiable
    require(raw["returncode"] == (1 if expected_error else 0), "actual ATP exit differs from selected fixture contract")
    typed = original.result.to_dict()
    require(typed["status"] == ("error" if expected_error else "candidate")
            and attempt.status.value == ("failed" if expected_error else "succeeded")
            and projected.status.value == ("error" if expected_error else "unknown"), "ATP terminal/candidate projection differs")
    require(projected.payload.to_dict()["result"] == typed
            and projected.payload.to_dict()["result_status"] == typed["status"], "original typed ATP payload lost")
    require(original.request_digest == req.digest == attempt.request_digest == projected.request_digest
            and projected.attempt_digest == attempt.digest, "ATP request/attempt binding differs")
    require(original.source_binding.source_digest == adapters.ATPSourceBinding.bind(req, req.payload.to_dict()["source"], "tptp-cnf").source_digest,
            "ATP source binding differs")
    if expected_error:
        require(original.proof_object is None and original.countermodel is None and "szs_status" not in typed["metadata"],
                "legacy E nonzero-exit behavior unexpectedly changed")
    else:
        require(typed["authority"] == "candidate" and typed["translation_ceiling"] == "advisory"
                and typed["metadata"]["szs_status"] == raw_szs, "unverified ATP evidence gained authority")
        require(typed["witness"]["candidate_kind"] == ("unvalidated_atp_model" if satisfiable else "unreconstructed_atp_proof"),
                "ATP candidate kind differs")
        if not satisfiable:
            require(original.proof_object is not None and not original.proof_object.verified
                    and original.proof_object.content == combined, "original unverified ATP proof output lost")
    require(factory_scopes[0]["deadline"] == native["request"]["deadline"], "ATP factory/native deadline differs")
    return {"case": label, "provider": provider, "satisfiable": satisfiable,
        "request": req.to_dict(), "request_digest": req.digest, "attempt": attempt.to_dict(), "attempt_digest": attempt.digest,
        "result": projected.to_dict(), "original_outcome": original.to_dict(), "native": native,
        "raw_szs_status": raw_szs, "existing_e_satisfiable_exit_limitation": expected_error,
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
    result = {"schema": "atp-default-admission-benchmark@1", "status": "running",
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
        for provider in ("vampire", "eprover"):
            for satisfiable in (False, True):
                result["cases"].append(run_case(provider, satisfiable, paths, audit))
                write(directory / "partial.json", result)
        result["checks"].update(four_real_atp_cases=len(result["cases"]) == 4,
            four_real_native_phases=len(audit.events) == len(audit.results) == len(audit.invocations) == 4,
            no_generic_authority_promotion=all(c["result"]["status"] in {"unknown", "error"} for c in result["cases"]),
            candidate_authority_preserved=all(c["existing_e_satisfiable_exit_limitation"] or c["original_outcome"]["result"]["authority"] == "candidate" for c in result["cases"]),
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
