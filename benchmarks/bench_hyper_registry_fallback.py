"""Controlled request-scoped Hyper fallback through the default registry.

Canonical adapters and the actual bounded evaluator run with synthetic missing
tool discovery. Native transport and scheduler access are denied. Generic input
payloads contain private traces, so artifacts retain only safe request descriptors
and redacted outcomes. No Python-evaluator host admission or scaling is claimed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch

import bench_hyper_counterexample_validation as controlled
import bench_hyper_fallback_validation as previous
from bench_smt_operation_control import ROOT, require, sha, write

LEGACY = "hyperltl_autohyper_mchyper"
SELECTORS = (*controlled.ENGINES, LEGACY)
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_registry_fallback.py"
CASES = tuple((selector, kind) for selector in SELECTORS for kind in ("violated", "clean", "limited")) + (
    ("hyperltl", "no_opt_in"), ("autohyper", "no_traces"), ("mchyper", "availability_veto"),
    (LEGACY, "probe_failure"), ("hyperltl", "cancel_evaluation"), ("autohyper", "timeout_evaluation"))


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def engine_for(selector):
    return "hyperltl" if selector == LEGACY else selector


def request(selector, kind, label):
    engine = engine_for(selector)
    fixture = previous.request(engine, kind if kind in {"violated", "clean", "limited"} else "clean", label)
    base = controlled.request(engine, "registry", label)
    traces = [{"trace_id": trace.trace_id, "public_inputs": dict(trace.public_inputs),
        "private_inputs": dict(trace.private_inputs), "observations": dict(trace.observations), "subject": dict(trace.subject)}
        for trace in fixture.traces]
    payload = {**base.payload.to_dict(), "allow_fallback": kind not in {"no_opt_in", "concurrent_no_opt_in"},
        "traces": [] if kind == "no_traces" else traces}
    return replace(base, requested_backend_id=selector, payload=payload)


def descriptor(req):
    return {"request_id": req.request_id, "request_digest": req.digest, "requested_backend_id": req.requested_backend_id,
        "logic_family": req.logic_family, "query_kind": req.query_kind.value, "bounds": req.bounds.to_dict(),
        "allow_fallback": req.payload.get("allow_fallback") is True, "trace_count": len(req.payload.get("traces", ())),
        "full_request_wire_persisted": False}


class Guards:
    """Explicit synthetic discovery; no scheduler, executor or output substitute."""

    def __init__(self):
        self.stack, self.local = ExitStack(), threading.local()
        self.discovery, self.native, self.scheduler, self.transport = [], [], [], []
        self.entered, self.release = threading.Event(), threading.Event()

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission as admission
        from ipfs_datasets_py.logic.backends.hyperproperties import adapters
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        def deny(bucket, name):
            def blocked(*args, **kwargs):
                bucket.append({"case": getattr(self.local, "case", "outside"), "operation": name})
                raise AssertionError("controlled fallback forbids " + name)
            return blocked
        self.stack.enter_context(patch.object(subprocess, "Popen", deny(self.native, "native Popen")))
        self.stack.enter_context(patch.object(os, "system", deny(self.native, "os.system")))
        self.stack.enter_context(patch.object(process.SubprocessExecutor, "execute", deny(self.transport, "subprocess executor")))
        self.stack.enter_context(patch.object(admission.ResourceAdmittedToolRunner, "run", deny(self.transport, "resource admitted transport")))
        self.stack.enter_context(patch.object(scheduler, "get_global_resource_scheduler", deny(self.scheduler, "shared scheduler")))
        self.stack.enter_context(patch.object(admission, "get_global_resource_scheduler", deny(self.scheduler, "admission scheduler")))
        def missing(backend):
            row = {"case": getattr(self.local, "case", "outside"), "engine": backend.engine.value,
                "synthetic_missing": not getattr(self.local, "probe_failure", False)}
            self.discovery.append(row)
            if getattr(self.local, "probe_failure", False):
                raise OSError("controlled discovery failure")
            return ""
        self.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", missing))
        return self

    def __exit__(self, *args):
        self.release.set()
        return self.stack.__exit__(*args)


def run_case(registry, guards, selector, kind, *, concurrent=False):
    from ipfs_datasets_py.logic.backends import resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    from ipfs_datasets_py.logic.software_verification.hyperproperties import HyperpropertyIR
    label = selector + ":" + kind
    guards.local.case, guards.local.probe_failure = label, kind == "probe_failure"
    req = request(selector, kind, label)
    # Digest stability is checked in memory; never persist the raw generic payload.
    original_digest, safe = req.digest, descriptor(req)
    row = {"case": label, "selector": selector, "engine": engine_for(selector), "kind": kind,
        "request_descriptor": safe, "status": "running", "concurrent": concurrent}
    cancellation, originals, evaluations, phases, active = threading.Event(), [], [], [], {}
    stopped = kind in {"cancel_evaluation", "timeout_evaluation"}
    allowed = kind in {"violated", "clean", "limited", "concurrent_fallback"}
    started = time.monotonic()

    def observe(frame, event, value):
        if event not in {"call", "return"}:
            return
        operation = current_proof_operation()
        if frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            backend = frame.f_locals["self"]
            expected = {"hyperltl": adapters.HyperLTLBackend, "autohyper": adapters.AutoHyperBackend, "mchyper": adapters.MCHyperBackend}[engine_for(selector)]
            require(type(backend) is expected and backend._managed_runner
                and type(backend._runner) is admission.ResourceAdmittedToolRunner and operation is not None,
                "default canonical delegate/runner/operation changed")
            phases.append({"event": event, "deadline": operation.deadline})
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                originals.append(value)
        if frame.f_code is HyperpropertyIR.evaluate_bounded_noninterference.__code__:
            if event == "call":
                require(operation is not None, "registry evaluator lacks an operation")
                active[id(frame)] = (time.monotonic(), operation.deadline)
                if concurrent and kind == "concurrent_fallback":
                    guards.entered.set()
                    require(guards.release.wait(1.0), "concurrent isolation rendezvous timed out")
                if stopped:
                    row["stop_trigger"] = {"deadline": operation.deadline,
                        "observer_boundary": "entry to actual bounded evaluator"}
                    if kind == "cancel_evaluation":
                        cancellation.set()
                    else:
                        delay = max(0.0, operation.deadline-time.monotonic()) + .01
                        require(delay <= .3, "controlled deadline delay exceeded bound")
                        time.sleep(delay)
            else:
                began, deadline = active.pop(id(frame))
                evaluations.append({"elapsed_seconds": time.monotonic()-began, "deadline": deadline,
                    "returned_evaluation": value is not None,
                    **({"verdict": value.verdict.value, "bound_hit": value.bound_hit,
                        "explored_traces": value.explored_traces, "explored_pairs": value.explored_pairs} if value is not None else {})})

    try:
        require(sys.getprofile() is None and current_proof_operation() is None, "unexpected ambient operation/observer")
        with ExitStack() as case_context:
            if kind == "availability_veto":
                case_context.enter_context(patch.object(registry[selector], "_availability_probe", lambda: False))
            row["public_available_before"] = registry.is_available(selector)
            require(row["public_available_before"] is False, "synthetic discovery reported native availability")
            sys.setprofile(observe)
            api_started = time.monotonic()
            try:
                attempt, result = registry.run(req, cancellation=cancellation,
                    operation_timeout_ms=250 if kind == "timeout_evaluation" else None)
            finally:
                sys.setprofile(None)
            row["elapsed_call_seconds"] = time.monotonic()-api_started
            row["public_available_after"] = registry.is_available(selector)
        require(not active and current_proof_operation() is None and req.digest == original_digest,
            "evaluation observer, ambient operation or request changed")
        require(attempt.backend_id == result.backend_id == selector
            and attempt.request_digest == result.request_digest == original_digest and result.attempt_digest == attempt.digest
            and result.status.value == "unknown", "registry binding or conservative authority changed")
        require(row["public_available_after"] is False, "request eligibility escaped into public availability")
        payload = result.payload.to_dict()
        if allowed:
            expected = "violated" if kind == "violated" else "unknown"
            require(attempt.status.value == "succeeded" and len(originals) == len(evaluations) == 1,
                "opted-in canonical fallback did not run exactly once")
            original = originals[0]
            require(original.result.status.value == expected and payload["result"] == original.result.to_dict()
                and original.result.bounds == req.bounds and original.request_digest == original_digest,
                "registry lost typed fallback result/request projection")
            require(original.receipt.evidence_path.value == "bounded_self_composition"
                and not original.receipt.external_tool_proof and not original.receipt.authorizes_universal_proof,
                "fallback acquired engine/theorem authority")
            expected_verdict = "violated" if kind == "violated" else "inconclusive" if kind == "limited" else "holds"
            require(evaluations[0]["verdict"] == expected_verdict and evaluations[0]["bound_hit"] is (kind == "limited"),
                "actual bounded fallback evaluation differs")
        else:
            expected = "cancelled" if kind == "cancel_evaluation" else "timed_out" if stopped else "unavailable"
            require(attempt.status.value == expected and not originals and "result" not in payload,
                "refused/stopped request exposed a typed fallback outcome")
            require(len(evaluations) == int(stopped) and all(not item["returned_evaluation"] for item in evaluations),
                "refused/stopped request published evaluation")
        row.update(status="passed", attempt=attempt.to_dict(), result=result.to_dict(),
            original_outcomes=[value.to_dict() for value in originals], evaluations=evaluations,
            operation_observations=phases, original_request_unchanged=True, ambient_restored=True)
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        sys.setprofile(None)
        row.update(elapsed_seconds=time.monotonic()-started,
            discovery=[value for value in guards.discovery if value["case"] == label],
            native_attempts=[value for value in guards.native if value["case"] == label],
            scheduler_attempts=[value for value in guards.scheduler if value["case"] == label],
            transport_attempts=[value for value in guards.transport if value["case"] == label])
        previous.assert_private_absent(row)
    return row


def concurrent_cases(directory):
    from ipfs_datasets_py.logic.backends.registry import default_backend_registry
    rows, workers = {}, []
    with Guards() as guards:
        registry = default_backend_registry()
        def worker(kind):
            rows[kind] = run_case(registry, guards, "hyperltl", kind, concurrent=True)
        positive = threading.Thread(target=worker, args=("concurrent_fallback",), name="fallback-opt-in")
        negative = threading.Thread(target=worker, args=("concurrent_no_opt_in",), name="fallback-no-opt-in")
        workers.append(positive)
        positive.start()
        try:
            require(guards.entered.wait(1.0), "fallback did not reach shared-registry rendezvous")
            workers.append(negative)
            negative.start()
            negative.join(1.0)
            require(not negative.is_alive() and positive.is_alive(), "concurrent no-opt-in did not complete while fallback was held")
        finally:
            guards.release.set()
            for thread in workers:
                thread.join(2.0)
        require(all(not thread.is_alive() for thread in workers), "controlled registry worker leaked")
        require(not guards.native and not guards.scheduler and not guards.transport, "concurrent guard was touched")
    for row in rows.values():
        row["shared_registry_overlap_observed"] = True
        previous.assert_private_absent(row)
    require(set(rows) == {"concurrent_fallback", "concurrent_no_opt_in"}, "concurrent result missing")
    return [rows["concurrent_fallback"], rows["concurrent_no_opt_in"]]


def main():
    from ipfs_datasets_py.logic.backends.registry import default_backend_registry
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "hyper-registry-fallback-controlled-benchmark@1", "status": "running", "cases": [], "checks": {},
        "source_pins_before": pins(), "native_launches": 0, "shared_pool_accesses": 0, "transport_calls": 0,
        "scope": {"actual_default_registry": True, "actual_bounded_evaluator": True, "synthetic_missing_tool_discovery": True,
            "explicit_availability_veto_fixture": True, "synthetic_probe_failure": True,
            "raw_generic_requests_persisted": False, "native_availability_falsely_enabled": False,
            "python_evaluator_scheduler_admission": False, "host_pressure_backoff_qualified": False,
            "native_solver_proof_claim": False, "many_core_scaling_claim": False,
            "registry_normalizes_stops_to_unknown": True, "cooperative_stop_at_evaluator_entry": True}}
    started = time.monotonic()
    try:
        for selector, kind in CASES:
            with Guards() as guards:
                row = run_case(default_backend_registry(), guards, selector, kind)
                require(not guards.native and not guards.scheduler and not guards.transport, "serial guard was touched")
            result["cases"].append(row)
            write(directory / (row["case"].replace(":", "-") + ".json"), row)
            write(directory / "partial.json", result)
            require(row["status"] == "passed", "controlled registry fallback case failed: " + row["case"])
        for row in concurrent_cases(directory):
            result["cases"].append(row)
            write(directory / (row["case"].replace(":", "-") + ".json"), row)
            require(row["status"] == "passed", "shared-registry isolation case failed")
        samples = [row["elapsed_call_seconds"] for row in result["cases"]]
        result["timings"] = {"api_samples_seconds": samples, "min_seconds": min(samples), "median_seconds": statistics.median(samples),
            "max_seconds": max(samples), "scope": "Controlled paths with deliberate deadline/rendezvous delays; not throughput or speedup"}
        result["source_pins_after"] = pins()
        result["checks"].update(all20_cases_passed=len(result["cases"]) == 20,
            all13_fallback_results_retained=sum(bool(row["original_outcomes"]) for row in result["cases"]) == 13,
            all5_refusals_unavailable=sum(row["attempt"]["status"] == "unavailable" for row in result["cases"]) == 5,
            all2_stops_unknown=sum(row["attempt"]["status"] in {"cancelled", "timed_out"} for row in result["cases"]) == 2,
            all_generic_results_unknown=all(row["result"]["status"] == "unknown" for row in result["cases"]),
            public_availability_unchanged=all(row["public_available_before"] is False and row["public_available_after"] is False for row in result["cases"]),
            no_native_or_scheduler_or_transport_attempts=all(not row["native_attempts"] and not row["scheduler_attempts"] and not row["transport_attempts"] for row in result["cases"]),
            private_fixture_values_absent=True, shared_registry_isolation_observed=True,
            sources_stable=result["source_pins_before"] == result["source_pins_after"])
        require(all(result["checks"].values()), "controlled registry checks failed")
        result["status"] = "passed_controlled"
    except BaseException:
        result.update(status="failed", error=traceback.format_exc(), source_pins_after=pins())
    finally:
        result["elapsed_seconds"] = time.monotonic()-started
        previous.assert_private_absent(result)
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "cases": len(result["cases"]), "elapsed_seconds": result["elapsed_seconds"]}))
    return 0 if result["status"] == "passed_controlled" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
