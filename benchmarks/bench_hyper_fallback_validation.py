"""Controlled bounded fallback evaluation and retained-trace consistency.

Nine fallback cases use real evaluation with synthetic unavailable discovery.
Three managed engine cases use synthetic SAT output and private admission. Three
stops interrupt real evaluation under the engine-owned operation. Private trace
values never enter recorded outputs; no native proof or scaling claim is made.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import statistics
import sys
import threading
import time
import traceback
from unittest.mock import patch

import bench_hyper_counterexample_validation as controlled
import bench_hyper_evidence_integrity as previous
from bench_smt_operation_control import ROOT, require, sha, write

ENGINES = controlled.ENGINES
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_fallback_validation.py"
CASES = tuple((engine, kind) for engine in ENGINES for kind in ("violated", "clean", "limited", "managed_sat")) + (
    ("hyperltl", "cancel_evaluation"), ("autohyper", "timeout_evaluation"), ("mchyper", "cancel_revalidation"))
PRIVATE_SENTINELS = tuple("private-fallback-sentinel-" + name for name in ("left", "right", "third", "renamed-left", "renamed-right", "renamed-third"))


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def assert_private_absent(value):
    encoded = json.dumps(value, sort_keys=True)
    require(all(token not in encoded for token in PRIVATE_SENTINELS), "private fixture value leaked into a public projection")


def request(engine, kind, label):
    from ipfs_datasets_py.logic.software_verification.hyperproperties import ExecutionTrace
    req = previous.request(engine, "satisfied", label)
    if kind == "managed_sat":
        return req
    count = 3 if kind == "limited" else 2
    traces = tuple(ExecutionTrace(trace_id="trace:fixture:" + str(index), public_inputs={"user": "alice"},
        private_inputs={"secret": PRIVATE_SENTINELS[index]},
        observations={"status": "leak" if kind == "violated" and index == 1 else "ok"},
        subject={"tenant": "tenant_a"}) for index in range(count))
    return replace(req, allow_fallback=True, traces=traces)


def mutation_matrix(result, kind):
    """Check redacted canonical equivalence, not identity of private inputs."""
    from ipfs_datasets_py.logic.backends.hyperproperties import execution_v2 as v2
    req, values = result.request, result.request.traces
    def changed_second(**changes):
        return (values[0], replace(values[1], **changes), *values[2:])
    changes = [("observation_change", changed_second(
        observations={"status": "ok" if kind == "violated" else "leak"}), False)]
    if kind == "violated":
        changes.extend((
            ("private_equalization", changed_second(private_inputs=dict(values[0].private_inputs)), False),
            ("public_mismatch", changed_second(public_inputs={"user": "bob"}), False),
            ("subject_mismatch", changed_second(subject={"tenant": "tenant_b"}), False),
            ("witness_trace_id", changed_second(trace_id="trace:fixture:renamed"), False),
        ))
    changes.extend((
        ("equivalent_private_renaming", tuple(replace(trace, private_inputs={"secret": PRIVATE_SENTINELS[index+3]})
            for index, trace in enumerate(values)), True),
        ("equivalent_permutation", tuple(reversed(values)), True),
    ))
    original, rows = result.to_dict(), []
    for label, traces, should_accept in changes:
        changed = replace(req, traces=traces)
        require(changed.to_dict() == req.to_dict(), "same-count trace mutation unexpectedly changed the public request wire")
        started = time.monotonic()
        try:
            rebuilt = replace(result, request=changed)
        except v2.HyperExecutionError as error:
            require(not should_accept, "equivalent redacted evaluation was rejected: " + label)
            row = {"mutation": label, "accepted": False, "rejected": True,
                "error_type": type(error).__name__, "error": str(error)}
        else:
            require(should_accept, "changed canonical fallback evaluation was accepted: " + label)
            require(rebuilt.to_dict() == original, "accepted equivalent evaluation changed existing evidence")
            row = {"mutation": label, "accepted": True, "rejected": False, "wire_unchanged": True}
        row.update(elapsed_seconds=time.monotonic()-started, request_wire_unchanged=True)
        assert_private_absent(row)
        require(result.to_dict() == original, "mutation changed retained result")
        rows.append(row)
    return rows


def run_case(engine, kind, directory):
    from ipfs_datasets_py.logic.backends import resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt.operation_budget import (
        ProofOperationCancelled, ProofOperationTimeout, current_proof_operation)
    from ipfs_datasets_py.logic.software_verification.hyperproperties import HyperpropertyIR
    label = engine + ":" + kind
    case_dir = directory / label.replace(":", "-")
    case_dir.mkdir()
    req = request(engine, kind, label)
    wire = req.to_dict()
    stopping = kind in {"cancel_evaluation", "timeout_evaluation", "cancel_revalidation"}
    managed = kind == "managed_sat"
    environment = controlled.Environment(case_dir / "private-pool.json", engine, controlled.fixtures.POSITIVE[engine])
    row = {"case": label, "engine": engine, "kind": kind, "request": wire, "status": "running",
        "mutations": [], "returned_result": False}
    cancellation, originals, evaluations, phases = threading.Event(), [], [], []
    active_evaluations = {}
    started, evaluation_count, triggered = time.monotonic(), 0, False

    def observe(frame, event, value):
        nonlocal evaluation_count, triggered
        if event not in {"call", "return"}:
            return
        operation = current_proof_operation()
        if frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            backend = frame.f_locals["self"]
            require(backend.engine.value == engine and backend._managed_runner
                and type(backend._runner) is admission.ResourceAdmittedToolRunner and operation is not None,
                "default managed V2 route/operation replaced")
            phases.append({"event": event, "deadline": operation.deadline})
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                originals.append(value)
        if frame.f_code is HyperpropertyIR.evaluate_bounded_noninterference.__code__:
            if event == "call":
                evaluation_count += 1
                active_evaluations[id(frame)] = (time.monotonic(), operation.deadline if operation else None)
                target = 2 if kind == "cancel_revalidation" else 1
                if stopping and not triggered and evaluation_count == target:
                    require(operation is not None, "stop case lacks an engine-owned operation")
                    triggered = True
                    row["stop_trigger"] = {"evaluation_index": evaluation_count, "deadline": operation.deadline,
                        "kind": "deadline" if kind == "timeout_evaluation" else "cancellation",
                        "observer_boundary": "entry to actual bounded evaluator"}
                    if kind == "timeout_evaluation":
                        delay = max(0.0, operation.deadline-time.monotonic()) + 0.01
                        require(delay <= 0.3, "controlled deadline delay exceeded its bound")
                        time.sleep(delay)
                    else:
                        cancellation.set()
            else:
                began, deadline = active_evaluations.pop(id(frame))
                evaluations.append({"elapsed_seconds": time.monotonic()-began, "deadline": deadline,
                    "returned_evaluation": value is not None,
                    **({"verdict": value.verdict.value, "explored_traces": value.explored_traces,
                        "explored_pairs": value.explored_pairs, "bound_hit": value.bound_hit} if value is not None else {})})

    try:
        with environment:
            if not managed:
                def unavailable(backend):
                    environment.discovery.append(backend.engine.value)
                    return ""
                environment.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", unavailable))
            require(current_proof_operation() is None and sys.getprofile() is None, "unexpected ambient operation/observer")
            api_started = time.monotonic()
            sys.setprofile(observe)
            try:
                result = v2.HyperExecutionEngineV2().execute(req, cancellation=cancellation,
                    operation_timeout_ms=250 if kind == "timeout_evaluation" else None)
            except (ProofOperationCancelled, ProofOperationTimeout) as error:
                require(stopping and triggered, "unexpected operation interruption")
                expected = ProofOperationTimeout if kind == "timeout_evaluation" else ProofOperationCancelled
                require(type(error) is expected, "wrong interruption type")
                row["interruption"] = {"error_type": type(error).__name__, "error": str(error)}
            else:
                require(not stopping, "stopped evaluation published evidence")
                row.update(returned_result=True, result=result.to_dict())
            finally:
                sys.setprofile(None)
            row.update(elapsed_call_seconds=time.monotonic()-api_started,
                original_outcomes=[value.to_dict() for value in originals], evaluations=evaluations, operation_observations=phases)
            require(not active_evaluations and current_proof_operation() is None and req.to_dict() == wire,
                "evaluation observer, ambient operation or request leaked")
            require(len(environment.invocations) == len(environment.lifecycle) == len(environment.admissions)
                == len(environment.workspaces) == int(managed), "unexpected executor/admission count")
            if stopping:
                require(evaluations and not evaluations[-1]["returned_evaluation"], "interrupted core evaluation returned evidence")
                require(len(originals) == int(kind == "cancel_revalidation"), "stopped backend publication differs")
            else:
                require(len(originals) == 1 and result.backend_result.to_dict() == originals[0].result.to_dict()
                    and result.request.to_dict() == wire and result.evidence.request_digest == v2._digest_of(wire)
                    and result.backend_result.bounds == req.bounds and not result.is_proved and not result.is_theorem_authority,
                    "original backend projection/request binding changed")
                require(result.disposition.value == ("satisfied" if managed else "violated" if kind == "violated" else "unknown")
                    and result.hyperproperty_established is managed, "fallback gained engine authority or changed verdict")
                if not managed:
                    require(result.evidence.evidence_path.value == "bounded_self_composition"
                        and not result.evidence.external_tool_proof and len(evaluations) >= 2,
                        "fallback was not evaluated and revalidated")
                    require(all(item["verdict"] == {"violated": "violated", "clean": "holds", "limited": "inconclusive"}[kind]
                        and item["bound_hit"] is (kind == "limited") for item in evaluations), "bounded evaluation outcome differs")
                    row["mutations"] = mutation_matrix(result, kind)
                rebuilt = previous.reconstruct(result, json.loads(json.dumps(result.to_dict())))
                require(rebuilt.to_dict() == result.to_dict(), "reconstruction changed evidence wire/digest")
                row["roundtrip"] = {"wire_unchanged": True, "content_digest": result.evidence.content_digest,
                    "retained_typed_request_context": True}
            row.update(original_request_unchanged=True, ambient_restored=True)
        require(environment.after["active_lease_count"] == environment.after["waiting_request_count"] == 0
            and all(lease.released for lease in environment.leases)
            and all(not Path(path).exists() for path in environment.workspaces)
            and not environment.native_attempts and not environment.shared_attempts, "owned work or guarded execution leaked")
        row["status"] = "passed"
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        sys.setprofile(None)
        environment.stack.close()
        row.update(elapsed_seconds=time.monotonic()-started, admissions=environment.admissions, lifecycle=environment.lifecycle,
            invocations=environment.invocations, discovery=environment.discovery, sample_history=environment.samples,
            workspaces=environment.workspaces, private_before=getattr(environment, "before", None),
            private_after=getattr(environment, "after", None),
            private_config=environment.owner.config.persisted_dict() if hasattr(environment, "owner") else None,
            native_launch_attempts=environment.native_attempts, shared_scheduler_attempts=environment.shared_attempts,
            workspace_cleanup=all(not Path(path).exists() for path in environment.workspaces),
            leases_released=all(lease.released for lease in environment.leases))
        assert_private_absent(row)
        write(case_dir / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "hyper-fallback-validation-controlled-benchmark@1", "status": "running", "cases": [], "checks": {},
        "source_pins_before": pins(), "native_launches": 0, "shared_pool_accesses": 0,
        "scope": {"actual_bounded_evaluator": True, "synthetic_unavailable_discovery": True,
            "synthetic_managed_outputs": True, "private_fixture_pools": True, "synthetic_healthy_host_samples": True,
            "retained_private_context_reevaluated": True, "private_trace_identity_claim": False,
            "public_private_trace_hash_added": False, "request_trace_count_only_digest_preserved": True,
            "cooperative_stop_at_evaluator_entry": True, "hard_preemption_tested": False,
            "native_solver_proof_claim": False, "actual_host_pressure_tested": False, "many_core_scaling_claim": False}}
    started = time.monotonic()
    try:
        for engine, kind in CASES:
            row = run_case(engine, kind, directory)
            result["cases"].append(row)
            write(directory / "partial.json", result)
            require(row["status"] == "passed", "controlled fallback case failed: " + row["case"])
        samples = [row["elapsed_call_seconds"] for row in result["cases"]]
        changes = [change for row in result["cases"] for change in row["mutations"]]
        result["timings"] = {"api_samples_seconds": samples, "min_seconds": min(samples), "median_seconds": statistics.median(samples),
            "max_seconds": max(samples), "scope": "Mixed controlled paths including an intentional deadline delay; not throughput or speedup"}
        result["checks"].update(all15_cases_passed=len(result["cases"]) == 15,
            exactly3_synthetic_executions=sum(len(row["invocations"]) for row in result["cases"]) == 3,
            all21_changed_evaluations_rejected=sum(change["rejected"] for change in changes) == 21,
            all18_equivalent_evaluations_accepted=sum(change["accepted"] for change in changes) == 18,
            all3_stops_withheld_results=sum(not row["returned_result"] and "interruption" in row for row in result["cases"]) == 3,
            private_values_absent=True,
            no_native_attempts=all(not row["native_launch_attempts"] for row in result["cases"]),
            no_shared_pool_attempts=all(not row["shared_scheduler_attempts"] for row in result["cases"]),
            owned_work_drained=all(row["workspace_cleanup"] and row["leases_released"] for row in result["cases"]))
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        require(all(result["checks"].values()), "controlled fallback checks failed")
        result["status"] = "passed_controlled"
    except BaseException:
        result.update(status="failed", error=traceback.format_exc(), source_pins_after=pins())
    finally:
        result["elapsed_seconds"] = time.monotonic()-started
        assert_private_absent(result)
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "cases": len(result["cases"]), "elapsed_seconds": result["elapsed_seconds"]}))
    return 0 if result["status"] == "passed_controlled" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
