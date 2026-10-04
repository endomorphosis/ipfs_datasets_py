"""Bind a completed affine fit to a private inherited 768-input decoder.

An unavailable or preparation-only parent emits zero student checkpoints and
imports no numerical libraries. A fitted parent admits a separately identified
CPU student, checks private weight composition, and publishes a synthetic probe
and exact reload receipt. No fitting, encoder execution or KD occurs here.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
CONFIG_SCHEMA = "gte-aligned-decoder-preparation-config/v1"
MANIFEST_SCHEMA = "gte-aligned-decoder-preparation-manifest/v1"
PARENT_SCHEMA = "gte-affine-alignment-manifest/v1"
MAX_BYTES = 128 * 1024 * 1024
REFERENCES = ("alignment_manifest", "initialization", "donor_pins")
HELPER_NAMES = ("gte_aligned_decoder", "gte_aligned_decoder_contract", "gte_decoder_reuse",
    "gte_decoder_warm_start", "gte_legacy8_decoder_donor", "gte_affine_bridge",
    "gte_alignment_contract", "gte_affine_alignment", "gte_bridge_pairs",
    "gte_multilingual_corpus", "gte_transfer_corpus", "gte_migration_inventory",
    "gte_bridge_teacher", "gte_worker_contract")
BASE_OUTPUTS = {"pairs.json", "plan.json", "teacher-binding.json", "initialization-binding.json", "summary.json"}
FIT_OUTPUTS = {"fitted-bridge.json", "fit-report.json", "resources.json"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _helper(name):
    return _module(HELPERS / (name + ".py"), "_gte_aligned_cli_" + name)


def _probe_helper():
    return _module(Path(__file__).with_name("prepare_gte_decoder_reuse.py"), "_gte_aligned_cli_probe")


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode()


def _same(left, right):
    return _raw(left) == _raw(right)


def _file(reader, path):
    _, receipt, _ = reader._read_stable(path, max_bytes=MAX_BYTES)
    return receipt


def _receipt(value, *, absolute):
    _require(type(value) is dict and set(value) == {"path", "bytes", "sha256"}, "closed file receipt required")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_BYTES,
             "bounded file byte count required")
    _require(type(value["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", value["sha256"]),
             "lowercase file SHA256 required")
    _require(type(value["path"]) is str and bool(value["path"]) and "\0" not in value["path"],
             "nonempty file path required")
    path = Path(value["path"])
    if absolute:
        _require(path.is_absolute() and ".." not in path.parts, "canonical absolute input receipt required")
    else:
        _require(path.name == value["path"] and value["path"] not in (".", ".."),
                 "flat relative output receipt required")


def _recheck(reader, receipts):
    for ref in receipts:
        _require(_file(reader, ref["path"]) == ref, "input or implementation changed during operation")


def _configuration(path, expected_sha256, reader):
    config, captured = reader.read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    _require(type(config) is dict and set(config) == {"schema", "workspace_root", "mode", *REFERENCES},
             "closed aligned decoder configuration required")
    _require(config["schema"] == CONFIG_SCHEMA and config["mode"] == "prepare",
             "aligned decoder configuration permits preparation only")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute existing workspace root required")
    root = root.resolve()
    payloads, inputs = {}, [captured]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed configuration reference required")
        _require(type(ref["path"]) is str and bool(ref["path"]), "workspace-relative input path required")
        relative = Path(ref["path"])
        _require(not relative.is_absolute() and ".." not in relative.parts, "workspace-relative input path required")
        resolved = (root / relative).resolve()
        _require(resolved.is_relative_to(root), "input outside workspace root")
        payloads[name], receipt = reader.read_pinned_json(resolved,
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        inputs.append(receipt)
    return config, payloads, inputs


def _admit_parent(manifest, manifest_receipt, reader):
    fields = {"schema", "completed", "captured_at_utc", "mode", "status", "inputs", "implementation_files",
              "outputs", "analytic_alignment_fit_executed", "distillation_executed",
              "encoder_inference_executed", "source_fidelity_qualified", "proof_authority"}
    _require(type(manifest) is dict and set(manifest) == fields and manifest["schema"] == PARENT_SCHEMA,
             "closed completed alignment manifest required")
    _require(manifest["completed"] is True and type(manifest["captured_at_utc"]) is str
             and bool(manifest["captured_at_utc"]), "completed parent alignment required")
    _require(manifest["mode"] in ("prepare", "fit")
             and type(manifest["analytic_alignment_fit_executed"]) is bool, "explicit parent fit mode required")
    _require(all(manifest[name] is False for name in ("distillation_executed", "encoder_inference_executed",
             "source_fidelity_qualified", "proof_authority")), "alignment cannot grant KD or qualification")
    fitted = manifest["analytic_alignment_fit_executed"]
    _require((fitted and manifest["mode"] == "fit" and manifest["status"] == "fitted_unqualified") or
             (not fitted and manifest["status"] in ("prepared", "unavailable")), "parent mode/status/fit flags differ")
    _require(not (manifest["mode"] == "fit" and manifest["status"] == "prepared"),
             "explicit fit mode cannot report preparation without a fit")
    receipts = []
    for field in ("inputs", "implementation_files"):
        refs = manifest[field]
        _require(type(refs) is list and 1 <= len(refs) <= 128, "bounded nonempty parent file list required")
        _require(len({item.get("path") for item in refs if type(item) is dict}) == len(refs),
                 "duplicate or malformed parent input receipts")
        for ref in refs:
            _receipt(ref, absolute=True)
            _require(_file(reader, ref["path"]) == ref, "parent input or implementation SHA256 differs")
            receipts.append(ref)
    outputs = manifest["outputs"]
    _require(type(outputs) is list and len(outputs) == len(BASE_OUTPUTS | (FIT_OUTPUTS if fitted else set())),
             "complete parent output inventory required")
    _require(len({ref.get("path") for ref in outputs if type(ref) is dict}) == len(outputs),
             "duplicate or malformed parent output receipts")
    _require({ref.get("path") for ref in outputs if type(ref) is dict}
             == BASE_OUTPUTS | (FIT_OUTPUTS if fitted else set()), "parent outputs differ from fit status")
    directory = Path(manifest_receipt["path"]).parent
    payloads, output_receipts = {}, {}
    for ref in outputs:
        _receipt(ref, absolute=False)
        path = directory / ref["path"]
        _require(not path.is_symlink(), "parent output cannot be a symlink")
        value, current = reader.read_pinned_json(path, expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        _require(current["bytes"] == ref["bytes"], "parent output byte count differs")
        payloads[ref["path"]], output_receipts[ref["path"]] = value, current
        receipts.append(current)
    return fitted, payloads, output_receipts, receipts


def _bindings(parent, payloads, configured_inputs):
    refs = dict(zip(REFERENCES, configured_inputs[1:]))
    initialization, pins = payloads["initialization"], payloads["donor_pins"]
    inventory = _helper("gte_decoder_reuse").inspect_dual_decoder(initialization, expected_donor_pins=pins)
    binding = parent["initialization-binding.json"]
    _require(_same(binding, {"schema": "gte-alignment-initialization-binding/v1",
        "initialization": refs["initialization"], "donor_pins": refs["donor_pins"],
        "representation_id": inventory["representation_id"],
        "copied_parameter_count": inventory["copied_parameter_count"],
        "original_initialization_unchanged": True, "auxiliary_connector_fitted": False}),
        "parent initialization bindings differ from configured immutable files")
    teacher = parent["teacher-binding.json"]
    _require(type(teacher) is dict and teacher.get("checkpoint_sha256") == pins["teacher384_checkpoint_sha256"]
             and teacher.get("weights_sha256") == pins["teacher384_weights_sha256"]
             and teacher.get("codec_sha256") == pins["teacher384_codec_sha256"]
             and _same(teacher.get("input_transform"), initialization["primary"]["input_transform"]),
             "parent teacher and inherited decoder bindings differ")
    source_relative = "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py"
    sources = teacher.get("sources")
    _require(type(sources) is list, "parent teacher source closure required")
    runtime_sources = [ref for ref in sources if type(ref) is dict and type(ref.get("path")) is str
                       and ref["path"].endswith("/" + source_relative)]
    _require(len(runtime_sources) == 1, "exact parent teacher source root required")
    source_root = Path(runtime_sources[0]["path"][:-len(source_relative)]).resolve()
    teacher_replay = _helper("gte_bridge_teacher").inspect_teacher(teacher["checkpoint"]["path"],
        expected_sha256=pins["teacher384_checkpoint_sha256"], domain_id="legal_ir", repository_root=source_root)
    _require(_same(teacher, teacher_replay), "parent teacher inspection does not replay from its pinned sources")
    plan, pairs = parent["plan.json"], parent["pairs.json"]
    contract = _helper("gte_alignment_contract")
    contract.inspect_alignment_plan(plan)
    recomputed = contract.prepare_alignment_plan(pairs,
        regularization_candidates=plan["regularization_candidates"], max_train_pairs=plan["max_train_pairs"],
        max_validation_pairs=plan["max_validation_pairs"])
    _require(_same(recomputed, plan), "parent plan does not reproduce from its paired corpus")
    summary = parent["summary.json"]
    summary_fields = {"schema", "mode", "status", "fit_ready", "pair_count", "pair_coverage_status",
        "missing_eligible_pair_receipts", "train_pair_count", "validation_pair_count",
        "regularization_candidates", "candidate_fits_executed", "analytic_alignment_fit_executed",
        "auxiliary_connector_fitted", "original_initialization_unchanged", "inherited_decoder_weights_unchanged",
        "encoder_inference_executed", "encoder_numerics_verified", "training_executed", "distillation_executed",
        "optimizer_steps", "download_executed", "teacher_qualified", "source_fidelity_qualified",
        "proof_authority", "unavailable_reasons", "elapsed_seconds"}
    _require(type(summary) is dict and set(summary) == summary_fields
             and summary["schema"] == "gte-affine-alignment-summary/v1", "closed parent summary required")
    _require(type(summary["analytic_alignment_fit_executed"]) is bool
             and summary["training_executed"] is summary["analytic_alignment_fit_executed"],
             "parent training and analytic fit flags differ")
    _require(all(summary[name] is False for name in ("auxiliary_connector_fitted", "encoder_inference_executed",
        "encoder_numerics_verified", "distillation_executed", "download_executed", "teacher_qualified",
        "source_fidelity_qualified", "proof_authority"))
        and summary["original_initialization_unchanged"] is True
        and summary["inherited_decoder_weights_unchanged"] is True
        and type(summary["optimizer_steps"]) is int and summary["optimizer_steps"] == 0,
        "parent summary cannot grant decoder training, resume or qualification")
    _require(type(summary["candidate_fits_executed"]) is int
             and summary["candidate_fits_executed"] == (len(plan["regularization_candidates"])
                if summary["analytic_alignment_fit_executed"] else 0)
             and _same(summary["regularization_candidates"], plan["regularization_candidates"])
             and _same(summary["unavailable_reasons"], plan["unavailable_reasons"])
             and type(summary["missing_eligible_pair_receipts"]) is int
             and summary["missing_eligible_pair_receipts"] == pairs["counts"]["missing_eligible_pair_receipts"],
             "parent candidate and coverage accounting differs")
    _require(type(summary) is dict and summary.get("fit_ready") is plan["fit_ready"]
             and type(summary.get("pair_count")) is int and summary["pair_count"] == len(pairs["pairs"])
             and summary.get("pair_coverage_status") == pairs["status"]
             and type(summary.get("train_pair_count")) is int
             and summary["train_pair_count"] == len(plan["train_rows"])
             and type(summary.get("validation_pair_count")) is int
             and summary["validation_pair_count"] == len(plan["validation_rows"]),
             "parent summary and split accounting differ")
    return inventory, plan, source_root


def _output(path, inputs, parent_directory, source_root):
    requested = Path(path).absolute()
    _require(not any(part.is_symlink() for part in (*requested.parents, requested)),
             "output namespace cannot contain symlinks")
    output = requested.resolve()
    _require(not output.exists(), "fresh output directory required")
    for ref in inputs:
        _require(not Path(ref["path"]).is_relative_to(output), "output aliases an input namespace")
    for namespace in (REPOSITORY, parent_directory, source_root):
        _require(not output.is_relative_to(namespace) and not namespace.is_relative_to(output),
                 "output aliases an implementation or parent namespace")
    return output


def _write(output, name, value):
    raw = _raw(value)
    with (output / name).open("xb") as stream:
        stream.write(raw)
    return {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def prepare_aligned_decoder(config_path, *, expected_config_sha256, output_directory,
                            threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=120):
    started = time.monotonic()
    reader = _helper("gte_worker_contract")
    tools = [_file(reader, Path(__file__)), _file(reader, Path(__file__).with_name("prepare_gte_decoder_reuse.py")),
             *[_file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    _, payloads, inputs = _configuration(config_path, expected_config_sha256, reader)
    configured_inputs = list(inputs)
    parent_manifest = payloads["alignment_manifest"]
    parent_ref = inputs[1]
    fitted, parent, parent_outputs, parent_files = _admit_parent(parent_manifest, parent_ref, reader)
    inputs.extend(parent_files)
    _require(all(ref in parent_manifest["inputs"] for ref in configured_inputs[2:]),
             "configured initialization and donor pins were not inputs to the parent fit")
    inventory, plan, source_root = _bindings(parent, payloads, configured_inputs)
    _require(parent["summary.json"].get("mode") == parent_manifest["mode"]
             and parent["summary.json"].get("status") == parent_manifest["status"]
             and parent["summary.json"].get("analytic_alignment_fit_executed") is fitted,
             "parent summary mode/status/fit flags differ")
    _require(not fitted or plan["fit_ready"] is True, "parent fit requires a ready training plan")
    output = _output(output_directory, inputs, Path(parent_ref["path"]).parent, source_root)
    common = {"schema": "gte-aligned-decoder-preparation-summary/v1", "operation": "prepare-aligned-student",
        "parent_alignment_manifest_sha256": parent_ref["sha256"], "dimension": 768,
        "original_initialization_unchanged": True, "inherited_decoder_weights_unchanged": True,
        "auxiliary_connector_fitted": False, "decoder_parameters_random": False,
        "boundary_alignment_required": True, "encoder_inference_executed": False,
        "training_executed": False, "distillation_executed": False, "optimizer_steps": 0,
        "download_executed": False, "source_fidelity_qualified": False, "proof_authority": False}
    outputs = {"parent-binding.json": {"schema": "gte-aligned-student-parent-binding/v1",
        "alignment_manifest": parent_ref, "initialization": configured_inputs[2], "donor_pins": configured_inputs[3],
        "parent_fit_executed": fitted, "original_representation_id": inventory["representation_id"]}}
    if fitted:
        _require(parent["fit-report.json"]["pair_coverage_status"] == parent["pairs.json"]["status"]
                 and parent["fit-report.json"]["missing_eligible_pair_receipts"]
                     == parent["pairs.json"]["counts"]["missing_eligible_pair_receipts"],
                 "fit report corpus coverage differs from admitted pairs")
        pins = {"initialization_sha256": configured_inputs[2]["sha256"],
            "bridge_checkpoint_sha256": parent_outputs["fitted-bridge.json"]["sha256"],
            "plan_sha256": parent_outputs["plan.json"]["sha256"],
            "fit_report_sha256": parent_outputs["fit-report.json"]["sha256"]}
        contract = _helper("gte_aligned_decoder_contract")
        handoff = contract.inspect_alignment_handoff(payloads["initialization"], parent["fitted-bridge.json"],
            plan, parent["fit-report.json"], expected_file_pins=pins, expected_donor_pins=payloads["donor_pins"])
        sys.dont_write_bytecode = True
        resources = reader.configure_cpu_process({"device": "cpu", "threads": threads, "max_rows": 1,
            "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
        numeric = _helper("gte_aligned_decoder")
        model, checkpoint = numeric.create_aligned_decoder(payloads["initialization"], parent["fitted-bridge.json"],
            plan, parent["fit-report.json"], expected_file_pins=pins, expected_donor_pins=payloads["donor_pins"])
        inspection = numeric.inspect_aligned_decoder(checkpoint, expected_file_pins=pins,
                                                      expected_donor_pins=payloads["donor_pins"])
        probe_helper = _probe_helper()
        probe, before = probe_helper._probe_model(model, _helper("gte_decoder_reuse"))
        outputs.update({"aligned-student.json": checkpoint, "parent-file-pins.json": pins,
                        "handoff.json": handoff, "inspection.json": inspection, "resources.json": resources})
        summary = {**common, "status": "constructed_unqualified", "aligned_checkpoint_count": 1,
            "numerical_model_loaded": True, "synthetic_gradient_probe_executed": True,
            "primary_input_boundary_fitted": True, "representation_id": parent["fit-report.json"]["aligned_representation_id"],
            "unavailable_reasons": []}
    else:
        reasons = ["alignment_fit_not_executed", *plan["unavailable_reasons"]]
        summary = {**common, "status": "unavailable", "aligned_checkpoint_count": 0,
            "numerical_model_loaded": False, "synthetic_gradient_probe_executed": False,
            "primary_input_boundary_fitted": False, "representation_id": None,
            "unavailable_reasons": list(dict.fromkeys(reasons))}
    _recheck(reader, [*inputs, *tools])
    output.mkdir(parents=True, exist_ok=False)
    refs = [_write(output, name, value) for name, value in outputs.items()]
    if fitted:
        checkpoint_ref = next(ref for ref in refs if ref["path"] == "aligned-student.json")
        saved, _ = reader.read_pinned_json(output / checkpoint_ref["path"],
            expected_sha256=checkpoint_ref["sha256"], max_bytes=MAX_BYTES)
        restored = numeric.load_aligned_decoder(saved, expected_file_pins=pins,
                                                expected_donor_pins=payloads["donor_pins"])
        probe["exact_saved_reload"] = probe_helper._verify_reload(model, restored, before, _helper("gte_decoder_reuse"))
        refs.append(_write(output, "gradient-probe.json", probe))
        summary["exact_saved_reload_passed"] = True
    summary["elapsed_seconds"] = time.monotonic() - started
    refs.append(_write(output, "summary.json", summary))
    _recheck(reader, [*inputs, *tools])
    for ref in refs:
        actual = _file(reader, output / ref["path"])
        _require(actual["sha256"] == ref["sha256"] and actual["bytes"] == ref["bytes"],
                 "output changed before completion manifest")
    manifest = {"schema": MANIFEST_SCHEMA, "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "status": summary["status"],
        "inputs": inputs, "implementation_files": tools, "outputs": refs,
        "aligned_checkpoint_count": summary["aligned_checkpoint_count"],
        "encoder_inference_executed": False, "training_executed": False,
        "distillation_executed": False, "source_fidelity_qualified": False, "proof_authority": False}
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
        result = prepare_aligned_decoder(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
