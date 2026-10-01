#!/usr/bin/env python3
"""Bounded current-384D reconstruction ablations; train/tuning observations only.

Uses existing architecture and separate fresh heads. Shared compiler weak labels
and verified local embeddings are prepared once. No legacy weights are loaded,
no evaluation labels enter fitting/selection, and no candidate is promoted.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import evaluate_actor_composition_curriculum as shared

PROFILE_IDS = ("baseline_v1", "raw_gain10_v1", "reconstruction_x10_v1")
MAX_SECONDS = 120
STEPS = 1000
FALSE = dict(shared.FALSE, independent_generalization_verified=False,
             checkpoint_promotion_performed=False, teacher_weights_loaded=False)
require, sha, raw, write = shared.require, shared.sha, shared.raw, shared.write


def profiles():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile
    return {name: get_training_profile(name) for name in PROFILE_IDS}


def sources():
    files = [Path(__file__), ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/formula_training_profiles.py"]
    return {**shared.sources(), **{str(path): sha(path) for path in files}}


def development_targets(prepared, partition):
    require(partition in ("training", "tuning"), "only training/tuning targets may be consumed")
    ref = prepared["files"][partition]
    require(Path(ref["path"]).name == "targets-" + partition + ".json", "target partition reference differs")
    return shared.read_reference(ref)


def require_raw_gain(reference, candidate, gain):
    """Check actual raw inputs, not merely the requested constructor options."""
    require(type(gain) in (int, float) and math.isfinite(gain) and gain > 0, "finite positive gain required")
    require(len(reference) == len(candidate), "raw row count differs")
    for before, after in zip(reference, candidate):
        require({k: v for k, v in before.items() if k != "latent"} ==
                {k: v for k, v in after.items() if k != "latent"}, "raw input provenance/targets differ")
        require(len(before["latent"]) == len(after["latent"]), "raw input dimension differs")
        require(all(type(x) in (int, float) and type(y) in (int, float) and
                    math.isfinite(x) and math.isfinite(y) and math.isfinite(gain * x) and
                    math.isclose(y, gain * x, rel_tol=1e-12, abs_tol=1e-14)
                    for x, y in zip(before["latent"], after["latent"])), "raw conditioning gain differs")


def training_candidate_key(result):
    train, tune = result["generation"]["training"], result["generation"]["tuning"]
    require(all(m["valid_evaluation"] and m["operational_complete"] for m in (train, tune)),
            "selection requires complete free-running evidence")
    loss = result["training"]["report"]["training_after"]
    require(loss["complete"] and math.isfinite(loss["token_cross_entropy"]), "selection requires finite complete loss")
    return (train["exact_reconstruction"]["matched"], tune["exact_reconstruction"]["matched"],
            sum(value["matched"] for value in tune["facets"].values()), -loss["token_cross_entropy"])


def select_training_candidate(results):
    require(set(results) == set(PROFILE_IDS), "all predeclared profiles must complete")
    return max(PROFILE_IDS, key=lambda name: training_candidate_key(results[name]))


def condition_diagnostics(checkpoint, rows):
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    decoder = learning.LatentFormulaDecoder(checkpoint)
    with torch.no_grad():
        latent = torch.tensor([row["latent"] for row in rows], dtype=torch.float32)
        projected = decoder.model.project(latent)
        hidden = decoder.model.start(projected)
        require(bool(torch.isfinite(projected).all()) and bool(torch.isfinite(hidden).all()), "nonfinite conditioning")
        return dict(raw_mean_l2=float(latent.norm(dim=1).mean()),
                    projected_mean_l2=float(projected.norm(dim=1).mean()),
                    condition_abs_above_0p99_fraction=float((hidden.abs() > .99).float().mean()),
                    rows=len(rows), labels_used_for_conditioning=False, **FALSE)


def run(directory):
    started = time.perf_counter()
    specifications, producer = profiles(), sources()
    directory.mkdir(parents=True, exist_ok=False)
    plan = dict(schema="formula-reconstruction-comparison-plan/v1", profiles=specifications,
        profile_order=list(PROFILE_IDS), source_hashes=producer, optimizer_steps=STEPS,
        max_seconds_per_profile=MAX_SECONDS, seed_count=1,
        selection_criteria=["training_exact", "tuning_exact", "tuning_total_facet_matches", "negative_training_token_ce"],
        evaluation_targets_used=False, full_logic_floor_coverage=False,
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
        metric_disk_cache=False, legal_ir_parallel_workers=1, sample_memory=False, temperature=0, **FALSE)
    write(directory / "plan.json", plan)
    plan_sha = sha(directory / "plan.json")
    shared.prepare(directory / "inputs", optimizer_steps=STEPS)
    _, curriculum, prepared, samples = shared.prepared_inputs(directory / "inputs")
    # Preparation produces all panel artifacts; this fitting/selection path
    # deliberately consumes only the training and tuning label partitions.
    targets = development_targets(prepared, "training")
    tuning_targets = development_targets(prepared, "tuning")
    training = [samples[row["id"]] for row in curriculum.rows("training")]
    tuning = [samples[row["id"]] for row in curriculum.rows("tuning")]
    require(len(training) == len(targets) == 24 and len(tuning) == len(tuning_targets) == 6, "unexpected development split")
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas

    results, initial_identity, reference_rows, reference_binding = {}, None, None, None
    for name in PROFILE_IDS:
        spec = specifications[name]
        runtime = runtimes.open_runtime("legal_ir", "current_v2", **spec["core_options"])
        original_core = raw(runtime.model.state.to_dict())
        binding = joint._core_binding(runtime.model)
        rows = joint._rows(runtime.model, training, targets)
        tune_rows = joint._rows(runtime.model, tuning, tuning_targets)
        if reference_rows is None:
            reference_rows, reference_binding = rows, binding
        require_raw_gain(reference_rows, rows, 10. if name == "raw_gain10_v1" else 1.)
        require((binding == reference_binding) == (name != "raw_gain10_v1"), "unexpected core configuration change")
        checkpoint = learning.build_checkpoint(binding, rows, tune_rows, **spec["formula_options"])
        identity = {key: learning.checkpoint_digest(checkpoint[key]) for key in ("model_state", "codec")}
        require(initial_identity is None or identity == initial_identity, "initial model weights/vocabulary differ")
        initial_identity = identity
        initial_condition = condition_diagnostics(checkpoint, rows)
        runtime.model.attach_formula_checkpoint(checkpoint)
        trained = runtime.train(training, validation_samples=tuning, formula_targets=targets,
            validation_formula_targets=tuning_targets, epochs=1000, max_optimizer_steps=STEPS, max_seconds=MAX_SECONDS)
        report = trained["report"]
        require(report["optimizer_steps"] == STEPS, "profile did not complete its fixed update budget")
        require(report["training_after"]["complete"] and report["tuning"]["complete"], "loss observations incomplete")
        require(raw(runtime.model.state.to_dict()) == original_core, "sparse core mutated")
        for group in ("projection", "decoder"):
            require(report["parameter_evidence"][group]["parameter_update_l2"] > 0, "parameter group did not train")
        tick = time.perf_counter()
        outputs = dict(training=runtime.infer(training), tuning=runtime.infer(tuning))
        seconds = time.perf_counter() - tick
        generation = {partition: compare_free_running_formulas(outputs[partition], labels, partition=partition)
                      for partition, labels in (("training", targets), ("tuning", tuning_targets))}
        require(all(m["valid_evaluation"] and m["operational_complete"] for m in generation.values()), "generation evidence incomplete")
        head = runtime.model.save_formula_checkpoint(directory / (name + "-head.json"))
        require(head["sha256"] == report["checkpoint_sha256"] and
                all(output["checkpoint_sha256"] == head["sha256"] for output in outputs.values()), "head identity differs")
        reloaded = runtimes.open_runtime("legal_ir", "current_v2", **spec["core_options"],
            formula_checkpoint=head["path"], formula_sha256=head["sha256"])
        require(reloaded.infer(tuning) == outputs["tuning"], "reload changed predictions")
        final_condition = condition_diagnostics(trained["checkpoint"], rows)
        resume = dict(validation_samples=tuning, formula_targets=targets, validation_formula_targets=tuning_targets,
                      epochs=1, max_optimizer_steps=1, max_seconds=60)
        require(runtime.train(training, **resume)["checkpoint"] == reloaded.train(training, **resume)["checkpoint"],
                "resumed and uninterrupted updates differ")
        results[name] = dict(profile=spec, head=head, core_binding=binding, initial_identity=identity,
            training=dict(report=report), outputs=outputs, generation=generation,
            condition_before=initial_condition, condition_after=final_condition,
            reload_prediction_exact=True, resume_checkpoint_exact=True,
            extra_resume_step_excluded_from_scored_head=True, core_sparse_state_unchanged=True,
            generation_seconds=seconds, generation_wall_seconds_per_span=seconds/30, **FALSE)
        write(directory / (name + "-result.json"), results[name])
        print(json.dumps(dict(profile=name, train=generation["training"]["exact_reconstruction"],
                              tuning=generation["tuning"]["exact_reconstruction"])), flush=True)
    require(sources() == producer and sha(directory / "plan.json") == plan_sha, "sealed producer/plan changed")
    selected = select_training_candidate(results)
    # Schema builds concern the already-scored selected checkpoint, never an
    # extra resumed step or a changed model selected using build outcomes.
    chosen = results[selected]
    runtime = runtimes.open_runtime("legal_ir", "current_v2", **chosen["profile"]["core_options"],
        formula_checkpoint=chosen["head"]["path"], formula_sha256=chosen["head"]["sha256"])
    write(directory / "frozen.json", dict(plan_sha256=plan_sha,
        candidate_reports={name: shared.reference(directory / (name + "-result.json")) for name in PROFILE_IDS},
        selected_training_candidate=selected, selection_is_not_promotion=True, **FALSE))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_decoded_schema as schemas
    schema = schemas.validate_decoded_outputs(runtime, training+tuning,
        output_directory=directory / "selected-schema", timeout_seconds=60)
    require(schema["checkpoint_sha256"] == chosen["head"]["sha256"], "schema checks used another checkpoint")
    schema_ok = shared.schema_checks_passed(schema, 30)
    require(sources() == producer, "producer changed during schema validation")
    result = dict(schema="formula-reconstruction-comparison/v1", plan=plan, prepared=prepared,
        results=results, selected_training_candidate=selected, selection_is_not_promotion=True,
        generated_schema=schema, operational_ok=schema_ok, evaluation_targets_used=False,
        training_quality_improved=chosen["generation"]["training"]["exact_reconstruction"]["matched"] >
                                  results["baseline_v1"]["generation"]["training"]["exact_reconstruction"]["matched"],
        seed_count=1, held_out_generalization_evaluated=False, full_logic_floor_coverage=False,
        temporal_kind_sidecars_encoded_by_head=False, bridge_on_evaluate=None, legal_ir_target_count=0,
        elapsed_seconds=time.perf_counter()-started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        **FALSE)
    write(directory / "report.json", result)
    require(schema_ok, "schema execution incomplete; inspect retained report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"] = "0"
    run(args.output_directory.resolve())


if __name__ == "__main__":
    main()
