"""Evaluate source-only decoder generations from immutable original caches.

The completed aligned training parent is admitted before numerical imports.
Unavailable native vectors still permit real original 384D/8D donor baselines.
All evidence remains exposed-validation regression or training diagnostics.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
SCHEMA = "gte-decoder-source-evaluation-config/v1"
REFERENCES = ("training_parent_manifest", "primary_checkpoint", "legacy8_checkpoint")
NEW_HELPERS = ("gte_decoder_source_evaluation", "gte_decoder_source_generation", "gte_decoder_source_comparison")
FALSE_FLAGS = ("training_executed", "distillation_executed", "encoder_inference_executed", "download_executed",
    "teacher_qualified", "production_kd_eligible", "source_fidelity_qualified", "proof_authority",
    "independent_holdout_evaluated", "reference_prefix_used")
MAX_BYTES = 128 * 1024 * 1024


def _module(name):
    spec = importlib.util.spec_from_file_location("_gte_source_evaluation_cli_" + name,
        Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _training_cli():
    return _module("run_gte_aligned_interface_training")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _configuration(path, expected_sha256, reader, native):
    config, captured = reader.read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=1024 * 1024)
    fields = {"schema", "workspace_root", "mode", "max_primary_rows", "max_auxiliary_rows", *REFERENCES}
    _require(type(config) is dict and set(config) == fields and config["schema"] == SCHEMA
             and config["mode"] in ("prepare", "evaluate"), "closed source evaluation configuration required")
    for name, cap in (("max_primary_rows", 60), ("max_auxiliary_rows", 2)):
        _require(type(config[name]) is int and 1 <= config[name] <= cap, "bounded " + name + " required")
    _require(type(config["workspace_root"]) is str, "absolute existing evaluation workspace required")
    root = Path(config["workspace_root"])
    _require(root.is_absolute() and root.is_dir(), "absolute existing evaluation workspace required")
    root = root.resolve()
    payloads, inputs = {}, [captured]
    for name in REFERENCES:
        ref = config[name]
        _require(type(ref) is dict and set(ref) == {"path", "sha256"}, "closed pinned source evaluation reference required")
        payloads[name], receipt = reader.read_pinned_json(native._relative(root, ref["path"]),
            expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        inputs.append(receipt)
    return config, payloads, inputs, root


def run_source_evaluation(config_path, *, expected_config_sha256, output_directory,
                          threads=1, memory_limit_mib=16384, cpu_time_limit_seconds=600):
    _require(type(threads) is int and threads == 1, "one reserved CPU thread required")
    training = _training_cli()
    native = training._native_cli()
    reader = native._helper("gte_worker_contract")
    budget = reader._resources({"device": "cpu", "threads": threads, "max_rows": 62,
        "memory_limit_mib": memory_limit_mib, "cpu_time_limit_seconds": cpu_time_limit_seconds})
    config, payloads, inputs, root = _configuration(config_path, expected_config_sha256, reader, native)
    parent = _module("gte_source_evaluation_parent").admit_training_parent(payloads["training_parent_manifest"], inputs[1],
        root=root, reader=reader, training_cli=training)
    original = parent["payloads"]
    pins = original["donor_pins"]
    _require(inputs[2]["sha256"] == pins["teacher384_checkpoint_sha256"]
             and inputs[3]["sha256"] == pins["legacy8_checkpoint_sha256"],
             "original raw donor files differ from authenticated initialization")
    implementations = [native._file(reader, Path(__file__)),
        native._file(reader, Path(__file__).with_name("gte_source_evaluation_parent.py")),
        *[native._file(reader, HELPERS / (name + ".py")) for name in NEW_HELPERS]]
    closure = parent["closure"]
    source = native._helper("gte_decoder_source_evaluation")
    plan_arguments = {"initialization": original["initialization"], "native_plan": original["native_batch"],
        "batch": original["batch"], "replay": original["replay"], "expected_donor_pins": pins}
    evaluation = source.prepare_source_evaluation(**plan_arguments,
        max_primary_rows=config["max_primary_rows"], max_auxiliary_rows=config["max_auxiliary_rows"])
    inspection = source.inspect_source_evaluation(evaluation, **plan_arguments)
    comparison_arguments = {**plan_arguments, "primary_checkpoint": payloads["primary_checkpoint"],
        "legacy8_checkpoint": payloads["legacy8_checkpoint"], "aligned_checkpoint": parent["aligned"]["checkpoint"],
        "expected_alignment_file_pins": parent["aligned"]["file_pins"] if parent["aligned"]["checkpoint"] is not None else None,
        "trained_checkpoint": parent["trained_checkpoint"]}
    comparison = native._helper("gte_decoder_source_comparison")
    # Authenticate original parsed donor bodies even in a dependency-free preparation.
    comparison._admit(evaluation, original["initialization"], original["native_batch"], original["batch"],
        original["replay"], pins, payloads["primary_checkpoint"], payloads["legacy8_checkpoint"],
        comparison_arguments["aligned_checkpoint"], comparison_arguments["expected_alignment_file_pins"],
        comparison_arguments["trained_checkpoint"])
    output = native._output_directory(output_directory, [*inputs, *closure, *implementations], parent["source_roots"])
    native._recheck(reader, [*inputs, *closure, *implementations])
    resources = result = None
    if config["mode"] == "evaluate":
        resources = reader.configure_cpu_process(budget)
        result = comparison.compare_source_decoders(evaluation, **comparison_arguments)
        comparison.inspect_source_comparison(result, evaluation, **comparison_arguments)
    executed = result is not None
    status = result["status"] if executed else "prepared_unqualified"
    summary = {"schema": "gte-decoder-source-evaluation-summary/v1", "mode": config["mode"], "status": status,
        "training_parent_status": parent["status"], "evaluation_plan_sha256": evaluation["plan_sha256"],
        "evaluation_native_status": evaluation["status"], "selected_row_count": evaluation["selected_row_count"],
        "donor_ready_row_count": evaluation["donor_ready_row_count"], "native_ready_row_count": evaluation["native_ready_row_count"],
        "native_missing_row_count": evaluation["native_missing_row_count"],
        "native_quarantined_row_count": evaluation["native_quarantined_row_count"],
        "decoder_inference_executed": executed, "native768_inputs_used": result["native768_inputs_used"] if executed else False,
        "aligned_generation_available": parent["aligned"]["checkpoint"] is not None,
        "trained_generation_available": parent["trained_checkpoint"] is not None,
        "head_metrics": {label: {name: head["summary"] for name, head in value["heads"].items()}
            for label, value in result["variants"].items()} if executed else {},
        "primary_evaluation_role": "original_validation_exposed_regression_only",
        "auxiliary_evaluation_role": "legacy_training_diagnostic_only", "optimizer_created": False, "optimizer_steps": 0,
        "old_embeddings_regenerated": False, "source_vectors_relabelled": False,
        **{name: False for name in FALSE_FLAGS}}
    native._recheck(reader, [*inputs, *closure, *implementations])
    output.mkdir(parents=True, exist_ok=False)
    exports = [("source-evaluation-plan.json", evaluation), ("plan-inspection.json", inspection), ("summary.json", summary)]
    if executed:
        exports += [("resources.json", resources), ("source-comparison.json", result)]
    outputs = [native._write(output, name, value) for name, value in exports]
    saved_values = {}
    for name, expected in exports:
        ref = next(ref for ref in outputs if ref["path"] == name)
        saved_value, _ = reader.read_pinned_json(output / name, expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        _require(comparison.digest(saved_value) == comparison.digest(expected),
                 "saved source evaluation output differs from actual execution: " + name)
        saved_values[name] = saved_value
    saved_evaluation = saved_values["source-evaluation-plan.json"]
    saved_plan_inspection = source.inspect_source_evaluation(saved_evaluation, **plan_arguments)
    _require(comparison.digest(saved_plan_inspection) == comparison.digest(saved_values["plan-inspection.json"]),
             "saved source plan inspection differs from admitted saved plan")
    replayed = False
    if executed:
        ref = next(ref for ref in outputs if ref["path"] == "source-comparison.json")
        saved, _ = reader.read_pinned_json(output / ref["path"], expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
        saved_inspection = comparison.inspect_source_comparison(saved, saved_evaluation, **comparison_arguments)
        # A new private model load and fresh source-only execution establish saved
        # numerical reproducibility; structural metadata alone cannot establish it.
        repeated = comparison.compare_source_decoders(saved_evaluation, **comparison_arguments)
        _require(comparison.digest(saved) == comparison.digest(repeated), "saved source comparison failed exact numerical replay")
        verification = {"schema": "gte-decoder-source-evaluation-replay/v1", "status": "exact_source_generation_replay_unqualified",
            "report_content_sha256": comparison.digest(saved), "evaluation_plan_sha256": evaluation["plan_sha256"],
            "fresh_private_models_loaded": True, "all_generated_tokens_and_logits_replayed_exactly": True,
            "all_selected_rows_retained": True, "all_inherited_tensors_unchanged": True, "optimizer_steps": 0,
            **{name: False for name in FALSE_FLAGS}}
        additional = [("comparison-inspection.json", saved_inspection), ("numerical-replay.json", verification)]
        for name, expected in additional:
            ref = native._write(output, name, expected)
            saved_value, _ = reader.read_pinned_json(output / name, expected_sha256=ref["sha256"], max_bytes=MAX_BYTES)
            _require(comparison.digest(saved_value) == comparison.digest(expected),
                     "saved source evaluation verification differs from actual execution: " + name)
            outputs.append(ref)
        replayed = True
    native._recheck(reader, [*inputs, *closure, *implementations])
    for ref in outputs:
        _require(native._file(reader, output / ref["path"]) == {**ref, "path": str(output / ref["path"])},
                 "source evaluation output changed before completion")
    manifest = {"schema": "gte-decoder-source-evaluation-manifest/v1", "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(), "mode": config["mode"], "status": status,
        "inputs": inputs, "parent_closure": closure, "implementation_files": implementations, "outputs": outputs,
        "decoder_inference_executed": executed, "saved_source_comparison_authenticated_and_replayed": replayed,
        "optimizer_steps": 0, **{name: False for name in FALSE_FLAGS}}
    completion = native._write(output, "manifest.json", manifest)
    return {**summary, "output_directory": str(output), "manifest_sha256": completion["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-limit-mib", type=int, default=16384)
    parser.add_argument("--cpu-time-limit-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        result = run_source_evaluation(args.config, expected_config_sha256=args.expected_config_sha256,
            output_directory=args.output_directory, threads=args.threads, memory_limit_mib=args.memory_limit_mib,
            cpu_time_limit_seconds=args.cpu_time_limit_seconds)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, OverflowError, ImportError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
