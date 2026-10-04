"""Authenticate a completed aligned interface run before source evaluation.

This reader imports no tensor libraries. It reconstructs both original parent
admissions and checks every status-dependent saved output. Historical reload
receipts remain byte-authenticated metadata; they do not execute a new replay
or qualify the donor, encoder producer, or generated source interpretations.
"""
from copy import deepcopy
import json
from pathlib import Path
import re


SCHEMA = "gte-aligned-interface-training-manifest/v1"
MAX_BYTES = 128 * 1024 * 1024
MAX_RECEIPTS = 512
FALSE_FLAGS = ("distillation_executed", "encoder_inference_executed", "download_executed",
               "teacher_qualified", "production_kd_eligible", "source_fidelity_qualified", "proof_authority")
BASE_OUTPUTS = {"native-inspection.json", "aligned-start-inspection.json", "summary.json"}
TRAINED_OUTPUTS = {"resources.json", "trained-interfaces.json", "training-report.json",
                   "checkpoint-inspection.json", "reload-verification.json"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    return json.dumps(left, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False) == json.dumps(right, sort_keys=True, separators=(",", ":"),
                                                   ensure_ascii=True, allow_nan=False)


def _receipt(ref, root, *, absolute):
    _require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"},
             "closed training parent file receipt required")
    _require(type(ref["bytes"]) is int and 0 < ref["bytes"] <= MAX_BYTES,
             "positive bounded training parent byte count required")
    _require(type(ref["sha256"]) is str and _SHA.fullmatch(ref["sha256"]) is not None,
             "lowercase training parent file SHA256 required")
    _require(type(ref["path"]) is str and bool(ref["path"]) and "\0" not in ref["path"],
             "nonempty training parent path required")
    path = Path(ref["path"])
    if absolute:
        _require(path.is_absolute() and ".." not in path.parts
                 and str(path.resolve()) == ref["path"] and path.is_relative_to(root),
                 "canonical training parent file inside workspace required")
    else:
        _require(path.name == ref["path"] and ref["path"] not in (".", ".."),
                 "flat relative training parent output required")
    return path


def _file_list(refs, root, reader, native, *, unique):
    _require(type(refs) is list and 1 <= len(refs) <= MAX_RECEIPTS,
             "bounded nonempty training parent file closure required")
    seen = {}
    for ref in refs:
        path = _receipt(ref, root, absolute=True)
        _require(path not in seen or (not unique and seen[path] == ref),
                 "duplicate or conflicting training parent file binding")
        seen[path] = ref
        _require(native._file(reader, path) == ref, "training parent file binding changed")


def _outputs(manifest, directory, root, reader, native, names):
    refs = manifest["outputs"]
    _require(type(refs) is list and len(refs) == len(names),
             "complete training parent output inventory required")
    values, receipts = {}, {}
    for ref in refs:
        relative = _receipt(ref, root, absolute=False)
        _require(ref["path"] in names and ref["path"] not in values,
                 "duplicate or unexpected training parent output")
        path = directory / relative
        _require(not path.is_symlink() and path.resolve().is_relative_to(root),
                 "training parent output outside workspace or symlinked")
        value, captured = reader.read_pinned_json(path, expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        _require(captured == {**ref, "path": str(path)} and native._file(reader, path) == captured,
                 "training parent output bytes changed during admission")
        values[ref["path"]], receipts[ref["path"]] = value, captured
    _require(set(values) == names, "training parent outputs differ from training status")
    return values, receipts


def _summary(config, plan, aligned, checkpoint, executed):
    start_ready = aligned["checkpoint"] is not None
    ready = plan["status"] == "ready" and start_ready
    status = "trained_unqualified" if executed else "prepared" if ready else (
        "unavailable" if not start_ready or plan["status"] == "unavailable" else "partial")
    return {"schema": "gte-aligned-interface-training-summary/v1", "mode": config["mode"], "status": status,
        "native_batch_status": plan["status"], "plan_sha256": plan["plan_sha256"],
        "initialization_representation_id": plan["initialization_representation_id"],
        "trained_representation_id": checkpoint["representation_id"] if executed else None,
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


def _reload_metadata(checkpoint, report, payloads, aligned, contract, numerical):
    plan = payloads["native_batch"]
    return {"schema": "gte-aligned-interface-reload-verification/v1",
        "status": "exact_trained_aligned_reload_verified_unqualified",
        "checkpoint_content_sha256": contract.digest(checkpoint), "training_report_sha256": contract.digest(report),
        "initialization_representation_id": payloads["initialization"]["representation_id"],
        "trained_representation_id": checkpoint["representation_id"],
        "primary_start": "authenticated_aligned_generation", "start_representation_id": aligned["checkpoint"]["representation_id"],
        "start_checkpoint_content_sha256": contract.digest(aligned["checkpoint"]),
        "start_model_state_sha256": aligned["checkpoint"]["model_state_sha256"],
        "alignment_file_pins": aligned["file_pins"], "plan_sha256": plan["plan_sha256"],
        "batch_sha256": payloads["batch"]["batch_sha256"], "replay_sha256": contract.digest(payloads["replay"]),
        "donor_pins": payloads["donor_pins"], "model_state_sha256": report["model_state_sha256_after"],
        "trained_reference_outputs_sha256": report["trained_reference_outputs_sha256"],
        "row_counts": {name: len(plan["heads"][name]["rows"]) for name in ("primary384", "legacy8")},
        "all_26_inherited_tensors_unchanged": True, "inherited_gradients_absent": True,
        "all_30_reloaded_tensors_bitwise_equal": True, "private_storage_disjoint": True,
        "trained_reference_outputs_match": True, "original_inputs_unchanged": True,
        "optimizer_created": False, "optimizer_steps": 0, "training_executed": False,
        **{name: False for name in FALSE_FLAGS}, "production_kd_enabled": False,
        "producer_execution_authenticated": False, "optimizer_resume_supported": False,
        "numerical_profile": {"device": "cpu", "dtype": "float32", "threads": 1, "evaluation_mode": True},
        "implementation": numerical._implementation()}


def admit_training_parent(manifest, manifest_receipt, *, root, reader, training_cli):
    """Reconstruct a byte-pinned training parent without numerical execution.

    Unavailable parents still expose admitted original caches for donor-only
    evaluation. A trained parent provides the saved four-interface generation,
    its matched report, pure inspection, and historical reload metadata.
    """
    root = Path(root).resolve()
    _require(root.is_absolute() and root.is_dir(), "existing absolute evaluation workspace required")
    native = training_cli._native_cli()
    parent_path = _receipt(manifest_receipt, root, absolute=True)
    saved_manifest, captured = reader.read_pinned_json(parent_path,
        expected_sha256=manifest_receipt["sha256"], max_bytes=MAX_BYTES)
    _require(captured == manifest_receipt and _same(saved_manifest, manifest)
             and native._file(reader, parent_path) == manifest_receipt,
             "training manifest byte binding changed")
    fields = {"schema", "completed", "captured_at_utc", "mode", "status", "inputs", "parent_closure",
        "implementation_files", "outputs", "aligned_start_admitted", "start_representation_id", "optimizer_steps",
        "training_executed", "trained_checkpoint_count", "saved_trained_checkpoint_authenticated_and_replayed", *FALSE_FLAGS}
    _require(type(manifest) is dict and set(manifest) == fields and manifest["schema"] == SCHEMA
             and manifest["completed"] is True and type(manifest["captured_at_utc"]) is str
             and bool(manifest["captured_at_utc"]) and manifest["mode"] in ("prepare", "train")
             and manifest["status"] in ("unavailable", "partial", "prepared", "trained_unqualified")
             and all(manifest[name] is False for name in FALSE_FLAGS),
             "closed completed unqualified aligned training parent required")
    _file_list(manifest["inputs"], root, reader, native, unique=False)
    _file_list(manifest["parent_closure"], root, reader, native, unique=False)
    _file_list(manifest["implementation_files"], root, reader, native, unique=True)
    original_ref = manifest["inputs"][0]
    original_config, _ = reader.read_pinned_json(original_ref["path"],
        expected_sha256=original_ref["sha256"], max_bytes=1024 * 1024)
    _require(type(original_config) is dict and type(original_config.get("workspace_root")) is str,
             "original aligned training workspace required")
    original_root = Path(original_config["workspace_root"])
    _require(original_root.is_absolute() and original_root.resolve().is_relative_to(root),
             "original aligned training workspace outside evaluation workspace")
    config, payloads, inputs, admitted_root = training_cli._configuration(
        original_ref["path"], original_ref["sha256"], reader, native)
    _require(admitted_root.is_relative_to(root) and inputs == manifest["inputs"]
             and config["mode"] == manifest["mode"], "training parent configured inputs or mode differ")
    implementation_paths = [Path(training_cli.__file__),
        *[Path(training_cli.__file__).with_name(name + ".py") for name in (
            "prepare_gte_decoder_native", "run_gte_decoder_interface_training",
            "prepare_gte_aligned_decoder", "gte_aligned_interface_parent")],
        *[training_cli.HELPERS / (name + ".py") for name in training_cli.HELPER_NAMES]]
    expected_implementation = [native._file(reader, path) for path in implementation_paths]
    _require(expected_implementation == manifest["implementation_files"],
             "training parent exact implementation inventory differs")
    named_inputs = dict(zip(training_cli.REFERENCES, inputs[1:]))
    closure, source_roots = training_cli._reference_cli()._parent(reader, native, payloads, named_inputs, admitted_root)
    aligned = training_cli._aligned_parent(payloads, named_inputs, admitted_root, reader, native)
    closure += aligned["closure"]
    source_roots += aligned["source_roots"]
    _require(closure == manifest["parent_closure"]
             and all(Path(path).resolve().is_relative_to(root) for path in source_roots),
             "training parent reconstructed source closure differs or leaves workspace")
    arguments = {"initialization": payloads["initialization"], "plan": payloads["native_batch"],
        "batch": payloads["batch"], "replay": payloads["replay"], "expected_donor_pins": payloads["donor_pins"],
        "aligned_checkpoint": aligned["checkpoint"], "expected_alignment_file_pins": aligned["file_pins"]}
    plan = payloads["native_batch"]
    native_inspection = native._helper("gte_decoder_native_batch").inspect_decoder_native_batch(plan,
        arguments["initialization"], arguments["batch"], arguments["replay"], expected_donor_pins=arguments["expected_donor_pins"])
    start_ready = aligned["checkpoint"] is not None
    executed = config["mode"] == "train" and plan["status"] == "ready" and start_ready
    _require(manifest["training_executed"] is executed
             and manifest["saved_trained_checkpoint_authenticated_and_replayed"] is executed
             and manifest["aligned_start_admitted"] is start_ready
             and type(manifest["optimizer_steps"]) is int
             and manifest["optimizer_steps"] == (config["steps"] if executed else 0)
             and type(manifest["trained_checkpoint_count"]) is int
             and manifest["trained_checkpoint_count"] == int(executed)
             and manifest["start_representation_id"] == (aligned["checkpoint"]["representation_id"] if start_ready else None),
             "training parent dependency, optimizer or checkpoint accounting differs")
    outputs, output_refs = _outputs(manifest, parent_path.parent, root, reader, native,
        BASE_OUTPUTS | (TRAINED_OUTPUTS if executed else set()))
    aligned_inspection = {"schema": "gte-aligned-interface-start-inspection/v1", "status": aligned["status"],
        "aligned_start_admitted": start_ready, "initialization_representation_id": plan["initialization_representation_id"],
        "aligned_representation_id": aligned["checkpoint"]["representation_id"] if start_ready else None,
        "alignment_file_pins": aligned["file_pins"], "inspection": aligned["inspection"]}
    _require(_same(outputs["native-inspection.json"], native_inspection)
             and _same(outputs["aligned-start-inspection.json"], aligned_inspection),
             "saved training parent dependency inspections differ")
    checkpoint = outputs["trained-interfaces.json"] if executed else None
    report = outputs["training-report.json"] if executed else None
    inspection = verification = None
    if executed:
        contract = native._helper("gte_aligned_interface_checkpoint")
        inspection = contract.inspect_interface_checkpoint(checkpoint, **arguments)
        _require(_same(report, checkpoint["training_report"])
                 and type(report["optimizer_steps"]) is int and report["optimizer_steps"] == config["steps"]
                 and report["optimizer"]["learning_rate"] == float(config["learning_rate"])
                 and report["max_grad_norm"] == float(config["max_grad_norm"])
                 and _same(report["head_weights"], {name: float(value) for name, value in config["head_weights"].items()})
                 and _same(outputs["checkpoint-inspection.json"], inspection),
                 "saved training report, configured optimizer or checkpoint inspection differs")
        verification = outputs["reload-verification.json"]
        numerical = native._helper("gte_aligned_interface_training")
        _require(_same(verification, _reload_metadata(checkpoint, report, payloads, aligned, contract, numerical)),
                 "saved historical trained reload metadata differs")
        resources = outputs["resources.json"]
        _require(type(resources) is dict and resources.get("schema") == "gte-worker-cpu-budget-receipt/v1"
                 and resources.get("device") == "cpu" and type(resources.get("threads")) is int
                 and resources["threads"] == 1, "historical training CPU resource receipt required")
    summary = _summary(config, plan, aligned, checkpoint, executed)
    _require(manifest["status"] == summary["status"] and _same(outputs["summary.json"], summary),
             "saved training parent summary or status differs")
    admitted = [manifest_receipt, *inputs, *closure, *manifest["implementation_files"], *output_refs.values()]
    deduplicated = {}
    for ref in admitted:
        _require(ref["path"] not in deduplicated or deduplicated[ref["path"]] == ref,
                 "conflicting admitted training parent closure pins")
        deduplicated[ref["path"]] = ref
    native._recheck(reader, list(deduplicated.values()))
    return {"payloads": deepcopy(payloads), "inputs": deepcopy(inputs),
        "closure": deepcopy(list(deduplicated.values())), "source_roots": [Path(path).resolve() for path in source_roots],
        "aligned": deepcopy(aligned), "trained_checkpoint": deepcopy(checkpoint), "training_report": deepcopy(report),
        "checkpoint_inspection": deepcopy(inspection), "reload_verification": deepcopy(verification), "status": summary["status"]}


__all__ = ["SCHEMA", "admit_training_parent"]
