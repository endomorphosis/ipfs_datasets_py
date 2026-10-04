"""Authenticate an existing aligned generation before interface training.

Admission is standard-library only. It replays the original preparation and
affine handoff contracts from independently pinned files. The saved synthetic
probe is checked as historical metadata; admission does not rerun its numerics
or establish encoder provenance, teacher qualification, or permission for KD.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re


SCHEMA = "gte-aligned-decoder-preparation-manifest/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_RECEIPTS = 128
FALSE_FLAGS = ("encoder_inference_executed", "training_executed",
               "distillation_executed", "source_fidelity_qualified", "proof_authority")
BASE_OUTPUTS = {"parent-binding.json", "summary.json"}
CONSTRUCTED_OUTPUTS = {"aligned-student.json", "parent-file-pins.json", "handoff.json",
                       "inspection.json", "resources.json", "gradient-probe.json"}
INTERFACES = {"primary.input_adapter.weight", "primary.input_adapter.bias",
              "auxiliary_connector.weight", "auxiliary_connector.bias"}
RESULT_NAMES = {"primary_logits", "auxiliary_logits", "shared_condition", "auxiliary_latent"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    return json.dumps(left, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) == json.dumps(right, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _receipt(ref, root, *, absolute):
    _require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"},
             "closed aligned parent file receipt required")
    _require(type(ref["bytes"]) is int and 0 < ref["bytes"] <= MAX_BYTES,
             "positive bounded aligned parent byte count required")
    _require(type(ref["sha256"]) is str and _SHA.fullmatch(ref["sha256"]) is not None,
             "lowercase aligned parent file SHA256 required")
    _require(type(ref["path"]) is str and bool(ref["path"]) and "\0" not in ref["path"],
             "nonempty aligned parent path required")
    path = Path(ref["path"])
    if absolute:
        _require(path.is_absolute() and ".." not in path.parts
                 and str(path.resolve()) == ref["path"] and path.is_relative_to(root),
                 "canonical aligned parent file inside workspace required")
    else:
        _require(path.name == ref["path"] and ref["path"] not in (".", ".."),
                 "flat relative aligned parent output required")
    return path


def _file_list(refs, root, reader, native, *, unique):
    _require(type(refs) is list and 1 <= len(refs) <= MAX_RECEIPTS,
             "bounded nonempty aligned parent file closure required")
    seen = {}
    for ref in refs:
        path = _receipt(ref, root, absolute=True)
        _require(path not in seen or (not unique and seen[path] == ref),
                 "duplicate or conflicting aligned parent file binding")
        seen[path] = ref
        _require(native._file(reader, path) == ref, "aligned parent file binding changed")


def _outputs(manifest, directory, root, reader, native, names):
    refs = manifest["outputs"]
    _require(type(refs) is list and len(refs) == len(names),
             "complete aligned parent output inventory required")
    seen, values, receipts = set(), {}, {}
    for ref in refs:
        relative = _receipt(ref, root, absolute=False)
        _require(ref["path"] in names and ref["path"] not in seen,
                 "duplicate or unexpected aligned parent output")
        seen.add(ref["path"])
        path = directory / relative
        _require(not path.is_symlink() and path.resolve().is_relative_to(root),
                 "aligned parent output outside workspace or symlinked")
        value, captured = reader.read_pinned_json(path, expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        _require(captured == {**ref, "path": str(path)}, "aligned parent output byte count changed")
        _require(native._file(reader, path) == captured, "aligned parent output changed during admission")
        values[ref["path"]], receipts[ref["path"]] = value, captured
    _require(seen == names, "aligned parent outputs differ from construction status")
    return values, receipts


def _finite(value, label, *, positive=False):
    _require(type(value) in (int, float), "finite " + label + " required")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError("finite " + label + " required") from None
    _require(math.isfinite(number) and (number > 0 if positive else number >= 0),
             "finite nonnegative " + label + " required")


def _probe_metadata(probe):
    fields = {"schema", "status", "probe_input_origin", "input_rows", "input_dimension", "input_dtype",
        "input_device", "input_l2_norm", "input_sha256", "decoder_prefix_policy", "primary_prefix",
        "auxiliary_prefix", "gradient_objective", "objective_value", "gradient_groups",
        "auxiliary_loss_reaches_shared_primary_boundary", "result_shapes", "result_sha256",
        "all_model_weights_unchanged", "inherited_heads_frozen", "process_cpu_rng_unchanged",
        "gradient_buffers_unchanged", "optimizer_steps", "exact_saved_reload", *FALSE_FLAGS}
    _require(type(probe) is dict and set(probe) == fields
             and probe["schema"] == "gte-dual-donor-synthetic-gradient-probe/v1"
             and probe["status"] == "passed", "closed historical aligned probe metadata required")
    expected = {"probe_input_origin": "fixed_synthetic_unit_vector_not_encoder_output",
        "input_dtype": "float32", "input_device": "cpu", "decoder_prefix_policy": "bos_only_no_reference_target",
        "primary_prefix": [[1]], "auxiliary_prefix": [[1]],
        "gradient_objective": "auxiliary_logits_squared_mean_connectivity_only"}
    _require(all(_same(probe[name], value) for name, value in expected.items()),
             "historical aligned probe conventions differ")
    _require(type(probe["input_rows"]) is int and probe["input_rows"] == 1
             and type(probe["input_dimension"]) is int and probe["input_dimension"] == 768
             and type(probe["optimizer_steps"]) is int and probe["optimizer_steps"] == 0
             and all(probe[name] is False for name in FALSE_FLAGS)
             and all(probe[name] is True for name in ("auxiliary_loss_reaches_shared_primary_boundary",
                 "all_model_weights_unchanged", "inherited_heads_frozen", "process_cpu_rng_unchanged",
                 "gradient_buffers_unchanged")), "historical probe cannot grant training or qualification")
    _finite(probe["input_l2_norm"], "synthetic input norm", positive=True)
    _finite(probe["objective_value"], "synthetic objective")
    _require(type(probe["input_sha256"]) is str and _SHA.fullmatch(probe["input_sha256"]) is not None,
             "synthetic input SHA256 required")
    groups = probe["gradient_groups"]
    _require(type(groups) is dict and set(groups) == INTERFACES, "four historical interface gradient groups required")
    for group in groups.values():
        _require(type(group) is dict and set(group) == {"l2_norm", "max_abs", "finite", "nonzero"}
                 and group["finite"] is True and group["nonzero"] is True,
                 "closed historical gradient metadata required")
        _finite(group["l2_norm"], "historical gradient norm", positive=True)
        _finite(group["max_abs"], "historical gradient maximum", positive=True)
    _require(type(probe["result_sha256"]) is dict and set(probe["result_sha256"]) == RESULT_NAMES
             and all(type(value) is str and _SHA.fullmatch(value) is not None
                     for value in probe["result_sha256"].values()), "historical result SHA256 inventory required")
    _require(type(probe["result_shapes"]) is dict and set(probe["result_shapes"]) == RESULT_NAMES
             and all(type(shape) is list and 2 <= len(shape) <= 3
                     and all(type(size) is int and size > 0 for size in shape)
                     for shape in probe["result_shapes"].values()), "historical output shape inventory required")
    reload = probe["exact_saved_reload"]
    reload_flags = {"saved_bytes_authenticated_before_load", "all_state_tensors_equal",
                    "all_output_tensors_equal", "tensor_storage_independent", "freeze_mode_equal"}
    _require(type(reload) is dict and set(reload) == reload_flags | {"result_sha256"}
             and all(reload[name] is True for name in reload_flags)
             and _same(reload["result_sha256"], probe["result_sha256"]),
             "historical exact saved reload metadata differs")


def admit_aligned_parent(payloads, named_inputs, root, reader, native, alignment_cli):
    """Return an authenticated checkpoint, or explicit unavailable admission.

    The caller has externally pinned the new configuration and its references.
    The returned closure preserves immutable file bindings. Repeated identical
    original inputs are legitimate; conflicting bindings and repeated output or
    implementation paths are rejected. No model or optimizer is instantiated.
    """
    root = Path(root).resolve()
    _require(root.is_absolute() and root.is_dir(), "existing absolute workspace required")
    manifest = payloads["aligned_parent_manifest"]
    parent_ref = named_inputs["aligned_parent_manifest"]
    _receipt(parent_ref, root, absolute=True)
    _require(native._file(reader, parent_ref["path"]) == parent_ref, "aligned manifest byte binding changed")
    fields = {"schema", "completed", "captured_at_utc", "status", "inputs", "implementation_files",
              "outputs", "aligned_checkpoint_count", *FALSE_FLAGS}
    _require(type(manifest) is dict and set(manifest) == fields and manifest["schema"] == SCHEMA
             and manifest["completed"] is True and type(manifest["captured_at_utc"]) is str
             and bool(manifest["captured_at_utc"]), "closed completed aligned parent manifest required")
    constructed = manifest["status"] == "constructed_unqualified"
    _require(manifest["status"] in ("unavailable", "constructed_unqualified")
             and type(manifest["aligned_checkpoint_count"]) is int
             and manifest["aligned_checkpoint_count"] == int(constructed)
             and all(manifest[name] is False for name in FALSE_FLAGS),
             "aligned parent construction status, count or declarations differ")
    _file_list(manifest["inputs"], root, reader, native, unique=False)
    _file_list(manifest["implementation_files"], root, reader, native, unique=True)
    directory = Path(parent_ref["path"]).parent
    outputs, output_refs = _outputs(manifest, directory, root, reader, native,
        BASE_OUTPUTS | (CONSTRUCTED_OUTPUTS if constructed else set()))

    original_ref = manifest["inputs"][0]
    config, original_payloads, original_inputs = alignment_cli._configuration(
        original_ref["path"], original_ref["sha256"], reader)
    _require(Path(config["workspace_root"]).resolve().is_relative_to(root),
             "original aligned workspace outside current workspace")
    _require(manifest["inputs"][:4] == original_inputs and len(original_inputs) == 4,
             "aligned parent configured input prefix differs")
    _require(original_inputs[2] == named_inputs["initialization"]
             and original_inputs[3] == named_inputs["donor_pins"]
             and _same(original_payloads["initialization"], payloads["initialization"])
             and _same(original_payloads["donor_pins"], payloads["donor_pins"]),
             "aligned parent and native donor initialization differ")
    affine_manifest = original_payloads["alignment_manifest"]
    # Preflight workspace bounds before the old helper reads affine references.
    _require(type(affine_manifest) is dict, "affine alignment parent required")
    for key in ("inputs", "implementation_files"):
        _file_list(affine_manifest.get(key), root, reader, native, unique=True)
    affine_refs = affine_manifest.get("outputs")
    _require(type(affine_refs) is list and 1 <= len(affine_refs) <= MAX_RECEIPTS,
             "bounded affine output closure required")
    for ref in affine_refs:
        _receipt(ref, root, absolute=False)
    fitted, affine, affine_outputs, affine_closure = alignment_cli._admit_parent(
        affine_manifest, original_inputs[1], reader)
    for ref in affine_closure:
        _receipt(ref, root, absolute=True)
    _require(manifest["inputs"] == [*original_inputs, *affine_closure],
             "aligned parent source closure differs from original preparation")
    inventory, plan, source_root = alignment_cli._bindings(affine, original_payloads, original_inputs)
    _require(Path(source_root).resolve().is_relative_to(root), "aligned donor source root outside workspace")
    _require(fitted is constructed and affine["summary.json"]["mode"] == affine_manifest["mode"]
             and affine["summary.json"]["status"] == affine_manifest["status"]
             and affine["summary.json"]["analytic_alignment_fit_executed"] is fitted
             and (not fitted or plan["fit_ready"] is True),
             "aligned construction differs from its affine parent")
    binding = {"schema": "gte-aligned-student-parent-binding/v1", "alignment_manifest": original_inputs[1],
        "initialization": original_inputs[2], "donor_pins": original_inputs[3], "parent_fit_executed": fitted,
        "original_representation_id": inventory["representation_id"]}
    _require(_same(outputs["parent-binding.json"], binding), "aligned parent binding differs")

    common = {"schema": "gte-aligned-decoder-preparation-summary/v1", "operation": "prepare-aligned-student",
        "parent_alignment_manifest_sha256": original_inputs[1]["sha256"], "dimension": 768,
        "original_initialization_unchanged": True, "inherited_decoder_weights_unchanged": True,
        "auxiliary_connector_fitted": False, "decoder_parameters_random": False,
        "boundary_alignment_required": True, "download_executed": False, "optimizer_steps": 0,
        **{name: False for name in FALSE_FLAGS}}
    reasons = [] if fitted else list(dict.fromkeys(["alignment_fit_not_executed", *plan["unavailable_reasons"]]))
    summary = {**common, "status": manifest["status"], "aligned_checkpoint_count": int(fitted),
        "numerical_model_loaded": fitted, "synthetic_gradient_probe_executed": fitted,
        "primary_input_boundary_fitted": fitted,
        "representation_id": affine["fit-report.json"]["aligned_representation_id"] if fitted else None,
        "unavailable_reasons": reasons}
    if fitted:
        summary["exact_saved_reload_passed"] = True
    saved_summary = outputs["summary.json"]
    _require(type(saved_summary) is dict and set(saved_summary) == {*summary, "elapsed_seconds"},
             "closed aligned parent summary required")
    _finite(saved_summary["elapsed_seconds"], "aligned preparation elapsed seconds")
    _require(_same({key: value for key, value in saved_summary.items() if key != "elapsed_seconds"}, summary),
             "aligned parent summary accounting or declarations differ")

    checkpoint, pins, inspection = None, None, None
    if fitted:
        _require(affine["fit-report.json"]["pair_coverage_status"] == affine["pairs.json"]["status"]
                 and type(affine["fit-report.json"]["missing_eligible_pair_receipts"]) is int
                 and affine["fit-report.json"]["missing_eligible_pair_receipts"]
                    == affine["pairs.json"]["counts"]["missing_eligible_pair_receipts"],
                 "fitted parent corpus coverage differs")
        pins = {"initialization_sha256": original_inputs[2]["sha256"],
            "bridge_checkpoint_sha256": affine_outputs["fitted-bridge.json"]["sha256"],
            "plan_sha256": affine_outputs["plan.json"]["sha256"],
            "fit_report_sha256": affine_outputs["fit-report.json"]["sha256"]}
        handoff = alignment_cli._helper("gte_aligned_decoder_contract").inspect_alignment_handoff(
            payloads["initialization"], affine["fitted-bridge.json"], plan, affine["fit-report.json"],
            expected_file_pins=pins, expected_donor_pins=payloads["donor_pins"])
        _require(_same(outputs["parent-file-pins.json"], pins)
                 and _same(outputs["handoff.json"], handoff), "saved aligned file pins or handoff differ")
        checkpoint = outputs["aligned-student.json"]
        _require(type(checkpoint) is dict and _same(checkpoint.get("initialization"), payloads["initialization"])
                 and _same(checkpoint.get("bridge"), affine["fitted-bridge.json"])
                 and _same(checkpoint.get("plan"), plan)
                 and _same(checkpoint.get("fit_report"), affine["fit-report.json"]),
                 "saved aligned checkpoint differs from independently admitted parent files")
        inspection = alignment_cli._helper("gte_aligned_decoder").inspect_aligned_decoder(checkpoint,
            expected_file_pins=pins, expected_donor_pins=payloads["donor_pins"])
        _require(_same(outputs["inspection.json"], inspection)
                 and checkpoint["representation_id"] == summary["representation_id"]
                 and checkpoint["source_profile_id"] == payloads["native_batch"]["profile_id"]
                 and checkpoint["plan"]["asset_manifest_sha256"]
                    == payloads["native_batch"]["asset_manifest_sha256"],
                 "saved aligned inspection, native input profile or producer assets differ")
        _probe_metadata(outputs["gradient-probe.json"])

    closure = [parent_ref, *manifest["inputs"], *manifest["implementation_files"], *output_refs.values()]
    deduplicated = {}
    for ref in closure:
        _require(ref["path"] not in deduplicated or deduplicated[ref["path"]] == ref,
                 "conflicting aligned parent closure pins")
        deduplicated[ref["path"]] = ref
    native._recheck(reader, list(deduplicated.values()))
    return {"checkpoint": deepcopy(checkpoint), "file_pins": deepcopy(pins),
        "closure": deepcopy(list(deduplicated.values())), "source_roots": [Path(source_root).resolve()],
        "inspection": deepcopy(inspection), "status": manifest["status"]}


__all__ = ["admit_aligned_parent", "SCHEMA"]
