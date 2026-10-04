"""Train new interfaces from an authenticated fitted boundary and learned heads.

Both completed source generations are byte-admitted before Torch loads. Missing
alignment or native inputs produce explicit preparation with zero updates.
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
SCHEMA = "gte-aligned-interface-training-config/v1"
REFERENCES = ("native_parent_manifest", "initialization", "donor_pins", "batch", "replay", "native_batch", "aligned_parent_manifest")
HELPER_NAMES = ("gte_decoder_interface_checkpoint", "gte_decoder_interface_training", "gte_worker_contract",
    "gte_decoder_native_batch", "gte_decoder_native_objective", "gte_decoder_transfer_batch",
    "gte_decoder_transfer_replay", "gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor",
    "gte_bridge_teacher", "gte_migration_inventory", "gte_affine_bridge", "gte_multilingual_corpus",
    "gte_transfer_corpus", "gte_embedding_reuse", "gte_aligned_interface_checkpoint",
    "gte_aligned_interface_training", "gte_aligned_decoder", "gte_aligned_decoder_contract",
    "gte_alignment_contract", "gte_affine_alignment", "gte_bridge_pairs")
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


def _module(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_gte_aligned_training_" + name, path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _reference_cli():
    return _module("run_gte_decoder_interface_training")


def _aligned_cli():
    return _module("prepare_gte_aligned_decoder")


def _aligned_parent(payloads, named_inputs, root, reader, native):
    return _module("gte_aligned_interface_parent").admit_aligned_parent(
        payloads, named_inputs, root, reader, native, _aligned_cli())


def run_aligned_decoder_interface_training(config_path, *, expected_config_sha256, output_directory,
                                   threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=120):
    _require(type(threads) is int and threads == 1, "one reserved CPU thread required")
    native = _native_cli()
    reader = native._helper("gte_worker_contract")
    budget = reader._resources({"device": "cpu", "threads": threads, "max_rows": 128,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    implementations = [native._file(reader, Path(__file__)),
        *[native._file(reader, Path(__file__).with_name(name + ".py")) for name in (
            "prepare_gte_decoder_native", "run_gte_decoder_interface_training",
            "prepare_gte_aligned_decoder", "gte_aligned_interface_parent")],
                       *[native._file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    config, payloads, inputs, root = _configuration(config_path, expected_config_sha256, reader, native)
    named_inputs = dict(zip(REFERENCES, inputs[1:]))
    closure, source_roots = _reference_cli()._parent(reader, native, payloads, named_inputs, root)
    aligned = _aligned_parent(payloads, named_inputs, root, reader, native)
    closure += aligned["closure"]
    source_roots += aligned["source_roots"]
    arguments = {"initialization": payloads["initialization"], "plan": payloads["native_batch"],
        "batch": payloads["batch"], "replay": payloads["replay"], "expected_donor_pins": payloads["donor_pins"]}
    plan = arguments["plan"]
    native_inspection = native._helper("gte_decoder_native_batch").inspect_decoder_native_batch(plan,
        arguments["initialization"], arguments["batch"], arguments["replay"], expected_donor_pins=arguments["expected_donor_pins"])
    arguments.update(aligned_checkpoint=aligned["checkpoint"], expected_alignment_file_pins=aligned["file_pins"])
    start_ready = aligned["checkpoint"] is not None
    ready = plan["status"] == "ready" and start_ready
    aligned_inspection = {"schema": "gte-aligned-interface-start-inspection/v1",
        "status": aligned["status"], "aligned_start_admitted": start_ready,
        "initialization_representation_id": plan["initialization_representation_id"],
        "aligned_representation_id": aligned["checkpoint"]["representation_id"] if start_ready else None,
        "alignment_file_pins": aligned["file_pins"], "inspection": aligned["inspection"]}
    output = native._output_directory(output_directory, [*inputs, *closure, *implementations], source_roots)
    native._recheck(reader, [*inputs, *closure, *implementations])
    result, resources, checkpoint_contract, numerical = None, None, None, None
    if config["mode"] == "train" and ready:
        resources = reader.configure_cpu_process(budget)
        numerical = native._helper("gte_aligned_interface_training")
        result = numerical.train_decoder_interfaces(plan, **{k: v for k, v in arguments.items() if k != "plan"},
            steps=config["steps"], learning_rate=config["learning_rate"], max_grad_norm=config["max_grad_norm"],
            head_weights=config["head_weights"])
        _require(type(result) is dict and set(result) == {"checkpoint", "report"}, "bounded trainer result required")
        checkpoint_contract = native._helper("gte_aligned_interface_checkpoint")
        checkpoint_contract.inspect_interface_checkpoint(result["checkpoint"], **arguments)
        _require(result["checkpoint"]["training_report"] == result["report"]
                 and type(result["report"]["optimizer_steps"]) is int
                 and result["report"]["optimizer_steps"] == config["steps"], "trained step count or report differs")
    executed = result is not None
    status = "trained_unqualified" if executed else "prepared" if ready else (
        "unavailable" if not start_ready or plan["status"] == "unavailable" else "partial")
    summary = {"schema": "gte-aligned-interface-training-summary/v1", "mode": config["mode"], "status": status,
        "native_batch_status": plan["status"], "plan_sha256": plan["plan_sha256"],
        "initialization_representation_id": plan["initialization_representation_id"],
        "trained_representation_id": result["checkpoint"]["representation_id"] if executed else None,
        "primary_start": "authenticated_aligned_generation", "planned_steps": config["steps"],
        "aligned_start_status": aligned["status"], "aligned_start_admitted": start_ready,
        "start_representation_id": aligned["checkpoint"]["representation_id"] if start_ready else None,
        "alignment_file_pins": aligned["file_pins"],
        "unavailable_reasons": (["alignment_fit_not_executed"] if not start_ready else []) +
            (["selected_native_inputs_missing"] if plan["status"] != "ready" else []),
        "aligned_start_unchanged": True,
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
    exports = [("native-inspection.json", native_inspection),
               ("aligned-start-inspection.json", aligned_inspection), ("summary.json", summary)]
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
        _require(type(verification) is dict and verification.get("schema") == "gte-aligned-interface-reload-verification/v1"
                 and verification.get("status") == "exact_trained_aligned_reload_verified_unqualified"
                 and verification.get("trained_representation_id") == saved["representation_id"]
                 and verification.get("initialization_representation_id") == plan["initialization_representation_id"]
                 and verification.get("start_representation_id") == aligned["checkpoint"]["representation_id"]
                 and verification.get("start_checkpoint_content_sha256") == checkpoint_contract.digest(aligned["checkpoint"])
                 and verification.get("start_model_state_sha256") == aligned["checkpoint"]["model_state_sha256"]
                 and verification.get("alignment_file_pins") == aligned["file_pins"]
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
    manifest = {"schema": "gte-aligned-interface-training-manifest/v1", "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "mode": config["mode"], "status": status,
        "inputs": inputs, "parent_closure": closure, "implementation_files": implementations, "outputs": outputs,
        "aligned_start_admitted": start_ready,
        "start_representation_id": summary["start_representation_id"],
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
        result = run_aligned_decoder_interface_training(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] in ("prepared", "trained_unqualified") else 1
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
