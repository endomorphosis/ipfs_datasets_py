"""Two real ProVerif cases through default registry resource admission.

Private and disclosed secrets produce real true/false outputs. Existing query
spelling mismatches remain explicit quarantined UNKNOWN outcomes. No runner,
compiler, version/availability probe, solver output or operation scope is injected.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import resource
import struct
import sys
import time
import traceback

import bench_eprover_satisfiable_exit as retained
import bench_native_operation_inheritance as previous
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

file_sha = retained.file_sha
TOOL = Path("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/proverif-2.05/proverif2.05/proverif")
TOOL_SHA256 = "05392dcfe51b0f193cc86505f74e678df71018e924fda8bcd6398e7b9476403c"
NEW_TEST = ROOT / "tests/unit/logic/backends/test_proverif_resource_admission.py"
PROTOCOL_FILES = ("logic/backends/protocol/proverif.py", "logic/software_verification/protocol.py",
    "logic/ir_core/canonical.py", "logic/backends/protocol/tamarin.py",
    "logic/backends/protocol/execution_v2.py", "logic/backends/toolchain_roles.py", "logic/families/namespaces.py")
TEST_ONLY_PIN_FILES = PROTOCOL_FILES[3:]
CASES = ("private_secret", "disclosed_secret")


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST),
        **{str(ROOT / "ipfs_datasets_py" / p): sha(ROOT / "ipfs_datasets_py" / p) for p in PROTOCOL_FILES}}


def selected_tools():
    require(os.uname().machine == "aarch64", "selected ProVerif ELF requires AArch64")
    require(TOOL.is_file() and os.access(TOOL, os.X_OK) and file_sha(TOOL) == TOOL_SHA256,
            "reviewed installed ProVerif ELF missing or changed")
    with TOOL.open("rb") as stream:
        header = stream.read(64)
    require(header[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", header, 18)[0] == 183,
            "selected ProVerif is not the reviewed ELF64 little-endian AArch64 target")
    return ({"proverif": str(TOOL)}, {str(TOOL): TOOL_SHA256}, {"proverif": {
        "elf_class": 64, "byte_order": "little", "machine": 183,
        "selected_binary_sha256": TOOL_SHA256, "version_probed": False,
        "selection": "underlying installed ELF; managed launcher not executed"}})


def request(fixture):
    require(fixture in CASES, "unknown ProVerif fixture")
    source = "free c: channel.\nfree s: bitstring [private].\nquery attacker(s).\nprocess "
    source += "out(c,s)" if fixture == "disclosed_secret" else "0"
    base = previous.old_request("protocol", source, memory_mb=128, timeout_ms=5000)
    return replace(base, request_id="request:proverif-admission:" + fixture,
        requested_backend_id="proverif", payload={"encoding": "pv", "source": source})


def run_case(fixture, paths, audit):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.protocol import proverif
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = "proverif:" + fixture
    dispatch = previous.prepare(audit, label, 128)
    req = request(fixture)
    require(current_proof_operation() is None, "unexpected ambient ProVerif scope")
    old_factories, old_profile = registry._factory_constructors, sys.getprofile()
    require(old_profile is None, "benchmark requires no existing profiler")
    factories = old_factories()
    created, outcomes, factory_scopes = [], [], []
    def factory():
        operation = current_proof_operation()
        require(operation is not None, "ProVerif factory escaped registry operation")
        backend = proverif.ProVerifBackend(executable=paths["proverif"])
        require(type(backend._runner) is ResourceAdmittedToolRunner
                and type(backend._compiler) is proverif.ProVerifCompiler
                and backend._version_probe is backend._opam_probe is backend._available_probe is None,
                "ProVerif default runner/compiler/probes differ")
        created.append(backend)
        factory_scopes.append({"deadline": operation.deadline, "at_monotonic": time.monotonic()})
        return backend
    def observer(frame, event, value):
        if event == "return" and frame.f_code is proverif.ProVerifBackend.run.__code__ and isinstance(value, proverif.ProVerifBackendOutcome):
            outcomes.append(value)
    started = time.monotonic()
    registry._factory_constructors = lambda: {**factories, "proverif": factory}
    try:
        owner = registry.default_backend_registry()
        require(not any(owner[name]._delegate_loaded for name in owner) and not created, "discovery initialized a delegate")
        sys.setprofile(observer)
        try:
            attempt, projected = owner.run(req)
        finally:
            sys.setprofile(old_profile)
        require(len(created) == len(outcomes) == len(factory_scopes) == 1
                and sum(owner[name]._delegate_loaded for name in owner) == 1, "ProVerif lazy route differs")
    finally:
        registry._factory_constructors = old_factories
        sys.setprofile(old_profile)
    require(current_proof_operation() is None, "ProVerif registry scope leaked")
    original = outcomes[0]
    native = previous.phase(audit, label, expected_memory_mb=128)
    raw = native["lifecycle"]["result"]
    combined = raw["stdout"] + "\n" + raw["stderr"]
    rows = re.findall(r"(?im)^\s*RESULT\s+(.+?)\s+is\s+(true|false)\s*\.?\s*$", combined)
    verdict = "false" if fixture == "disclosed_secret" else "true"
    require(rows and all(v == verdict and re.fullmatch(r"not attacker\(s(?:\[\])?\)", q) for q, v in rows),
            "actual native ProVerif query verdict differs from finite fixture")
    require(raw["returncode"] == 0, "native ProVerif failed")
    typed, receipt = original.result.to_dict(), original.receipt.to_dict()
    require(typed["status"] == "unknown" and typed["authority"] == "protocol"
            and typed["translation_ceiling"] == "none" and attempt.status.value == "succeeded"
            and projected.status.value == "unknown", "quarantined ProVerif authority changed")
    require(projected.payload.to_dict()["result"] == typed and projected.payload.to_dict()["result_status"] == "unknown",
            "original typed ProVerif payload lost")
    source = req.payload.to_dict()["source"]
    require(original.request_digest == req.digest == attempt.request_digest == projected.request_digest
            and projected.attempt_digest == attempt.digest, "request/attempt binding differs")
    require(original.source_binding == proverif.ProVerifSourceBinding.bind(req, source, "pv")
            and original.compile_result.source == source
            and original.compile_result.claim_queries.to_dict() == {"query:0": "attacker(s)"}, "source/compiled claim binding changed")
    parsed = receipt["claim_outcomes"]
    require([(r["query_text"], r["verdict"]) for r in parsed[:-1]] == rows
            and all(r["claim_id"] == r["query_text"] and r["claim_id"] != "query:0" for r in parsed[:-1])
            and parsed[-1]["claim_id"] == "query:0" and parsed[-1]["query_text"] == "attacker(s)"
            and parsed[-1]["verdict"] == "unknown", "native query spelling mismatch was hidden")
    require(receipt["accepted"] is False and receipt["quarantine"]["reason"] == "inconclusive"
            and receipt["quarantine"]["claim_ids"] == ["query:0"], "existing query-binding gap not quarantined")
    ceiling = receipt["ceiling"]
    require(ceiling["adversary_model"] == "dolev_yao" and ceiling["computational_soundness"] is False
            and ceiling["bitstring_level"] is False and ceiling["perfect_cryptography"] is True,
            "symbolic protocol ceiling changed")
    require(receipt["toolchain"]["tool_version"] == "proverif"
            and receipt["toolchain"]["dependencies"][0]["version"] == "unspecified", "default unverified toolchain metadata changed")
    require(typed["metadata"]["process"]["returncode"] == raw["returncode"]
            and typed["metadata"]["protocol_receipt"] == receipt, "native/receipt metadata lost")
    require(factory_scopes[0]["deadline"] == native["request"]["deadline"], "factory/native deadline differs")
    return {"case": label, "fixture": fixture, "request": req.to_dict(), "request_digest": req.digest,
        "attempt": attempt.to_dict(), "attempt_digest": attempt.digest, "result": projected.to_dict(),
        "original_outcome": original.to_dict(), "native": native, "raw_result_rows": rows,
        "raw_verdict": verdict, "query_normalization_gap": True, "dispatch": dispatch,
        "factory_scopes": factory_scopes, "elapsed_seconds": time.monotonic() - started,
        "default_runner_compiler_and_probes": True, "factory_override": "installed executable only",
        "ambient_absent_before_and_after": True, "operation_scope_owner": "production_registry",
        "observer_and_factory_restored": registry._factory_constructors is old_factories and sys.getprofile() is old_profile}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "proverif-default-admission-benchmark@1", "status": "running",
        "source_pins_before": pins(), "runtime": saved.runtime(), "cases": [], "checks": {},
        "scope": {"production_registry_scope": True, "benchmark_operation_scope_injected": False,
            "native_runner_or_probe_injected": False, "resource_sampler_injected": False,
            "installation": False, "version_probe": False, "native_v2_execution": False, "managed_launcher_execution": False,
            "verified_toolchain_metadata": False, "semantic_attack_replay": False,
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
        for fixture in CASES:
            result["cases"].append(run_case(fixture, paths, audit))
            write(directory / "partial.json", result)
        result["checks"].update(two_real_proverif_cases=len(result["cases"]) == 2,
            two_real_native_phases=len(audit.events) == len(audit.results) == len(audit.invocations) == 2,
            no_generic_authority_promotion=all(c["result"]["status"] == "unknown" for c in result["cases"]),
            query_normalization_gap_preserved=all(c["query_normalization_gap"] for c in result["cases"]),
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
