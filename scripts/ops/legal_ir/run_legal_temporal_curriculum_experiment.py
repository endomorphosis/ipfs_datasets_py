#!/usr/bin/env python3
"""Matched architecture-by-temporal-curriculum fitting and sealed generation.

No challenge target bytes are opened in this process. Selected models and parent
fallbacks keep distinct trial identities; every trained stage remains auditable.
The separate qualifier replays, compiles and only then opens challenge targets.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_grounding_experiment as previous
from scripts.ops.legal_ir import run_legal_mixed_replay_experiment as prior_mixed
from scripts.ops.legal_ir.compare_legal_decoder_architectures import score

require, read, sha, write, digest = previous.require, previous.read, previous.sha, previous.write, previous.digest
ref, read_ref, source_rows, generate, comparable = previous.ref, previous.read_ref, previous.source_rows, previous.generate, previous.comparable
SCHEMA = "legal-temporal-curriculum-experiment/v1"
SEEDS = (1729, 1730, 1731)
ARMS = {
    f"{curriculum}_{architecture}": {"curriculum": curriculum, "architecture": architecture, "enabled": enabled}
    for curriculum in ("baseline", "temporal_augmented")
    for architecture, enabled in (("continuation", False), ("grounding", True))
}
TUNING_PANELS = ("earlier", "prior_new", "temporal")
STAGE_STEPS = 400
NORMAL_PANELS = ("tuning_earlier", "tuning_prior_new", "tuning_temporal", "fresh", "earlier_regression", "exposed_regression", "mixed_regression")
FALSE = {"qualified": False, "production_ready": False, "semantic_correctness_verified": False,
         "all_logic_families_supported": False, "statutory_gold_available": False, "promotion_performed": False}


def target_metadata(reference):
    require(type(reference) is dict and set(reference) == {"path", "sha256", "bytes"}
        and type(reference["path"]) is str and reference["path"]
        and type(reference["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", reference["sha256"])
        and type(reference["bytes"]) is int and reference["bytes"] > 0, "closed sealed-target commitment required")


def select_retained_stage(stages, parent_tuning_exact):
    """Earlier-tuning retention first, then temporal/prior-new/earlier/earliest."""
    require(type(parent_tuning_exact) is int and 0 <= parent_tuning_exact <= 96, "bounded parent tuning exact required")
    require(type(stages) is list and stages and len({r["steps"] for r in stages}) == len(stages), "unique stages required")
    bounds = {"earlier": 96, "prior_new": 96, "temporal": 120}
    for stage in stages:
        require(type(stage["steps"]) is int and stage["steps"] > 0 and all(
            type(stage["tuning_" + panel + "_exact"]) is int and
            0 <= stage["tuning_" + panel + "_exact"] <= bound for panel, bound in bounds.items()), "valid tuning counts required")
    eligible = [stage for stage in stages if stage["tuning_earlier_exact"] >= parent_tuning_exact - 1]
    return max(eligible, key=lambda stage: (stage["tuning_temporal_exact"], stage["tuning_prior_new_exact"],
        stage["tuning_earlier_exact"], -stage["steps"])) if eligible else None


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_temporal_curriculum as corpus_module
    config = read(path)
    keys = {"schema", "corpus_manifest", "parent_heads", "baseline_reference_heads",
        "earlier_regression_sources", "earlier_regression_targets", "exposed_regression_sources", "exposed_regression_targets",
        "mixed_regression_sources", "mixed_regression_targets", "prior_curriculum_design", "producer_files"}
    targets = {"earlier_regression_targets", "exposed_regression_targets", "mixed_regression_targets"}
    require(type(config) is dict and set(config) == keys and config["schema"] == "legal-temporal-curriculum-run-config/v1",
        "closed temporal curriculum configuration required")
    for key in keys - {"schema", "producer_files"} - targets:
        read_ref(config[key], parse=False)
    for key in targets:
        target_metadata(config[key])
    for item in config["producer_files"]:
        read_ref(item, parse=False)
    loaded = corpus_module.load_training_inputs(config["corpus_manifest"]["path"])
    manifest, training, tuning, fresh = (loaded[key] for key in ("manifest", "training", "tuning", "fresh_sources"))
    target_metadata(manifest["artifacts"]["challenge_targets"])
    require(set(training) == {"baseline", "temporal_augmented"} and set(tuning) == set(TUNING_PANELS),
        "exact curriculum/tuning inventories required")
    require(len(training["baseline"]) == 1752 and len(training["temporal_augmented"]) == 2352 and
        [len(tuning[panel]) for panel in TUNING_PANELS] == [96, 96, 120] and len(fresh) == 180,
        "declared complete temporal corpus counts required")
    require(training["temporal_augmented"][:1752] == training["baseline"], "augmentation must retain the exact ordered baseline")
    for curriculum, rows in training.items():
        require(sum(row["domain"] == "earlier" for row in rows) == 1152 and
            sum(row["domain"] == "new" for row in rows) == (600 if curriculum == "baseline" else 1200),
            "exact old/new training inventory required")
    require(all(row["domain"] == ("earlier" if panel == "earlier" else "new") for panel in TUNING_PANELS
                for row in tuning[panel]), "tuning domains differ")
    old_regression = read_ref(config["earlier_regression_sources"])["challenge"]
    exposed_regression = read_ref(config["exposed_regression_sources"])
    mixed_regression = read_ref(config["mixed_regression_sources"])
    require([len(rows) for rows in (old_regression, exposed_regression, mixed_regression)] == [192, 150, 144],
        "complete exposed regression inventories required")
    for rows in (fresh, old_regression, exposed_regression, mixed_regression):
        require(all(not {"canonical_ir", "facet_spans", "trigger_span"} & set(row) for row in rows),
            "generation sources contain targets")
    groups = [source_rows(rows) for rows in (training["temporal_augmented"],
        *[tuning[panel] for panel in TUNING_PANELS], fresh, old_regression, exposed_regression, mixed_regression)]
    seen_ids, seen_texts = set(), set()
    for group in groups:
        ids, texts = {row["id"] for row in group}, {row["source_sha256"] for row in group}
        require(len(ids) == len(texts) == len(group) and not ids & seen_ids and not texts & seen_texts,
            "temporal fitting/evaluation sources overlap")
        seen_ids |= ids
        seen_texts |= texts
    inventory = read_ref(config["parent_heads"])
    parents = [row for row in inventory if row["arm"] == "source_only"]
    require(len(parents) == 3 and {row["seed"] for row in parents} == set(SEEDS), "three unique original parent seeds required")
    parents = {row["seed"]: row["checkpoint"] for row in parents}
    baseline_heads = read_ref(config["baseline_reference_heads"])
    require(len(baseline_heads) == 6 and {row["name"] for row in baseline_heads} == {
        f"mixed_{architecture}-{seed}" for architecture in ("continuation", "grounding") for seed in SEEDS},
        "complete previous baseline stage inventory required")
    baseline_stages = {}
    for head in baseline_heads:
        require(head["parent"] == parents[head["seed"]] and [row["steps"] for row in head["stages"]] == [400, 800],
            "previous baseline parent or stages differ")
        baseline_stages[head["name"].removeprefix("mixed_")] = head["stages"]
    return {"config": config, "manifest": manifest, "training": training, "tuning": tuning,
        "sources": dict(zip(NORMAL_PANELS, groups[1:])), "parents": parents, "baseline_stages": baseline_stages}


def verify_baseline_reproduction(checkpoint, previous_checkpoint):
    """Expanded tuning metadata cannot alter baseline weights, moments or draws."""
    require(checkpoint["source_parent_checkpoint_sha256"] == previous_checkpoint["source_parent_checkpoint_sha256"],
        "baseline source parent differs")
    require(checkpoint["config"] == previous_checkpoint["config"] and
        checkpoint["training_manifest_sha256"] == previous_checkpoint["training_manifest_sha256"],
        "baseline fit configuration or training sources differ")
    for key in ("model_state", "optimizer_state", "progress"):
        require(checkpoint[key] == previous_checkpoint[key], "baseline numerical reproduction differs: " + key)
    return {"model_state_exact": True, "optimizer_moments_exact": True, "sampler_progress_exact": True,
        "model_state_sha256": digest(checkpoint["model_state"]),
        "optimizer_state_sha256": digest(checkpoint["optimizer_state"]),
        "comparison": "same fitting inputs/math/updates; expanded tuning metadata intentionally differs",
        "target_access": False}


def fit_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    parent = dimensions.load_checkpoint(job["parent"]["path"], expected_sha256=job["parent"]["sha256"])
    require(parent["config"]["seed"] == job["seed"] and parent["config"]["latent_dimension"] == 0,
        "same-seed original source-only parent required")
    tuning = [row for panel in TUNING_PANELS for row in job["tuning"][panel]]
    checkpoint = mixed.build_checkpoint(parent, job["training"], tuning, trigger_enabled=job["enabled"], learning_rate=.001, batch_size=12)
    initial_sha = digest(checkpoint)
    initial_model_sha = checkpoint["initial_model_state_sha256"]
    initial_source_sha = checkpoint["initial_source_model_sha256"]
    folder = Path(job["folder"])
    folder.mkdir()
    parent_decoder, initial_decoder = dimensions.DimensionalSpanDecoder(parent), mixed.MixedReplayDecoder(checkpoint)
    parent_scores, initial_reports = {}, {}
    for panel in TUNING_PANELS:
        sources = source_rows(job["tuning"][panel])
        original = generate(parent_decoder, sources, parent=True)
        initial = generate(initial_decoder, sources)
        require(comparable(original) == comparable(initial), "initial source predictions/diagnostics differ from parent")
        metric = score(original["rows"], sources, job["tuning"][panel])
        parent_scores[panel] = metric["exact"]
        initial_reports[panel] = {"parent_generation": original, "initial_generation": initial, "parent_metrics": metric}
    initialization = write(folder / "initialization.json", {"parent": job["parent"], "checkpoint_sha256": initial_sha,
        "source_model_sha256": mixed.initial_source_model_digest(checkpoint), "panels": initial_reports,
        "all_tuning_source_predictions_and_recorded_span_logits_equal": True})
    stages = []
    for ordinal in (1, 2):
        previous_sha = digest(checkpoint)
        result = mixed.train_decoder(checkpoint, job["training"], tuning, max_steps=STAGE_STEPS, max_seconds=600)
        checkpoint = result["checkpoint"]
        steps = mixed.optimizer_steps(checkpoint)
        require(steps == ordinal * STAGE_STEPS, "complete matched training budget required")
        stage = {"steps": steps, "checkpoint": mixed.save_checkpoint(checkpoint, folder / f"checkpoint-{steps}.json"),
            "previous_checkpoint_sha256": previous_sha, "training_report": write(folder / f"training-{steps}.json", result["report"])}
        decoder = mixed.MixedReplayDecoder(checkpoint)
        for panel in TUNING_PANELS:
            sources = source_rows(job["tuning"][panel])
            generation = generate(decoder, sources)
            metric = score(generation["rows"], sources, job["tuning"][panel])
            stage["tuning_" + panel] = write(folder / f"tuning-{panel}-{steps}.json", {"generation": generation, "metrics": metric})
            stage["tuning_" + panel + "_exact"] = metric["exact"]
        if job["curriculum"] == "baseline":
            prior_reference = next(row["checkpoint"] for row in job["baseline_stages"] if row["steps"] == steps)
            prior_checkpoint = mixed.load_checkpoint(prior_reference["path"], expected_sha256=prior_reference["sha256"])
            stage["baseline_reproduction"] = {"previous_checkpoint": prior_reference,
                **verify_baseline_reproduction(checkpoint, prior_checkpoint)}
        else:
            stage["baseline_reproduction"] = None
        stage["retention_eligible"] = stage["tuning_earlier_exact"] >= parent_scores["earlier"] - 1
        stages.append(stage)
        print(json.dumps({"phase": "trained", "arm": job["arm"], "seed": job["seed"], "steps": steps,
            "earlier_tuning_exact": stage["tuning_earlier_exact"], "prior_new_tuning_exact": stage["tuning_prior_new_exact"],
            "temporal_tuning_exact": stage["tuning_temporal_exact"],
            "retention_eligible": stage["retention_eligible"], "parent_earlier_tuning_exact": parent_scores["earlier"]}), flush=True)
    selected = select_retained_stage(stages, parent_scores["earlier"])
    return {"name": f"{job['arm']}-{job['seed']}", "arm": job["arm"], "seed": job["seed"],
        "architecture": job["architecture"], "curriculum": job["curriculum"],
        "requested_enabled": job["enabled"], "enabled": job["enabled"] if selected is not None else False,
        "decoder_kind": "mixed" if selected is not None else "parent", "selection": "candidate" if selected is not None else "parent_fallback",
        "checkpoint": selected["checkpoint"] if selected is not None else job["parent"],
        "selected_steps": selected["steps"] if selected is not None else 0, "executed_steps": 800,
        "parent": job["parent"], "parent_tuning_exact": parent_scores, "initialization": initialization, "stages": stages,
        "initial_checkpoint_sha256": initial_sha, "initial_model_state_sha256": initial_model_sha,
        "initial_source_model_sha256": initial_source_sha}


def generation_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    item = job["item"]
    is_parent = item["decoder_kind"] == "parent"
    module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if is_parent else (mixed, mixed.MixedReplayDecoder)
    checkpoint = module.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"])
    decoder = cls(checkpoint)
    folder = Path(job["folder"])
    folder.mkdir(exist_ok=True)
    files = {}
    for panel in NORMAL_PANELS:
        files[panel] = write(folder / f"{panel}-generation.json", generate(decoder, job["sources"][panel], parent=is_parent))
    if item["enabled"]:
        require(not is_parent, "fallback cannot have enabled new residuals")
        files["fresh_disabled"] = write(folder / "fresh-disabled-generation.json", generate(decoder, job["sources"]["fresh"], ablation="disabled"))
    print(json.dumps({"phase": "generated", "model": item["name"], "decoder_kind": item["decoder_kind"]}), flush=True)
    return item["name"], files


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from scripts.ops.legal_ir import prepare_legal_temporal_curriculum as corpus_module
    require(1 <= args.workers <= 3, "one to three workers required")
    inputs = load_config(args.config)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in
        (previous, previous.shared, prior_mixed, dimensions, mixed, corpus_module, sys.modules[score.__module__], sys.modules[__name__])}
    plan = {"schema": SCHEMA, "config": ref(args.config), "arms": ARMS, "seeds": list(SEEDS), "stage_steps": STAGE_STEPS,
        "stages": 2, "learning_rate": .001, "batch_size": 12, "domain_batch_sizes": {"earlier": 6, "new": 6},
        "training_domain_counts": {"baseline": {"earlier": 1152, "new": 600},
            "temporal_augmented": {"earlier": 1152, "new": 1200}}, "counts": {k: len(v) for k, v in inputs["sources"].items()},
        "producer_pins": pins, "retention_tolerance": 1,
        "selection": "eligible if earlier_tuning_exact >= parent_earlier_exact-1; maximize temporal exact, prior_new exact, earlier exact, then earliest step; no eligible means unchanged parent",
        "objective": "equal earlier/new domain means for semantic and actor losses; trigger loss over supervised new rows only",
        "fit_target_policy": "earlier trigger labels remain null and masked; canonical facet labels retained",
        "comparison_scope": "matched architecture by curriculum; both curricula use six old plus six new rows; augmented new pool doubles, so prior-new exposure is diluted at fixed updates",
        "architecture_changed": False, "temporal_head_added": False, "loss_weights_changed": False,
        "baseline_exact_reproduction_required": True, "common_tuning_panels": list(TUNING_PANELS),
        "fresh_panel_scope": inputs["manifest"].get("scope", "fresh authored sources; construction exposure audit in corpus manifest"),
        "challenge_target_access": False, "regression_target_access": False,
        "torch_device": "cpu", "torch_threads_per_worker": 1, "optimizer_trajectory_replay_required": False, **FALSE}
    plan_ref = write(output / "plan.json", plan)
    source_ref = write(output / "source-inputs.json", inputs["sources"])
    jobs = [{"arm": arm, **settings, "seed": seed, "parent": inputs["parents"][seed],
        "training": inputs["training"][settings["curriculum"]], "tuning": inputs["tuning"],
        "baseline_stages": inputs["baseline_stages"][f"{settings['architecture']}-{seed}"],
        "folder": str(output / f"{arm}-{seed}")} for arm, settings in ARMS.items() for seed in SEEDS]
    heads = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(fit_job, job) for job in jobs]):
            heads.append(future.result())
    heads.sort(key=lambda r: r["name"])
    for seed in SEEDS:
        same_seed = [head for head in heads if head["seed"] == seed]
        require(len(same_seed) == 4 and len({head["initial_model_state_sha256"] for head in same_seed}) == 1
            and len({head["initial_source_model_sha256"] for head in same_seed}) == 1,
            "architecture/curriculum initial tensors differ")
    heads_ref = write(output / "heads-frozen.json", heads)
    items = heads + [{"name": f"parent-{seed}", "arm": "parent", "seed": seed, "checkpoint": inputs["parents"][seed],
        "decoder_kind": "parent", "selection": "unchanged_parent", "enabled": False,
        "architecture": "parent", "curriculum": "parent",
        "requested_enabled": False, "selected_steps": 0, "executed_steps": 0} for seed in SEEDS]
    files = {}
    jobs = [{"item": item, "sources": inputs["sources"], "folder": str(output / item["name"])} for item in items]
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(generation_job, job) for job in jobs]):
            name, generated = future.result()
            files[name] = generated
    require(all(sha(path) == wanted for path, wanted in pins.items()), "producer changed during experiment")
    refreshed = load_config(args.config)
    require(refreshed == inputs, "fitting/source inputs changed during experiment")
    result = {"schema": SCHEMA, "plan": plan_ref, "sources": source_ref, "heads": heads_ref, "models": items,
        "files": files, "all_training_selection_and_generation_complete": True,
        "challenge_targets_opened": False, "regression_targets_opened": False,
        "retention_gate_failures": [item["name"] for item in heads if item["selection"] == "parent_fallback"],
        "executed_optimizer_updates": 9600, "all_architecture_curriculum_initial_tensors_match": True,
        "all_twelve_baseline_stage_reproductions_exact": True, **FALSE}
    write(output / "generation-frozen.json", result)
    print(json.dumps({"phase": "frozen", "models": 15, "optimizer_updates": 9600,
        "fallbacks": result["retention_gate_failures"]}), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
