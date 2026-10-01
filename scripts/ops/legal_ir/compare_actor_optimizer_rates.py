#!/usr/bin/env python3
"""Predeclared development-only learning-rate comparison on an existing panel.

Only training/tuning formula artifacts are consumed. New heads start from the
same initialization as the recorded .02 run; no continuation, evaluation-label
access, architecture change, weight download, or qualification is performed.
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
from scripts.ops.legal_ir import evaluate_actor_composition_curriculum as ablation

RATES = (0.005, 0.002)
STEPS = 1000
MAX_SECONDS = 120
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
SELECTION_ORDER = ("reference_lr_0p02", "lr_0p005", "lr_0p002")
FALSE = dict(ablation.FALSE, independent_generalization_verified=False,
             evaluation_target_access=False, evaluation_results_used=False,
             checkpoint_promotion_performed=False)
require, raw, sha, write = ablation.require, ablation.raw, ablation.sha, ablation.write


def source_hashes():
    return {**ablation.sources(), str(Path(__file__).resolve()): sha(Path(__file__))}


def read_development_targets(prepared, partition):
    """A closed path gate; evaluation references cannot enter fitting/selection."""
    require(partition in ("training", "tuning"), "only training/tuning targets may be opened")
    reference = prepared["files"][partition]
    require(Path(reference["path"]).name == "targets-" + partition + ".json",
            "development target reference points to another partition")
    return ablation.read_reference(reference)


def selection_key(result):
    """Predeclared order: tuning exact, actor, facet count, then negative CE."""
    metrics, observed = result["generation"]["tuning"], result["report"]["tuning"]
    require(metrics["valid_evaluation"] and metrics["operational_complete"],
            "selection requires complete free-running generation evidence")
    require(observed["complete"] and observed["rows_evaluated"] == 6,
            "selection requires complete tuning loss observations")
    loss = observed["token_cross_entropy"]
    require(type(loss) in (float, int) and math.isfinite(loss), "selection requires finite tuning cross-entropy")
    return (metrics["exact_reconstruction"]["matched"], metrics["facets"]["actor"]["matched"],
            sum(metrics["facets"][field]["matched"] for field in FACETS), -float(loss))


def choose_development_candidate(results):
    require(set(results) == set(SELECTION_ORDER), "all predeclared candidates must be retained")
    # Python's max preserves the first candidate on an exact tie. The recorded
    # reference is preferred when no predeclared measure improves.
    return max(SELECTION_ORDER, key=lambda identifier: selection_key(results[identifier]))


def run(input_directory, output_directory):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas

    started, sources = time.perf_counter(), source_hashes()
    plan, curriculum, prepared, samples = ablation.prepared_inputs(input_directory)
    frozen, prior_fits = ablation.verify_frozen_artifacts(input_directory, plan)
    reference = prior_fits["balanced"]
    require(plan["optimizer_steps_per_arm"] == STEPS and plan["formula_options"] == ablation.OPTIONS,
            "reference does not match the declared fixed-budget .02 experiment")
    require(reference["training_row_count"] == 24 and reference["tuning_row_count"] == 6,
            "reference training/tuning split differs")
    targets = read_development_targets(prepared, "training")
    tuning_targets = read_development_targets(prepared, "tuning")
    training = [samples[row["id"]] for row in curriculum.rows("training", training_subset="balanced")]
    tuning = [samples[row["id"]] for row in curriculum.rows("tuning")]
    require(len(training) == len(targets) == 24 and len(tuning) == len(tuning_targets) == 6,
            "development sample/target counts differ")
    references = {name: ablation.reference(input_directory / name)
                  for name in ("plan.json", "prepared.json", "frozen.json", "balanced-training.json")}
    references.update(training_targets=prepared["files"]["training"], tuning_targets=prepared["files"]["tuning"],
                      reference_head=frozen["heads"]["balanced"])
    baseline_head = ablation.read_reference(references["reference_head"])
    output_directory.mkdir(parents=True, exist_ok=False)
    development_plan = dict(schema="actor-optimizer-development-plan/v1", source_hashes=sources,
        input_artifacts=references, input_directory=str(input_directory), rates=list(RATES),
        optimizer_steps_per_candidate=STEPS, max_seconds_per_candidate=MAX_SECONDS,
        shared_options_except_learning_rate=ablation.OPTIONS, reference_learning_rate=0.02,
        initial_identity=reference["initial_identity"], training_rows=24, tuning_rows=6,
        selection_criteria=["tuning_exact_rule_count", "tuning_actor_match_count",
                            "sum_tuning_seven_facet_matches", "negative_tuning_teacher_forced_token_cross_entropy"],
        exact_tie_order=list(SELECTION_ORDER), evaluation_partition_never_opened=True,
        seed_count=1, causal_learning_rate_effect_established=False,
        inference_input="same source-bound raw modal representation as the reference",
        training_scope="fresh frozen sparse core; residual projection and formula head only",
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
        metric_disk_cache=False, legal_ir_parallel_workers=1, sample_memory=False, temperature=0, **FALSE)
    write(output_directory / "plan.json", development_plan)
    plan_sha = sha(output_directory / "plan.json")
    results = {"reference_lr_0p02": reference}
    for rate, identifier in zip(RATES, SELECTION_ORDER[1:]):
        runtime = runtimes.open_runtime("legal_ir", "current_v2", compute_device="cpu")
        core = raw(runtime.model.state.to_dict())
        options = dict(ablation.OPTIONS, learning_rate=rate)
        initial = learning.build_checkpoint(joint._core_binding(runtime.model),
            joint._rows(runtime.model, training, targets), joint._rows(runtime.model, tuning, tuning_targets), **options)
        identity = {name: learning.checkpoint_digest(initial[name]) for name in ("binding", "codec", "model_state")}
        require(all(identity[name] == reference["initial_identity"][name] for name in identity),
                "fresh candidate differs from reference initialization, vocabulary or core")
        require({name: value for name, value in initial["config"].items() if name != "learning_rate"} ==
                {name: value for name, value in baseline_head["config"].items() if name != "learning_rate"},
                "candidate changes more than its learning rate")
        require(initial["training_manifest_sha256"] == baseline_head["training_manifest_sha256"]
                and initial["tuning_manifest_sha256"] == baseline_head["tuning_manifest_sha256"],
                "candidate raw inputs/targets differ from reference manifests")
        runtime.model.attach_formula_checkpoint(initial)
        fitted = runtime.train(training, validation_samples=tuning, formula_targets=targets,
            validation_formula_targets=tuning_targets, epochs=1000, max_optimizer_steps=STEPS, max_seconds=MAX_SECONDS)
        report = fitted["report"]
        require(report["optimizer_steps"] == STEPS and report["training_after"]["complete"] and report["tuning"]["complete"],
                "candidate failed to complete its predeclared budget/observations")
        require(raw(runtime.model.state.to_dict()) == core, "candidate changed sparse core weights")
        for group in ("projection", "decoder"):
            evidence = report["parameter_evidence"][group]
            require(evidence["parameter_update_l2"] > 0 and evidence["gradient_norm_max"] > 0,
                    "candidate parameter group received no actual update")
        outputs = {"training": runtime.infer(training), "tuning": runtime.infer(tuning)}
        generation = {partition: compare_free_running_formulas(outputs[partition], labels, partition=partition)
                      for partition, labels in (("training", targets), ("tuning", tuning_targets))}
        require(all(metric["valid_evaluation"] and metric["operational_complete"] for metric in generation.values()),
                "candidate generation evidence is incomplete")
        head = runtime.model.save_formula_checkpoint(output_directory / (identifier + "-head.json"))
        require(head["sha256"] == report["checkpoint_sha256"] and
                all(value["checkpoint_sha256"] == head["sha256"] for value in outputs.values()),
                "candidate report, inference and saved head differ")
        reloaded = runtimes.open_runtime("legal_ir", "current_v2", compute_device="cpu",
            formula_checkpoint=head["path"], formula_sha256=head["sha256"])
        require(reloaded.infer(tuning) == outputs["tuning"], "candidate checkpoint reload changes predictions")
        results[identifier] = dict(learning_rate=rate, initial_identity=identity, head=head, report=report,
            outputs=outputs, generation=generation, reload_prediction_exact=True,
            training_rows=24, tuning_rows=6, sparse_core_unchanged=True, **FALSE)
        write(output_directory / (identifier + "-development.json"), results[identifier])
        print(json.dumps({"candidate": identifier, "optimizer_steps": report["optimizer_steps"],
                          "training_exact": generation["training"]["exact_reconstruction"],
                          "tuning_exact": generation["tuning"]["exact_reconstruction"]}), flush=True)
    require(source_hashes() == sources, "producer sources changed during development comparison")
    require(sha(output_directory / "plan.json") == plan_sha, "predeclared development plan changed")
    for value in references.values():
        ablation.read_reference(value)
    selected = choose_development_candidate(results)
    summary = dict(schema="actor-optimizer-development-result/v1", operational_ok=True,
        plan_sha256=plan_sha, plan=development_plan, candidates=results,
        selected_development_candidate=selected,
        selection_keys={name: selection_key(value) for name, value in results.items()},
        hyperparameter_selection_performed=True, selection_partition="tuning_only",
        evaluation_partition_never_opened=True, independent_evaluation_required_before_generalization_claim=True,
        causal_learning_rate_effect_established=False, seed_count=1,
        elapsed_seconds=time.perf_counter()-started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        lake_executed=False, full_logic_floor_coverage=False, teacher_weights_loaded=False,
        bridge_on_evaluate=None, **FALSE)
    write(output_directory / "report.json", summary)
    print(json.dumps({"selected_development_candidate": selected,
                      "selection_keys": summary["selection_keys"], **FALSE}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS"] = "0"
    run(args.input_directory.resolve(), args.output_directory.resolve())


if __name__ == "__main__":
    main()
