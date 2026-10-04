"""Controlled V2 result binding, immutable payloads and evidence reconstruction.

Six default managed engine calls use synthetic outputs/discovery and fresh private
pools. Six non-authoritative paths perform no native execution. Reconstruction
retains the actual typed request/source/model because the existing request wire
contains digests and trace counts, not complete source/model/private-trace data.
No native solver, private-trace digest or parallel-scaling claim is made.
"""
from __future__ import annotations

import argparse
from dataclasses import fields, replace
import json
from pathlib import Path
import statistics
import sys
import time
import traceback
from unittest.mock import patch

import bench_hyper_counterexample_validation as controlled
import bench_process_workspace_guard as previous
from bench_smt_operation_control import ROOT, require, sha, write

ENGINES = controlled.ENGINES
NEW_TEST = ROOT / "tests/unit/logic/backends/test_hyper_evidence_integrity.py"
CASES = tuple((engine, kind) for engine in ENGINES for kind in ("satisfied", "violated", "capability")) + (
    ("hyperltl", "mock"), ("autohyper", "fallback_output"), ("mchyper", "evaluator_fallback"))
DIGEST_FIELDS = ("bounds", "disposition", "engine", "formula", "mode", "request_digest", "request_id", "system", "witness")


def pins():
    return {**previous.pins(), str(Path(__file__).resolve()): sha(__file__), str(NEW_TEST): sha(NEW_TEST)}


def arguments(cls, wire):
    return {field.name: wire[field.name] for field in fields(cls) if field.init and field.name in wire}


def evidence_from_wire(wire):
    from ipfs_datasets_py.logic.backends.hyperproperties.execution_v2 import HyperProviderEvidenceV2
    return HyperProviderEvidenceV2(**arguments(HyperProviderEvidenceV2, wire))


def reconstruct(result, wire):
    """Rebuild exported attachments while retaining omitted typed request context."""
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.results import HyperpropertyResult
    from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage
    request_wire = result.request.to_dict()
    request = replace(result.request, metadata=request_wire["metadata"],
        mock_output=request_wire["mock_output"], fallback_output=request_wire["fallback_output"])
    backend = None
    if wire["backend_result"] is not None:
        data = arguments(HyperpropertyResult, wire["backend_result"])
        data.update(bounds=ExecutionBounds.from_dict(data["bounds"]), usage=ResourceUsage.from_dict(data["usage"]))
        backend = HyperpropertyResult(**data)
    translation = None
    if wire["translation"] is not None:
        data = arguments(adapters.HyperpropertyTranslation, wire["translation"])
        data.update(observation_map=adapters.ObservationMap.from_dict(data["observation_map"]),
            quantifier_order=adapters.QuantifierOrder(**arguments(adapters.QuantifierOrder, data["quantifier_order"])))
        translation = adapters.HyperpropertyTranslation(**data)
    return v2.HyperExecutionResultV2(request=request, evidence=evidence_from_wire(wire["evidence"]),
        backend_result=backend, translation=translation)


def request(engine, kind, label):
    from ipfs_datasets_py.logic.backends.hyperproperties import execution_v2 as v2
    from ipfs_datasets_py.logic.software_verification.hyperproperties import ExecutionTrace
    source_metadata = {"benchmark": {"labels": ["original"], "settings": {"enabled": True}}}
    req = replace(controlled.request(engine, "standalone_v2", label),
        source_ref_ids=("source:controlled-hyper",), metadata=source_metadata)
    if kind == "capability":
        req = replace(req, mode=v2.HyperExecutionMode.CAPABILITY_PROBE)
    elif kind == "mock":
        req = replace(req, mock_output={"status": "satisfied", "nested": {"values": ["original"]}})
    elif kind == "fallback_output":
        req = replace(req, fallback_output={"status": "satisfied", "nested": {"values": ["original"]}})
    elif kind == "evaluator_fallback":
        traces = tuple(ExecutionTrace(trace_id="trace:fixture:"+value, public_inputs={"user": "alice"},
            private_inputs={"secret": value}, observations={"status": "ok"}, subject={"tenant": "tenant_a"})
            for value in ("left", "right"))
        req = replace(req, allow_fallback=True, traces=traces)
    frozen = req.to_dict()
    source_metadata["benchmark"]["labels"][0] = "source-mutated"
    require(req.to_dict() == frozen, "request retained an alias to constructor metadata")
    return req


def mutation_matrix(result):
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.results import ResultNormalizationError
    req, evidence = result.request, result.evidence
    def with_request(changed):
        return replace(result, request=changed,
            evidence=replace(evidence, request_digest=v2._digest_of(changed.to_dict()), content_digest=""))
    changed_doc = replace(req.document, metadata={"fixture": "changed"}, document_id="")
    candidates = [
        ("request_id", lambda: replace(result, request=replace(req, request_id=req.request_id+":other"))),
        ("evidence_request_digest", lambda: replace(result, evidence=replace(evidence, request_digest="f"*64, content_digest=""))),
        ("request_source_refs", lambda: with_request(replace(req, source_ref_ids=("source:other",)))),
        ("request_document", lambda: with_request(replace(req, document=changed_doc))),
        ("request_model", lambda: with_request(replace(req, system_model=(req.system_model or "fixture:model")+"\n"))),
        ("evidence_formula", lambda: replace(result, evidence=replace(evidence,
            formula=replace(evidence.formula, formula_digest="f"*64), content_digest=""))),
        ("evidence_system", lambda: replace(result, evidence=replace(evidence,
            system=replace(evidence.system, system_digest="f"*64), content_digest=""))),
        ("evidence_source_refs", lambda: replace(result, evidence=replace(evidence, source_ref_ids=("source:other",), content_digest=""))),
        ("evidence_bounds", lambda: replace(result, evidence=replace(evidence,
            bounds=replace(evidence.bounds, max_steps=evidence.bounds.max_steps+1), content_digest=""))),
        ("translation_attachment", lambda: replace(result, translation=replace(result.translation,
            formula_text=result.translation.formula_text+" "))),
        ("backend_status", lambda: replace(result, backend_result=replace(result.backend_result,
            status="violated" if result.backend_result.status.value == "satisfied" else "satisfied"))),
        ("backend_bounds", lambda: replace(result, backend_result=replace(result.backend_result,
            bounds=replace(req.bounds, max_memory_bytes=req.bounds.max_memory_bytes+1)))),
        ("receipt_engine", lambda: replace(result, evidence=replace(evidence,
            receipt={**evidence.to_dict()["receipt"], "engine": next(engine for engine in ENGINES if engine != req.provider.value)}, content_digest=""))),
        ("stale_content_digest", lambda: replace(evidence, content_digest="0"*64)),
    ]
    for name in ("timeout_ms", "max_memory_bytes", "max_output_bytes", "max_steps"):
        changed = replace(req, bounds=replace(req.bounds, **{name: getattr(req.bounds, name)+1}))
        candidates.append(("request_bound:"+name, lambda changed=changed: with_request(changed)))
    before = result.to_dict()
    rows = []
    for name, build in candidates:
        started = time.monotonic()
        try:
            build()
        except (v2.HyperExecutionError, adapters.HyperpropertyAdapterError, ResultNormalizationError) as error:
            rows.append({"mutation": name, "rejected": True, "error_type": type(error).__name__,
                "error": str(error), "elapsed_seconds": time.monotonic()-started})
        else:
            raise AssertionError("changed evidence/request attachment accepted: "+name)
        require(result.to_dict() == before, "rejected mutation changed source result")
    return rows


def check_immutability(result):
    """Attempt public nested writes; never use object.__setattr__ bypasses."""
    req, ev = result.request, result.evidence
    probes = [
        ("request_metadata_sequence", req.metadata["benchmark"]["labels"], 0, "changed"),
        ("request_metadata_mapping", req.metadata["benchmark"]["settings"], "enabled", False),
        ("formula_prefix", ev.formula.quantifier_prefix[0], "quantifier", "exists"),
        ("system_observation_map", ev.system.observation_map["low_input_fields"], 0, "changed"),
        ("capability_mapping", ev.capability.capability, "engine", "changed"),
    ]
    if ev.receipt is not None:
        probes.append(("receipt_projection", ev.receipt["observation_map"]["low_input_fields"], 0, "changed"))
    if ev.witness.counterexample is not None:
        probes.append(("counterexample_trace", ev.witness.counterexample["traces"][0]["observations"], "status", "changed"))
    if result.translation is not None:
        probes.extend((("translation_auxiliary", result.translation.auxiliary_files, "property.hltl", "changed"),
            ("translation_observation_map", result.translation.observation_map.observation_kinds, "status", "changed"),
            ("translation_quantifier_binding", result.translation.quantifier_order.bindings[0], "quantifier", "exists")))
    if req.mock_output is not None:
        probes.append(("request_mock_output", req.mock_output["nested"]["values"], 0, "changed"))
    if req.fallback_output is not None:
        probes.append(("request_fallback_output", req.fallback_output["nested"]["values"], 0, "changed"))
    before, rows = result.to_dict(), []
    for name, target, key, value in probes:
        try:
            target[key] = value
        except (TypeError, AttributeError) as error:
            rows.append({"mutation": name, "rejected": True, "error_type": type(error).__name__})
        else:
            raise AssertionError("public nested mutation was accepted: "+name)
        require(result.to_dict() == before, "public mutation changed frozen result")
    return rows


def roundtrip(result):
    from ipfs_datasets_py.logic.backends.hyperproperties import execution_v2 as v2
    original = result.to_dict()
    exported = json.loads(json.dumps(original))
    rebuilt = reconstruct(result, exported)
    require(rebuilt.to_dict() == original, "existing wire schema changed on reconstruction with retained context")
    ev_wire = rebuilt.evidence.to_dict()
    require(rebuilt.evidence.content_digest == v2._digest_of({key: ev_wire[key] for key in DIGEST_FIELDS}),
        "legacy evidence content digest preimage changed")
    # Constructor inputs and fresh exports must both detach nested data.
    exported["evidence"]["formula"]["quantifier_prefix"][0]["quantifier"] = "exists"
    exported["evidence"]["system"]["observation_map"]["low_input_fields"][0] = "changed"
    exported["request"]["metadata"]["benchmark"]["labels"][0] = "changed"
    require(rebuilt.to_dict() == original and result.to_dict() == original, "constructor retained exported input aliases")
    detached = rebuilt.to_dict()
    detached["evidence"]["formula"]["quantifier_prefix"][0]["quantifier"] = "exists"
    detached["request"]["metadata"]["benchmark"]["settings"]["enabled"] = False
    require(rebuilt.to_dict() == original, "to_dict exposed nested mutable storage")
    copied = rebuilt.evidence.system.to_dict()["observation_map"]
    copied["low_input_fields"][0] = "changed"
    require(rebuilt.to_dict() == original, "public system snapshot retained nested aliases")
    return {"wire_stable_with_retained_request_context": True, "legacy_digest_preimage_unchanged": True,
        "constructor_inputs_detached": True, "exports_detached": True, "public_snapshot_detached": True,
        "content_digest": rebuilt.evidence.content_digest, "request_digest": rebuilt.evidence.request_digest}


def run_case(engine, kind, directory):
    from ipfs_datasets_py.logic.backends import resource_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import adapters, execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    label = engine+":"+kind
    case_dir = directory / label.replace(":", "-")
    case_dir.mkdir()
    req = request(engine, kind, label)
    stdout = controlled.fixtures.POSITIVE[engine] if kind == "satisfied" else controlled.output(engine, "valid")[0]
    environment = controlled.Environment(case_dir / "private-pool.json", engine, stdout)
    row = {"case": label, "engine": engine, "kind": kind, "request": req.to_dict(), "status": "running"}
    original_wire = req.to_dict()
    originals, phases = [], []
    def observe(frame, event, value):
        if event in {"call", "return"} and frame.f_code is adapters.HyperpropertyBackend.check.__code__:
            backend, operation = frame.f_locals["self"], current_proof_operation()
            require(backend.engine.value == engine and backend._managed_runner
                and type(backend._runner) is admission.ResourceAdmittedToolRunner and operation is not None,
                "default managed V2 route/scope replaced")
            phases.append({"event": event, "deadline": operation.deadline})
            if event == "return" and isinstance(value, adapters.HyperCheckOutcome):
                originals.append(value)
    started = time.monotonic()
    try:
        with environment:
            if kind == "evaluator_fallback":
                def unavailable(backend):
                    environment.discovery.append(backend.engine.value)
                    return ""
                environment.stack.enter_context(patch.object(adapters.HyperpropertyBackend, "resolve_executable", unavailable))
            require(sys.getprofile() is None and current_proof_operation() is None, "unexpected ambient observer/operation")
            sys.setprofile(observe)
            api_started = time.monotonic()
            try:
                result = v2.HyperExecutionEngineV2().execute(req)
            finally:
                sys.setprofile(None)
            row.update(elapsed_call_seconds=time.monotonic()-api_started, result=result.to_dict(),
                original_outcomes=[value.to_dict() for value in originals], operation_observations=phases)
            require(current_proof_operation() is None and req.to_dict() == original_wire, "operation/request leaked")
            executing = kind in {"satisfied", "violated"}
            require(len(environment.invocations) == len(environment.lifecycle) == len(environment.admissions) == len(environment.workspaces) == int(executing),
                "non-native case executed or engine did not run once")
            require(len(originals) == int(executing or kind == "evaluator_fallback"), "unexpected backend outcome count")
            require(result.request == req and result.evidence.request_id == req.request_id
                and result.evidence.request_digest == v2._digest_of(req.to_dict())
                and result.evidence.source_ref_ids == req.source_ref_ids
                and not result.is_proved and not result.is_theorem_authority
                and result.hyperproperty_established is executing, "result authority or primary request binding differs")
            if executing:
                require(result.backend_result.to_dict() == originals[0].result.to_dict()
                    and result.backend_result.status.value == kind
                    and result.backend_result.bounds == req.bounds
                    and result.evidence.witness.replayed is (kind == "violated"), "original engine projection changed")
                raw = environment.lifecycle[0]["result"]
                require(raw["pid"] is None and raw["returncode"] == 0 and raw["stdout"] == stdout and raw["workspace_cleaned"]
                    and not any(raw[key] for key in ("cancelled", "timed_out", "resource_exhausted", "unavailable",
                        "workspace_limit_exceeded", "output_truncated", "process_tree_terminated")), "controlled lifecycle failed")
                row["binding_mutations"] = mutation_matrix(result)
            else:
                expected = {"capability": "capability_only", "mock": "mock_rejected", "fallback_output": "fallback_rejected", "evaluator_fallback": "unknown"}[kind]
                require(result.disposition.value == expected, "non-authoritative path changed disposition")
                row["binding_mutations"] = []
            row.update(roundtrip=roundtrip(result), immutable_mutations=check_immutability(result))
            require(all(not result.evidence.establishes_other_engine(other) for other in ENGINES if other != engine), "engine capability transferred")
            row.update(original_request_unchanged=True, ambient_restored=True)
        require(environment.after["active_lease_count"] == environment.after["waiting_request_count"] == 0
            and all(lease.released for lease in environment.leases)
            and all(not Path(path).exists() for path in environment.workspaces)
            and not environment.native_attempts and not environment.shared_attempts, "private work or guarded execution leaked")
        row["status"] = "passed"
    except BaseException:
        row.update(status="failed", error=traceback.format_exc())
    finally:
        environment.stack.close()
        row.update(elapsed_seconds=time.monotonic()-started, admissions=environment.admissions, lifecycle=environment.lifecycle,
            invocations=environment.invocations, discovery=environment.discovery, sample_history=environment.samples,
            workspaces=environment.workspaces, private_before=getattr(environment, "before", None),
            private_after=getattr(environment, "after", None),
            private_config=environment.owner.config.persisted_dict() if hasattr(environment, "owner") else None,
            native_launch_attempts=environment.native_attempts, shared_scheduler_attempts=environment.shared_attempts,
            workspace_cleanup=all(not Path(path).exists() for path in environment.workspaces),
            leases_released=all(lease.released for lease in environment.leases))
        write(case_dir / "result.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / "command.json", {"argv": [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(directory)],
        "cwd": str(Path.cwd()), "benchmark_sha256": sha(__file__)})
    result = {"schema": "hyper-evidence-integrity-controlled-benchmark@1", "status": "running", "cases": [], "checks": {},
        "source_pins_before": pins(), "native_launches": 0, "shared_pool_accesses": 0,
        "scope": {"synthetic_executor_output": True, "synthetic_discovery": True, "synthetic_healthy_host_samples": True,
            "private_fixture_pools": True, "default_managed_v2_execution": True, "actual_host_pressure_tested": False,
            "retained_request_context_for_reconstruction": True, "standalone_full_result_wire_deserialization_claim": False,
            "private_trace_digest_binding_claim": False, "request_trace_count_only_digest_preserved": True,
            "native_model_membership_tested": False, "native_proof_claim": False, "many_core_scaling_claim": False}}
    started = time.monotonic()
    try:
        for engine, kind in CASES:
            row = run_case(engine, kind, directory)
            result["cases"].append(row)
            write(directory / "partial.json", result)
            require(row["status"] == "passed", "controlled integrity case failed: "+row["case"])
        samples = [row["elapsed_call_seconds"] for row in result["cases"]]
        result["timings"] = {"api_samples_seconds": samples, "min_seconds": min(samples), "median_seconds": statistics.median(samples),
            "max_seconds": max(samples), "scope": "Mixed controlled paths; observational timings, not throughput or speedup"}
        result["checks"].update(all12_cases_passed=len(result["cases"]) == 12,
            exactly6_synthetic_executions=sum(len(row["invocations"]) for row in result["cases"]) == 6,
            all108_binding_mutations_rejected=sum(len(row["binding_mutations"]) for row in result["cases"]) == 108,
            all_roundtrips_stable=all(row["roundtrip"]["wire_stable_with_retained_request_context"] for row in result["cases"]),
            no_native_attempts=all(not row["native_launch_attempts"] for row in result["cases"]),
            no_shared_pool_attempts=all(not row["shared_scheduler_attempts"] for row in result["cases"]),
            owned_work_drained=all(row["workspace_cleanup"] and row["leases_released"] for row in result["cases"]))
        result["status"] = "passed_controlled"
    except BaseException:
        result.update(status="failed", error=traceback.format_exc())
    finally:
        result["source_pins_after"] = pins()
        result["checks"]["sources_stable"] = result["source_pins_before"] == result["source_pins_after"]
        result["elapsed_seconds"] = time.monotonic()-started
        if not all(result["checks"].values()):
            result["status"] = "failed"
        write(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "checks": result["checks"], "result": str(directory / "result.json")}))
    return 0 if result["status"] == "passed_controlled" else 1


if __name__ == "__main__":
    sys.path[:0] = [str(ROOT.parent / "ipfs_accelerate"), str(ROOT)]
    raise SystemExit(main())
