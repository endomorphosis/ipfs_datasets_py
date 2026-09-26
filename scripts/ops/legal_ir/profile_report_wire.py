#!/usr/bin/env python3
"""Measure one rejected native full-report wire graph without changing its caps.

Only the frozen fourth source record is generated. The original 15-second
producer timeout remains active. After generation, a narrowly matched final-DAG
JSON observer measures the existing serialization before its normal size check.
A diagnostic positional representation is inverted and compared byte-for-byte
with that same DAG; it is never loaded as a production report or published.
Only bounded primitive statistics/hashes are persisted, never report payloads.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = Path(__file__).with_name("benchmark_daemon_shared_reports.py")
HARNESS_SHA = "9a6643f10da541173c465ed502a724ffa58804d9a85aa15642d75735ce288c53"
if hashlib.sha256(HARNESS_PATH.read_bytes()).hexdigest() != HARNESS_SHA:
    raise RuntimeError("frozen report benchmark changed")
import benchmark_daemon_shared_reports as frozen

base = frozen.base
SAMPLE_ID = "us-code-22-4021a-fce42ca5c6a35f9d"
MAX_CHILD_SECONDS = 180
MAX_DIAGNOSTIC_BYTES = 256 * 1024 * 1024
MAX_DIAGNOSTIC_VALUES = MAX_DIAGNOSTIC_BYTES
CANDIDATE_SCHEMA = "diagnostic-positional-report-dag-v1"
NODE_TYPES = ("dict", "list", "tuple", "MultiViewLegalIRReport", "BridgeEvaluationReport",
              "GraphProjectionResult", "LegalIRDocument", "LogicIRView", "ProofGateResult", "RoundTripMetrics")


def error_record(exc):
    return {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}


def compact_dag(data, fields):
    """Pure reversible framing transform; all native containers remain nodes."""
    tag = {kind: index for index, kind in enumerate(NODE_TYPES)}
    def value(item):
        if type(item) is dict:
            if set(item) == {"ref"} and type(item["ref"]) is int:
                return [0, item["ref"]]
            if set(item) == {"str"} and type(item["str"]) is int:
                return [1, item["str"]]
            raise ValueError("unknown original DAG reference")
        if item is None or type(item) in (bool, int, float, str):
            return item
        raise ValueError("unknown original DAG scalar")
    nodes = []
    for node in data["nodes"]:
        kind = node["type"]
        if kind in ("list", "tuple"):
            payload = [value(item) for item in node["items"]]
        elif kind == "dict":
            payload = [value(item) for pair in node["items"] for item in pair]
        else:
            if [pair[0] for pair in node["fields"]] != list(fields[kind]):
                raise ValueError("native field order differs from fixed schema")
            payload = [value(pair[1]) for pair in node["fields"]]
        nodes.append([tag[kind], payload])
    return {"schema_version": CANDIDATE_SCHEMA, "original_schema": data["schema_version"],
            "node_types": list(NODE_TYPES), "fields": {kind: list(fields[kind]) for kind in NODE_TYPES[3:]},
            "strings": data["strings"], "nodes": nodes, "root": data["root"]["ref"]}


def expand_compact_dag(data, fields, original_schema):
    """Restore the original tagged DAG, including reference indices and types."""
    if (set(data) != {"schema_version", "original_schema", "node_types", "fields", "strings", "nodes", "root"}
            or data["schema_version"] != CANDIDATE_SCHEMA or data["original_schema"] != original_schema
            or data["node_types"] != list(NODE_TYPES)
            or data["fields"] != {kind: list(fields[kind]) for kind in NODE_TYPES[3:]}):
        raise ValueError("unknown diagnostic positional schema")
    def value(item):
        if type(item) is list:
            if len(item) != 2 or type(item[0]) is not int or item[0] not in (0, 1) or type(item[1]) is not int:
                raise ValueError("invalid diagnostic reference")
            return {"ref" if item[0] == 0 else "str": item[1]}
        if item is None or type(item) in (bool, int, float, str):
            return item
        raise ValueError("invalid diagnostic scalar")
    nodes = []
    for row in data["nodes"]:
        if type(row) is not list or len(row) != 2 or type(row[0]) is not int or not 0 <= row[0] < len(NODE_TYPES) or type(row[1]) is not list:
            raise ValueError("invalid diagnostic node")
        kind, payload = NODE_TYPES[row[0]], row[1]
        if kind in ("list", "tuple"):
            node = {"type": kind, "items": [value(item) for item in payload]}
        elif kind == "dict":
            if len(payload) % 2:
                raise ValueError("odd diagnostic dictionary payload")
            node = {"type": kind, "items": [[value(payload[i]), value(payload[i + 1])] for i in range(0, len(payload), 2)]}
        else:
            if len(payload) != len(fields[kind]):
                raise ValueError("diagnostic field count differs")
            node = {"type": kind, "fields": [[name, value(item)] for name, item in zip(fields[kind], payload)]}
        nodes.append(node)
    return {"schema_version": original_schema, "strings": data["strings"], "nodes": nodes, "root": {"ref": data["root"]}}


def wire_histogram(data, raw_size, native_json):
    """Exact JSON byte-size arithmetic plus bounded fixed-key structural totals."""
    scalar_lengths, visited = {}, 0
    def size(item):
        nonlocal visited
        visited += 1
        if visited > MAX_DIAGNOSTIC_VALUES:
            raise ValueError("diagnostic histogram work bound exceeded")
        kind = type(item)
        if kind is str:
            if item not in scalar_lengths:
                scalar_lengths[item] = len(native_json(item))
            return scalar_lengths[item]
        if item is None or kind in (bool, int, float):
            return len(native_json(item))
        if kind is list:
            return 2 + max(0, len(item) - 1) + sum(size(child) for child in item)
        if kind is dict:
            return 2 + max(0, len(item) - 1) + sum(size(key) + 1 + size(child) for key, child in item.items())
        raise TypeError("unexpected DAG wire value")
    by_type = {kind: {"nodes": 0, "json_bytes": 0, "entries": 0} for kind in NODE_TYPES}
    scalars = {kind: 0 for kind in ("null", "bool", "int", "float", "str")}
    references, pairs, field_count = {"compound": 0, "string": 0}, 0, 0
    for node in data["nodes"]:
        kind = node["type"]
        entries = node["items" if kind in ("dict", "list", "tuple") else "fields"]
        row = by_type[kind]
        row["nodes"] += 1
        row["entries"] += len(entries)
        row["json_bytes"] += size(node)
        if kind == "dict":
            pairs += len(entries)
        elif kind not in ("list", "tuple"):
            field_count += len(entries)
        values = entries if kind in ("list", "tuple") else (item for pair in entries for item in pair)
        for item in values:
            if type(item) is dict:
                references["compound" if "ref" in item else "string"] += 1
            else:
                scalars["null" if item is None else type(item).__name__] += 1
    node_bytes = sum(row["json_bytes"] for row in by_type.values())
    string_table_bytes = size(data["strings"])
    calculated = size(data)
    if calculated != raw_size:
        raise ValueError("independent wire byte arithmetic disagrees with actual serialization")
    return {"node_types": by_type, "node_count": len(data["nodes"]), "dictionary_pairs": pairs,
            "declared_fields": field_count, "references": references, "inline_scalars_and_keys": scalars,
            "string_table_count": len(data["strings"]), "string_table_json_bytes": string_table_bytes,
            "node_json_bytes": node_bytes, "envelope_and_nodes_array_bytes": raw_size - node_bytes - string_table_bytes,
            "calculated_exact_bytes": calculated, "visited_wire_values": visited,
            "simple_ref_array_savings_bytes": 4 * sum(references.values()),
            "flattened_dictionary_pair_savings_bytes": 2 * pairs,
            "payload_values_retained": False}


@contextmanager
def observe_final_dag(codec, observation):
    """Observe only the final exact DAG envelope; preserve original codec result."""
    original = codec._json
    observation.update(final_envelope_calls=0, wrapper_restored=False)
    def observed(value):
        final = (type(value) is dict and set(value) == {"schema_version", "strings", "nodes", "root"}
                 and value["schema_version"] == codec.DAG_SCHEMA_VERSION)
        if not final:
            return original(value)
        observation["final_envelope_calls"] += 1
        if observation["final_envelope_calls"] != 1:
            raise ValueError("more than one final DAG serialization observed")
        started = time.perf_counter()
        raw = original(value)
        observation["original_final_json_seconds"] = time.perf_counter() - started
        observation["original_wire"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                        "within_production_shard_bound": len(raw) <= codec.DEFAULT_MAX_SHARD_BYTES}
        try:
            if len(raw) > MAX_DIAGNOSTIC_BYTES or len(value["nodes"]) > codec.MAX_NODES:
                raise ValueError("diagnostic byte/node bound exceeded")
            started = time.perf_counter()
            observation["histogram"] = wire_histogram(value, len(raw), original)
            observation["histogram_seconds"] = time.perf_counter() - started
            started = time.perf_counter()
            compact = compact_dag(value, codec._FIELDS)
            observation["candidate_build_seconds"] = time.perf_counter() - started
            started = time.perf_counter()
            compact_raw = original(compact)
            observation["candidate_json_seconds"] = time.perf_counter() - started
            observation["candidate_wire"] = {"schema": CANDIDATE_SCHEMA, "bytes": len(compact_raw),
                "sha256": hashlib.sha256(compact_raw).hexdigest(),
                "within_production_shard_byte_count": len(compact_raw) <= codec.DEFAULT_MAX_SHARD_BYTES,
                "production_format_compatible": False}
            if len(compact_raw) > MAX_DIAGNOSTIC_BYTES:
                raise ValueError("diagnostic candidate byte bound exceeded")
            started = time.perf_counter()
            # Parse the actual candidate bytes, not its pre-serialization object.
            parsed = json.loads(compact_raw)
            restored = expand_compact_dag(parsed, codec._FIELDS, value["schema_version"])
            observation["candidate_parse_inverse_seconds"] = time.perf_counter() - started
            del compact, compact_raw, parsed
            started = time.perf_counter()
            restored_raw = original(restored)
            observation["inverse_json_seconds"] = time.perf_counter() - started
            observation["inverse_wire"] = {"bytes": len(restored_raw), "sha256": hashlib.sha256(restored_raw).hexdigest(),
                "exact_original_bytes_equal": restored_raw == raw}
            del restored, restored_raw
        except Exception as exc:
            observation["diagnostic_error"] = error_record(exc)
        return raw  # Existing report_to_bytes performs its unchanged rejection.
    codec._json = observed
    try:
        yield
    finally:
        codec._json = original
        observation["wrapper_restored"] = codec._json is original


def child_run(result):
    from audit_native_uscode_embedding_production import _deny_network
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_report_bundle as codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingConfig, TrainingJobSpec, _JOB_LOCK, _worker_environment, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import _bridge_report_telemetry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview
    from ipfs_datasets_py.logic.bridge.multiview import MultiViewLegalIRReport
    helper = base.dependencies()
    result["network_guard"] = _deny_network()
    if base.sha(helper.PRIOR) != helper.PRIOR_SHA:
        raise ValueError("frozen input-selection receipt changed")
    prior = base.read(helper.PRIOR)
    row = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]
    payload, worker = row["worker"]["job_spec"], row["worker"]
    job = TrainingJobSpec.from_dict(payload)
    if prior["passed"] is not True or job.canonical_sha256 != worker["job_spec_canonical_sha256"]:
        raise ValueError("invalid frozen source selection")
    worker_ref = {**row["completed"]["worker_receipt_artifact"], "path": str(Path(job.output_directory) / "receipt.json")}
    helper.verify_descriptor(worker_ref)
    if base.read(worker_ref["path"]) != worker:
        raise ValueError("hashed parent worker receipt changed")
    result["parent_worker_receipt"] = worker_ref
    helper.validate_config(payload)
    result["input_verification"] = verify_corpus_job_inputs(job)
    result["config_before"] = helper.config_probe(payload["training_config"])
    result["parent_receipt"] = {"path": str(helper.PRIOR), "sha256": helper.PRIOR_SHA}
    helper.verify_descriptor({"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES})
    table, adapter, samples = base.fixture(payload)
    sample = samples[3]
    if sample.sample_id != SAMPLE_ID or base.canonical(payload["validation_samples"][0]) != base.canonical(asdict(job.validation_samples[0])):
        raise ValueError("frozen fourth sample selection changed")
    result["selected_sample"] = {"sample_id": sample.sample_id, "record": payload["validation_samples"][0],
                                 "sample_json_sha256": hashlib.sha256(sample.to_json().encode()).hexdigest()}
    if result["config_before"]["target_timeout_seconds"] != 15.0:
        raise ValueError("original 15-second target timeout changed")
    config = TrainingConfig.from_dict(payload["training_config"])
    if not _JOB_LOCK.acquire(blocking=False):
        raise ValueError("another job is active")
    try:
        with _worker_environment():
            started = time.perf_counter()
            try:
                report = modal._evaluate_legal_ir_multiview_with_timeout(
                    evaluate_legal_ir_multiview, timeout_seconds=15.0, text=sample.text,
                    bridge_names=config.legal_ir_bridge_names, document_id=sample.sample_id, citation=sample.citation,
                    source=sample.source, source_embedding=sample.embedding_vector,
                    evaluate_provers=False, compiler_guidance=None, cache=False)
            except modal._LegalIRTargetTimeout as exc:
                result["bridge_report_telemetry"] = _bridge_report_telemetry(outer_timeout=exc)
                raise
            finally:
                result["native_generation_seconds"] = time.perf_counter() - started
            if type(report) is not MultiViewLegalIRReport:
                raise TypeError("native report unavailable")
            result["bridge_report_telemetry"] = _bridge_report_telemetry(report)
            result["complete_five_adapter_report"] = list(report.bridge_names) == base.BRIDGES and set(report.reports) == set(base.BRIDGES) and not report.failures
            observation = result["wire_observation"] = {}
            started = time.perf_counter()
            try:
                with observe_final_dag(codec, observation):
                    returned = codec.report_to_bytes(report)
                result["production_codec_returned_bytes"] = len(returned)
                del returned
            except codec.ReportBundleError as exc:
                result["production_codec_rejection"] = error_record(exc)
            finally:
                result["codec_call_seconds_including_diagnostic"] = time.perf_counter() - started
            del report
    finally:
        _JOB_LOCK.release()
        result["config_after"] = helper.config_probe(payload["training_config"])
        result["source_unchanged"] = base.canonical(result["config_before"]) == base.canonical(result["config_after"])
        result["input_verification_after"] = verify_corpus_job_inputs(job)
        result["checkpoint_source_unchanged"] = base.sha(helper.PINNED) == helper.PINNED_SHA
    result["passed"] = (result["source_unchanged"] and result["checkpoint_source_unchanged"]
        and result["complete_five_adapter_report"] and observation["wrapper_restored"]
        and observation["final_envelope_calls"] == 1 and "diagnostic_error" not in observation
        and observation.get("inverse_wire", {}).get("exact_original_bytes_equal") is True
        and result.get("production_codec_rejection", {}).get("message") == "encoded report exceeds shard byte bound")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ.update(base.ENVIRONMENT)
    output = args.output.resolve()
    if output.exists():
        parser.error("new evidence path required")
    result = {"schema": "single-native-report-wire-diagnostic-v1", "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "harness_sha256": base.sha(__file__),
        "frozen_dependency": {"path": str(HARNESS_PATH), "sha256": HARNESS_SHA}, "sample_id": SAMPLE_ID,
        "environment": base.ENVIRONMENT, "native_sample_count": 1, "native_timeout_seconds": 15.0,
        "outer_child_timeout_seconds": MAX_CHILD_SECONDS, "report_payload_persisted": False,
        "production_limits_changed": False, "checkpoint_loaded": False, "training_performed": False,
        "artifact_produced": False, "admitted": False, "native_daemon_qualified": False, "speed_claim": False,
        "pass_scope": "complete native report, observed unchanged production rejection, exact reversible diagnostic framing, stable inputs/source",
        "diagnostic_limits": {"serialized_bytes": MAX_DIAGNOSTIC_BYTES, "histogram_values": MAX_DIAGNOSTIC_VALUES},
        "timing_scope": "original native generation timeout; post-generation serializer/histogram/candidate timings diagnostic only"}
    started = time.perf_counter()
    try:
        if args.child:
            child_run(result)
        else:
            if args.directory is None:
                parser.error("--directory required")
            directory = args.directory.resolve()
            if directory.exists() or ROOT not in directory.parents:
                raise ValueError("fresh diagnostic directory under canonical checkout required")
            directory.mkdir(parents=True)
            source = directory / "profile_report_wire.py"
            with source.open("xb") as handle:
                handle.write(Path(__file__).read_bytes())
            child_output, log_path = directory / "child.json", directory / "process.log"
            with log_path.open("xb") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", "--output", str(child_output)],
                    cwd=ROOT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    result["child_exit"] = process.wait(timeout=MAX_CHILD_SECONDS)
                    result["outer_timeout"] = False
                except subprocess.TimeoutExpired:
                    result["outer_timeout"] = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        result["child_exit"] = process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        result["child_exit"] = process.wait()
            result["child"] = base.read(child_output) if child_output.exists() else {"passed": False, "error": {"type": "MissingChildReceipt"}}
            result["process_log"] = base.descriptor(log_path)
            result["child_receipt"] = base.descriptor(child_output) if child_output.exists() else None
            result["source_snapshot"] = base.descriptor(source)
            result["passed"] = result["child"].get("passed") is True and result["child_exit"] == 0 and not result["outer_timeout"]
    except BaseException as exc:
        result["error"] = error_record(exc)
    finally:
        result["elapsed_seconds"] = time.perf_counter() - started
        result["harness_unchanged"] = base.sha(__file__) == result["harness_sha256"] and base.sha(HARNESS_PATH) == HARNESS_SHA
        result["passed"] = result["passed"] and result["harness_unchanged"] and "error" not in result
        base.write(output, result)
    print(json.dumps({"receipt": str(output), "passed": result["passed"], "error": result.get("error")}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
