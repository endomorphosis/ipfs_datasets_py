"""Join cached native inputs to inherited decoder targets without re-encoding.

Preparation stays dependency-free. An explicitly selected probe mode may check
reference-loss gradients on a complete selected native batch; it never creates
an optimizer, updates tensors or executes an encoder.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
SCHEMA = "gte-decoder-native-preparation-config/v1"
REFERENCES = ("parent_manifest", "initialization", "donor_pins", "batch", "replay",
              "primary_training_archive", "primary_validation_archive", "legacy8_inputs", "receipts_768")
HELPER_NAMES = ("gte_worker_contract", "gte_decoder_native_batch", "gte_decoder_native_objective",
    "gte_decoder_transfer_batch", "gte_decoder_transfer_replay", "gte_decoder_reuse",
    "gte_decoder_warm_start", "gte_legacy8_decoder_donor", "gte_bridge_teacher",
    "gte_migration_inventory", "gte_affine_bridge", "gte_multilingual_corpus",
    "gte_transfer_corpus", "gte_embedding_reuse")
MAX_BYTES = 128 * 1024 * 1024
PARENT_SCHEMA = "gte-decoder-transfer-preparation-manifest/v1"
PARENT_OUTPUTS = {"batch.json", "replay.json", "teacher384-binding.json",
                  "legacy8-binding.json", "resources.json", "summary.json"}
FALSE_FLAGS = ("training_executed", "distillation_executed", "encoder_inference_executed",
               "download_executed", "teacher_qualified", "production_kd_eligible",
               "source_fidelity_qualified", "proof_authority")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_native_cli_" + name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def _file(reader, path):
    _, receipt, _ = reader._read_stable(path, max_bytes=MAX_BYTES)
    return receipt


def _recheck(reader, references):
    for ref in references:
        _require(_file(reader, ref["path"]) == ref, "input or implementation changed during native preparation")


def _relative(root, value):
    _require(type(value) is str and bool(value), "nonempty workspace-relative path required")
    path = Path(value)
    _require(not path.is_absolute() and ".." not in path.parts, "workspace-relative path required")
    resolved = (root / path).resolve()
    _require(resolved.is_relative_to(root), "input is outside the workspace")
    return resolved


def _configuration(path, expected_sha256, reader):
    config, captured = reader.read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "mode", "expected_asset_manifest_sha256", *REFERENCES}
    _require(type(config) is dict and set(config) == fields and config["schema"] == SCHEMA
             and config["mode"] in ("prepare", "probe"), "closed native preparation configuration required")
    _require(type(config["expected_asset_manifest_sha256"]) is str
             and re.fullmatch("[0-9a-f]{64}", config["expected_asset_manifest_sha256"]),
             "explicit selected native asset manifest SHA256 required")
    _require(type(config["workspace_root"]) is str, "absolute existing workspace root required")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute existing workspace root required")
    root = root.resolve()
    payloads, inputs = {}, [captured]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed pinned input reference required")
        payloads[name], receipt = reader.read_pinned_json(_relative(root, ref["path"]),
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        inputs.append(receipt)
    return config, payloads, inputs, root


def _parent(reader, payloads, configured_inputs, root):
    parent = payloads["parent_manifest"]
    flags = {"distillation_executed", "encoder_inference_executed", "training_executed",
             "production_kd_eligible", "proof_authority", "source_fidelity_qualified", "teacher_qualified"}
    fields = {"schema", "captured_at_utc", "completed", "status", "inputs",
              "implementation_files", "outputs", "optimizer_steps", *flags}
    _require(type(parent) is dict and set(parent) == fields and parent["schema"] == PARENT_SCHEMA
             and parent["completed"] is True and parent["status"] == "behavior_preserved_unqualified",
             "completed inherited-decoder replay parent required")
    _require(type(parent["optimizer_steps"]) is int and parent["optimizer_steps"] == 0
             and all(parent[name] is False for name in flags), "parent cannot claim training or qualification")
    admitted = []
    for key in ("inputs", "implementation_files"):
        refs = parent[key]
        _require(type(refs) is list and 1 <= len(refs) <= 128, "bounded parent source closure required")
        for ref in refs:
            _require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}
                     and type(ref["path"]) is str and type(ref["bytes"]) is int
                     and 0 <= ref["bytes"] <= MAX_BYTES, "closed parent file binding required")
            path = Path(ref["path"])
            _require(path.is_absolute() and path.resolve().is_relative_to(root), "parent source outside workspace")
            _require(_file(reader, path) == ref, "parent source closure changed")
            admitted.append(ref)
    _require(len({ref["path"] for ref in admitted}) == len(admitted), "duplicate parent source binding")
    outputs = parent["outputs"]
    _require(type(outputs) is list and len(outputs) == len(PARENT_OUTPUTS)
             and all(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"} for ref in outputs)
             and {ref["path"] for ref in outputs} == PARENT_OUTPUTS, "exact parent replay outputs required")
    parent_directory = Path(configured_inputs["parent_manifest"]["path"]).parent
    parent_outputs = {}
    for ref in outputs:
        _require(type(ref["bytes"]) is int and 0 <= ref["bytes"] <= MAX_BYTES,
                 "bounded parent output size required")
        actual = _file(reader, parent_directory / ref["path"])
        _require(actual["bytes"] == ref["bytes"] and actual["sha256"] == ref["sha256"],
                 "parent output closure changed")
        parent_outputs[ref["path"]] = actual
    for name, filename in (("batch", "batch.json"), ("replay", "replay.json")):
        _require(configured_inputs[name] == parent_outputs[filename], "configured transfer output differs from parent")
    for name in ("initialization", "donor_pins", "primary_training_archive", "legacy8_inputs"):
        _require(configured_inputs[name] in parent["inputs"], "configured archive or initialization differs from parent")
    return [*admitted, *parent_outputs.values()]


def _source_roots(reader, parent, root):
    ref = parent["inputs"][0]
    original, _ = reader.read_pinned_json(ref["path"], expected_sha256=ref["sha256"], max_bytes=1024 * 1024)
    original_refs = {"initialization", "donor_pins", "primary_checkpoint", "legacy8_checkpoint",
                     "primary_training_archive", "legacy8_inputs", "legacy8_inference"}
    source_keys = {"teacher384_repository_root", "legacy8_implementation_root"}
    fields = {"schema", "workspace_root", "mode", "max_rows_per_head", *source_keys, *original_refs}
    _require(type(original) is dict and set(original) == fields
             and original["schema"] == "gte-decoder-transfer-preparation-config/v1"
             and original["mode"] == "prepare", "authenticated original replay configuration required")
    _require(type(original["workspace_root"]) is str, "original absolute workspace root required")
    original_root = Path(original["workspace_root"])
    _require(original_root.is_absolute() and original_root.is_dir(), "original absolute workspace root required")
    roots = [_relative(original_root.resolve(), original[name]) for name in sorted(source_keys)]
    _require(all(path.is_dir() and path.is_relative_to(root) for path in roots),
             "original donor implementation roots must exist inside workspace")
    return roots


def _output_directory(path, references, source_roots):
    requested = Path(path).absolute()
    _require(not any(part.is_symlink() for part in (*requested.parents, requested)),
             "output namespace cannot contain symlinks")
    output = requested.resolve()
    _require(not output.exists(), "fresh output directory required")
    for namespace in (REPOSITORY, *source_roots, *(Path(ref["path"]).parent for ref in references)):
        _require(not output.is_relative_to(namespace) and not namespace.is_relative_to(output),
                 "output aliases an input or implementation namespace")
    return output


def _write(directory, name, value):
    raw = _raw(value)
    _require(len(raw) <= MAX_BYTES, "native preparation output exceeds byte limit")
    with (directory / name).open("xb") as stream:
        stream.write(raw)
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def prepare_decoder_native(config_path, *, expected_config_sha256, output_directory,
                           threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=120):
    _require(type(threads) is int and threads == 1, "one reserved CPU thread required")
    reader = _helper("gte_worker_contract")
    budget = reader._resources({"device": "cpu", "threads": threads, "max_rows": 128,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    implementations = [_file(reader, Path(__file__)),
                       *[_file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    config, payloads, inputs, root = _configuration(config_path, expected_config_sha256, reader)
    named_inputs = dict(zip(REFERENCES, inputs[1:]))
    closure = _parent(reader, payloads, named_inputs, root)
    source_roots = _source_roots(reader, payloads["parent_manifest"], root)
    contract = _helper("gte_decoder_native_batch")
    plan = contract.prepare_decoder_native_batch(payloads["initialization"], payloads["batch"], payloads["replay"],
        expected_donor_pins=payloads["donor_pins"], primary_training_archive=payloads["primary_training_archive"],
        primary_validation_archive=payloads["primary_validation_archive"], legacy8_inputs=payloads["legacy8_inputs"],
        receipts_768=payloads["receipts_768"], expected_asset_manifest_sha256=config["expected_asset_manifest_sha256"])
    inspection = contract.inspect_decoder_native_batch(plan, payloads["initialization"], payloads["batch"],
        payloads["replay"], expected_donor_pins=payloads["donor_pins"])
    output = _output_directory(output_directory, [*inputs, *closure, *implementations], source_roots)
    _recheck(reader, [*inputs, *closure, *implementations])
    probe, resources, numerical = None, None, None
    if config["mode"] == "probe" and plan["status"] == "ready":
        resources = reader.configure_cpu_process(budget)
        numerical = _helper("gte_decoder_native_objective")
        probe = numerical.probe_native_reference_gradients(plan,
            initialization=payloads["initialization"], batch=payloads["batch"], replay=payloads["replay"],
            expected_donor_pins=payloads["donor_pins"])
        _require(type(probe) is dict and type(probe.get("optimizer_steps")) is int
                 and probe["optimizer_steps"] == 0 and all(probe.get(name) is False for name in FALSE_FLAGS),
                 "native gradient probe cannot claim optimizer training or qualification")
        numerical.inspect_native_reference_probe(probe, plan, initialization=payloads["initialization"],
            batch=payloads["batch"], replay=payloads["replay"], expected_donor_pins=payloads["donor_pins"])
    summary = {"schema": "gte-decoder-native-preparation-summary/v1", "operation": "join-original-caches-to-native-inputs",
        "mode": config["mode"], "status": plan["status"], "plan_sha256": plan["plan_sha256"],
        "initialization_representation_id": plan["initialization_representation_id"],
        "selected_row_count": plan["selected_row_count"], "ready_row_count": plan["ready_row_count"],
        "missing_row_count": plan["missing_row_count"], "quarantined_row_count": plan["quarantined_row_count"],
        "task_count": plan["cache_reuse"]["task_count"],
        "cached_receipt_count": plan["cache_reuse"]["cached_receipt_count"],
        "missing_task_count": plan["cache_reuse"]["missing_task_count"],
        "full_task_cache_status": plan["cache_reuse"]["status"],
        "profile_id": plan["profile_id"], "asset_manifest_sha256": plan["asset_manifest_sha256"],
        "native_gradient_probe_executed": probe is not None, "native768_inputs_used": probe is not None,
        "optimizer_steps": 0, "existing_assets_and_embeddings_reused": True,
        "old_embeddings_regenerated": False, "source_vectors_relabelled": False,
        "original_decoder_initialization_unchanged": True, **{name: False for name in FALSE_FLAGS}}
    _recheck(reader, [*inputs, *closure, *implementations])
    output.mkdir(parents=True, exist_ok=False)
    exports = [("native-batch.json", plan), ("tasks.json", plan["task_manifest"]),
               ("missing-tasks.json", plan["cache_reuse"]["missing_tasks"]),
               ("receipts.json", plan["cache_reuse"]["reused_receipts"]),
               ("inspection.json", inspection), ("summary.json", summary)]
    if probe is not None:
        exports += [("resources.json", resources), ("probe.json", probe)]
    outputs = [_write(output, name, value) for name, value in exports]
    _recheck(reader, [*inputs, *closure, *implementations])
    for ref in outputs:
        _require(_file(reader, output / ref["path"]) == {**ref, "path": str(output / ref["path"])},
                 "native output changed before completion")
    saved_ref = next(ref for ref in outputs if ref["path"] == "native-batch.json")
    saved_plan, _ = reader.read_pinned_json(output / "native-batch.json",
        expected_sha256=saved_ref["sha256"], max_bytes=MAX_BYTES)
    saved_inspection = contract.inspect_decoder_native_batch(saved_plan, payloads["initialization"],
        payloads["batch"], payloads["replay"], expected_donor_pins=payloads["donor_pins"])
    _require(_raw(saved_inspection) == _raw(inspection), "saved native batch inspection differs")
    if probe is not None:
        probe_ref = next(ref for ref in outputs if ref["path"] == "probe.json")
        saved_probe, _ = reader.read_pinned_json(output / "probe.json",
            expected_sha256=probe_ref["sha256"], max_bytes=MAX_BYTES)
        numerical.inspect_native_reference_probe(saved_probe, saved_plan, initialization=payloads["initialization"],
            batch=payloads["batch"], replay=payloads["replay"], expected_donor_pins=payloads["donor_pins"])
    _recheck(reader, [*inputs, *closure, *implementations])
    for ref in outputs:
        _require(_file(reader, output / ref["path"]) == {**ref, "path": str(output / ref["path"])},
                 "native output changed after saved inspection")
    manifest = {"schema": "gte-decoder-native-preparation-manifest/v1", "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "mode": config["mode"], "status": summary["status"],
        "inputs": inputs, "parent_closure": closure, "implementation_files": implementations, "outputs": outputs,
        "optimizer_steps": 0, "native_gradient_probe_executed": probe is not None,
        "saved_native_batch_authenticated_and_reinspected": True, **{name: False for name in FALSE_FLAGS}}
    completion = _write(output, "manifest.json", manifest)
    return {**summary, "output_directory": str(output), "manifest_sha256": completion["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-limit-mib", type=int, default=16384)
    parser.add_argument("--cpu-time-limit-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        result = prepare_decoder_native(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] == "ready" else 1
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
