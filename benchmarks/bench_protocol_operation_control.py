"""Three real standalone protocol V2 calls under the engine's operation scope.

Only the installed ProVerif executable is selected explicitly. Observers delegate
unchanged calls; no runner, probe, compiler, output, sampler or scope is injected.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import resource
import sys
import time
import traceback

import bench_proverif_query_binding as retained
import bench_native_operation_inheritance as previous
from bench_smt_operation_control import MIB, ROOT, install_saved_owner, require, saved, sha, write

selected_tools, file_sha = retained.selected_tools, retained.file_sha
CASES = retained.CASES
NEW_TEST = ROOT / "tests/unit/logic/backends/test_protocol_operation_control.py"
TEST_ONLY_PIN_FILES = ("logic/backends/protocol/tamarin.py",)


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def request(fixture):
    from ipfs_datasets_py.logic.backends.protocol.execution_v2 import ProtocolExecutionRequestV2
    original = retained.request(fixture)
    return ProtocolExecutionRequestV2(request_id="request:protocol-operation:" + fixture,
        provider="proverif", source=original.payload.to_dict()["source"], source_format="pv", bounds=original.bounds)


def canonical_request(req):
    """Independent expected conversion for evidence checks, never a runner input."""
    from ipfs_datasets_py.logic.backends.protocol.execution_v2 import _digest_of
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, QueryKind
    digest = _digest_of(req.to_dict())
    return BackendRequest(request_id=req.request_id, claim_id="claim:protocol:" + req.request_id,
        declaration_id="declaration:protocol:" + req.request_id, claim_digest=digest,
        obligation_id="obligation:protocol:" + req.request_id, obligation_digest=digest, assumption_ids=(),
        logic_family="cryptographic_protocol", query_kind=QueryKind.THEOREM_PROOF, bounds=req.bounds,
        payload=FrozenMap({"encoding": "pv", "source": req.source}), requested_backend_id="proverif")


class Audit(previous.Audit):
    """Adapt only observation of the V2 engine's explicit ambient stop signal.

    The retained native observer requires no explicitly forwarded signal. V2
    deliberately forwards its operation for plain-runner compatibility, so this
    observer requires that identity instead. Admission and lifecycle observation,
    saved-owner policy and phase validation are reused unchanged.
    """

    def install_observers(self):
        previous.LaunchAudit.install_observers(self)
        from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
        from ipfs_datasets_py.logic.backends.process import SubprocessExecutor
        from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
        run = ResourceAdmittedToolRunner.run

        def observed_run(runner, request, **kwargs):
            operation = current_proof_operation()
            require(operation is not None and kwargs.get("cancellation") is operation,
                    "V2 runner did not receive its current engine operation")
            self.requests.append({"case": self.local.case, "at_monotonic": time.monotonic(),
                "deadline": operation.deadline, "argv": list(request.argv), "limits": asdict(request.limits),
                "input_files": dict(request.input_files), "environment": dict(request.environment),
                "explicit_cancellation_forwarded": True, "forwarded_signal_is_current_operation": True})
            return run(runner, request, **kwargs)

        ResourceAdmittedToolRunner.run = observed_run
        execute = SubprocessExecutor.execute

        def observed_execute(executor, invocation, cancellation=None):
            operation = current_proof_operation()
            require(operation is not None and cancellation is not None, "executor lacks the engine stop signal")
            now = time.monotonic()
            remaining = operation.deadline - now
            require(0 < invocation.limits.timeout_seconds <= remaining + .05
                    and invocation.limits.cpu_seconds is not None
                    and 0 < invocation.limits.cpu_seconds <= remaining + .05,
                    "native limits exceed remaining engine deadline")
            self.invocations.append({"case": self.local.case, "at_monotonic": now,
                "deadline": operation.deadline, "remaining_seconds": remaining,
                "argv": list(invocation.argv), "limits": asdict(invocation.limits),
                "workspace": str(invocation.cwd), "environment": dict(invocation.environment),
                "inherited_signal_present": True})
            return execute(executor, invocation, cancellation)

        SubprocessExecutor.execute = observed_execute
        initialize = SubprocessExecutor.__init__

        def observed_initialize(executor, *args, **kwargs):
            initialize(executor, *args, **kwargs)
            popen = executor._popen

            def observed_popen(*args, **kwargs):
                child = popen(*args, **kwargs)
                operation = current_proof_operation()
                require(operation is not None, "native launch escaped the engine operation")
                self.live.append({"case": self.local.case, "pid": child.pid, "at_monotonic": time.monotonic(),
                    "deadline": operation.deadline, "observed_live": child.poll() is None})
                return child

            executor._popen = observed_popen

        SubprocessExecutor.__init__ = observed_initialize


def run_case(fixture, paths, audit):
    from ipfs_datasets_py.logic.backends.protocol import execution_v2 as v2, proverif, tamarin
    from ipfs_datasets_py.logic.backends.resource_admission import ResourceAdmittedToolRunner
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = "protocol-operation:" + fixture
    dispatch = previous.prepare(audit, label, 128)
    req, expected_request = request(fixture), canonical_request(request(fixture))
    require(current_proof_operation() is None and sys.getprofile() is None, "unexpected ambient operation/profiler")
    backend = proverif.ProVerifBackend(executable=paths["proverif"])
    require(type(backend._runner) is ResourceAdmittedToolRunner and type(backend._compiler) is proverif.ProVerifCompiler
            and backend._version_probe is backend._opam_probe is backend._available_probe is None,
            "ProVerif default runner/compiler/probes differ")
    engine = v2.ProtocolExecutionEngineV2(proverif=backend)
    methods = {function.__code__: name for name, function in (
        ("capability_receipt", v2.ProtocolExecutionEngineV2.capability_receipt),
        ("availability", proverif.ProVerifBackend.is_available),
        ("compile_request", proverif.ProVerifBackend._compile_request),
        ("toolchain", proverif.ProVerifBackend.probe_toolchain),
        ("backend_run", proverif.ProVerifBackend.run),
        ("evidence_packaging", v2.ProtocolExecutionEngineV2._from_backend_outcome))}
    forbidden = {f.__code__ for f in (tamarin.TamarinBackend.run, tamarin.TamarinBackend.is_available,
        tamarin.TamarinBackend.probe_toolchain, v2.ProtocolExecutionEngineV2.probe_all,
        v2.ProtocolExecutionEngineV2.execute_split_providers)}
    observations, outcomes, backend_requests = [], [], []

    def observer(frame, event, value):
        if event not in {"call", "return"}:
            return
        require(frame.f_code not in forbidden, "unselected Tamarin or bulk provider path executed")
        if frame.f_code not in methods:
            return
        operation = current_proof_operation()
        require(operation is not None, "protocol phase escaped the engine operation")
        phase = methods[frame.f_code]
        observations.append({"phase": phase, "event": event, "deadline": operation.deadline,
            "at_monotonic": time.monotonic()})
        if phase == "backend_run":
            if event == "call":
                require(frame.f_locals.get("cancellation") is operation, "backend stop signal differs from engine operation")
                backend_requests.append(frame.f_locals["request"])
            elif isinstance(value, proverif.ProVerifBackendOutcome):
                outcomes.append(value)

    started = time.monotonic()
    sys.setprofile(observer)
    try:
        result = engine.execute(req)
    finally:
        sys.setprofile(None)
    require(current_proof_operation() is None, "engine operation leaked")
    require(len(outcomes) == len(backend_requests) == 1 and backend_requests[0] == expected_request,
            "canonical backend request differs from source-bound V2 request")
    require({r["phase"] for r in observations} == set(methods.values())
            and {r["event"] for r in observations if r["phase"] == "evidence_packaging"} == {"call", "return"},
            "operation observations omit setup or final evidence packaging")
    original = outcomes[0]
    native = previous.phase(audit, label, expected_memory_mb=128)
    raw = native["lifecycle"]["result"]
    require(all(row["deadline"] == native["request"]["deadline"] for row in observations), "engine/native deadline changed")
    require(all(row["at_monotonic"] < row["deadline"] for row in observations), "successful phase escaped its deadline")
    rows = re.findall(r"(?im)^\s*RESULT\s+(.+?)\s+is\s+(true|false)\s*\.?\s*$", raw["stdout"] + "\n" + raw["stderr"])
    expected = {"query:0": ("not attacker(s[])", "true" if fixture == "private_secret" else "false")}
    if fixture == "mixed_secrets":
        expected["query:1"] = ("not attacker(t[])", "true")
    require(len(rows) == len(expected) and set(rows) == set(expected.values()) and type(raw["returncode"]) is int
            and raw["returncode"] == 0, "actual native verdict set or returncode differs")
    wire, typed, receipt = result.to_dict(), original.result.to_dict(), original.receipt.to_dict()
    secure = fixture == "private_secret"
    require(wire["backend_outcome"] == original.to_dict() and wire["backend_result"] == typed
            and wire["evidence"]["receipt"] == receipt, "V2 changed the canonical backend evidence")
    require(wire["disposition"] == ("secure" if secure else "quarantined")
            and typed["status"] == ("secure" if secure else "unknown")
            and wire["protocol_established"] is secure and receipt["accepted"] is secure,
            "V2 protocol disposition or acceptance differs")
    evidence = wire["evidence"]
    require(evidence["result_authority"] == "protocol" and evidence["translation_ceiling"] == ("bounded" if secure else "none")
            and evidence["bindings_complete"] is True and evidence["request_digest"] == expected_request.claim_digest,
            "V2 authority/request binding differs")
    require(not wire["is_proved"] and not wire["is_theorem_authority"]
            and not any(evidence[k] for k in ("claim_proof", "claim_theorem", "claim_satisfiability",
                "claim_other_provider_assumptions", "authorizes_universal_proof")), "protocol evidence gained broader authority")
    require(evidence["document"]["compile_digest"] == original.compile_result.source_digest
            and set(evidence["document"]["claim_ids"]) == set(expected)
            and original.compile_result.source == req.source
            and original.source_binding == proverif.ProVerifSourceBinding.bind(expected_request, req.source, "pv"),
            "source/compile/document/claim binding differs")
    claims = receipt["claim_outcomes"]
    require(len(claims) == len(expected) and {r["claim_id"]: (r["query_text"], r["verdict"]) for r in claims} == expected
            and all(r["attack_trace"] is None for r in claims), "complete unique native claim map or attack authority differs")
    attack = evidence["attack"]
    require(wire["attack_status"] == attack["status"] == ("secure_no_attack" if secure else "none")
            and attack["attack_count"] == 0 and not attack["attack_traces"] and not attack["replay_tokens"]
            and not attack["replayed"] and not attack["authorizes_universal_proof"], "V2 promoted unvalidated attack evidence")
    require(receipt["quarantine"] is None if secure else receipt["quarantine"]["reason"] ==
            ("disagreement" if fixture == "mixed_secrets" else "malformed_output"), "quarantine differs")
    return {"case": label, "fixture": fixture, "request": req.to_dict(), "canonical_request": expected_request.to_dict(),
        "result": wire, "original_outcome": original.to_dict(), "native": native, "raw_result_rows": rows,
        "raw_verdicts": {key: value[1] for key, value in expected.items()}, "dispatch": dispatch,
        "operation_observations": observations, "operation_scope_owner": "production_protocol_v2_engine",
        "source_claims_bound": True, "default_runner_compiler_and_probes": True,
        "explicit_backend_selection": "installed ProVerif executable only", "tamarin_probed_or_run": False,
        "ambient_absent_before_and_after": True, "observer_restored": sys.getprofile() is None,
        "elapsed_seconds": time.monotonic() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "protocol-operation-control-benchmark@1", "status": "running",
        "source_pins_before": pins(), "runtime": saved.runtime(), "cases": [], "checks": {},
        "scope": {"production_protocol_v2_scope": True, "native_v2_execution": True,
            "benchmark_operation_scope_injected": False, "native_runner_or_probe_injected": False,
            "resource_sampler_injected": False, "installation": False, "version_probe": False,
            "registry_execution": False, "native_tamarin_execution": False, "managed_launcher_execution": False,
            "verified_toolchain_metadata": False, "semantic_attack_replay": False,
            "proof_reconstruction": False, "model_validation": False, "theorem_authority_promotion": False,
            "native_cancellation_tested": False, "parallel_scaling_claim": False, "hard_aggregate_containment": False}}
    owner = audit = None
    started = time.monotonic()
    try:
        paths, files, headers = selected_tools()
        result.update(tool_selection=paths, tool_files_before=files, tool_headers=headers)
        saved.capture_config(directory / "saved-scheduler-config.json")
        owner, envelope = install_saved_owner(directory / "saved-scheduler-config.json")
        result.update(shared_before=saved.state_summary(owner.state_path), shared_pool_compatibility=owner._benchmark_pool_compatibility)
        audit = Audit(owner)
        audit.install_observers()
        sys.addaudithook(audit.observe)
        for fixture in CASES:
            result["cases"].append(run_case(fixture, paths, audit))
            write(directory / "partial.json", result)
        result["checks"].update(three_real_proverif_cases=len(result["cases"]) == 3,
            three_real_native_phases=len(audit.events) == len(audit.results) == len(audit.invocations) == 3,
            source_claims_bound=all(c["source_claims_bound"] for c in result["cases"]),
            engine_scope_observed=all(c["operation_scope_owner"] == "production_protocol_v2_engine" for c in result["cases"]),
            no_tamarin_execution=all(not c["tamarin_probed_or_run"] for c in result["cases"]),
            observer_restored=all(c["observer_restored"] for c in result["cases"]),
            engine_cancellation_forwarded=all(r["forwarded_signal_is_current_operation"] for r in audit.requests))
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
