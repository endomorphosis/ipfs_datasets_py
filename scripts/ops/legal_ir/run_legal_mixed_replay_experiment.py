#!/usr/bin/env python3
"""Matched mixed-supervision fitting, retention selection and sealed generation.

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
from scripts.ops.legal_ir.compare_legal_decoder_architectures import score

require, read, sha, write, digest = previous.require, previous.read, previous.sha, previous.write, previous.digest
ref, read_ref, source_rows, generate, comparable = previous.ref, previous.read_ref, previous.source_rows, previous.generate, previous.comparable
SCHEMA = "legal-mixed-replay-experiment/v1"
SEEDS = (1729, 1730, 1731)
ARMS = {"mixed_continuation": False, "mixed_grounding": True}
STAGE_STEPS = 400
NORMAL_PANELS = ("tuning_earlier", "tuning_new", "fresh", "earlier_regression", "exposed_regression")
FALSE = {"qualified": False, "production_ready": False, "semantic_correctness_verified": False,
         "all_logic_families_supported": False, "statutory_gold_available": False, "promotion_performed": False}


def target_metadata(reference):
    require(type(reference) is dict and set(reference) == {"path", "sha256", "bytes"}
        and type(reference["path"]) is str and reference["path"]
        and type(reference["sha256"]) is str and re.fullmatch("[0-9a-f]{64}", reference["sha256"])
        and type(reference["bytes"]) is int and reference["bytes"] > 0, "closed sealed-target commitment required")


def select_retained_stage(stages, parent_tuning_exact):
    """Tuning-only gate; None means an explicit unchanged-parent fallback."""
    require(type(parent_tuning_exact) is int and 0 <= parent_tuning_exact <= 96, "bounded parent tuning exact required")
    require(type(stages) is list and stages and len({r["steps"] for r in stages}) == len(stages), "unique stages required")
    for stage in stages:
        require(type(stage["steps"]) is int and stage["steps"] > 0 and all(type(stage[key]) is int and
            0 <= stage[key] <= 96 for key in ("tuning_earlier_exact", "tuning_new_exact")), "valid tuning counts required")
    eligible = [stage for stage in stages if stage["tuning_earlier_exact"] >= parent_tuning_exact - 1]
    return max(eligible, key=lambda stage: (stage["tuning_new_exact"], stage["tuning_earlier_exact"], -stage["steps"])) if eligible else None


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_mixed_replay_corpus as corpus_module
    config = read(path)
    keys = {"schema", "corpus_manifest", "parent_heads", "earlier_regression_sources", "earlier_regression_targets",
        "exposed_regression_sources", "exposed_regression_targets", "prior_replay_design", "producer_files"}
    require(type(config) is dict and set(config) == keys and config["schema"] == "legal-mixed-replay-run-config/v1",
        "closed mixed replay configuration required")
    for key in keys - {"schema", "producer_files", "earlier_regression_targets", "exposed_regression_targets"}:
        read_ref(config[key], parse=False)
    for key in ("earlier_regression_targets", "exposed_regression_targets"):
        target_metadata(config[key])
    for item in config["producer_files"]:
        read_ref(item, parse=False)
    manifest, training, earlier, newer, fresh = corpus_module.load_training_inputs(config["corpus_manifest"]["path"])
    target_metadata(manifest["artifacts"]["challenge_targets"])
    require(len(training) == 1752 and len(earlier) == len(newer) == 96 and len(fresh) == 144, "declared complete corpus counts required")
    require(sum(r["domain"] == "earlier" for r in training) == 1152 and
        sum(r["domain"] == "new" for r in training) == 600, "exact old/new training inventory required")
    require(all(r["domain"] == "earlier" for r in earlier) and all(r["domain"] == "new" for r in newer), "tuning domains differ")
    old_regression = read_ref(config["earlier_regression_sources"])["challenge"]
    new_regression = read_ref(config["exposed_regression_sources"])
    require(len(old_regression) == 192 and len(new_regression) == 150, "complete exposed regression inventories required")
    for rows in (fresh, old_regression, new_regression):
        require(all(not {"canonical_ir", "facet_spans", "trigger_span"} & set(r) for r in rows), "generation sources contain targets")
    groups = [source_rows(rows) for rows in (training, earlier, newer, fresh, old_regression, new_regression)]
    seen_ids, seen_texts = set(), set()
    for group in groups:
        ids, texts = {r["id"] for r in group}, {r["source_sha256"] for r in group}
        require(len(ids) == len(texts) == len(group) and not ids & seen_ids and not texts & seen_texts,
            "mixed fitting/evaluation sources overlap")
        seen_ids |= ids
        seen_texts |= texts
    inventory = read_ref(config["parent_heads"])
    parents = [r for r in inventory if r["arm"] == "source_only"]
    require(len(parents) == 3 and {r["seed"] for r in parents} == set(SEEDS), "three unique original parent seeds required")
    sources = dict(zip(NORMAL_PANELS, groups[1:]))
    return {"config": config, "manifest": manifest, "training": training, "tuning": {"earlier": earlier, "new": newer},
        "sources": sources, "parents": {r["seed"]: r["checkpoint"] for r in parents}}


def fit_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    parent = dimensions.load_checkpoint(job["parent"]["path"], expected_sha256=job["parent"]["sha256"])
    require(parent["config"]["seed"] == job["seed"] and parent["config"]["latent_dimension"] == 0,
        "same-seed original source-only parent required")
    tuning = job["tuning"]["earlier"] + job["tuning"]["new"]
    checkpoint = mixed.build_checkpoint(parent, job["training"], tuning, trigger_enabled=job["enabled"], learning_rate=.001, batch_size=12)
    initial_sha = digest(checkpoint)
    folder = Path(job["folder"])
    folder.mkdir()
    parent_decoder, initial_decoder = dimensions.DimensionalSpanDecoder(parent), mixed.MixedReplayDecoder(checkpoint)
    parent_scores, initial_reports = {}, {}
    for panel in ("earlier", "new"):
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
        for panel in ("earlier", "new"):
            sources = source_rows(job["tuning"][panel])
            generation = generate(decoder, sources)
            metric = score(generation["rows"], sources, job["tuning"][panel])
            stage["tuning_" + panel] = write(folder / f"tuning-{panel}-{steps}.json", {"generation": generation, "metrics": metric})
            stage["tuning_" + panel + "_exact"] = metric["exact"]
        stage["retention_eligible"] = stage["tuning_earlier_exact"] >= parent_scores["earlier"] - 1
        stages.append(stage)
        print(json.dumps({"phase": "trained", "arm": job["arm"], "seed": job["seed"], "steps": steps,
            "earlier_tuning_exact": stage["tuning_earlier_exact"], "new_tuning_exact": stage["tuning_new_exact"],
            "retention_eligible": stage["retention_eligible"], "parent_earlier_tuning_exact": parent_scores["earlier"]}), flush=True)
    selected = select_retained_stage(stages, parent_scores["earlier"])
    return {"name": f"{job['arm']}-{job['seed']}", "arm": job["arm"], "seed": job["seed"],
        "requested_enabled": job["enabled"], "enabled": job["enabled"] if selected is not None else False,
        "decoder_kind": "mixed" if selected is not None else "parent", "selection": "candidate" if selected is not None else "parent_fallback",
        "checkpoint": selected["checkpoint"] if selected is not None else job["parent"],
        "selected_steps": selected["steps"] if selected is not None else 0, "executed_steps": 800,
        "parent": job["parent"], "parent_tuning_exact": parent_scores, "initialization": initialization, "stages": stages,
        "initial_checkpoint_sha256": initial_sha}


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
    from scripts.ops.legal_ir import prepare_legal_mixed_replay_corpus as corpus_module
    require(1 <= args.workers <= 3, "one to three workers required")
    inputs = load_config(args.config)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in
        (previous, previous.shared, dimensions, mixed, corpus_module, sys.modules[score.__module__], sys.modules[__name__])}
    plan = {"schema": SCHEMA, "config": ref(args.config), "arms": ARMS, "seeds": list(SEEDS), "stage_steps": STAGE_STEPS,
        "stages": 2, "learning_rate": .001, "batch_size": 12, "domain_batch_sizes": {"earlier": 6, "new": 6},
        "training_domain_counts": {"earlier": 1152, "new": 600}, "counts": {k: len(v) for k, v in inputs["sources"].items()},
        "producer_pins": pins, "retention_tolerance": 1,
        "selection": "eligible if earlier_tuning_exact >= parent_earlier_exact-1; maximize new exact, earlier exact, then earliest step; no eligible means unchanged parent",
        "objective": "equal earlier/new domain means for semantic and actor losses; trigger loss over supervised new rows only",
        "fit_target_policy": "earlier trigger labels remain null and masked; canonical facet labels retained",
        "comparison_scope": "matched mixed arms; fewer new-row exposures and different domain weighting than prior new-only run",
        "fresh_panel_scope": inputs["manifest"].get("scope", "fresh authored sources; construction exposure audit in corpus manifest"),
        "challenge_target_access": False, "regression_target_access": False,
        "torch_device": "cpu", "torch_threads_per_worker": 1, "optimizer_trajectory_replay_required": False, **FALSE}
    plan_ref = write(output / "plan.json", plan)
    source_ref = write(output / "source-inputs.json", inputs["sources"])
    jobs = [{"arm": arm, "enabled": enabled, "seed": seed, "parent": inputs["parents"][seed],
        "training": inputs["training"], "tuning": inputs["tuning"], "folder": str(output / f"{arm}-{seed}")}
        for arm, enabled in ARMS.items() for seed in SEEDS]
    heads = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(fit_job, job) for job in jobs]):
            heads.append(future.result())
    heads.sort(key=lambda r: r["name"])
    heads_ref = write(output / "heads-frozen.json", heads)
    items = heads + [{"name": f"parent-{seed}", "arm": "parent", "seed": seed, "checkpoint": inputs["parents"][seed],
        "decoder_kind": "parent", "selection": "unchanged_parent", "enabled": False,
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
        "executed_optimizer_updates": 4800, **FALSE}
    write(output / "generation-frozen.json", result)
    print(json.dumps({"phase": "frozen", "models": 9, "optimizer_updates": 4800,
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
