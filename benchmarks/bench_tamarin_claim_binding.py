"""Controlled Tamarin claim-binding E2E and bounded parser microbenchmarks.

All solver output, executable availability and host pressure are synthetic.
Default backend factories, admitted runners, compilers, parsers, classification,
workspace cleanup and result projections run unchanged against a private pool.
Native process creation and shared scheduler resolution are denied. Results do
not establish native proofs, native throughput, pressure backoff or speedup.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

import bench_tamarin_default_admission as retained
from bench_generic_prover_admission import request as old_request
from bench_smt_operation_control import MIB, ROOT, require, sha, write

NEW_TEST = ROOT / "tests/unit/logic/backends/test_tamarin_claim_binding.py"
ROUTES = ("direct", "registry", "standalone_v2")
FIXTURES = ("complete", "unknown", "conflicting", "missing", "falsified")
PARSER_FIXTURES = FIXTURES[:4]
SIZES = (10, 100, 1000)
REPEATS = 3
OUTPUT_BYTES = 256 * 1024


def pins():
    return {**retained.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def digest(value):
    data = value.encode("utf-8") if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def fixture(kind, count=2):
    require(kind in FIXTURES and count in (2, *SIZES), "fixture outside the bounded matrix")
    names = ["c" + str(i) for i in range(count)]
    source = "theory ControlledBinding\nbegin\n" + "".join('lemma ' + name + ': "T"\n' for name in names) + "end\n"
    rows = [name + " (all-traces): verified (1 steps)" for name in names]
    prefix = ""
    if kind == "unknown":
        rows.append("undeclared (all-traces): verified (1 steps)")
    elif kind == "conflicting":
        rows.append("c0 (all-traces): falsified - found trace (1 steps)")
    elif kind == "missing":
        rows.pop()
    elif kind == "falsified":
        rows = [name + " (all-traces): falsified - found trace (1 steps)" for name in names]
        prefix = "rule SyntheticReveal(secret)\nevent SyntheticAttack(secret)\n"
    stdout = prefix + "summary of summaries:\n" + "\n".join(rows) + "\n"
    require(len(source.encode()) < OUTPUT_BYTES and len(stdout.encode()) < OUTPUT_BYTES,
            "fixture exceeds its finite source/output envelope")
    return {"fixture": kind, "claim_count": count, "source": source, "stdout": stdout,
        "stderr": "", "claim_lemmas": {name: name for name in names},
        "source_sha256": digest(source), "stdout_sha256": digest(stdout)}


def request(route, kind):
    data = fixture(kind)
    original = old_request("cryptographic_protocol", data["source"], memory_mb=512, timeout_ms=5000)
    bounds = replace(original.bounds, max_output_bytes=OUTPUT_BYTES)
    request_id = "request:tamarin-controlled:" + route + ":" + kind
    if route == "standalone_v2":
        from ipfs_datasets_py.logic.backends.protocol.execution_v2 import ProtocolExecutionRequestV2
        return ProtocolExecutionRequestV2(request_id=request_id, provider="tamarin", source=data["source"],
            source_format="spthy", bounds=bounds)
    return replace(original, request_id=request_id, requested_backend_id="tamarin", bounds=bounds,
        payload={"encoding": "spthy", "source": data["source"]})


def canonical_request(route, kind):
    req = request(route, kind)
    if route != "standalone_v2":
        return req
    from ipfs_datasets_py.logic.backends.protocol.execution_v2 import _digest_of
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, QueryKind
    value = _digest_of(req.to_dict())
    return BackendRequest(request_id=req.request_id, claim_id="claim:protocol:" + req.request_id,
        declaration_id="declaration:protocol:" + req.request_id, claim_digest=value,
        obligation_id="obligation:protocol:" + req.request_id, obligation_digest=value, assumption_ids=(),
        logic_family="cryptographic_protocol", query_kind=QueryKind.THEOREM_PROOF,
        bounds=req.bounds, payload={"encoding": "spthy", "source": req.source}, requested_backend_id="tamarin")


def check_claims(rows, data, status, accepted):
    expected = data["claim_lemmas"]
    bound = [r for r in rows if r["claim_id"] in expected]
    unbound = [r for r in rows if r["claim_id"] not in expected]
    require({r["claim_id"]: r["lemma_name"] for r in bound} == expected,
            "declared claim results do not cover the complete source population")
    extra = data["fixture"] in {"unknown", "conflicting"}
    require(len(rows) == data["claim_count"] + int(extra), "diagnostic/conflicting result multiplicity differs")
    if data["fixture"] == "unknown":
        require(len(unbound) == 1 and unbound[0]["verdict"] == "unknown"
                and unbound[0]["lemma_name"] == "undeclared", "unknown result acquired a declared claim identity")
    else:
        require(not unbound, "known summary gained an unexpected unbound result")
    if data["fixture"] == "conflicting":
        require({r["verdict"] for r in bound if r["claim_id"] == "c0"} == {"verified", "falsified"},
                "conflicting summary rows were silently overwritten")
    else:
        require(len({r["claim_id"] for r in rows}) == len(rows), "nonconflicting claim identities repeated")
    if data["fixture"] == "missing":
        require(next(r for r in bound if r["claim_id"] == "c" + str(data["claim_count"] - 1))["verdict"] == "unknown",
                "missing declaration did not retain its unknown result")
    require(all(r["attack_trace"] is None for r in rows), "synthetic text gained attack reconstruction authority")
    secure = data["fixture"] == "complete"
    require(status == ("secure" if secure else "unknown") and accepted is secure,
            "complete binding/invalid binding classification differs")
    if secure:
        require(all(r["verdict"] == "verified" for r in rows), "complete declared claims not verified")


class ControlledEnvironment:
    """Private fixture scheduler and synthetic executor; no shared/native work."""

    def __init__(self, directory):
        self.directory, self.stack = directory, ExitStack()
        self.invocations, self.lifecycle, self.resolutions, self.acquisitions = [], [], [], []
        self.native_attempts, self.shared_attempts = [], []
        self.case, self.data = "", None

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        def deny_native(*args, **kwargs):
            self.native_attempts.append(self.case)
            raise AssertionError("controlled benchmark forbids native processes")
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(self.case)
            raise AssertionError("controlled benchmark forbids shared scheduler resolution")
        self.stack.enter_context(patch.object(subprocess, "Popen", deny_native))
        self.stack.enter_context(patch.object(os, "system", deny_native))
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny_shared))
        self.healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        def healthy_fixture():
            return self.healthy
        config = scheduler.ResourceSchedulerConfig.for_proof_host(
            state_path=self.directory / "private-fixture-pool.json", proof_resource_sampler=healthy_fixture,
            total_cpu_slots=2, total_memory_mb=512, total_child_process_slots=8,
            proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
            proof_backoff_seconds=.01, poll_interval_seconds=.002)
        self.owner = scheduler.GlobalResourceScheduler(config)
        self.before = self.owner.snapshot()
        def private_owner():
            self.resolutions.append(self.case)
            return self.owner
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", private_owner))
        self.stack.enter_context(patch.object(process.shutil, "which", lambda executable, **kwargs:
            sys.executable if executable == "tamarin-prover" else None))
        acquire = self.owner.acquire
        def observed_acquire(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            self.acquisitions.append({"case": self.case, "lease": lease})
            return lease
        self.stack.enter_context(patch.object(self.owner, "acquire", observed_acquire))
        run = admission.ResourceAdmittedToolRunner.run
        def observed_run(runner, tool, **kwargs):
            operation = current_proof_operation()
            value = run(runner, tool, **kwargs)
            self.lifecycle.append({"case": self.case, "result": value.to_dict(),
                "tool_request": {"argv": list(tool.argv), "limits": asdict(tool.limits),
                    "input_files": dict(tool.input_files), "environment": dict(tool.environment)},
                "deadline": operation.deadline if operation else None,
                "explicit_cancellation_forwarded": kwargs.get("cancellation") is not None,
                "forwarded_signal_is_current_operation": operation is not None and kwargs.get("cancellation") is operation})
            return value
        self.stack.enter_context(patch.object(admission.ResourceAdmittedToolRunner, "run", observed_run))
        def synthetic_execute(executor, invocation, cancellation=None):
            require(self.data is not None and cancellation is not None and not cancellation.is_set(), "missing fixture or live stop signal")
            source = (invocation.cwd / "protocol.spthy").read_text()
            require(source == self.data["source"], "materialized source differs from the independent fixture")
            snapshot = self.owner.snapshot()
            require(snapshot["active_lease_count"] == snapshot["active_root_lease_count"] == 1
                    and snapshot["allocated"] == {"cpu_slots": 2, "memory_mb": 512}
                    and snapshot["allocated_child_process_slots"] == 8, "default owned admission profile changed")
            require(invocation.argv == (str(Path(sys.executable).resolve()), "--prove", "--with-maude=maude",
                str(invocation.cwd / "protocol.spthy"), "+RTS", "-N1", "-M268435456", "-RTS"), "default argv changed")
            limits = invocation.limits
            require(limits.memory_bytes == 2048*MIB and limits.resident_memory_bytes == 512*MIB
                    and 0 < limits.timeout_seconds <= 5 and 0 < limits.cpu_seconds <= 5
                    and limits.max_output_bytes == limits.max_input_bytes == OUTPUT_BYTES
                    and limits.max_workspace_bytes == 2*OUTPUT_BYTES, "finite lifecycle profile changed")
            require("GHCRTS" not in invocation.environment and "DEBUG_MAUDE" not in invocation.environment,
                    "owned environment retained uncontrolled runtime flags")
            self.invocations.append({"case": self.case, "workspace": str(invocation.cwd),
                "argv": list(invocation.argv), "limits": asdict(limits), "source_sha256": digest(source),
                "environment": dict(invocation.environment), "snapshot": snapshot,
                "executor_kind": "synthetic_fixture", "pid": None})
            return process.RawProcessResult(returncode=0, stdout=self.data["stdout"], stderr=self.data["stderr"])
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", synthetic_execute))
        return self

    def __exit__(self, *args):
        self.after = self.owner.snapshot()
        return self.stack.__exit__(*args)


def run_case(route, kind, environment):
    from ipfs_datasets_py.logic.backends import registry, resource_admission as admission
    from ipfs_datasets_py.logic.backends.protocol import tamarin, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    require(current_proof_operation() is None and sys.getprofile() is None, "unexpected ambient operation/profiler")
    data, req = fixture(kind), request(route, kind)
    environment.case, environment.data = route + ":" + kind, data
    outcomes, requests, parsed_sources, observations = [], [], [], []
    def observer(frame, event, value):
        if event in {"call", "return"} and frame.f_code is tamarin.TamarinBackend.run.__code__:
            operation = current_proof_operation()
            observations.append({"event": event, "deadline": operation.deadline if operation else None})
            if event == "call":
                selected = frame.f_locals["self"]
                require(selected._owns_runner and type(selected._runner) is admission.ResourceAdmittedToolRunner
                        and type(selected._compiler) is tamarin.TamarinCompiler
                        and selected._version_probe is selected._maude_probe is selected._available_probe is None,
                        "default backend construction was replaced")
                requests.append(frame.f_locals["request"])
            elif event == "return" and isinstance(value, tamarin.TamarinBackendOutcome):
                outcomes.append(value)
        if event == "call" and frame.f_code is tamarin.parse_tamarin_claim_outcomes.__code__:
            parsed_sources.append(frame.f_locals.get("source"))
    started = time.perf_counter()
    sys.setprofile(observer)
    attempt = None
    try:
        if route == "direct":
            returned = tamarin.TamarinBackend().run(req)
        elif route == "registry":
            attempt, returned = registry.default_backend_registry().run(req)
        else:
            returned = v2.ProtocolExecutionEngineV2().execute(req)
    finally:
        sys.setprofile(None)
    require(current_proof_operation() is None and len(outcomes) == len(requests) == 1
            and requests[0] == canonical_request(route, kind) and parsed_sources == [data["source"]],
            "request/source/parser binding or scope restoration differs")
    original = outcomes[0]
    typed, receipt = original.result.to_dict(), original.receipt.to_dict()
    check_claims(receipt["claim_outcomes"], data, typed["status"], receipt["accepted"])
    secure = kind == "complete"
    require(typed["authority"] == "protocol" and typed["translation_ceiling"] == ("bounded" if secure else "none")
            and original.compile_result.source == data["source"]
            and original.compile_result.claim_lemmas.to_dict() == data["claim_lemmas"]
            and original.source_binding == tamarin.TamarinSourceBinding.bind(requests[0], data["source"], "spthy")
            and original.request_digest == requests[0].digest, "source/authority ceiling differs")
    require((receipt["quarantine"] is None) is secure and "attack_traces" not in typed["witness"]
            and "attack_trace_replay" not in typed["witness"], "synthetic result escaped quarantine or gained replay authority")
    if kind == "falsified":
        require(receipt["quarantine"]["reason"] == "malformed_output", "unvalidated falsification was promoted")
    wire = returned.to_dict()
    if route == "registry":
        require(attempt.status.value == "succeeded" and wire["status"] == "unknown"
                and returned.payload.to_dict()["result"] == typed
                and returned.request_digest == attempt.request_digest == requests[0].digest
                and returned.attempt_digest == attempt.digest, "registry changed original payload or promoted authority")
    elif route == "standalone_v2":
        require(wire["backend_outcome"] == original.to_dict()
                and wire["protocol_established"] is secure and wire["disposition"] == ("secure" if secure else "quarantined")
                and not wire["is_proved"] and not wire["is_theorem_authority"], "V2 result/authority differs")
        attack = wire["evidence"]["attack"]
        require(not attack["attack_traces"] and not attack["replay_tokens"] and not attack["replayed"]
                and not attack["authorizes_universal_proof"], "V2 gained synthetic attack replay authority")
    invocations = [r for r in environment.invocations if r["case"] == environment.case]
    lifecycle = [r for r in environment.lifecycle if r["case"] == environment.case]
    leases = [r["lease"] for r in environment.acquisitions if r["case"] == environment.case]
    require(len(invocations) == len(lifecycle) == len(leases) == 1 and leases[0].released
            and not Path(invocations[0]["workspace"]).exists(), "fixture lease/workspace did not clean up")
    raw = lifecycle[0]["result"]
    require(raw["stdout"] == data["stdout"] and raw["stderr"] == "" and raw["returncode"] == 0
            and raw["pid"] is None and raw["workspace_cleaned"]
            and not any(raw[key] for key in ("cancelled", "timed_out", "unavailable", "resource_exhausted",
                "output_truncated", "workspace_limit_exceeded", "process_tree_terminated", "error")), "synthetic lifecycle differs")
    metadata = {key: raw[key] for key in ("cancelled", "command", "error", "output_truncated",
        "process_tree_terminated", "returncode", "resource_exhausted", "timed_out", "termination_reason",
        "unavailable", "workspace_cleaned", "workspace_limit_exceeded")}
    metadata.update(stdout_digest=tamarin.stable_digest({"content": raw["stdout"]}),
        stderr_digest=tamarin.stable_digest({"content": raw["stderr"]}))
    require(typed["metadata"]["process"] == metadata, "controlled raw lifecycle metadata changed")
    require(len(observations) == 2 and all(row["deadline"] == lifecycle[0]["deadline"] for row in observations)
            and (lifecycle[0]["deadline"] is None) == (route == "direct")
            and lifecycle[0]["explicit_cancellation_forwarded"] == (route == "standalone_v2")
            and lifecycle[0]["forwarded_signal_is_current_operation"] == (route == "standalone_v2"),
            "default operation/cancellation forwarding changed")
    snapshot = environment.owner.snapshot()
    require(snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0, "private fixture work leaked")
    return {"case": environment.case, "route": route, "fixture": kind, "fixture_data": data,
        "request": req.to_dict(), "canonical_request": requests[0].to_dict(), "original_outcome": original.to_dict(),
        "result": wire, "attempt": attempt.to_dict() if attempt else None,
        "invocation": invocations[0], "lifecycle": lifecycle[0], "operation_observations": observations,
        "workspace_cleaned": True, "lease_released": True, "default_backend_and_runner": True,
        "native_solver_executed": False, "source_passed_to_parser": True,
        "elapsed_seconds": time.perf_counter() - started}


def parser_benchmark():
    from ipfs_datasets_py.logic.backends.protocol import tamarin
    aggregates = []
    for count in SIZES:
        for kind in PARSER_FIXTURES:
            data = fixture(kind, count)
            samples, digests = [], []
            for repeat in range(REPEATS):
                started = time.perf_counter()
                outcomes = tamarin.parse_tamarin_claim_outcomes(data["stdout"], data["stderr"],
                    claim_lemmas=data["claim_lemmas"], source=data["source"])
                elapsed = time.perf_counter() - started
                status, quarantine, accepted = tamarin.classify_claim_outcomes(outcomes)
                rows = [row.to_dict() for row in outcomes]
                check_claims(rows, data, status.value, accepted)
                digests.append(digest(rows))
                samples.append({"repeat": repeat, "elapsed_seconds": elapsed, "outcome_count": len(rows),
                    "status": status.value, "accepted": accepted,
                    "quarantine": quarantine.reason.value if quarantine else None})
            require(len(set(digests)) == 1, "bounded parser result changed across identical repeats")
            times = [r["elapsed_seconds"] for r in samples]
            aggregates.append({"fixture": kind, "claim_count": count, "samples": samples,
                "source_bytes": len(data["source"].encode()), "stdout_bytes": len(data["stdout"].encode()),
                "source_sha256": data["source_sha256"], "stdout_sha256": data["stdout_sha256"],
                "outcomes_sha256": digests[0], "min_seconds": min(times), "median_seconds": statistics.median(times),
                "max_seconds": max(times), "median_seconds_per_claim": statistics.median(times)/count,
                "scope": "Python parser only; classification/serialization/assertions excluded from timing"})
    return aggregates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    directory = parser.parse_args().output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "tamarin-claim-binding-controlled-benchmark@1", "status": "running",
        "source_pins_before": pins(), "cases": [], "parser_benchmarks": [], "checks": {},
        "scope": {"synthetic_executor_output": True, "synthetic_executable_availability": True,
            "synthetic_healthy_pressure": True, "private_fixture_scheduler": True,
            "default_owned_runner_compiler_parser": True, "benchmark_operation_scope_injected": False,
            "shared_pool_used": False, "native_solver_execution": False, "native_proof_claim": False,
            "semantic_attack_reconstruction": False, "parallel_scaling_claim": False, "host_backoff_qualified": False},
        "native_launches": 0, "shared_pool_accesses": 0}
    environment = ControlledEnvironment(directory)
    started = time.perf_counter()
    try:
        with environment:
            result["private_scheduler_config"] = environment.owner.config.persisted_dict()
            result["synthetic_host_resources"] = asdict(environment.healthy)
            result["private_scheduler_before"] = environment.before
            for route in ROUTES:
                for kind in FIXTURES:
                    result["cases"].append(run_case(route, kind, environment))
                    write(directory / "partial.json", result)
            result["parser_benchmarks"] = parser_benchmark()
        result["private_scheduler_after"] = environment.after
        result["checks"].update(controlled_cases_complete=len(result["cases"]) == 15,
            timed_parser_calls=sum(len(r["samples"]) for r in result["parser_benchmarks"]) == 36,
            no_native_launch_attempts=not environment.native_attempts,
            no_shared_scheduler_attempts=not environment.shared_attempts,
            private_work_drained=environment.after["active_lease_count"] == environment.after["waiting_request_count"] == 0,
            workspaces_removed=all(not Path(r["workspace"]).exists() for r in environment.invocations),
            leases_released=all(r["lease"].released for r in environment.acquisitions))
        result["status"] = "passed_controlled"
    except BaseException:
        result["status"] = "failed"
        result["error"] = traceback.format_exc()
    finally:
        if environment is not None:
            environment.stack.close()
            result["synthetic_executor_calls"] = len(environment.invocations)
            result["native_launch_attempts"] = environment.native_attempts
            result["shared_pool_attempts"] = environment.shared_attempts
            result["private_owner_resolutions"] = environment.resolutions
            result["audit_sha256"] = {}
            for name, value in (("invocation-audit.json", environment.invocations),
                    ("lifecycle-audit.json", environment.lifecycle)):
                write(directory / name, value)
                result["audit_sha256"][name] = sha(directory / name)
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        result["elapsed_seconds"] = time.perf_counter() - started
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed_controlled" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
