"""Replay inherited decoder knowledge on its original cached training inputs.

This bounded preparation exports separate reference-prefix teacher distributions
and verifies copied student heads before fitting their new interfaces. No native
768D inputs, encoder execution, optimizer updates or KD fitting occur here.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
SCHEMA = "gte-decoder-transfer-preparation-config/v1"
REFERENCES = ("initialization", "donor_pins", "primary_checkpoint", "legacy8_checkpoint",
              "primary_training_archive", "legacy8_inputs", "legacy8_inference")
SOURCE_ROOTS = ("teacher384_repository_root", "legacy8_implementation_root")
HELPER_NAMES = ("gte_worker_contract", "gte_decoder_transfer_batch", "gte_decoder_transfer_replay",
    "gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor",
    "gte_bridge_teacher", "gte_migration_inventory", "gte_affine_bridge")
MAX_BYTES = 128 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_transfer_cli_" + name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def _file(reader, path):
    _, receipt, _ = reader._read_stable(path, max_bytes=MAX_BYTES)
    return receipt


def _recheck(reader, receipts):
    for ref in receipts:
        _require(_file(reader, ref["path"]) == ref, "input or implementation changed during decoder transfer")


def _relative(root, value):
    _require(type(value) is str and bool(value), "nonempty workspace-relative path required")
    relative = Path(value)
    _require(not relative.is_absolute() and ".." not in relative.parts, "workspace-relative path required")
    resolved = (root / relative).resolve()
    _require(resolved.is_relative_to(root), "input is outside the workspace")
    return resolved


def _configuration(path, expected_sha256, reader):
    config, captured = reader.read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "mode", "max_rows_per_head", *SOURCE_ROOTS, *REFERENCES}
    _require(type(config) is dict and set(config) == fields and config["schema"] == SCHEMA
             and config["mode"] == "prepare", "closed preparation-only transfer configuration required")
    _require(type(config["max_rows_per_head"]) is int and 1 <= config["max_rows_per_head"] <= 64,
             "max_rows_per_head must be between 1 and 64")
    _require(type(config["workspace_root"]) is str, "absolute existing workspace root required")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute existing workspace root required")
    root = root.resolve()
    roots = {name: _relative(root, config[name]) for name in SOURCE_ROOTS}
    _require(all(path.is_dir() for path in roots.values()), "existing pinned source roots required")
    payloads, inputs = {}, [captured]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed pinned input reference required")
        payloads[name], receipt = reader.read_pinned_json(_relative(root, ref["path"]),
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        inputs.append(receipt)
    return config, payloads, inputs, roots


def _output(path, inputs, roots):
    requested = Path(path).absolute()
    _require(not any(part.is_symlink() for part in (*requested.parents, requested)),
             "output namespace cannot contain symlinks")
    output = requested.resolve()
    _require(not output.exists(), "fresh output directory required")
    for namespace in (REPOSITORY, *roots.values(), *(Path(ref["path"]).parent for ref in inputs)):
        _require(not output.is_relative_to(namespace) and not namespace.is_relative_to(output),
                 "output aliases an input or implementation namespace")
    return output


def _write(directory, name, value):
    raw = _raw(value)
    with (directory / name).open("xb") as stream:
        stream.write(raw)
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def prepare_decoder_transfer(config_path, *, expected_config_sha256, output_directory,
                             threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=120):
    _require(type(threads) is int and threads == 1, "one reserved CPU thread required")
    reader = _helper("gte_worker_contract")
    tools = [_file(reader, Path(__file__)), *[_file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    config, payloads, inputs, roots = _configuration(config_path, expected_config_sha256, reader)
    configured_inputs = list(inputs)
    refs = dict(zip(REFERENCES, configured_inputs[1:]))
    pins = payloads["donor_pins"]
    _helper("gte_decoder_reuse").inspect_dual_decoder(payloads["initialization"], expected_donor_pins=pins)
    _require(refs["primary_checkpoint"]["sha256"] == pins["teacher384_checkpoint_sha256"]
             and refs["legacy8_checkpoint"]["sha256"] == pins["legacy8_checkpoint_sha256"],
             "configured donor files differ from initialization pins")
    primary = _helper("gte_bridge_teacher").inspect_teacher(refs["primary_checkpoint"]["path"],
        expected_sha256=pins["teacher384_checkpoint_sha256"], domain_id="legal_ir",
        repository_root=roots["teacher384_repository_root"])
    legacy = _helper("gte_legacy8_decoder_donor").inspect_legacy8_decoder_donor(refs["legacy8_checkpoint"]["path"],
        expected_sha256=pins["legacy8_checkpoint_sha256"], implementation_root=roots["legacy8_implementation_root"])
    _require(primary["weights_sha256"] == pins["teacher384_weights_sha256"]
             and primary["codec_sha256"] == pins["teacher384_codec_sha256"]
             and legacy["model_state_sha256"] == pins["legacy8_weights_sha256"]
             and legacy["codec_sha256"] == pins["legacy8_codec_sha256"], "admitted donor weights or codecs differ")
    for ref in [*primary["sources"], *legacy["implementation_files"]]:
        receipt = {name: ref[name] for name in ("path", "bytes", "sha256")}
        _require(_file(reader, receipt["path"]) == receipt, "donor source changed during admission")
        inputs.append(receipt)
    batch = _helper("gte_decoder_transfer_batch").prepare_decoder_transfer_batch(payloads["initialization"],
        expected_donor_pins=pins, primary_checkpoint=payloads["primary_checkpoint"],
        primary_archive=payloads["primary_training_archive"], legacy8_checkpoint=payloads["legacy8_checkpoint"],
        legacy8_inputs=payloads["legacy8_inputs"], legacy8_inference=payloads["legacy8_inference"],
        max_rows_per_head=config["max_rows_per_head"])
    output = _output(output_directory, inputs, roots)
    _recheck(reader, [*inputs, *tools])
    resources = reader.configure_cpu_process({"device": "cpu", "threads": threads, "max_rows": 128,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    numeric = _helper("gte_decoder_transfer_replay")
    replay = numeric.export_decoder_transfer_batch(payloads["initialization"], batch,
        expected_donor_pins=pins, primary_checkpoint=payloads["primary_checkpoint"],
        legacy8_checkpoint=payloads["legacy8_checkpoint"])
    _require(replay["status"] == "behavior_preserved_unqualified", "copied decoder behavior was not preserved")
    _require(replay["batch_sha256"] == batch["batch_sha256"]
             and replay["original_decoder_initialization_unchanged"] is True
             and replay["all_26_inherited_tensors_unchanged"] is True,
             "replay batch or inherited state evidence differs")
    _require(all(replay[name] is False for name in ("input_adapter_exercised", "auxiliary_connector_exercised",
        "native768_inputs_used", "encoder_inference_executed", "training_executed", "distillation_executed",
        "teacher_qualified", "production_kd_eligible", "proof_authority"))
        and type(replay["optimizer_steps"]) is int and replay["optimizer_steps"] == 0,
        "decoder replay cannot claim native interface fitting or KD")
    numeric.inspect_decoder_transfer_replay(replay, batch, initialization=payloads["initialization"],
                                           expected_donor_pins=pins)
    summary = {"schema": "gte-decoder-transfer-summary/v1", "status": replay["status"],
        "operation": "replay-inherited-decoder-knowledge", "batch_sha256": batch["batch_sha256"],
        "initialization_representation_id": batch["initialization_representation_id"],
        "primary384_rows": batch["heads"]["primary384"]["selected_row_count"],
        "legacy8_rows": batch["heads"]["legacy8"]["selected_row_count"],
        "copied_decoder_tensor_count": 26, "decoder_parameters_random": False,
        "archived_inputs_reused": True, "raw_8d_latents_reconstructed_from_original_cache": True,
        "original_decoder_initialization_unchanged": True, "all_26_inherited_tensors_unchanged": True,
        "input_adapter_exercised": False, "auxiliary_connector_exercised": False,
        "native768_inputs_used": False, "encoder_inference_executed": False,
        "optimizer_steps": 0, "training_executed": False, "distillation_executed": False,
        "teacher_qualified": False, "production_kd_eligible": False,
        "download_executed": False, "source_fidelity_qualified": False, "proof_authority": False}
    _recheck(reader, [*inputs, *tools])
    output.mkdir(parents=True, exist_ok=False)
    outputs = [_write(output, name, value) for name, value in (
        ("batch.json", batch), ("teacher384-binding.json", primary), ("legacy8-binding.json", legacy),
        ("replay.json", replay), ("resources.json", resources), ("summary.json", summary))]
    _recheck(reader, [*inputs, *tools])
    for ref in outputs:
        current = _file(reader, output / ref["path"])
        _require(current["bytes"] == ref["bytes"] and current["sha256"] == ref["sha256"],
                 "decoder transfer output changed before completion")
    saved = {}
    for name in ("batch.json", "replay.json"):
        ref = next(ref for ref in outputs if ref["path"] == name)
        saved[name], _ = reader.read_pinned_json(output / name, expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
    numeric.inspect_decoder_transfer_replay(saved["replay.json"], saved["batch.json"],
        initialization=payloads["initialization"], expected_donor_pins=pins)
    _recheck(reader, [*inputs, *tools])
    manifest = {"schema": "gte-decoder-transfer-preparation-manifest/v1", "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "status": summary["status"],
        "inputs": inputs, "implementation_files": tools, "outputs": outputs,
        "encoder_inference_executed": False, "optimizer_steps": 0, "training_executed": False,
        "distillation_executed": False, "teacher_qualified": False, "production_kd_eligible": False,
        "source_fidelity_qualified": False, "proof_authority": False}
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
        result = prepare_decoder_transfer(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
