"""Create a private dual-donor 768-input student and probe its new interfaces.

Run this CPU-only operation in a separate process: resource limits are applied
before numerical imports and cannot be relaxed. The probe uses one synthetic
unit vector and BOS tokens. It never embeds source text, fits weights or performs
knowledge distillation. Decoder alignment and source fidelity remain pending.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
MAX_BYTES = 64 * 1024 * 1024
MANIFEST_SCHEMA = "gte-decoder-reuse-preparation-manifest/v1"
_INTERFACES = ("primary.input_adapter.weight", "primary.input_adapter.bias",
               "auxiliary_connector.weight", "auxiliary_connector.bias")
_HELPER_NAMES = ("gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor",
                 "gte_bridge_teacher", "gte_affine_bridge", "gte_worker_contract", "gte_migration_inventory")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_decoder_reuse_cli_" + name,
                                                HELPERS / (name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load decoder preparation helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode()


def _file(reader, path):
    _, receipt, _ = reader._read_stable(path, max_bytes=MAX_BYTES)
    return receipt


def _recheck(reader, receipts):
    for receipt in receipts:
        _, current, _ = reader._read_stable(receipt["path"], expected_sha256=receipt["sha256"], max_bytes=MAX_BYTES)
        _require(current == receipt, "pinned file changed during initialization")


def _output(path, inputs, source_roots):
    requested = Path(path).absolute()
    for component in (*requested.parents, requested):
        _require(not component.is_symlink(), "output namespace cannot contain symlinks")
    output = requested.resolve()
    _require(not output.exists(), "fresh output directory required")
    for receipt in inputs:
        _require(not Path(receipt["path"]).is_relative_to(output), "output aliases an input namespace")
    namespaces = [HELPERS, REPOSITORY / "scripts/ops/autoencoder"]
    # An explicitly selected source archive must remain an immutable input.
    namespaces.extend(Path(root).resolve() for root in source_roots if root is not None
                      and Path(root).resolve() != REPOSITORY)
    for namespace in namespaces:
        _require(not output.is_relative_to(namespace) and not namespace.is_relative_to(output),
                 "output aliases an implementation namespace")
    return output


def _write(reader, output, filename, payload):
    receipt = reader.write_fresh_output_json(output, filename, payload)
    return {"path": filename, "bytes": receipt["bytes"], "sha256": receipt["sha256"]}


def _synthetic_inputs():
    import torch
    values = [math.sin(index + 1) for index in range(768)]
    vectors = torch.tensor([values], dtype=torch.float32, device="cpu")
    vectors = vectors / torch.linalg.vector_norm(vectors, dim=1, keepdim=True)
    prefix = torch.tensor([[1]], dtype=torch.int64, device="cpu")
    return vectors, prefix


def _probe_model(model, reuse):
    """Check gradient connectivity without .backward(), an optimizer or updates."""
    import torch
    parameters = dict(model.named_parameters())
    _require({name for name, parameter in parameters.items() if parameter.requires_grad} == set(_INTERFACES),
             "both learned decoder heads must be frozen; only new interfaces are trainable")
    _require(all(parameter.device.type == "cpu" and parameter.dtype == torch.float32
                 for parameter in parameters.values()), "CPU float32 decoder parameters required")
    before = {name: value.detach().clone() for name, value in model.state_dict().items()}
    modes = {name: module.training for name, module in model.named_modules()}
    grad_before = {name: None if parameter.grad is None else parameter.grad.detach().clone()
                   for name, parameter in parameters.items()}
    rng_before = torch.get_rng_state().clone()
    vectors, prefix = _synthetic_inputs()
    result = model(vectors, prefix, prefix)
    _require(set(result) == {"primary_logits", "auxiliary_logits", "shared_condition", "auxiliary_latent"},
             "closed dual-decoder forward result required")
    _require(all(bool(torch.isfinite(value).all()) for value in result.values()), "nonfinite synthetic model output")
    # Auxiliary loss must reach the PRIMARY adapter through the shared condition.
    loss = result["auxiliary_logits"].square().mean()
    _require(bool(torch.isfinite(loss)), "nonfinite auxiliary connectivity objective")
    gradients = torch.autograd.grad(loss, [parameters[name] for name in _INTERFACES],
                                    allow_unused=False, create_graph=False, retain_graph=False)
    norms = {}
    for name, gradient in zip(_INTERFACES, gradients):
        _require(bool(torch.isfinite(gradient).all()), "nonfinite new-interface gradient")
        norm = float(torch.linalg.vector_norm(gradient.to(dtype=torch.float64)))
        maximum = float(gradient.abs().max())
        _require(math.isfinite(norm) and norm > 0 and maximum > 0,
                 "auxiliary loss failed to reach a new interface: " + name)
        norms[name] = {"l2_norm": norm, "max_abs": maximum, "finite": True, "nonzero": True}
    _require(set(before) == set(model.state_dict()) and all(torch.equal(value, model.state_dict()[name])
             for name, value in before.items()), "model weights changed during connectivity probe")
    _require(modes == {name: module.training for name, module in model.named_modules()},
             "model modes changed during connectivity probe")
    _require(torch.equal(rng_before, torch.get_rng_state()), "process CPU RNG changed during probe")
    _require(all((parameter.grad is None and grad_before[name] is None) or
                 (parameter.grad is not None and grad_before[name] is not None
                  and torch.equal(parameter.grad, grad_before[name])) for name, parameter in parameters.items()),
             "parameter gradient buffers changed during connectivity probe")
    result_digests = {name: reuse.digest(value.detach().tolist()) for name, value in result.items()}
    return {"schema": "gte-dual-donor-synthetic-gradient-probe/v1", "status": "passed",
        "probe_input_origin": "fixed_synthetic_unit_vector_not_encoder_output", "input_rows": 1,
        "input_dimension": 768, "input_dtype": "float32", "input_device": "cpu",
        "input_l2_norm": float(torch.linalg.vector_norm(vectors)), "input_sha256": reuse.digest(vectors.tolist()),
        "decoder_prefix_policy": "bos_only_no_reference_target", "primary_prefix": [[1]], "auxiliary_prefix": [[1]],
        "gradient_objective": "auxiliary_logits_squared_mean_connectivity_only", "objective_value": float(loss.detach()),
        "gradient_groups": norms, "auxiliary_loss_reaches_shared_primary_boundary": True,
        "result_shapes": {name: list(value.shape) for name, value in result.items()},
        "result_sha256": result_digests, "all_model_weights_unchanged": True,
        "inherited_heads_frozen": True, "process_cpu_rng_unchanged": True, "gradient_buffers_unchanged": True,
        "optimizer_steps": 0, "encoder_inference_executed": False, "training_executed": False,
        "distillation_executed": False, "source_fidelity_qualified": False, "proof_authority": False}, before


def _verify_reload(original, restored, before, reuse):
    import torch
    _require(set(before) == set(restored.state_dict()) == set(original.state_dict()), "reloaded tensor names differ")
    _require(all(torch.equal(value, restored.state_dict()[name]) and torch.equal(value, original.state_dict()[name])
                 for name, value in before.items()), "saved student initialization did not reload exactly")
    _require(all(restored.state_dict()[name].data_ptr() != original.state_dict()[name].data_ptr()
                 for name in before), "reloaded student aliases original tensor storage")
    _require({name: parameter.requires_grad for name, parameter in original.named_parameters()}
             == {name: parameter.requires_grad for name, parameter in restored.named_parameters()},
             "reloaded inherited freeze mode differs")
    vectors, prefix = _synthetic_inputs()
    with torch.inference_mode():
        first, second = original(vectors, prefix, prefix), restored(vectors, prefix, prefix)
    _require(set(first) == set(second) and all(torch.equal(value, second[name]) for name, value in first.items()),
             "saved initialization outputs did not reload exactly")
    return {"saved_bytes_authenticated_before_load": True, "all_state_tensors_equal": True,
        "all_output_tensors_equal": True, "tensor_storage_independent": True, "freeze_mode_equal": True,
        "result_sha256": {name: reuse.digest(value.tolist()) for name, value in second.items()}}


def prepare_decoder_reuse(teacher384_path, legacy8_path, *, expected_teacher384_sha256,
                          expected_legacy8_sha256, output_directory, repository_root=None,
                          legacy_implementation_root=None, bridge_checkpoint_path=None,
                          expected_bridge_sha256=None, seed=1729, threads=1,
                          memory_limit_mib=16384, cpu_time_limit_seconds=120):
    """Create an initialization artifact and bounded synthetic evidence offline."""
    started = time.monotonic()
    sys.dont_write_bytecode = True
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded integer seed required")
    _require((bridge_checkpoint_path is None) == (expected_bridge_sha256 is None),
             "bridge path and expected digest must be supplied together")
    reader = _helper("gte_worker_contract")
    reuse = _helper("gte_decoder_reuse")
    tools = [_file(reader, Path(__file__)), *[_file(reader, HELPERS / (name + ".py")) for name in _HELPER_NAMES]]
    inputs = []
    for path, pin in ((teacher384_path, expected_teacher384_sha256), (legacy8_path, expected_legacy8_sha256)):
        _, receipt = reader.read_pinned_json(path, expected_sha256=pin, max_bytes=MAX_BYTES)
        inputs.append(receipt)
    if bridge_checkpoint_path is not None:
        _, receipt = reader.read_pinned_json(bridge_checkpoint_path, expected_sha256=expected_bridge_sha256,
                                            max_bytes=MAX_BYTES)
        inputs.append(receipt)
    output = _output(output_directory, inputs, (repository_root, legacy_implementation_root))
    # Inspect the complete donor closures before importing Torch or lowering limits.
    teacher = reuse._PRIMARY._TEACHER.inspect_teacher(teacher384_path, expected_sha256=expected_teacher384_sha256,
        domain_id="legal_ir", repository_root=repository_root)
    legacy = reuse._LEGACY.inspect_legacy8_decoder_donor(legacy8_path, expected_sha256=expected_legacy8_sha256,
                                                         implementation_root=legacy_implementation_root)
    source_inputs = [{key: receipt[key] for key in ("path", "bytes", "sha256")}
                     for receipt in [*teacher["sources"], *legacy["implementation_files"]]]
    by_path = {}
    for receipt in [*inputs, *source_inputs]:
        _require(receipt["path"] not in by_path or by_path[receipt["path"]] == receipt,
                 "one input path has conflicting pins")
        by_path[receipt["path"]] = receipt
    inputs = sorted(by_path.values(), key=lambda receipt: receipt["path"])
    _output(output, inputs, (repository_root, legacy_implementation_root))
    resources = reader.configure_cpu_process({"device": "cpu", "threads": threads, "max_rows": 1,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    model, bundle = reuse.create_dual_decoder(teacher384_path, legacy8_path,
        expected_teacher384_sha256=expected_teacher384_sha256, expected_legacy8_sha256=expected_legacy8_sha256,
        repository_root=repository_root, legacy_implementation_root=legacy_implementation_root, seed=seed,
        bridge_checkpoint_path=bridge_checkpoint_path, expected_bridge_sha256=expected_bridge_sha256)
    pins = bundle["donor_pins"]
    _require(pins["teacher384_weights_sha256"] == teacher["weights_sha256"]
             and pins["teacher384_codec_sha256"] == teacher["codec_sha256"]
             and pins["legacy8_weights_sha256"] == legacy["model_state_sha256"]
             and pins["legacy8_codec_sha256"] == legacy["codec_sha256"], "copied donors differ from inspected closures")
    inspection = reuse.inspect_dual_decoder(bundle, expected_donor_pins=pins)
    probe, before = _probe_model(model, reuse)
    _recheck(reader, [*inputs, *tools])
    output.mkdir(parents=True, exist_ok=False)
    refs = [_write(reader, output, "student-initialization.json", bundle),
            _write(reader, output, "donor-pins.json", pins)]
    saved, _ = reader.read_pinned_json(output / refs[0]["path"], expected_sha256=refs[0]["sha256"], max_bytes=MAX_BYTES)
    saved_pins, _ = reader.read_pinned_json(output / refs[1]["path"], expected_sha256=refs[1]["sha256"], max_bytes=1024 * 1024)
    _require(saved_pins == pins, "saved external donor pins differ")
    restored = reuse.load_dual_decoder(saved, expected_donor_pins=saved_pins)
    probe["exact_saved_reload"] = _verify_reload(model, restored, before, reuse)
    refs.extend((_write(reader, output, "inspection.json", inspection),
                 _write(reader, output, "gradient-probe.json", probe),
                 _write(reader, output, "resources.json", resources)))
    summary = {"schema": "gte-decoder-reuse-preparation-summary/v1", "operation": "initialize-and-probe",
        "status": "initialized_unaligned", "dimension": 768, "representation_id": bundle["representation_id"],
        "copied_parameter_count": inspection["copied_parameter_count"],
        "primary_copied_tensor_count": inspection["primary_copied_tensor_count"],
        "legacy8_copied_tensor_count": inspection["legacy8_copied_tensor_count"],
        "new_boundary_parameter_count": inspection["new_boundary_parameter_count"],
        "new_auxiliary_connector_parameter_count": inspection["new_auxiliary_connector_parameter_count"],
        "decoder_parameters_random": False, "boundary_alignment_required": True,
        "both_inherited_heads_frozen": True, "separate_vocabularies": True, "optimizer_state": None,
        "optimizer_steps": 0, "synthetic_gradient_probe_passed": True, "exact_saved_reload_passed": True,
        "auxiliary_loss_reaches_shared_primary_boundary": True, "all_model_weights_unchanged": True,
        "teacher384_source_closure_verified": True,
        "legacy8_source_closure_verified": legacy["implementation_files_verified"],
        "probe_input_origin": probe["probe_input_origin"], "primary_max_target_tokens": inspection["primary_max_target_tokens"],
        "auxiliary_max_target_tokens": inspection["auxiliary_max_target_tokens"],
        "encoder_inference_executed": False, "encoder_numerics_verified": False, "training_executed": False,
        "distillation_executed": False, "download_executed": False, "source_fidelity_qualified": False,
        "proof_authority": False, "elapsed_seconds": time.monotonic() - started}
    refs.append(_write(reader, output, "summary.json", summary))
    _recheck(reader, [*inputs, *tools])
    for receipt in refs:
        _, actual, _ = reader._read_stable(output / receipt["path"], expected_sha256=receipt["sha256"], max_bytes=MAX_BYTES)
        _require(actual["bytes"] == receipt["bytes"], "output changed before completion manifest")
    manifest = {"schema": MANIFEST_SCHEMA, "operation": summary["operation"], "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "status": summary["status"],
        "inputs": inputs, "implementation_files": tools, "outputs": refs, "donor_pins": pins,
        "decoder_parameters_random": False, "boundary_alignment_required": True,
        "encoder_inference_executed": False, "training_executed": False, "distillation_executed": False,
        "source_fidelity_qualified": False, "proof_authority": False}
    completion = _write(reader, output, "manifest.json", manifest)
    return {**summary, "output_directory": str(output), "manifest_sha256": completion["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher384", required=True)
    parser.add_argument("--teacher384-sha256", required=True)
    parser.add_argument("--legacy8", required=True)
    parser.add_argument("--legacy8-sha256", required=True)
    parser.add_argument("--repository-root")
    parser.add_argument("--legacy-implementation-root")
    parser.add_argument("--bridge")
    parser.add_argument("--bridge-sha256")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-limit-mib", type=int, default=16384)
    parser.add_argument("--cpu-time-limit-seconds", type=int, default=120)
    arguments = parser.parse_args(argv)
    try:
        result = prepare_decoder_reuse(arguments.teacher384, arguments.legacy8,
            expected_teacher384_sha256=arguments.teacher384_sha256, expected_legacy8_sha256=arguments.legacy8_sha256,
            repository_root=arguments.repository_root, legacy_implementation_root=arguments.legacy_implementation_root,
            bridge_checkpoint_path=arguments.bridge, expected_bridge_sha256=arguments.bridge_sha256,
            output_directory=arguments.output, seed=arguments.seed, threads=arguments.threads,
            memory_limit_mib=arguments.memory_limit_mib, cpu_time_limit_seconds=arguments.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
