"""Prepare exact-source affine bridge inputs or probe a pinned teacher offline."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
CONFIG_SCHEMA = "gte-affine-bridge-preparation-config/v1"
MANIFEST_SCHEMA = "gte-affine-bridge-preparation-manifest/v1"
REFERENCES = ("rows_384", "corpus_audit", "tasks", "receipts_768", "teacher_checkpoint")
MAX_JSON_BYTES = 128 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_bridge_cli_" + name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _file(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _require(len(raw) <= MAX_JSON_BYTES, "bounded local file required")
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _tools(*names):
    return [_file(Path(__file__)), *[_file(HELPERS / (name + ".py")) for name in names]]


def _recheck(reader, inputs, tools):
    for entry in inputs:
        _, current = reader.read_pinned_json(entry["path"], expected_sha256=entry["sha256"],
                                             max_bytes=MAX_JSON_BYTES)
        _require(current == entry, "input file changed during operation")
    for entry in tools:
        _require(_file(entry["path"]) == entry, "implementation changed during operation")


def _output(path, inputs):
    output = Path(path).resolve()
    _require(not output.exists(), "fresh output directory required")
    for entry in inputs:
        _require(not Path(entry["path"]).is_relative_to(output), "output aliases an input namespace")
    for namespace in (HELPERS, REPOSITORY / "scripts/ops/autoencoder"):
        _require(not output.is_relative_to(namespace) and not namespace.is_relative_to(output),
                 "output aliases an implementation namespace")
    return output


def _write(path, value):
    raw = _raw(value)
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _publish(output, payloads, summary, *, reader, inputs, tools, recheck_teacher):
    _recheck(reader, inputs, tools)
    recheck_teacher()
    output.mkdir(parents=True, exist_ok=False)
    refs = [_write(output / name, value) for name, value in payloads.items()]
    refs.append(_write(output / "summary.json", summary))
    _recheck(reader, inputs, tools)
    recheck_teacher()
    manifest = {"schema": MANIFEST_SCHEMA, "operation": summary["operation"], "completed": True,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "inputs": inputs, "implementation_files": tools, "outputs": refs,
                "status": summary["status"], "training_executed": False,
                "teacher_qualified": False, "proof_authority": False}
    receipt = _write(output / "manifest.json", manifest)
    return {**summary, "output_directory": str(output), "manifest_sha256": receipt["sha256"]}


def _configuration(config_path, expected_sha256, reader):
    config, receipt = reader.read_pinned_json(Path(config_path).resolve(),
        expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "domain_id", "max_rows", "mode", "seed", *REFERENCES}
    _require(type(config) is dict and set(config) == fields, "closed bridge configuration required")
    _require(config["schema"] == CONFIG_SCHEMA and config["mode"] == "prepare",
             "bridge configuration admits preparation only")
    _require(type(config["max_rows"]) is int and 1 <= config["max_rows"] <= 4096,
             "bounded max_rows required")
    _require(type(config["seed"]) is int and 0 <= config["seed"] < 2**31, "invalid seed")
    _require(config["domain_id"] in ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir"),
             "unsupported domain")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute workspace_root required")
    root = root.resolve()
    payloads, inputs = {}, [receipt]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed input reference required")
        relative = Path(ref["path"])
        _require(not relative.is_absolute() and ".." not in relative.parts, "workspace-relative input required")
        path = (root / relative).resolve()
        _require(path.is_relative_to(root), "input outside workspace")
        payloads[name], captured = reader.read_pinned_json(path, expected_sha256=ref["sha256"],
                                                          max_bytes=MAX_JSON_BYTES)
        inputs.append(captured)
    return config, payloads, inputs


def prepare_bridge(config_path, *, expected_config_sha256, output_directory):
    tools = _tools("gte_worker_contract", "gte_bridge_pairs", "gte_bridge_teacher",
                   "gte_multilingual_corpus", "gte_transfer_corpus", "gte_migration_inventory")
    reader = _helper("gte_worker_contract")
    config, payloads, inputs = _configuration(config_path, expected_config_sha256, reader)
    output = _output(output_directory, inputs)
    teacher_helper = _helper("gte_bridge_teacher")
    teacher_path = inputs[-1]["path"]
    teacher_pin = config["teacher_checkpoint"]["sha256"]
    teacher = teacher_helper.inspect_teacher(teacher_path, expected_sha256=teacher_pin,
        domain_id=config["domain_id"], repository_root=REPOSITORY)
    pairs = _helper("gte_bridge_pairs").prepare_bridge_pairs(
        payloads["rows_384"], payloads["corpus_audit"], payloads["tasks"], payloads["receipts_768"],
        domain_id=config["domain_id"], max_rows=config["max_rows"])
    _require(pairs["source_vector_space_id"] == teacher["source_representation_id"],
             "paired source coordinates differ from teacher input convention")
    summary = {"schema": "gte-affine-bridge-preparation-summary/v1", "operation": "prepare",
               "status": pairs["status"], "domain_id": config["domain_id"],
               "pair_count": len(pairs["pairs"]), "pair_split_counts": pairs["split_counts"],
               "counts": pairs["counts"], "teacher_checkpoint_sha256": teacher_pin,
               "teacher_runtime_id": teacher["teacher_runtime_id"],
               "teacher_qualified": False, "teacher_model_loaded": False,
               "native_768d_inference_executed": False, "training_executed": False,
               "download_executed": False, "proof_authority": False}
    def recheck_teacher():
        _require(teacher_helper.inspect_teacher(teacher_path, expected_sha256=teacher_pin,
            domain_id=config["domain_id"], repository_root=REPOSITORY) == teacher,
            "teacher binding changed during preparation")
    return _publish(output, {"pairs.json": pairs, "teacher-binding.json": teacher}, summary,
                    reader=reader, inputs=inputs, tools=tools, recheck_teacher=recheck_teacher)


def probe_teacher(teacher_path, *, expected_teacher_sha256, output_directory, domain_id="legal_ir",
                  seed=1729, threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=120):
    # This operation belongs in its own subprocess: process resource limits are
    # applied before numerical imports and cannot be relaxed in this worker.
    started = time.monotonic()
    sys.dont_write_bytecode = True
    tools = _tools("gte_worker_contract", "gte_bridge_teacher", "gte_affine_bridge", "gte_migration_inventory")
    reader = _helper("gte_worker_contract")
    checkpoint, input_receipt = reader.read_pinned_json(Path(teacher_path).resolve(),
        expected_sha256=expected_teacher_sha256, max_bytes=MAX_JSON_BYTES)
    inputs = [input_receipt]
    output = _output(output_directory, inputs)
    _require(type(seed) is int and 0 <= seed < 2**31, "invalid seed")
    teacher_helper = _helper("gte_bridge_teacher")
    teacher = teacher_helper.inspect_teacher(input_receipt["path"], expected_sha256=expected_teacher_sha256,
        domain_id=domain_id, repository_root=REPOSITORY)
    resources = reader.configure_cpu_process({"device": "cpu", "threads": threads, "max_rows": 1,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    sys.path.insert(0, str(REPOSITORY))
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    # Capture caches in a separate fresh worker namespace, outside published
    # outputs. No target model or tokenizer is needed for this synthetic probe.
    cache = output.with_name(output.name + "-cache")
    _require(not cache.exists(), "fresh probe cache required")
    cache.mkdir(parents=True, exist_ok=False)
    os.environ.update(HF_HOME=str(cache / "huggingface"), XDG_CACHE_HOME=str(cache),
                      TORCH_HOME=str(cache / "torch"))
    from ipfs_datasets_py.logic.formalization.autoencoder.source_training_v2 import load_checkpoint
    import torch

    runtime = load_checkpoint(input_receipt["path"], expected_sha256=expected_teacher_sha256,
                              expected_domain=domain_id)
    numeric = _helper("gte_affine_bridge")
    bridge = numeric.create_affine_bridge(seed=seed)
    # Fixed, explicitly synthetic coordinates; no source embedding is invented.
    vector = [math.sin(index + 1) for index in range(768)]
    norm = math.hypot(*vector)
    vector = [value / norm for value in vector]
    data = torch.tensor([vector], dtype=torch.float32)
    prefix = torch.tensor([[1]], dtype=torch.long)  # BOS only, no target prefix.
    gradient = numeric.probe_gradient_flow(bridge, runtime.model, data,
        input_transform=teacher["input_transform"], decoder_tokens=prefix)
    packed = numeric.pack_bridge_checkpoint(bridge, seed=seed,
        domain_id=domain_id, teacher_runtime_id=teacher["teacher_runtime_id"],
        source_representation_id=teacher["source_representation_id"],
        student_representation_id=numeric.STUDENT_REPRESENTATION_ID,
        teacher_checkpoint_sha256=expected_teacher_sha256, input_transform=teacher["input_transform"])
    reloaded = numeric.load_bridge_checkpoint(packed,
        expected_source_representation_id=teacher["source_representation_id"],
        expected_student_representation_id=numeric.STUDENT_REPRESENTATION_ID,
        expected_teacher_checkpoint_sha256=expected_teacher_sha256,
        input_transform=teacher["input_transform"], expected_domain_id=domain_id,
        expected_teacher_runtime_id=teacher["teacher_runtime_id"])
    _require(all(torch.equal(value, reloaded.state_dict()[name]) for name, value in bridge.state_dict().items()),
             "bridge checkpoint reload differs")
    summary = {"schema": "gte-affine-bridge-preparation-summary/v1", "operation": "probe-teacher",
               "status": "passed_local_gradient_probe", "domain_id": domain_id,
               "teacher_checkpoint_sha256": expected_teacher_sha256,
               "teacher_model_loaded": True, "teacher_qualified": False,
               "probe_input_origin": "fixed_synthetic_unit_vector_not_encoder_output",
               "probe_vector_sha256": hashlib.sha256(_raw(vector)).hexdigest(),
               "decoder_prefix_policy": "bos_only_no_reference_target",
               "native_768d_inference_executed": False, "optimizer_steps": 0,
               "training_executed": False, "download_executed": False,
               "bridge_checkpoint_reloaded_exactly": True, "elapsed_seconds": time.monotonic() - started,
               "proof_authority": False}
    def recheck_teacher():
        _require(teacher_helper.inspect_teacher(input_receipt["path"], expected_sha256=expected_teacher_sha256,
            domain_id=domain_id, repository_root=REPOSITORY) == teacher, "teacher binding changed during probe")
    return _publish(output, {"teacher-binding.json": teacher, "gradient-probe.json": gradient,
                            "untrained-bridge.json": packed, "resources.json": resources}, summary,
                    reader=reader, inputs=inputs, tools=tools, recheck_teacher=recheck_teacher)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--config", required=True)
    prepare.add_argument("--expected-config-sha256", required=True)
    prepare.add_argument("--output-directory", required=True)
    probe = commands.add_parser("probe-teacher")
    probe.add_argument("--teacher-checkpoint", required=True)
    probe.add_argument("--expected-teacher-sha256", required=True)
    probe.add_argument("--domain-id", default="legal_ir")
    probe.add_argument("--output-directory", required=True)
    probe.add_argument("--seed", type=int, default=1729)
    probe.add_argument("--threads", type=int, default=1)
    probe.add_argument("--memory-limit-mib", type=int, default=16384)
    probe.add_argument("--cpu-time-limit-seconds", type=int, default=120)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "prepare":
            result = prepare_bridge(arguments.config, expected_config_sha256=arguments.expected_config_sha256,
                                    output_directory=arguments.output_directory)
        else:
            result = probe_teacher(arguments.teacher_checkpoint,
                expected_teacher_sha256=arguments.expected_teacher_sha256,
                domain_id=arguments.domain_id, output_directory=arguments.output_directory,
                seed=arguments.seed, threads=arguments.threads, memory_limit_mib=arguments.memory_limit_mib,
                cpu_time_limit_seconds=arguments.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 1 if result["status"] in ("partial", "unavailable") else 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

