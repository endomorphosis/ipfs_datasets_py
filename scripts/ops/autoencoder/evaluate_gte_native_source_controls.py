"""Freeze reference-free native decoder generations before exposed-cohort scoring.

This runner reuses the existing immutable decoder admissions, checkpoint loaders,
source-only generator and scorer. It adds the original-start trained checkpoint,
explicit outer numerical-runtime receipts, and input-zero/cross-source controls.
The 60 historical validation examples are exposed regression; two legacy rows
are training diagnostics. Neither group is an independent holdout.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
HELPERS = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder"
VARIANTS = ("original_donor", "original_initialization", "aligned_initialization",
            "original_trained", "aligned_trained")
CONTROLS = ("source", "zero", "cross_source")
HEADS = ("primary384", "legacy8")
SCHEMA = "gte-native-source-controls-config/v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def module(name, directory=HELPERS):
    spec = importlib.util.spec_from_file_location("_gte_native_controls_" + name, directory / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def file_ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read_ref(ref):
    require(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}, "closed file reference required")
    require(file_ref(ref["path"]) == ref, "file binding changed: " + str(ref["path"]))
    return json.loads(Path(ref["path"]).read_text())


def write(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    with Path(path).open("xb") as handle:
        handle.write(raw)
    return file_ref(path)


def runtime_receipt(ref, *, expected_start):
    """Bind the actual numerical adapter; the inner manifest alone is insufficient."""
    value = read_ref(ref)
    require(value.get("schema") == "gte-precise-interface-runtime-receipt/v1"
        and value.get("completed") is True and value.get("training_executed") is True
        and value.get("inner_implementation_pins_alone_are_complete") is False
        and value.get("configured_bound_relaxed") is False
        and value.get("original_source_files_modified") is False
        and value.get("proof_authority") is False and value.get("source_fidelity_qualified") is False,
        "explicit unqualified numerical-adapter runtime required")
    require(value["algorithm"] == "cpu-float32-gradient-float64-l2-clip-with-four-epsilon-margin/v1"
        and value["gradient_dtype"] == "float32" and value["norm_dtype"] == "float64",
        "unexpected training numerical adapter")
    require(type(value["optimizer_steps"]) is int and value["optimizer_steps"] > 0
        and len(value["clipping_calls"]) == value["optimizer_steps"], "runtime step accounting differs")
    for call in value["clipping_calls"]:
        require(call["algorithm"] == value["algorithm"] and call["gradient_tensor_count"] == 4
            and all(type(call[name]) in (int, float) and math.isfinite(call[name])
                    for name in ("norm_before", "norm_after", "max_norm", "scale"))
            and 0 <= call["norm_after"] <= call["max_norm"] and 0 < call["scale"] <= 1,
            "invalid precise clipping receipt")
    require(value["result"]["primary_start"] == expected_start
        and value["result"]["optimizer_steps"] == value["optimizer_steps"], "runtime start or steps differ")
    refs = [value[name] for name in ("checkpoint", "manifest", "config", "training_report", "reload_verification")]
    refs += value["implementation_files"]
    require(len(value["implementation_files"]) == 4
        and {Path(r["path"]).name for r in value["implementation_files"]} >= {
            "run_gte_precise_interface_training.py", "gte_precise_gradient_clipping.py"},
        "numerical adapter implementation closure missing")
    for child in refs:
        require(file_ref(child["path"]) == child, "runtime bound file changed")
    require(value["result"]["manifest_sha256"] == value["manifest"]["sha256"], "runtime manifest differs")
    return value, [ref, *refs]


def intervention_input(rows, index, control, *, donor):
    """Select a source vector without access to references or target lengths."""
    require(control in CONTROLS and type(index) is int and 0 <= index < len(rows), "invalid intervention")
    key = "generation_input" if donor else "native_generation_input"
    row = rows[index]
    require(type(row.get(key)) is dict, "complete input coverage required")
    original = row[key]["input_vector"]
    origin = None
    if control == "source":
        vector = deepcopy(original)
    elif control == "zero":
        vector = [0.0] * len(original)
    else:
        # Fixed cyclic permutation by source identity, with no target access.
        order = sorted(range(len(rows)), key=lambda i: (rows[i]["source_sha256"], rows[i]["id"]))
        position = order.index(index)
        other = rows[order[(position + 1) % len(order)]]
        require(other["source_sha256"] != row["source_sha256"], "cross-source donor must be distinct")
        vector = deepcopy(other[key]["input_vector"])
        origin = {"id": other["id"], "source_sha256": other["source_sha256"],
                  "input_sha256": other[key]["input_sha256"]}
    return vector, {"control": control, "receiving_id": row["id"],
        "receiving_source_sha256": row["source_sha256"], "original_input_sha256": digest(original),
        "effective_input_sha256": digest(vector), "donor": origin,
        "provenance": "native_source_receipt" if not donor else "original_donor_source_coordinates",
        "zero_input_is_disabled_context": False, "target_access": False}


def admit_original(value, parent, *, reader, native, training):
    """Authenticate original-start bytes, parent closure and strict saved head."""
    manifest = read_ref(value["manifest"])
    require(manifest.get("schema") == "gte-decoder-interface-training-manifest/v1"
        and manifest.get("completed") is True and manifest.get("training_executed") is True
        and manifest.get("saved_trained_checkpoint_authenticated_and_replayed") is True
        and manifest.get("optimizer_steps") == value["optimizer_steps"]
        and manifest.get("status") == "trained_unqualified", "completed original trained manifest required")
    require(manifest["inputs"][0] == value["config"], "original config binding differs")
    closure = []
    for key in ("inputs", "parent_closure", "implementation_files"):
        for ref in manifest[key]:
            require(file_ref(ref["path"]) == ref, "original training closure changed")
            closure.append(ref)
    output = Path(value["manifest"]["path"]).parent
    exports = {ref["path"]: {**ref, "path": str(output / ref["path"])} for ref in manifest["outputs"]}
    require(len(exports) == len(manifest["outputs"]) and set(exports) == {
        "native-inspection.json", "summary.json", "resources.json", "trained-interfaces.json",
        "training-report.json", "checkpoint-inspection.json", "reload-verification.json"},
        "original training output inventory differs")
    for ref in exports.values():
        require(file_ref(ref["path"]) == ref, "original trained output changed")
        closure.append(ref)
    for key, name in (("checkpoint", "trained-interfaces.json"), ("training_report", "training-report.json"),
                      ("reload_verification", "reload-verification.json")):
        require(value[key] == exports[name], "outer runtime and original manifest disagree")
    cli = training._reference_cli()
    config, payloads, inputs, root = cli._configuration(value["config"]["path"], value["config"]["sha256"], reader, native)
    require(inputs == manifest["inputs"] and config["mode"] == "train", "original configured input closure differs")
    inherited, _ = cli._parent(reader, native, payloads, dict(zip(cli.REFERENCES, inputs[1:])), root)
    require(inherited == manifest["parent_closure"], "original reconstructed parent closure differs")
    require(all(payloads[name] == parent["payloads"][name] for name in (
        "initialization", "donor_pins", "batch", "replay", "native_batch")), "trained starts use different corpora or donors")
    checkpoint = read_ref(value["checkpoint"])
    args = {"initialization": payloads["initialization"], "plan": payloads["native_batch"],
        "batch": payloads["batch"], "replay": payloads["replay"], "expected_donor_pins": payloads["donor_pins"]}
    inspection = native._helper("gte_decoder_interface_checkpoint").inspect_interface_checkpoint(checkpoint, **args)
    require(inspection == read_ref(exports["checkpoint-inspection.json"])
        and checkpoint["training_report"] == read_ref(value["training_report"])
        and checkpoint["training_report"]["optimizer_steps"] == config["steps"], "original checkpoint report differs")
    return checkpoint, args, closure


def run(config_path, expected_sha256, output):
    config_ref = file_ref(config_path)
    require(config_ref["sha256"] == expected_sha256, "configuration SHA256 mismatch")
    config = read_ref(config_ref)
    require(set(config) == {"schema", "workspace_root", "original_runtime", "aligned_runtime",
        "primary_checkpoint", "legacy8_checkpoint"} and config["schema"] == SCHEMA, "closed evaluation config required")
    root = Path(config["workspace_root"]).resolve()
    original_runtime, original_refs = runtime_receipt(config["original_runtime"], expected_start="original_initialization")
    aligned_runtime, aligned_refs = runtime_receipt(config["aligned_runtime"], expected_start="authenticated_aligned_generation")
    training = module("run_gte_aligned_interface_training", Path(__file__).parent)
    native = training._native_cli()
    reader = native._helper("gte_worker_contract")
    parent = module("gte_source_evaluation_parent", Path(__file__).parent).admit_training_parent(
        read_ref(aligned_runtime["manifest"]), aligned_runtime["manifest"], root=root, reader=reader, training_cli=training)
    original_checkpoint, arguments, original_closure = admit_original(original_runtime, parent,
        reader=reader, native=native, training=training)
    p = parent["payloads"]
    primary, legacy = read_ref(config["primary_checkpoint"]), read_ref(config["legacy8_checkpoint"])
    pins = p["donor_pins"]
    require(config["primary_checkpoint"]["sha256"] == pins["teacher384_checkpoint_sha256"]
        and config["legacy8_checkpoint"]["sha256"] == pins["legacy8_checkpoint_sha256"], "donor file hashes differ")
    source = native._helper("gte_decoder_source_evaluation")
    ev = source.prepare_source_evaluation(p["initialization"], p["native_batch"], p["batch"], p["replay"],
        expected_donor_pins=pins, max_primary_rows=60, max_auxiliary_rows=2)
    require(ev["native_ready_row_count"] == ev["selected_row_count"] == 62, "all original evaluation native vectors required")
    comparison = native._helper("gte_decoder_source_comparison")
    _, legacy_snapshot, aligned_arguments, _ = comparison._admit(ev, p["initialization"], p["native_batch"],
        p["batch"], p["replay"], pins, primary, legacy, parent["aligned"]["checkpoint"],
        parent["aligned"]["file_pins"], parent["trained_checkpoint"])
    # Deliberately drop all reference fields from the input to the numerical loop.
    sources = {name: [{key: deepcopy(row[key]) for key in ("id", "source_text", "source_sha256", "evaluation_role",
        "generation_input", "native_generation_input", "native_receipt_sha256")} for row in ev["heads"][name]["rows"]]
        for name in HEADS}
    input_record = {"schema": "gte-native-source-control-inputs/v1", "heads": sources,
        "target_access": False, "contains_references": False, "independent_holdout": False}
    implementations = [file_ref(Path(__file__)), *[file_ref(HELPERS / (name + ".py")) for name in (
        "gte_decoder_source_generation", "gte_decoder_source_evaluation", "gte_decoder_source_comparison",
        "gte_decoder_interface_checkpoint", "gte_aligned_interface_checkpoint")]]
    closure = {ref["path"]: ref for ref in [config_ref, *original_refs, *aligned_refs, *original_closure,
        *parent["closure"], config["primary_checkpoint"], config["legacy8_checkpoint"], *implementations]}
    output = Path(output).resolve()
    require(not output.exists() and output.is_relative_to(root), "fresh output within workspace required")
    output.mkdir(parents=True)
    input_ref = write(output / "inputs.json", input_record)
    planned = {"schema": "gte-native-source-controls-plan/v1", "variants": list(VARIANTS), "controls": list(CONTROLS),
        "heads": list(HEADS), "inputs": input_ref, "configuration": config_ref, "closure": list(closure.values()),
        "per_head_rows": {name: len(sources[name]) for name in HEADS},
        "budgets": {name: {key: ev["heads"][name][key] for key in ("max_new_tokens", "inherited_max_target_tokens")}
                    for name in HEADS},
        "selection": "all_variants_all_controls_no_selection", "all_generation_frozen_before_scoring": True,
        "reference_prefix_used": False, "independent_holdout": False, "proof_authority": False}
    plan_ref = write(output / "plan.json", planned)
    import torch
    torch.set_num_threads(1)
    preserved = native._helper("gte_decoder_transfer_replay")
    generation = native._helper("gte_decoder_source_generation")
    init = p["initialization"]
    donors = {"primary384": preserved._original_primary_model(torch, primary),
        "legacy8": native._helper("gte_legacy8_decoder_donor").load_private_legacy8_decoder_snapshot(legacy_snapshot,
            expected_source_checkpoint_sha256=pins["legacy8_checkpoint_sha256"],
            expected_source_model_state_sha256=pins["legacy8_weights_sha256"])["model"]}
    loaders = {
        "original_initialization": lambda: native._helper("gte_decoder_reuse").load_dual_decoder(init, expected_donor_pins=pins),
        "aligned_initialization": lambda: native._helper("gte_aligned_decoder").load_aligned_decoder(parent["aligned"]["checkpoint"],
            expected_file_pins=parent["aligned"]["file_pins"], expected_donor_pins=pins),
        "original_trained": lambda: native._helper("gte_decoder_interface_checkpoint").load_interface_checkpoint(original_checkpoint, **arguments),
        "aligned_trained": lambda: native._helper("gte_aligned_interface_checkpoint").load_interface_checkpoint(parent["trained_checkpoint"], **aligned_arguments),
    }
    panels = []
    for label in VARIANTS:
        model = None if label == "original_donor" else loaders[label]()
        for control in CONTROLS:
            records = []
            for name in HEADS:
                for index, row in enumerate(sources[name]):
                    vector, intervention = intervention_input(sources[name], index, control, donor=label == "original_donor")
                    selected_model = donors[name] if model is None else model
                    receipt = generation.generate_source_only(selected_model,
                        variant=("donor384" if name == "primary384" else "legacy8") if model is None else "student768",
                        head=name, input_vector=vector, **planned["budgets"][name])
                    generation.inspect_source_only_generation(receipt)
                    records.append({"id": row["id"], "source_text": row["source_text"], "source_sha256": row["source_sha256"],
                        "evaluation_role": row["evaluation_role"], "head": name, "variant": label,
                        "intervention": intervention, "generation": receipt})
            ref = write(output / ("generation-" + label + "-" + control + ".json"),
                {"schema": "gte-native-source-control-generation/v1", "variant": label, "control": control,
                 "reference_prefix_used": False, "references_used_for_generation": False, "rows": records})
            panels.append(ref)
            print(json.dumps({"completed": label, "control": control, "rows": len(records)}), flush=True)
        del model
    # Freeze every variant/control generation before scoring any reference.
    frozen = write(output / "generation-frozen.json", {"schema": "gte-native-source-controls-frozen/v1",
        "plan": plan_ref, "inputs": input_ref, "generation_files": panels,
        "generation_count": sum(len(sources[h]) for h in HEADS) * len(VARIANTS) * len(CONTROLS),
        "all_variants_completed": True, "reference_prefix_used": False,
        "scoring_started": False, "captured_at_utc": datetime.now(timezone.utc).isoformat()})
    scored = []
    for ref in panels:
        panel = read_ref(ref)
        for row in panel["rows"]:
            name = row["head"]
            reference = next(r["reference"] for r in ev["heads"][name]["rows"] if r["id"] == row["id"])
            codec = init["primary" if name == "primary384" else "legacy8"]["codec"]
            score = source.score_generation({key: row["generation"][key] for key in ("generated_ids", "terminated", "truncated")},
                reference, codec, name)
            scored.append({"id": row["id"], "source_text": row["source_text"], "source_sha256": row["source_sha256"],
                "head": name, "variant": row["variant"], "control": panel["control"],
                "evaluation_role": row["evaluation_role"], "generation_file": ref,
                "generation_sha256": digest(row["generation"]), "score": score})
    score_ref = write(output / "scores.json", {"schema": "gte-native-source-control-scores/v1", "generation_freeze": frozen,
        "rows": scored, "reference_prefix_used": False, "independent_holdout": False, "proof_authority": False})
    summary = []
    for label in VARIANTS:
        for control in CONTROLS:
            for name in HEADS:
                rows = [r for r in scored if r["variant"] == label and r["control"] == control and r["head"] == name]
                normal = {r["id"]: r for r in scored if r["variant"] == label and r["control"] == "source" and r["head"] == name}
                summary.append({"variant": label, "control": control, "head": name, "count": len(rows),
                    **{metric: sum(r["score"][metric] for r in rows) for metric in (
                        "syntax_valid", "exact_target_match", "terminated", "truncated", "invalid_generation")},
                    "changed_generated_token_sequences": sum(r["score"]["generated_ids_sha256"] !=
                        normal[r["id"]]["score"]["generated_ids_sha256"] for r in rows)})
    for ref in [*closure.values(), input_ref, plan_ref, *panels, frozen, score_ref]:
        require(file_ref(ref["path"]) == ref, "input or saved output changed before completion")
    report = {"schema": "gte-native-source-controls-summary/v1", "status": "completed_exposed_regression_unqualified",
        "generation_freeze": frozen, "scores": score_ref, "panels": summary,
        "total_generations": len(scored), "source_vector_dimensions": {"primary_donor": 384, "legacy_donor": 8, "native_models": 768},
        "training_executed": False, "optimizer_steps": 0, "reference_prefix_used": False,
        "teacher_forced_loss_used_as_accuracy": False, "independent_holdout": False,
        "source_fidelity_qualified": False, "proof_authority": False,
        "zero_input_interpretation": "zero source coordinates; biases remain active; not a disabled architecture branch",
        "comparison_scope": "60 original exposed validation rows and 2 legacy training diagnostics; fixed inherited vocabularies",
        "training_runtime_receipts": [config["original_runtime"], config["aligned_runtime"]]}
    report_ref = write(output / "summary.json", report)
    print(json.dumps({"status": report["status"], "summary": report_ref}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args()
    run(args.config, args.expected_config_sha256, args.output_directory)


if __name__ == "__main__":
    main()
