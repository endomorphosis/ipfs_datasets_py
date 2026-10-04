"""Three real ProVerif cases qualifying source-bound secrecy query results.

Native true results may establish bounded symbolic protocol evidence. Native
false results remain unvalidated diagnostics, and generic conclusions remain
UNKNOWN. No runner, compiler, probes, output or operation scope is injected.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import resource
import sys
import time
import traceback

import bench_proverif_default_admission as retained
import bench_native_operation_inheritance as previous
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

selected_tools, file_sha = retained.selected_tools, retained.file_sha
TEST_ONLY_PIN_FILES = retained.TEST_ONLY_PIN_FILES
NEW_TEST = ROOT / "tests/unit/logic/backends/test_proverif_query_binding.py"
CASES = ("private_secret", "disclosed_secret", "mixed_secrets")


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def request(fixture):
    require(fixture in CASES, "unknown ProVerif fixture")
    source = "free c: channel.\nfree s: bitstring [private].\n"
    if fixture == "mixed_secrets":
        source += "free t: bitstring [private].\n"
    source += "query attacker(s).\n"
    if fixture == "mixed_secrets":
        source += "query attacker(t).\n"
    source += "process " + ("0" if fixture == "private_secret" else "out(c,s)")
    base = previous.old_request("protocol", source, memory_mb=128, timeout_ms=5000)
    return replace(base, request_id="request:proverif-query-binding:" + fixture,
        requested_backend_id="proverif", payload={"encoding": "pv", "source": source})


def run_case(fixture, paths, audit):
    from ipfs_datasets_py.logic.backends import registry
    from ipfs_datasets_py.logic.backends.protocol import proverif
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = "proverif-binding:" + fixture
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
    expected = {"query:0": ("not attacker(s[])", "true" if fixture == "private_secret" else "false")}
    compiled_queries = {"query:0": "attacker(s)"}
    if fixture == "mixed_secrets":
        expected["query:1"] = ("not attacker(t[])", "true")
        compiled_queries["query:1"] = "attacker(t)"
    require(len(rows) == len(expected) and set(rows) == set(expected.values()),
            "actual native verdicts differ from complete fixture claim set")
    require(type(raw["returncode"]) is int and raw["returncode"] == 0, "native ProVerif failed")
    typed, receipt = original.result.to_dict(), original.receipt.to_dict()
    secure = fixture == "private_secret"
    require(typed["status"] == ("secure" if secure else "unknown") and typed["authority"] == "protocol"
            and typed["translation_ceiling"] == ("bounded" if secure else "none")
            and attempt.status.value == "succeeded" and projected.status.value == "unknown",
            "bounded protocol/generic authority differs")
    require(projected.payload.to_dict()["result"] == typed and projected.payload.to_dict()["result_status"] == typed["status"],
            "original typed ProVerif payload lost")
    source = req.payload.to_dict()["source"]
    require(original.request_digest == req.digest == attempt.request_digest == projected.request_digest
            and projected.attempt_digest == attempt.digest, "request/attempt binding differs")
    require(original.source_binding == proverif.ProVerifSourceBinding.bind(req, source, "pv")
            and original.compile_result.source == source
            and original.compile_result.claim_queries.to_dict() == compiled_queries, "source/compiled claim binding changed")
    parsed = receipt["claim_outcomes"]
    require(len(parsed) == len(expected) and len({r["claim_id"] for r in parsed}) == len(parsed)
            and {r["claim_id"]: (r["query_text"], r["verdict"]) for r in parsed} == expected,
            "native results are not bound uniquely to the complete requested claim set")
    require(all(r["attack_trace"] is None for r in parsed)
            and all("unvalidated" in r["reason"].lower() for r in parsed if r["verdict"] == "false")
            and "attack_traces" not in typed["witness"] and "attack_trace_replay" not in typed["witness"],
            "native false verdict gained unvalidated attack replay authority")
    require(receipt["accepted"] is secure, "protocol receipt acceptance differs")
    if secure:
        require(receipt["quarantine"] is None, "fully bound true claim remained quarantined")
    else:
        require(receipt["quarantine"]["reason"] == ("disagreement" if fixture == "mixed_secrets" else "malformed_output"),
                "unvalidated false/mixed outcomes escaped quarantine")
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
        "raw_verdicts": {key: value[1] for key, value in expected.items()}, "source_claims_bound": True, "dispatch": dispatch,
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
    result = {"schema": "proverif-query-binding-benchmark@1", "status": "running",
        "source_pins_before": pins(), "runtime": saved.runtime(), "cases": [], "checks": {},
        "scope": {"production_registry_scope": True, "benchmark_operation_scope_injected": False,
            "native_runner_or_probe_injected": False, "resource_sampler_injected": False,
            "installation": False, "version_probe": False, "native_v2_execution": False, "managed_launcher_execution": False,
            "verified_toolchain_metadata": False, "semantic_attack_replay": False,
            "proof_reconstruction": False, "model_validation": False, "generic_authority_promotion": False, "bounded_protocol_true_result": True,
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
        result["checks"].update(three_real_proverif_cases=len(result["cases"]) == 3,
            three_real_native_phases=len(audit.events) == len(audit.results) == len(audit.invocations) == 3,
            no_generic_authority_promotion=all(c["result"]["status"] == "unknown" for c in result["cases"]),
            source_claims_bound=all(c["source_claims_bound"] for c in result["cases"]),
            false_claims_without_attack_authority=all(r["attack_trace"] is None for c in result["cases"] for r in c["original_outcome"]["receipt"]["claim_outcomes"]),
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
