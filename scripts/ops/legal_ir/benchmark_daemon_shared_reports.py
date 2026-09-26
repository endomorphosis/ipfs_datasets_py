#!/usr/bin/env python3
"""Qualify full-report sharing in the actual daemon with bounded local inputs.

The frozen target-only benchmark remains unchanged. This run generates one full
report bundle, verifies its exact native roundtrip, and compares fresh cold and
full-report-shared daemon cycles. Cold native report caches are exported only
after the daemon timer stops; no evaluator, trainer or producer is wrapped in a
timed daemon. The same disclosed loader-only fixture boundary is used in both.
"""
from __future__ import annotations

import argparse
import dataclasses
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import struct
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
BASE_PATH = Path(__file__).with_name("benchmark_daemon_shared_targets.py")
BASE_SHA = "c464ca6ada2837b9fdb00685e049cd5d0740725c7e9035b3bdbbe1b5f16aacb1"
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA:
    raise RuntimeError("frozen target-only harness changed")
import benchmark_daemon_shared_targets as base

sha, read, write, descriptor, canonical = base.sha, base.read, base.write, base.descriptor, base.canonical
BRIDGES = base.BRIDGES
MAX_REPORT_BYTES = 64 * 1024 * 1024
# These audit limits follow the production expanded-tree/compound/depth bounds,
# independently of the wire representation. They are not Python RSS bounds.
MAX_AUDIT_TOKEN_BYTES = 256 * 1024 * 1024
MAX_NATIVE_COMPOUNDS = 1_000_000
MAX_NATIVE_DEPTH = 100
# Every primitive, key and compound visit requires at least one byte in the
# production expanded tagged tree. Shared compounds are traversed only once.
# This deliberately conservative work limit is a value COUNT, not byte memory.
MAX_NATIVE_VALUES = MAX_AUDIT_TOKEN_BYTES
DATE_PATHS = frozenset({
    ("document", "views", "deontic_norms.deontic_graph", "payload", "metadata", field)
    for field in ("created_at", "last_updated")
} | {
    ("reports", "deontic_norms", "ir_document", "views", "deontic_graph", "payload", "metadata", field)
    for field in ("created_at", "last_updated")
})


def native_classes():
    from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
    from ipfs_datasets_py.logic.bridge.types import (
        BridgeEvaluationReport, GraphProjectionResult, LegalIRDocument,
        LogicIRView, ProofGateResult, RoundTripMetrics,
    )
    return frozenset({MultiViewLegalIRReport, BridgeEvaluationReport, GraphProjectionResult,
                     LegalIRDocument, LogicIRView, ProofGateResult, RoundTripMetrics})


def native_fingerprint(value):
    """Independent streaming fingerprint of exact fields, types, order and aliases.

    This does not call report.to_dict or either artifact codec. References use
    deterministic traversal IDs, preserving repeated container/dataclass sharing.
    Primitive float bytes include signed zero. Exact immutable string values are
    memoized as UTF-8 length/digest; each occurrence still emits a token. No scalar
    identity claim is made. Unique UTF-8 bytes plus emitted token payload bytes
    share a diagnostic budget derived from the production expanded-tree bound;
    that accounting is neither exact codec bytes nor RSS, and can reject a valid
    graph conservatively. Cycles/custom objects are rejected.
    """
    allowed, seen, active, strings = native_classes(), {}, set(), {}
    digest, charged, nodes = hashlib.sha256(), 0, 0

    def charge(size):
        nonlocal charged
        charged += size
        if charged > MAX_AUDIT_TOKEN_BYTES:
            raise ValueError("native fingerprint diagnostic token/unique-string bound exceeded")

    def emit(data):
        charge(len(data))
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NATIVE_VALUES or depth > MAX_NATIVE_DEPTH:
            raise ValueError("native fingerprint node/depth bound exceeded")
        kind = type(item)
        if item is None:
            emit(b"none")
        elif kind is bool:
            emit(b"bool" + bytes([item]))
        elif kind is int:
            emit(b"int" + str(item).encode())
        elif kind is float:
            emit(b"float" + struct.pack(">d", item))
        elif kind is str:
            identity = strings.get(item)
            if identity is None:
                encoded = item.encode("utf-8")
                charge(len(encoded))
                identity = len(encoded), hashlib.sha256(encoded).digest()
                strings[item] = identity
            emit(b"str_sha256" + struct.pack(">Q", identity[0]) + identity[1])
        else:
            if kind not in allowed and kind not in (dict, list, tuple):
                raise TypeError("unsupported native fingerprint value: " + kind.__qualname__)
            identity = id(item)
            if identity in active:
                raise ValueError("cyclic native report")
            if identity in seen:
                emit(b"ref" + str(seen[identity]).encode())
                return
            if len(seen) >= MAX_NATIVE_COMPOUNDS:
                raise ValueError("native fingerprint compound count bound exceeded")
            seen[identity] = len(seen)
            active.add(identity)
            emit(("object:" + kind.__module__ + "." + kind.__qualname__).encode())
            if kind in allowed:
                fields = dataclasses.fields(item)
                if set(vars(item)) != {field.name for field in fields}:
                    raise ValueError("extra native report attributes")
                for field in fields:
                    emit(field.name.encode())
                    visit(getattr(item, field.name), depth + 1)
            elif kind is dict:
                emit(str(len(item)).encode())
                for key, child in item.items():
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                emit(str(len(item)).encode())
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)

    visit(value)
    return {"sha256": digest.hexdigest(), "charged_bytes": charged,
            "visited_values": nodes, "distinct_native_objects": len(seen),
            "unique_string_values": len(strings),
            "charge_scope": "unique UTF-8 bytes plus emitted diagnostic token payloads; not exact codec expanded bytes or RSS",
            "bounds": {"diagnostic_token_bytes": MAX_AUDIT_TOKEN_BYTES, "visited_values": MAX_NATIVE_VALUES,
                       "distinct_compounds": MAX_NATIVE_COMPOUNDS, "depth": MAX_NATIVE_DEPTH},
            "schema": "native-fields-order-alias-fingerprint-v2"}


def target_fingerprint(target):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import _encode, _json
    raw = _json(_encode(target))
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("derived target exceeds original target shard bound")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def report_evidence(report, *, attempt=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import report_to_bytes
    def phase(name):
        if attempt is not None:
            attempt["phase"] = name
    phase("derive_target")
    target = report.training_target()
    phase("report_to_bytes")
    raw = report_to_bytes(report)
    if attempt is not None:
        attempt["report_dag_bytes"] = len(raw)
    phase("independent_native_fingerprint")
    fingerprint = native_fingerprint(report)
    phase("target_fingerprint")
    target_identity = target_fingerprint(target)
    phase("document_hash")
    document_hash = report.document.canonical_hash()
    phase("completed")
    return {"report_dag_sha256": hashlib.sha256(raw).hexdigest(), "report_dag_bytes": len(raw),
        "independent_native_fingerprint": fingerprint,
        "derived_target": target_identity, "document_hash": document_hash,
        "target_shares_report_document": target.document is report.document}


def observed_report_evidence(report, sample_id, observation):
    """Charge every audit attempt, including failure, without retaining reports."""
    attempts = observation["fingerprint_attempts"]
    if len(attempts) >= 6:
        raise ValueError("report fingerprint attempt count exceeds fixed fixture")
    attempt = {"sample_id": sample_id, "phase": "starting", "status": "running",
               "error": None, "elapsed_seconds": None}
    attempts.append(attempt)
    started = time.perf_counter()
    try:
        evidence = report_evidence(report, attempt=attempt)
        attempt["status"] = "completed"
        return evidence
    except BaseException as exc:
        attempt["status"] = "failed"
        attempt["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
        raise
    finally:
        attempt["elapsed_seconds"] = time.perf_counter() - started
        observation["fingerprint_seconds_outside_generation_intervals"] += attempt["elapsed_seconds"]


def load_bundle(artifact, config):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import load_report_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    return load_report_bundle(artifact["path"], expected_sha256=artifact["sha256"],
        expected_size_bytes=artifact["bytes"], config=TargetSnapshotConfig.from_dict(config))


def roundtrip_audit(artifact, config, samples, original_evidence):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import report_to_bytes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    bundle, rows = load_bundle(artifact, config), []
    try:
        for sample in samples:
            selection = bundle.selection_for([sample], config=TargetSnapshotConfig.from_dict(config))
            report, target = selection.reports[sample.sample_id], selection.targets[sample.sample_id]
            raw = report_to_bytes(report)
            actual = {"report_dag_sha256": hashlib.sha256(raw).hexdigest(), "report_dag_bytes": len(raw),
                "independent_native_fingerprint": native_fingerprint(report),
                "derived_target": target_fingerprint(target), "document_hash": report.document.canonical_hash(),
                "target_shares_report_document": target.document is report.document}
            expected = original_evidence[sample.sample_id]
            rows.append({"sample_id": sample.sample_id, "exact_original_fields_types_order_aliases_and_target": canonical(actual) == canonical(expected),
                         "original": expected, "loaded": actual})
            del selection, report, target, raw
        bundle.verify_unchanged()
        return {"rows": rows, "passed": len(rows) == 6 and all(row["exact_original_fields_types_order_aliases_and_target"] for row in rows),
                "scope": "sequential full native reports and derived targets; original field fingerprint independent of codec"}
    finally:
        bundle.close()


def prepare_child(spec, result):
    from audit_native_uscode_embedding_production import _deny_network
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_report_preparation as module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig
    helper = base.dependencies()
    result["network_guard"] = _deny_network()
    result["config"] = helper.config_probe(spec["payload"]["training_config"])
    original = module._bounded_target_results
    outcomes, fingerprints = [], {}
    result["preparation_observation"] = {"outcomes": outcomes, "retains_native_reports": False,
        "producer_boundary_observed": True, "native_daemon_wrapped": False, "wrapper_restored": False,
        "fingerprint_attempts": [], "fingerprint_timing_includes_failed_attempts": True,
        "fingerprint_seconds_outside_generation_intervals": 0.0}

    def observed(generate, samples, workers):
        generated = original(generate, samples, workers)
        try:
            for sample, item in generated:
                if type(item) is not tuple or len(item) != 4 or len(outcomes) >= 6:
                    raise ValueError("unexpected native report generation result")
                key, report, status, telemetry = item
                outcomes.append({"sample_id": key, "status": status, "bridge_report_telemetry": json.loads(canonical(telemetry))})
                if report is not None:
                    fingerprints[key] = observed_report_evidence(report, key, result["preparation_observation"])
                yield sample, item
                del sample, item, report
        finally:
            generated.close()

    module._bounded_target_results = observed
    try:
        payload = spec["payload"]
        result["prepared"] = module.prepare_legal_ir_reports(
            [SampleRecord.from_dict(row) for row in payload["samples"]], spec["bundle_path"],
            validation_records=[SampleRecord.from_dict(row) for row in payload["validation_samples"]],
            training_config=TrainingConfig.from_dict(payload["training_config"]))
    finally:
        module._bounded_target_results = original
        result["preparation_observation"]["wrapper_restored"] = module._bounded_target_results is original
        result["native_report_evidence"] = fingerprints
    prepared = result["prepared"]
    if ({row["sample_id"]: row["status"] for row in outcomes} != prepared["statuses"]
            or {row["sample_id"]: row["bridge_report_telemetry"] for row in outcomes} != prepared["bridge_report_telemetry"]
            or not helper.complete_bridge_reports(prepared)):
        raise ValueError("six complete native report outcomes required; no retry")
    _table, _adapter, samples = base.fixture(spec["payload"])
    started = time.perf_counter()
    result["roundtrip"] = roundtrip_audit(prepared["artifact"], result["config"], samples, fingerprints)
    result["roundtrip_seconds_outside_generation"] = time.perf_counter() - started
    result["config_after"] = helper.config_probe(spec["payload"]["training_config"])
    result["passed"] = result["roundtrip"]["passed"] and canonical(result["config"]) == canonical(result["config_after"])


def cold_cache_export(runner, samples, cycle, config, destination, observation):
    from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget, MultiViewLegalIRReport
    from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import _bridge_report_telemetry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import write_report_bundle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    fingerprints, ties = {}, []
    outcomes = {}
    observation.update(native_report_evidence=fingerprints, optimizer_target_ties=ties, bridge_report_telemetry=outcomes)
    recorded = {}
    for key in base.EVALUATION_KEYS:
        for sample_id, digest in cycle[key]["legal_ir_target_hashes"].items():
            if sample_id in recorded and recorded[sample_id] != digest:
                raise ValueError("optimizer target document changed during cold cycle")
            recorded[sample_id] = digest

    def rows():
        for sample in samples:
            report_key = runner._bridge_ir_report_cache_key(sample, bridge_names=BRIDGES, evaluate_provers=False)
            target_key = modal._legal_ir_target_cache_key(sample, bridge_names=BRIDGES, evaluate_provers=False)
            with runner._BRIDGE_IR_REPORT_CACHE_LOCK:
                report = runner._BRIDGE_IR_REPORT_CACHE.get(report_key)
            with modal._LEGAL_IR_TARGET_CACHE_LOCK:
                target = modal._LEGAL_IR_TARGET_CACHE.get(target_key)
            if (type(report) is not MultiViewLegalIRReport or type(target) is not LegalIRTrainingTarget
                    or type(report.document) is not LegalIRDocument or target.document is not report.document):
                raise ValueError("cold native report/target cache headers or shared document identity differ")
            outcomes[sample.sample_id] = _bridge_report_telemetry(report)
            if list(report.bridge_names) != BRIDGES or set(report.reports) != set(BRIDGES) or report.failures:
                raise ValueError("cold report lacks all five returned adapters; preserving actual outcome")
            evidence = report_evidence(report)
            actual_target = target_fingerprint(target)
            tied = evidence["derived_target"] == actual_target and evidence["document_hash"] == recorded.get(sample.sample_id)
            ties.append({"sample_id": sample.sample_id, "actual_optimizer_target": actual_target,
                         "recorded_document_hash": recorded.get(sample.sample_id), "exact_report_target_tie": tied})
            if not tied:
                raise ValueError("cold report does not reproduce its actual optimizer target")
            fingerprints[sample.sample_id] = evidence
            yield sample, report, None
            del report, target

    saved = write_report_bundle(destination, rows(), config=TargetSnapshotConfig.from_dict(config))
    artifact = {key: saved[key] for key in ("path", "sha256", "bytes")}
    observation.update(artifact=artifact, report_snapshot_id=saved["snapshot_id"], statuses=saved["statuses"],
        all_six_exact_optimizer_ties=len(ties) == 6 and all(row["exact_report_target_tie"] for row in ties))
    return observation


def daemon_child(spec, result):
    helper = base.dependencies()
    from audit_native_uscode_embedding_production import _deny_network
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint
    result["tree_pin"] = require_workspace_logic_tree()
    payload = spec["payload"]
    result["input_verification"] = verify_corpus_job_inputs(TrainingJobSpec.from_dict(payload))
    result["config_before"] = helper.config_probe(payload["training_config"])
    if canonical(result["config_before"]) != canonical(spec["config"]):
        raise ValueError("daemon package/config differs from fresh report preparation")
    work = Path(spec["work_directory"])
    if work.exists():
        raise ValueError("fresh private daemon workspace required")
    work.mkdir(parents=True)
    os.chdir(work)
    run_id = "bounded-reports-" + spec["policy"]
    state_path = work / "workspace/todo-queues" / (run_id + ".state.json")
    state_path.parent.mkdir(parents=True)
    helper.verify_descriptor({"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES})
    with helper.PINNED.open("rb") as source, state_path.open("xb") as destination:
        while chunk := source.read(1024 * 1024):
            destination.write(chunk)
    result["initial_private_checkpoint"] = descriptor(state_path)
    if result["initial_private_checkpoint"]["sha256"] != helper.PINNED_SHA:
        raise ValueError("private state copy differs from pinned checkpoint")
    initial = load_checkpoint(state_path, recover=False)
    result["initial_state_identity"] = initial.state.state_identity_record().to_dict()
    capacity = max(8192, initial.state.generalizable_entry_count() + 1)
    table, adapter, samples = base.fixture(payload)
    blocked = set(initial.state.decoded_embeddings) | set(initial.state.family_logits)
    result["initial_sample_memory_overlap"] = {"training": sorted(blocked & {row.sample_id for row in samples[:3]}),
                                               "validation": sorted(blocked & {row.sample_id for row in samples[3:]})}
    sample_hashes = [hashlib.sha256(row.to_json().encode()).hexdigest() for row in samples]
    result["sample_ids"] = [row.sample_id for row in samples]
    argv = base.daemon_argv(run_id, capacity, {}, "cold")
    if spec["policy"] == "shared":
        prepared = spec["prepared"]
        argv.extend(["--autoencoder-report-bundle", prepared["artifact"]["path"],
            "--autoencoder-report-bundle-sha256", prepared["artifact"]["sha256"],
            "--autoencoder-report-bundle-bytes", str(prepared["artifact"]["bytes"]),
            "--autoencoder-report-snapshot-id", prepared["report_snapshot_id"]])
    elif spec["policy"] != "cold":
        raise ValueError("unknown report qualification arm")
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(argv)
    result["argv"] = argv
    result["effective_arguments"] = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    old_loader, old_row = runner.load_laws_table, runner.row_to_sample
    runner.load_laws_table, runner.row_to_sample = lambda: table, adapter
    result["loader_adapters_restored"] = False
    del initial
    result["network_guard"] = _deny_network()
    try:
        ti, train, vi, validation, _attempts = runner.sample_train_validation_rows(table, random.Random(10),
            train_count=3, validation_count=0, blocked_train_sample_ids={sample.sample_id for sample in samples[3:]},
            blocked_validation_sample_ids=blocked, max_sample_text_chars=0)
        if ti != [0, 1, 2] or vi or validation or train != samples[:3]:
            raise ValueError("native input sampling differs from frozen order")
        result["memory_before_daemon"] = base.memory_observation()
        started = time.perf_counter()
        try:
            result["daemon_exit_code"] = runner.run_guarded_uscode_modal_daemon(args)
        finally:
            result["daemon_seconds_including_native_shutdown"] = time.perf_counter() - started
            result["memory_after_daemon_before_audit"] = base.memory_observation()
    finally:
        runner.load_laws_table, runner.row_to_sample = old_loader, old_row
        result["loader_adapters_restored"] = runner.load_laws_table is old_loader and runner.row_to_sample is old_row
    summary_path = work / "workspace/test-logs" / (run_id + ".summary")
    log_path = summary_path.with_suffix(".jsonl")
    summary, cycle = read(summary_path), base.read_cycle(log_path)
    result.update(summary=summary, cycle=cycle, summary_artifact=descriptor(summary_path), log_artifact=descriptor(log_path))
    result["native_phase_seconds"] = summary["latest_cycle_phase_timings"]
    result["bridge_on_evaluation_timings"] = {name: {"seconds": result["native_phase_seconds"][name],
        "seconds_per_span": result["native_phase_seconds"][name] / 3, "sample_count": 3, "bridge_names": BRIDGES,
        "sample_memory": name in {"before_train_eval", "after_train_eval"}}
        for name in ("before_train_eval", "before_validation_eval", "after_train_eval", "after_validation_eval")}
    if state_path.stat().st_size > base.MAX_CHECKPOINT_BYTES:
        raise ValueError("native final checkpoint exceeds byte bound")
    final = load_checkpoint(state_path, delta_path=state_path.with_name(run_id + ".state-deltas.bin"), recover=False)
    result["final_state_identity"] = final.state.state_identity_record().to_dict()
    result["final_checkpoint"] = descriptor(state_path)
    result["final_checkpoint_manifest"] = final.manifest.to_dict()
    del final
    if spec["policy"] == "cold":
        started = time.perf_counter()
        result["cold_report_export"] = {}
        cold_cache_export(runner, samples, cycle, spec["config"], spec["cold_export_path"], result["cold_report_export"])
        result["cold_report_export_seconds_after_daemon_timer"] = time.perf_counter() - started
        started = time.perf_counter()
        result["cold_report_roundtrip"] = roundtrip_audit(result["cold_report_export"]["artifact"], spec["config"], samples,
            result["cold_report_export"]["native_report_evidence"])
        result["cold_report_roundtrip_seconds_after_daemon_timer"] = time.perf_counter() - started
    result["config_after"] = helper.config_probe(payload["training_config"])
    result["input_verification_after"] = verify_corpus_job_inputs(TrainingJobSpec.from_dict(payload))
    checks = {
        "source_unchanged": canonical(result["config_before"]) == canonical(result["config_after"]),
        "checkpoint_source_unchanged": sha(helper.PINNED) == helper.PINNED_SHA,
        "sample_objects_unchanged": sample_hashes == [hashlib.sha256(row.to_json().encode()).hexdigest() for row in samples],
        "complete_bridge_diagnostics": all(base.bridge_diagnostics_complete(cycle[key]) for key in ("logic_bridge_train", "logic_bridge_validation")),
        "complete_optimizer_targets": all(cycle[key].get("legal_ir_target_count") == 3 for key in base.EVALUATION_KEYS),
        "projection_performed": bool(cycle["feature_projection_report"].get("epoch_reports")),
        "startup_state_uncompacted": summary["startup_autoencoder_generalizable_capacity"]["compacted"] is False,
        "native_persistence_durable": summary["final_state_persistence"]["durable"] is True and summary["async_artifact_writer_shutdown"]["drained"] is True,
        "selection_exact": cycle["train_indices"] == [0, 1, 2] and cycle["validation_indices"] == [3, 4, 5] and cycle["rotating_validation_indices"] == [],
    }
    if spec["policy"] == "cold":
        checks["cold_report_roundtrip"] = result["cold_report_roundtrip"]["passed"] and result["cold_report_export"]["all_six_exact_optimizer_ties"]
    else:
        # The runner retains this public summary key for both session kinds.
        session = summary.get("shared_target_session")
        result["shared_report_session"] = session
        checks["shared_report_session_complete"] = (isinstance(session, dict) and session.get("closed") is True
            and session.get("active") is False and session.get("poisoned") is False and session.get("failure") is None
            and session.get("artifact_kind") == "full_report_bundle"
            and session.get("counts") == {"cycles_started": 1, "cycles_completed": 1, "hydrations": 1, "cache_hits": 0, "skipped_cycles": 0}
            and session.get("current_cycle", {}).get("applied") is True
            and session.get("current_cycle", {}).get("report_statuses") == spec["prepared"]["statuses"])
        checks["diagnostics_consume_verified_reports"] = all(
            cycle[key].get("supplied_report_count") == 3
            and cycle[key].get("report_source") == "explicit_reports"
            and cycle[key].get("persistent_cache_policy") == "bypassed_for_explicit_reports"
            and cycle[key].get("verified_report_identity", {}).get("artifact_sha256") == spec["prepared"]["artifact"]["sha256"]
            and cycle[key].get("verified_report_identity", {}).get("snapshot_id") == spec["prepared"]["report_snapshot_id"]
            for key in ("logic_bridge_train", "logic_bridge_validation"))
        expected_hashes = spec["prepared_document_hashes"]
        checks["optimizer_consumes_prepared_report_documents"] = all(
            len(cycle[key]["legal_ir_target_hashes"]) == 3
            and all(expected_hashes.get(sample_id) == digest for sample_id, digest in cycle[key]["legal_ir_target_hashes"].items())
            for key in base.EVALUATION_KEYS)
    result["checks"] = checks
    result["passed"] = result["daemon_exit_code"] == 0 and summary["cycles"] == 1 and result["loader_adapters_restored"] and all(checks.values())


def graph_differences(left, right):
    """Compare all fields/order/aliases; classify only observed exact date paths."""
    allowed, pairs, reverse, differences = native_classes(), {}, {}, []
    total, visited = 0, 0

    def difference(path, reason, a, b):
        nonlocal total
        total += 1
        permitted = path in DATE_PATHS and type(a) is type(b) is str and reason == "value"
        if permitted:
            try:
                datetime.fromisoformat(a.replace("Z", "+00:00"))
                datetime.fromisoformat(b.replace("Z", "+00:00"))
            except ValueError:
                permitted = False
        def bounded(item):
            if type(item) in (str, int, float, bool) or item is None:
                raw = canonical(item)
                return item if len(raw) <= 2048 else {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            return {"type": type(item).__module__ + "." + type(item).__qualname__}
        if len(differences) < 64:
            differences.append({"path": list(path), "reason": reason, "cold": bounded(a), "prepared": bounded(b),
                                "explicit_deontic_wall_timestamp": permitted})

    def walk(a, b, path=(), depth=0):
        nonlocal visited
        visited += 1
        if visited > MAX_NATIVE_VALUES or depth > MAX_NATIVE_DEPTH:
            raise ValueError("full graph comparison exceeds node/depth bound")
        kind = type(a)
        if kind is not type(b):
            difference(path, "type", a, b)
            return
        if a is None or kind in (bool, int, str, float):
            equal = struct.pack(">d", a) == struct.pack(">d", b) if kind is float else a == b
            if not equal:
                difference(path, "value", a, b)
            return
        if kind not in allowed and kind not in (dict, list, tuple):
            raise TypeError("unsupported full graph comparison object")
        aid, bid = id(a), id(b)
        if aid in pairs or bid in reverse:
            if pairs.get(aid) != bid or reverse.get(bid) != aid:
                difference(path, "alias_topology", a, b)
            return
        if len(pairs) >= MAX_NATIVE_COMPOUNDS:
            raise ValueError("full graph comparison exceeds compound count bound")
        pairs[aid], reverse[bid] = bid, aid
        if kind in allowed:
            for field in dataclasses.fields(a):
                walk(getattr(a, field.name), getattr(b, field.name), (*path, field.name), depth + 1)
        elif kind is dict:
            if list(a) != list(b):
                difference(path, "mapping_key_order", list(a), list(b))
                return
            for key in a:
                walk(a[key], b[key], (*path, key), depth + 1)
        else:
            if len(a) != len(b):
                difference(path, "length", len(a), len(b))
                return
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, (*path, index), depth + 1)

    walk(left, right)
    return {"differences": differences, "difference_count": total, "visited_values": visited,
            "distinct_compound_pairs": len(pairs),
            "bounds": {"visited_values": MAX_NATIVE_VALUES, "distinct_compounds": MAX_NATIVE_COMPOUNDS,
                       "depth": MAX_NATIVE_DEPTH, "value_count_basis": "at least one expanded tagged-tree byte per visited value; not RSS"},
            "all_differences_retained": total == len(differences), "strict_native_graph_equal": total == 0,
            "only_observed_explicit_deontic_wall_timestamps": total == len(differences) and all(row["explicit_deontic_wall_timestamp"] for row in differences)}


def compare_graph_artifacts(cold_artifact, prepared_artifact, config, samples):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_report_bundle import report_to_bytes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
    cold, prepared, rows = load_bundle(cold_artifact, config), load_bundle(prepared_artifact, config), []
    try:
        for sample in samples:
            left = cold.selection_for([sample], config=TargetSnapshotConfig.from_dict(config))
            right = prepared.selection_for([sample], config=TargetSnapshotConfig.from_dict(config))
            a, b = left.reports[sample.sample_id], right.reports[sample.sample_id]
            row = graph_differences(a, b)
            row.update(sample_id=sample.sample_id, strict_report_dag_bytes_equal=report_to_bytes(a) == report_to_bytes(b),
                       cold_report_fingerprint=native_fingerprint(a), prepared_report_fingerprint=native_fingerprint(b))
            rows.append(row)
            del left, right, a, b
        cold.verify_unchanged()
        prepared.verify_unchanged()
        return {"rows": rows, "all_six_compared": len(rows) == 6,
            "strict_all_native_graphs_equal": all(row["strict_native_graph_equal"] and row["strict_report_dag_bytes_equal"] for row in rows),
            "all_native_graphs_equal_except_observed_explicit_wall_timestamps": len(rows) == 6 and all(row["only_observed_explicit_deontic_wall_timestamps"] for row in rows),
            "scope": "all seven native report types, every field/container order/scalar bit/alias; only listed observed deontic graph date leaves may be classified separately"}
    finally:
        cold.close()
        prepared.close()


def child_main(spec_path, output):
    spec = read(spec_path)
    result = {"schema": "daemon-full-report-child-v1", "passed": False, "kind": spec["kind"],
              "pid": os.getpid(), "harness_sha256": sha(__file__), "started_at": datetime.now(timezone.utc).isoformat()}
    started = time.perf_counter()
    try:
        if spec["kind"] == "prepare":
            prepare_child(spec, result)
        elif spec["kind"] == "daemon":
            daemon_child(spec, result)
        else:
            raise ValueError("unsupported child operation")
    except BaseException as exc:
        result["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        result["child_seconds"] = time.perf_counter() - started
        result["harness_unchanged"] = sha(__file__) == result["harness_sha256"] and sha(BASE_PATH) == BASE_SHA
        result["passed"] = result["passed"] and result["harness_unchanged"] and "error" not in result
        write(output, result)
    return 0 if result["passed"] else 1


def run_child(directory, name, spec):
    spec_path, result_path = directory / (name + "-spec.json"), directory / (name + "-result.json")
    log_path = directory / (name + "-process.log")
    write(spec_path, spec)
    started, timeout = time.perf_counter(), False
    with log_path.open("xb") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child-spec", str(spec_path),
            "--child-output", str(result_path)], cwd=ROOT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=base.MAX_CHILD_SECONDS)
        except subprocess.TimeoutExpired:
            timeout = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
    result = read(result_path) if result_path.exists() else {"passed": False, "error": {"type": "MissingChildReceipt"}}
    return {"process_seconds_including_shutdown_and_post_timer_audit": time.perf_counter() - started,
        "exit_code": code, "outer_timeout": timeout, "spec_artifact": descriptor(spec_path),
        "receipt_artifact": descriptor(result_path) if result_path.exists() else None, "process_log": descriptor(log_path), "result": result}


def run(args, receipt):
    helper = base.dependencies()
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    helper.verify_descriptor({"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES})
    if sha(helper.PRIOR) != helper.PRIOR_SHA:
        raise ValueError("frozen selection receipt changed")
    prior = read(helper.PRIOR)
    row = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]
    payload = row["worker"]["job_spec"]
    job = TrainingJobSpec.from_dict(payload)
    if prior["passed"] is not True or job.canonical_sha256 != row["worker"]["job_spec_canonical_sha256"] or job.base_checkpoint.sha256 != helper.PINNED_SHA:
        raise ValueError("parent source selection/checkpoint identity differs")
    worker_ref = {**row["completed"]["worker_receipt_artifact"], "path": str(Path(job.output_directory) / "receipt.json")}
    helper.verify_descriptor(worker_ref)
    if read(worker_ref["path"]) != row["worker"]:
        raise ValueError("parent worker receipt differs from hashed artifact")
    helper.validate_config(payload)
    receipt.update(parent_worker_receipt=worker_ref, parent_input_verification=verify_corpus_job_inputs(job),
        tree_pin=require_workspace_logic_tree(), parent_receipt={"path": str(helper.PRIOR), "sha256": helper.PRIOR_SHA},
        pinned_checkpoint=descriptor(helper.PINNED), ordered_input_records={"training": payload["samples"], "validation": payload["validation_samples"]},
        selection=prior["selection"], config_before=helper.config_probe(payload["training_config"]))
    write(args.directory / "config-before.json", receipt["config_before"])
    receipt["source_snapshots"] = []
    for name in ("uscode_modal_daemon_runner.py", "autoencoder_daemon_report_session.py", "autoencoder_report_preparation.py",
                 "legal_ir_report_bundle.py", "modal_autoencoder.py", "modal_autoencoder_checkpoint.py"):
        source = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / name
        target = args.directory / "source-code" / name
        target.parent.mkdir(exist_ok=True)
        with target.open("xb") as handle:
            handle.write(source.read_bytes())
        ref = descriptor(target)
        if ref["sha256"] != receipt["config_before"]["code_sha256"][source.relative_to(ROOT / "ipfs_datasets_py").as_posix()]:
            raise ValueError("source snapshot differs from producer manifest")
        receipt["source_snapshots"].append({"source": str(source), **ref})
    prep = run_child(args.directory, "preparation", {"kind": "prepare", "payload": payload,
        "bundle_path": str(args.directory / "prepared-reports.bundle")})
    receipt["preparation"] = prep
    if not prep["result"]["passed"] or prep["exit_code"] or prep["outer_timeout"]:
        raise ValueError("full-report preparation/roundtrip failed; no retry")
    if canonical(prep["result"]["config"]) != canonical(receipt["config_before"]):
        raise ValueError("producer configuration changed before preparation")
    prepared = prep["result"]["prepared"]
    for policy in ("cold", "shared"):
        row = run_child(args.directory, policy, {"kind": "daemon", "policy": policy, "payload": payload,
            "config": receipt["config_before"], "prepared": prepared,
            "prepared_document_hashes": {key: row["document_hash"] for key, row in prep["result"]["native_report_evidence"].items()},
            "work_directory": str(args.directory / (policy + "-workspace")),
            "cold_export_path": str(args.directory / "cold-native-reports.bundle")})
        receipt["runs"].append({"policy": policy, **row})
        if not row["result"]["passed"] or row["exit_code"] or row["outer_timeout"]:
            raise ValueError(policy + " actual daemon qualification failed; no retry")
    cold, shared = [row["result"] for row in receipt["runs"]]
    receipt["comparison"] = base.compare_runs(cold, shared)
    _table, _adapter, samples = base.fixture(payload)
    started = time.perf_counter()
    receipt["full_native_graph_comparison"] = compare_graph_artifacts(cold["cold_report_export"]["artifact"],
        prepared["artifact"], receipt["config_before"], samples)
    receipt["post_timer_full_graph_comparison_seconds"] = time.perf_counter() - started
    receipt["all_native_cycles_completed"] = True
    receipt["input_verification_after"] = verify_corpus_job_inputs(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child-spec", type=Path)
    parser.add_argument("--child-output", type=Path)
    args = parser.parse_args()
    os.environ.update(base.ENVIRONMENT)
    sys.path.insert(0, str(ROOT))
    if args.child_spec is not None:
        if args.child_output is None:
            parser.error("--child-output required")
        return child_main(args.child_spec, args.child_output)
    if args.directory is None or args.output is None:
        parser.error("--directory and --output required")
    args.directory, args.output = args.directory.resolve(), args.output.resolve()
    if args.directory.exists() or args.output.exists() or ROOT not in args.directory.parents:
        parser.error("use new paths; workspace must remain under the canonical checkout")
    args.directory.mkdir(parents=True)
    receipt = {"schema": "guarded-daemon-full-report-qualification-v1", "passed": False, "runs": [],
        "recorded_at": datetime.now(timezone.utc).isoformat(), "harness_sha256": sha(__file__),
        "base_harness": {"path": str(BASE_PATH), "sha256": BASE_SHA}, "environment": base.ENVIRONMENT,
        "qualification_scope": "native daemon evaluator/projection/unchanged diagnostic aggregation/persistence with loader-only verified local fixture",
        "ordinary_cli_input_path_qualified": False, "input_adapter_scope": ["load_laws_table", "row_to_sample"],
        "native_timed_evaluator_trainer_or_producer_wrapped": False,
        "preparation_boundary_observer": "primitive outcomes plus full native fingerprints outside original producer timeout/generation intervals; no report retention beyond current row",
        "cold_graph_capture": "existing native report/target caches inspected and serialized after daemon timer; no capture hooks in timed execution",
        "cold_vs_shared_policy": "one cold native cycle versus one fresh-process full-report artifact cycle; no second target artifact/hydration",
        "train_sample_memory": True, "validation_sample_memory": False, "metric_disk_cache": 0,
        "compiler_artifact_cache": "unmodified always-on cache, fresh private cwd per arm", "bridge_names": BRIDGES,
        "legal_ir_evaluate_provers": False, "legal_ir_parallel_workers": 1, "adapter_workers": 1,
        "prover_scope": "requested flag false; native router/FLogic work still permitted locally",
        "timing_scope": "daemon call includes native startup/shutdown; post-timer graph export/codec audit separately charged; whole child/process includes those extra checks and is not a symmetric daemon performance comparison",
        "admitted": False, "formalized": False, "heldout_canary_qualified": False,
        "promotion_performed": False, "publication_performed": False, "weights_downloaded": False,
        "warm_daemon_qualified": False, "speed_claim": False, "automatic_retry_or_reselection": False,
        "ontology_capture_parity": "raw capture/triple outputs are not persisted by daemon; this audit covers full bridge report graphs and optimizer targets",
        "pass_scope": "native execution, exact codec roundtrip, minimum numeric/grammar/acceptance/state parity, and full report graph parity except explicitly observed deontic wall timestamps"}
    started = time.perf_counter()
    try:
        run(args, receipt)
    except BaseException as exc:
        receipt["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        try:
            helper = base.dependencies()
            receipt["harness_unchanged"] = sha(__file__) == receipt["harness_sha256"] and sha(BASE_PATH) == BASE_SHA
            receipt["pinned_checkpoint_unchanged"] = sha(helper.PINNED) == helper.PINNED_SHA
            if "config_before" in receipt:
                prior = read(helper.PRIOR)
                config = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]["worker"]["job_spec"]["training_config"]
                receipt["config_after"] = helper.config_probe(config)
                receipt["source_unchanged"] = canonical(receipt["config_before"]) == canonical(receipt["config_after"])
            receipt["source_snapshots_unchanged"] = all(sha(ref["path"]) == ref["sha256"] for ref in receipt.get("source_snapshots", []))
        except BaseException as exc:
            receipt["final_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        receipt["elapsed_seconds"] = time.perf_counter() - started
        receipt["passed"] = ("error" not in receipt and "final_guard_error" not in receipt
            and receipt.get("all_native_cycles_completed") is True and receipt.get("harness_unchanged") is True
            and receipt.get("pinned_checkpoint_unchanged") is True and receipt.get("source_unchanged") is True
            and receipt.get("source_snapshots_unchanged") is True
            and receipt.get("comparison", {}).get("numeric_grammar_acceptance_and_complete_state_parity") is True
            and receipt.get("comparison", {}).get("independent_bridge_adapter_metrics_equal") is True
            and receipt.get("full_native_graph_comparison", {}).get("all_native_graphs_equal_except_observed_explicit_wall_timestamps") is True)
        write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "error": receipt.get("error")}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
