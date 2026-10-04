"""Prepare paired-vector alignment or explicitly fit a private affine boundary.

Preparation and unavailable outcomes import no numerical libraries. Fitting runs
in a separate bounded CPU process, touches only the new 768-to-384 boundary, and
never changes the inherited initialization or either donor checkpoint.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
CONFIG_SCHEMA = "gte-affine-alignment-config/v1"
MANIFEST_SCHEMA = "gte-affine-alignment-manifest/v1"
MAX_BYTES = 128 * 1024 * 1024
REFERENCES = ("rows_384", "corpus_audit", "tasks", "receipts_768", "teacher_checkpoint",
              "initialization", "donor_pins")
HELPER_NAMES = ("gte_alignment_contract", "gte_affine_alignment", "gte_bridge_pairs",
    "gte_bridge_teacher", "gte_decoder_reuse", "gte_decoder_warm_start", "gte_legacy8_decoder_donor",
    "gte_affine_bridge", "gte_worker_contract", "gte_multilingual_corpus", "gte_transfer_corpus",
    "gte_migration_inventory")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_alignment_cli_" + name, HELPERS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode()


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _file(reader, path):
    _, receipt, _ = reader._read_stable(path, max_bytes=MAX_BYTES)
    return receipt


def _recheck(reader, references):
    for ref in references:
        _require(_file(reader, ref["path"]) == ref, "input or implementation changed during operation")


def _config(path, pin, reader):
    value, config_ref = reader.read_pinned_json(path, expected_sha256=pin, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "domain_id", "max_rows", "mode", "seed",
              "regularization_candidates", "max_train_pairs", "max_validation_pairs",
              "teacher_repository_root", *REFERENCES}
    _require(type(value) is dict and set(value) == fields, "closed alignment configuration required")
    _require(value["schema"] == CONFIG_SCHEMA and value["mode"] in ("prepare", "fit"),
             "alignment schema or explicit mode differs")
    _require(value["domain_id"] == "legal_ir", "current dual-donor initialization supports Legal only")
    _require(type(value["seed"]) is int and 0 <= value["seed"] < 2**31, "bounded seed required")
    for name in ("max_rows", "max_train_pairs", "max_validation_pairs"):
        _require(type(value[name]) is int and 1 <= value[name] <= 4096, "bounded integer " + name + " required")
    grid = value["regularization_candidates"]
    _require(type(grid) is list and 1 <= len(grid) <= 16 and all(type(item) in (int, float)
        and math.isfinite(item) and 1e-8 <= item <= 1e6 for item in grid)
        and grid == sorted(set(grid)), "increasing positive bounded regularization grid required")
    root = Path(value["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute existing workspace root required")
    root = root.resolve()

    def relative_path(text):
        _require(type(text) is str and bool(text) and "\0" not in text, "workspace-relative path required")
        relative = Path(text)
        _require(not relative.is_absolute() and ".." not in relative.parts, "workspace-relative path required")
        resolved = (root / relative).resolve()
        _require(resolved.is_relative_to(root), "reference outside workspace root")
        return resolved

    source_root = relative_path(value["teacher_repository_root"])
    _require(source_root.is_dir(), "existing pinned teacher source tree required")
    payloads, inputs = {}, [config_ref]
    for name in REFERENCES:
        ref = value[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed input reference required")
        payloads[name], captured = reader.read_pinned_json(relative_path(ref["path"]),
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        inputs.append(captured)
    return value, payloads, inputs, source_root


def _output(path, inputs, source_root):
    requested = Path(path).absolute()
    _require(not any(component.is_symlink() for component in (*requested.parents, requested)),
             "output namespace cannot contain symlinks")
    output = requested.resolve()
    _require(not output.exists(), "fresh output directory required")
    for ref in inputs:
        _require(not Path(ref["path"]).is_relative_to(output), "output aliases an input namespace")
    for protected in (REPOSITORY, source_root):
        _require(not output.is_relative_to(protected) and not protected.is_relative_to(output),
                 "output aliases an implementation namespace")
    return output


def _fit_candidates(plan, numeric=None):
    """Fit train rows per lambda; validation chooses one without refitting."""
    _helper("gte_alignment_contract").inspect_alignment_plan(plan)
    _require(plan["fit_ready"] is True, "ready paired alignment plan required before numerical work")
    numeric = _helper("gte_affine_alignment") if numeric is None else numeric
    train_x = [row["student_embedding_768"] for row in plan["train_rows"]]
    train_y = [row["source_embedding_384"] for row in plan["train_rows"]]
    val_x = [row["student_embedding_768"] for row in plan["validation_rows"]]
    val_y = [row["source_embedding_384"] for row in plan["validation_rows"]]
    candidates, best, best_key = [], None, None
    for regularization in plan["regularization_candidates"]:
        fitted = numeric.fit_affine_ridge(train_x, train_y, regularization=regularization)
        validation = numeric.score_affine_ridge(fitted["model_state"], val_x, val_y)
        _require(fitted["regularization"] == regularization and fitted["validation_used_for_fit"] is False,
                 "numerical candidate violated fitting policy")
        if val_x:
            score = validation["mean_squared_l2"]
            _require(validation["status"] == "available" and type(score) in (int, float)
                     and math.isfinite(score) and score >= 0, "finite validation selection metric required")
            key = (score, regularization)
        else:
            _require(len(plan["regularization_candidates"]) == 1 and validation["status"] == "unavailable",
                     "multiple candidates require separate validation rows")
            key = (0., regularization)
        _require(fitted["diagnostics"]["training_rows"] == len(train_x)
                 and fitted["train_metrics"]["rows"] == len(train_x)
                 and validation["rows"] == len(val_x), "numerical candidate row accounting differs")
        _require(fitted["objective_residual_reduction"] == "sum",
                 "ridge regularization requires the declared summed-residual convention")
        entry = {"regularization": regularization, "weights_sha256": fitted["weights_sha256"],
                 "train_metrics": fitted["train_metrics"], "validation_metrics": validation,
                 "diagnostics": fitted["diagnostics"], "objective": fitted["objective"],
                 "objective_residual_reduction": fitted["objective_residual_reduction"],
                 "exported_training_objective": fitted["exported_training_objective"]}
        candidates.append(entry)
        if best_key is None or key < best_key:
            best, best_key = fitted, key
    selection = {"schema": "gte-affine-alignment-selection/v1", "candidates": candidates,
                 "candidate_count": len(candidates), "selected_regularization": best["regularization"],
                 "selected_weights_sha256": best["weights_sha256"],
                 "selection_policy": plan["selection_policy"], "tie_break_policy": "smaller_regularization",
                 "train_rows": len(train_x), "validation_rows": len(val_x),
                 "validation_used_for_fit": False, "refit_with_validation": False,
                 "test_or_canary_used": False, "optimizer_steps": 0}
    return selection, best["model_state"]


def _pack_bridge(state, *, config, teacher):
    import torch
    numeric = _helper("gte_affine_bridge")
    bridge = numeric.create_affine_bridge(seed=config["seed"])
    bridge.load_state_dict({name: torch.tensor(value, dtype=torch.float32, device="cpu")
                           for name, value in state.items()}, strict=True)
    packed = numeric.pack_bridge_checkpoint(bridge, seed=config["seed"], domain_id=config["domain_id"],
        teacher_runtime_id=teacher["teacher_runtime_id"], source_representation_id=teacher["source_representation_id"],
        student_representation_id=numeric.STUDENT_REPRESENTATION_ID,
        teacher_checkpoint_sha256=teacher["checkpoint_sha256"], input_transform=teacher["input_transform"])
    restored = numeric.load_bridge_checkpoint(packed, expected_domain_id=config["domain_id"],
        expected_teacher_runtime_id=teacher["teacher_runtime_id"],
        expected_source_representation_id=teacher["source_representation_id"],
        expected_student_representation_id=numeric.STUDENT_REPRESENTATION_ID,
        expected_teacher_checkpoint_sha256=teacher["checkpoint_sha256"], input_transform=teacher["input_transform"])
    _require(all(torch.equal(value, restored.state_dict()[name]) for name, value in bridge.state_dict().items()),
             "fitted bridge reload differs")
    _require(packed["model_state"] == state, "bridge export rounded fitted state")
    return packed


def run_alignment(config_path, *, expected_config_sha256, output_directory, threads=1,
                  memory_limit_mib=16384, cpu_time_limit_seconds=120):
    started = time.monotonic()
    reader = _helper("gte_worker_contract")
    tools = [_file(reader, Path(__file__)), *[_file(reader, HELPERS / (name + ".py")) for name in HELPER_NAMES]]
    config, payloads, inputs, source_root = _config(config_path, expected_config_sha256, reader)
    output = _output(output_directory, inputs, source_root)
    by_name = dict(zip(REFERENCES, inputs[1:]))
    teacher = _helper("gte_bridge_teacher").inspect_teacher(by_name["teacher_checkpoint"]["path"],
        expected_sha256=by_name["teacher_checkpoint"]["sha256"], domain_id=config["domain_id"],
        repository_root=source_root)
    inputs.extend(teacher["sources"])
    _output(output, inputs, source_root)
    initialization = payloads["initialization"]
    pins = payloads["donor_pins"]
    inspection = _helper("gte_decoder_reuse").inspect_dual_decoder(initialization, expected_donor_pins=pins)
    _require(pins["teacher384_checkpoint_sha256"] == by_name["teacher_checkpoint"]["sha256"]
             and pins["teacher384_weights_sha256"] == teacher["weights_sha256"]
             and pins["teacher384_codec_sha256"] == teacher["codec_sha256"]
             and initialization["primary"]["input_transform"] == teacher["input_transform"],
             "initialization and selected teacher bindings differ")
    pairs = _helper("gte_bridge_pairs").prepare_bridge_pairs(payloads["rows_384"], payloads["corpus_audit"],
        payloads["tasks"], payloads["receipts_768"], domain_id=config["domain_id"], max_rows=config["max_rows"])
    _require(pairs["source_vector_space_id"] == teacher["source_representation_id"],
             "alignment target coordinates differ from donor input convention")
    contract = _helper("gte_alignment_contract")
    plan = contract.prepare_alignment_plan(pairs, regularization_candidates=config["regularization_candidates"],
        max_train_pairs=config["max_train_pairs"], max_validation_pairs=config["max_validation_pairs"])
    contract.inspect_alignment_plan(plan)
    binding = {"schema": "gte-alignment-initialization-binding/v1",
               "initialization": by_name["initialization"], "donor_pins": by_name["donor_pins"],
               "representation_id": inspection["representation_id"],
               "copied_parameter_count": inspection["copied_parameter_count"],
               "original_initialization_unchanged": True, "auxiliary_connector_fitted": False}
    payload_outputs = {"pairs.json": pairs, "plan.json": plan, "teacher-binding.json": teacher,
                       "initialization-binding.json": binding}
    fit_executed = config["mode"] == "fit" and plan["fit_ready"]
    if fit_executed:
        sys.dont_write_bytecode = True
        resources = reader.configure_cpu_process({"device": "cpu", "threads": threads,
            "max_rows": config["max_rows"], "memory_limit_mib": memory_limit_mib,
            "cpu_time_limit_seconds": cpu_time_limit_seconds})
        selection, state = _fit_candidates(plan)
        packed = _pack_bridge(state, config=config, teacher=teacher)
        identity_binding = {"initialization_sha256": by_name["initialization"]["sha256"],
                            "plan_sha256": _digest(plan), "bridge_weights_sha256": packed["weights_sha256"]}
        fit_report = {"schema": "gte-affine-alignment-fit/v1", **identity_binding,
            "bridge_checkpoint_sha256": hashlib.sha256(_raw(packed)).hexdigest(),
            "initialization_representation_id": inspection["representation_id"],
            "aligned_representation_id": "legal_ir:aligned_dual_decoder_768:" + _digest(identity_binding),
            "donor_pins": pins, "source_profile_id": pairs["student_profile_id"],
            "train_rows_sha256": plan["train_rows_sha256"], "validation_rows_sha256": plan["validation_rows_sha256"],
            "plan_content_sha256": plan["plan_sha256"], "pair_coverage_status": pairs["status"],
            "missing_eligible_pair_receipts": pairs["counts"]["missing_eligible_pair_receipts"],
            "selection": selection, "analytic_alignment_fit_executed": True,
            "primary_input_boundary_fitted": True, "auxiliary_connector_fitted": False,
            "validation_used_for_fit": False, "original_initialization_unchanged": True,
            "inherited_decoder_weights_unchanged": True, "fitted_bridge_reloaded_exactly": True,
            "adapter_outputs_normalized": False, "donor_transform_applied_by_decoder_only": True,
            "encoder_numerics_verified": False, "source_vectors_producer_verified": False,
            "student_vectors_producer_verified": False, "source_fidelity_qualified": False,
            "teacher_qualified": False, "optimizer_steps": 0, "distillation_executed": False,
            "student_decoder_gradient_training_executed": False, "proof_authority": False}
        payload_outputs.update({"fitted-bridge.json": packed, "fit-report.json": fit_report, "resources.json": resources})
    summary = {"schema": "gte-affine-alignment-summary/v1", "mode": config["mode"],
        "status": "fitted_unqualified" if fit_executed else "prepared" if plan["fit_ready"] else "unavailable",
        "fit_ready": plan["fit_ready"], "pair_count": len(pairs["pairs"]),
        "pair_coverage_status": pairs["status"],
        "missing_eligible_pair_receipts": pairs["counts"]["missing_eligible_pair_receipts"],
        "train_pair_count": len(plan["train_rows"]), "validation_pair_count": len(plan["validation_rows"]),
        "regularization_candidates": config["regularization_candidates"],
        "candidate_fits_executed": len(config["regularization_candidates"]) if fit_executed else 0,
        "analytic_alignment_fit_executed": bool(fit_executed), "auxiliary_connector_fitted": False,
        "original_initialization_unchanged": True, "inherited_decoder_weights_unchanged": True,
        "encoder_inference_executed": False, "encoder_numerics_verified": False,
        "training_executed": bool(fit_executed), "distillation_executed": False,
        "optimizer_steps": 0, "download_executed": False, "teacher_qualified": False,
        "source_fidelity_qualified": False, "proof_authority": False,
        "unavailable_reasons": plan["unavailable_reasons"], "elapsed_seconds": time.monotonic() - started}
    _recheck(reader, [*inputs, *tools])
    output.mkdir(parents=True, exist_ok=False)
    references = []
    for name, payload in {**payload_outputs, "summary.json": summary}.items():
        raw = _raw(payload)
        with (output / name).open("xb") as stream:
            stream.write(raw)
        references.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    _recheck(reader, [*inputs, *tools])
    for ref in references:
        current = _file(reader, output / ref["path"])
        _require(current["sha256"] == ref["sha256"] and current["bytes"] == ref["bytes"],
                 "output changed before completion manifest")
    manifest = {"schema": MANIFEST_SCHEMA, "completed": True, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": config["mode"], "status": summary["status"], "inputs": inputs,
        "implementation_files": tools, "outputs": references,
        "analytic_alignment_fit_executed": bool(fit_executed), "distillation_executed": False,
        "encoder_inference_executed": False, "source_fidelity_qualified": False, "proof_authority": False}
    raw = _raw(manifest)
    with (output / "manifest.json").open("xb") as stream:
        stream.write(raw)
    return {**summary, "output_directory": str(output), "manifest_sha256": hashlib.sha256(raw).hexdigest()}


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
        result = run_alignment(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
