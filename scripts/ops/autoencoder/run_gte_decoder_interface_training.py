"""Prepare or run a bounded reference fit of four inherited-student interfaces.

The original decoder heads and checkpoint generations remain immutable. Missing
native inputs create an explicit preparation result with zero optimizer steps.
Actual training requires a ready pinned native batch and an explicit train mode.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
SCHEMA = "gte-decoder-interface-training-config/v1"
REFERENCES = ("native_parent_manifest", "initialization", "donor_pins", "batch", "replay", "native_batch")
HELPER_NAMES = ("gte_decoder_interface_checkpoint", "gte_decoder_interface_training", "gte_worker_contract",
    "gte_decoder_native_batch", "gte_decoder_native_objective", "gte_decoder_transfer_batch",
    "gte_decoder_transfer_replay", "gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor",
    "gte_bridge_teacher", "gte_migration_inventory", "gte_affine_bridge", "gte_multilingual_corpus",
    "gte_transfer_corpus", "gte_embedding_reuse")
MAX_BYTES = 128 * 1024 * 1024
FALSE_FLAGS = ("distillation_executed", "encoder_inference_executed", "download_executed", "teacher_qualified",
               "production_kd_eligible", "source_fidelity_qualified", "proof_authority")


def _native_cli():
    path = Path(__file__).with_name("prepare_gte_decoder_native.py")
    spec = importlib.util.spec_from_file_location("_gte_interface_native_cli", path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _controls(config):
    _require(type(config["steps"]) is int and 1 <= config["steps"] <= 64, "steps must be an integer from 1 to 64")
    for key, lower, upper in (("learning_rate", 1e-6, 1e-2), ("max_grad_norm", .01, 100.)):
        value = config[key]
        _require(type(value) in (int, float) and lower <= value <= upper and math.isfinite(value),
                 "finite bounded " + key + " required")
    weights = config["head_weights"]
    _require(type(weights) is dict and set(weights) == {"primary384", "legacy8"}, "separate head weights required")
    _require(all(type(value) in (int, float) and 0 < value <= 100 and math.isfinite(value)
                 for value in weights.values()), "both head weights must be finite, positive and bounded")


def _configuration(path, expected_sha256, reader, native):
    config, captured = reader.read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "mode", "steps", "learning_rate", "max_grad_norm", "head_weights", *REFERENCES}
    _require(type(config) is dict and set(config) == fields and config["schema"] == SCHEMA
             and config["mode"] in ("prepare", "train"), "closed interface training configuration required")
    _controls(config)
    _require(type(config["workspace_root"]) is str, "absolute existing workspace root required")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute existing workspace root required")
    root = root.resolve()
    payloads, inputs = {}, [captured]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed pinned input reference required")
        payloads[name], receipt = reader.read_pinned_json(native._relative(root, ref["path"]),
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        inputs.append(receipt)
    return config, payloads, inputs, root


def _parent(reader, native, payloads, named_inputs, root):
    parent = payloads["native_parent_manifest"]
    fields = {"schema", "captured_at_utc", "completed", "mode", "status", "inputs", "parent_closure",
        "implementation_files", "outputs", "optimizer_steps", "native_gradient_probe_executed",
        "saved_native_batch_authenticated_and_reinspected", "training_executed", *FALSE_FLAGS}
    _require(type(parent) is dict and set(parent) == fields
             and parent["schema"] == "gte-decoder-native-preparation-manifest/v1"
             and parent["completed"] is True and parent["mode"] in ("prepare", "probe")
             and parent["status"] in ("ready", "partial", "unavailable")
             and parent["saved_native_batch_authenticated_and_reinspected"] is True,
             "completed native input preparation parent required")
    _require(type(parent["optimizer_steps"]) is int and parent["optimizer_steps"] == 0
             and parent["training_executed"] is False and all(parent[name] is False for name in FALSE_FLAGS)
             and type(parent["native_gradient_probe_executed"]) is bool,
             "native parent cannot claim optimizer training or qualification")
    admitted = []
    for key in ("inputs", "parent_closure", "implementation_files"):
        refs = parent[key]
        _require(type(refs) is list and 1 <= len(refs) <= 128, "bounded native parent file closure required")
        for ref in refs:
            _require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}
                     and type(ref["path"]) is str and type(ref["bytes"]) is int
                     and 0 <= ref["bytes"] <= MAX_BYTES, "closed native parent file binding required")
            path = Path(ref["path"])
            _require(path.is_absolute() and path.resolve().is_relative_to(root), "native parent source outside workspace")
            _require(native._file(reader, path) == ref, "native parent source closure changed")
            admitted.append(ref)
    names = {"native-batch.json", "tasks.json", "missing-tasks.json", "receipts.json", "inspection.json", "summary.json"}
    if parent["native_gradient_probe_executed"]:
        _require(parent["mode"] == "probe" and parent["status"] == "ready", "native parent probe readiness differs")
        names |= {"resources.json", "probe.json"}
    refs = parent["outputs"]
    _require(type(refs) is list and len(refs) == len(names)
             and all(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"} for ref in refs)
             and {ref["path"] for ref in refs} == names, "exact native parent output closure required")
    directory = Path(named_inputs["native_parent_manifest"]["path"]).parent
    outputs = {}
    for ref in refs:
        _require(type(ref["bytes"]) is int and 0 <= ref["bytes"] <= MAX_BYTES, "bounded native parent output required")
        actual = native._file(reader, directory / ref["path"])
        _require(actual["bytes"] == ref["bytes"] and actual["sha256"] == ref["sha256"], "native parent output changed")
        outputs[ref["path"]] = actual
    _require(named_inputs["native_batch"] == outputs["native-batch.json"], "configured native batch differs from parent")
    for name in ("initialization", "donor_pins", "batch", "replay"):
        _require(named_inputs[name] in parent["inputs"], "configured donor or replay input differs from native parent")
    _require(payloads["native_batch"]["status"] == parent["status"], "native parent readiness differs from batch")
    original_ref = parent["inputs"][0]
    _, original_payloads, original_inputs, original_root = native._configuration(original_ref["path"],
        original_ref["sha256"], reader)
    _require(original_inputs == parent["inputs"], "native parent input closure differs from original configuration")
    closure = native._parent(reader, original_payloads, dict(zip(native.REFERENCES, original_inputs[1:])), original_root)
    _require(closure == parent["parent_closure"], "inherited decoder parent closure differs")
    roots = native._source_roots(reader, original_payloads["parent_manifest"], original_root)
    _require(all(path.is_relative_to(root) for path in roots), "original donor source root outside workspace")
    return [*admitted, *outputs.values()], roots


def run_decoder_interface_training(config_path, *, expected_config_sha256, output_directory,
                                   threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=120):
    _require(type(threads) is int and threads == 1, "one reserved CPU thread required")
    native = _native_cli()
    reader = native._helper("gte_worker_contract")
    budget = reader._resources({"device": "cpu", "threads": threads, "max_rows": 128,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    implementations = [native._file(reader, Path(__file__)), native._file(reader, Path(__file__).with_name("prepare_gte_decoder_native.py")),
                       *[native._file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    config, payloads, inputs, root = _configuration(config_path, expected_config_sha256, reader, native)
    closure, source_roots = _parent(reader, native, payloads, dict(zip(REFERENCES, inputs[1:])), root)
    arguments = {"initialization": payloads["initialization"], "plan": payloads["native_batch"],
        "batch": payloads["batch"], "replay": payloads["replay"], "expected_donor_pins": payloads["donor_pins"]}
    plan = arguments["plan"]
    native_inspection = native._helper("gte_decoder_native_batch").inspect_decoder_native_batch(plan,
        arguments["initialization"], arguments["batch"], arguments["replay"], expected_donor_pins=arguments["expected_donor_pins"])
    output = native._output_directory(output_directory, [*inputs, *closure, *implementations], source_roots)
    native._recheck(reader, [*inputs, *closure, *implementations])
    result, resources, checkpoint_contract, numerical = None, None, None, None
    if config["mode"] == "train" and plan["status"] == "ready":
        resources = reader.configure_cpu_process(budget)
        numerical = native._helper("gte_decoder_interface_training")
        result = numerical.train_decoder_interfaces(plan, **{k: v for k, v in arguments.items() if k != "plan"},
            steps=config["steps"], learning_rate=config["learning_rate"], max_grad_norm=config["max_grad_norm"],
            head_weights=config["head_weights"])
        _require(type(result) is dict and set(result) == {"checkpoint", "report"}, "bounded trainer result required")
        checkpoint_contract = native._helper("gte_decoder_interface_checkpoint")
        checkpoint_contract.inspect_interface_checkpoint(result["checkpoint"], **arguments)
        _require(result["checkpoint"]["training_report"] == result["report"]
                 and type(result["report"]["optimizer_steps"]) is int
                 and result["report"]["optimizer_steps"] == config["steps"], "trained step count or report differs")
    executed = result is not None
    status = "trained_unqualified" if executed else "prepared" if plan["status"] == "ready" else plan["status"]
    summary = {"schema": "gte-decoder-interface-training-summary/v1", "mode": config["mode"], "status": status,
        "native_batch_status": plan["status"], "plan_sha256": plan["plan_sha256"],
        "initialization_representation_id": plan["initialization_representation_id"],
        "trained_representation_id": result["checkpoint"]["representation_id"] if executed else None,
        "primary_start": "original_initialization", "planned_steps": config["steps"],
        "optimizer_steps": config["steps"] if executed else 0, "trained_checkpoint_count": int(executed),
        "selected_rows": plan["selected_row_count"], "ready_rows": plan["ready_row_count"], "missing_rows": plan["missing_row_count"],
        "original_decoder_initialization_unchanged": True, "inherited_decoder_tensor_count": 26,
        "trainable_interface_tensor_count": 4, "native768_inputs_used": executed,
        "training_executed": executed, "reference_supervised_training_executed": executed,
        "optimizer_resume_supported": False, "donor_optimizer_moments_used": False,
        "old_embeddings_regenerated": False, "source_vectors_relabelled": False,
        **{name: False for name in FALSE_FLAGS}}
    native._recheck(reader, [*inputs, *closure, *implementations])
    output.mkdir(parents=True, exist_ok=False)
    exports = [("native-inspection.json", native_inspection), ("summary.json", summary)]
    if executed:
        exports += [("resources.json", resources), ("trained-interfaces.json", result["checkpoint"]),
                    ("training-report.json", result["report"])]
    outputs = [native._write(output, name, value) for name, value in exports]
    native._recheck(reader, [*inputs, *closure, *implementations])
    for ref in outputs:
        _require(native._file(reader, output / ref["path"]) == {**ref, "path": str(output / ref["path"])},
                 "interface training output changed before completion")
    if executed:
        checkpoint_ref = next(ref for ref in outputs if ref["path"] == "trained-interfaces.json")
        saved, _ = reader.read_pinned_json(output / checkpoint_ref["path"], expected_sha256=checkpoint_ref["sha256"], max_bytes=MAX_BYTES)
        report_ref = next(ref for ref in outputs if ref["path"] == "training-report.json")
        saved_report, _ = reader.read_pinned_json(output / report_ref["path"], expected_sha256=report_ref["sha256"], max_bytes=MAX_BYTES)
        _require(native._raw(saved_report) == native._raw(saved["training_report"]), "saved checkpoint and training report differ")
        inspection = checkpoint_contract.inspect_interface_checkpoint(saved, **arguments)
        verification = numerical.verify_trained_interface_reload(saved, **arguments)
        _require(type(verification) is dict and verification.get("schema") == "gte-decoder-interface-reload-verification/v1"
                 and verification.get("status") == "exact_trained_reload_verified_unqualified"
                 and verification.get("trained_representation_id") == saved["representation_id"]
                 and verification.get("initialization_representation_id") == plan["initialization_representation_id"]
                 and verification.get("plan_sha256") == plan["plan_sha256"]
                 and verification.get("model_state_sha256") == saved["model_state_sha256"]
                 and verification.get("trained_reference_outputs_sha256") == saved_report["trained_reference_outputs_sha256"]
                 and verification.get("optimizer_created") is False
                 and type(verification.get("optimizer_steps")) is int and verification["optimizer_steps"] == 0
                 and verification.get("training_executed") is False
                 and all(verification.get(name) is False for name in FALSE_FLAGS)
                 and all(verification.get(name) is True for name in ("all_26_inherited_tensors_unchanged",
                     "all_30_reloaded_tensors_bitwise_equal", "private_storage_disjoint", "trained_reference_outputs_match",
                     "original_inputs_unchanged")), "saved trained checkpoint reload verification failed")
        outputs += [native._write(output, "checkpoint-inspection.json", inspection),
                    native._write(output, "reload-verification.json", verification)]
    native._recheck(reader, [*inputs, *closure, *implementations])
    for ref in outputs:
        _require(native._file(reader, output / ref["path"]) == {**ref, "path": str(output / ref["path"])},
                 "interface training output changed after reload verification")
    manifest = {"schema": "gte-decoder-interface-training-manifest/v1", "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "mode": config["mode"], "status": status,
        "inputs": inputs, "parent_closure": closure, "implementation_files": implementations, "outputs": outputs,
        "optimizer_steps": summary["optimizer_steps"], "training_executed": executed,
        "trained_checkpoint_count": int(executed), "saved_trained_checkpoint_authenticated_and_replayed": executed,
        **{name: False for name in FALSE_FLAGS}}
    completion = native._write(output, "manifest.json", manifest)
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
        result = run_decoder_interface_training(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] in ("prepared", "trained_unqualified") else 1
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
