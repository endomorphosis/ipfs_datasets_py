#!/usr/bin/env python3
"""Continue a frozen boundary model with replay or balanced construction data.

All six runs share one pretrained initial state; seeds vary minibatch order only.
The existing network, loss, inference thresholds, and conservative scope guards
remain unchanged. Fresh labels are never opened by this producer.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_construction_retention_experiment as retention
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary

require, read, sha, write, digest = retention.require, retention.read, retention.sha, retention.write, retention.digest
ref, read_ref, target_metadata = retention.ref, retention.read_ref, retention.target_metadata
SCHEMA = "legal-boundary-curriculum-experiment/v1"
CONFIG_SCHEMA = "legal-boundary-curriculum-run-config/v1"
SEEDS = (1729, 1730, 1731)
CURRICULA = ("replay_only", "expanded")
ARCHITECTURES = ("continuation", "grounding")
STEPS = (200, 400, 600)
PANELS = ("tuning_old", "tuning_new", "fresh_documents", "prior_construction_documents", "exposed_documents")
COUNTS = dict(zip(PANELS, (48, 96, 96, 96, 96)))
FALSE = {key: value for key, value in retention.FALSE.items() if key != "training_executed"}
SOURCE_KEYS = {"candidate_id", "source_text", "source_sha256"}


def select_stage(stages, parent_old_supported_exact):
    """Gate old interval retention and new guard acceptance before ranking."""
    require(type(parent_old_supported_exact) is int and 0 <= parent_old_supported_exact <= 36,
        "bounded old supported parent count required")
    require(type(stages) is list and len(stages) == 3 and {row["steps"] for row in stages} == set(STEPS),
        "all three additional-update stages required")
    for stage in stages:
        require(type(stage["steps"]) is int and all(type(stage[key]) is int and 0 <= stage[key] <= maximum
            for key, maximum in (("old_supported_exact", 36), ("old_decision_exact", 48),
                ("new_supported_exact", 72), ("new_unsupported_accepted", 24))), "bounded complete tuning counts required")
    eligible = [row for row in stages if row["old_supported_exact"] >= parent_old_supported_exact - 1
        and row["new_unsupported_accepted"] == 0]
    return max(eligible, key=lambda row: (row["new_supported_exact"], row["old_decision_exact"], -row["steps"])) if eligible else None


def validate_sources(rows, count):
    require(type(rows) is list and len(rows) == count and all(set(row) == SOURCE_KEYS for row in rows),
        "closed complete source-only document panel required")
    require(len({row["candidate_id"] for row in rows}) == len({row["source_sha256"] for row in rows}) == count,
        "unique source and document identities required")
    require(all(type(row["candidate_id"]) is str and row["candidate_id"] and
        row["source_sha256"] == boundary.text_sha(row["source_text"]) for row in rows), "document source identity/hash differs")
    for row in rows:
        boundary.tokenize(row["source_text"])


def validate_references(rows, count, supported):
    validate_sources(clauses.source_rows(rows), count)
    require(all(type(row["supported"]) is bool for row in rows) and
        sum(row["supported"] for row in rows) == supported, "complete supported/guard label inventory required")
    for row in rows:
        require(type(row["repeated_rule_occurrences"]) is bool and type(row["construction"]) is str,
            "boundary reference metadata required")
        if row["supported"]:
            declarations = [{"clause_id": f"reference-{i}", "char_start": clause["char_start"],
                "char_end": clause["char_end"], "scope": clauses.compose.FLAT_SCOPE}
                for i, clause in enumerate(row["clauses"])]
            clauses.compose.prepare_source_plan({key: row[key] for key in SOURCE_KEYS}, declarations)
            ends = {token["char_end"] for token in boundary.tokenize(row["source_text"])}
            require(all(clause["char_end"] in ends for clause in row["clauses"]), "reference ends must be token boundaries")
        else:
            require(row["clauses"] == [], "guard references must not invent flat clauses")


def clause_inventory(frozen, heads):
    require(frozen["schema"] == retention.SCHEMA and frozen["all_selection_and_generation_complete"] is True and
        frozen["challenge_targets_opened"] is frozen["regression_targets_opened"] is False,
        "complete frozen prior clause generation required")
    expected = {f"{arm}-{seed}" for arm in retention.ARMS for seed in SEEDS} | {f"parent-{seed}" for seed in SEEDS}
    models = {row["name"]: row for row in frozen["models"]}
    require(len(models) == len(frozen["models"]) == len(heads) == 15 and set(models) == expected and
        heads == frozen["models"], "prior clause model inventory differs")
    controls = {}
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            item = models[f"prior_{architecture}-{seed}"]
            require(item["architecture"] == architecture and item["seed"] == seed and item["decoder_kind"] == "mixed"
                and item["curriculum"] == "temporal_augmented" and item["selection_policy"] == "prior"
                and item["selected_steps"] == 800 and item["enabled"] is (architecture == "grounding")
                and item["requested_enabled"] is item["enabled"] and item["selection"] == "prior_selected"
                and item["source_trial_name"] == f"temporal_augmented_{architecture}-{seed}",
                "immutable temporal800 clause control required")
            read_ref(item["checkpoint"], parse=False)
            controls[(architecture, seed)] = item
    return controls


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as corpus
    config = read(path)
    target_keys = {"prior_construction_targets", "exposed_document_targets"}
    keys = {"schema", "corpus_manifest", "boundary_parent", "prior_generation", "prior_boundary_plan",
        "prior_construction_sources", "exposed_document_sources", "study_design", "producer_files", *target_keys}
    require(type(config) is dict and set(config) == keys and config["schema"] == CONFIG_SCHEMA,
        "closed boundary curriculum configuration required")
    for key in keys - target_keys - {"schema", "producer_files"}:
        read_ref(config[key], parse=False)
    for key in target_keys:
        target_metadata(config[key])
    for reference in config["producer_files"]:
        read_ref(reference, parse=False)
    loaded = corpus.load_training_inputs(config["corpus_manifest"]["path"])
    manifest = loaded["manifest"]
    target_metadata(manifest["artifacts"]["fresh_targets"])
    original = read_ref(config["prior_boundary_plan"])
    require(original["schema"] == clauses.SCHEMA and original["config"] == boundary.CONFIG,
        "original boundary configuration differs")
    require(all(sha(file) == wanted for file, wanted in original["producer_pins"].items()), "original boundary producer drift")
    replay, old_tuning = (read_ref(original["references"][name]) for name in ("train", "tuning"))
    require(replay == loaded["replay"], "original replay labels changed")
    require(clauses.source_rows(replay) == read_ref(original["sources"]["train"]) and
        clauses.source_rows(old_tuning) == read_ref(original["sources"]["tuning"]), "original source binding differs")
    new_train, new_tuning = loaded["new_train"], loaded["new_tuning"]
    for rows, count, supported in ((replay, 192, 144), (old_tuning, 48, 36), (new_train, 384, 288), (new_tuning, 96, 72)):
        validate_references(rows, count, supported)
    sources = {"tuning_old": clauses.source_rows(old_tuning), "tuning_new": clauses.source_rows(new_tuning),
        "fresh_documents": loaded["fresh_sources"], "prior_construction_documents": read_ref(config["prior_construction_sources"]),
        "exposed_documents": read_ref(config["exposed_document_sources"])}
    for name, rows in sources.items():
        validate_sources(rows, COUNTS[name])
    ids, texts = set(), set()
    for rows in (replay, new_train, *sources.values()):
        row_ids = {row["candidate_id"] for row in rows}; row_texts = {row["source_sha256"] for row in rows}
        require(not ids & row_ids and not texts & row_texts, "training, tuning, or evaluation source overlap")
        ids |= row_ids; texts |= row_texts
    parent = read_ref(config["boundary_parent"])
    require(parent["optimizer_steps"] == 200 and parent["training_manifest_sha256"] == digest(replay)
        and parent["tuning_manifest_sha256"] == digest(old_tuning), "pretrained boundary parent provenance differs")
    boundary.restore(parent)
    prior = read_ref(config["prior_generation"])
    prior_plan = read_ref(prior["plan"])
    require(all(sha(file) == wanted for file, wanted in prior_plan["producer_pins"].items()), "prior clause producer drift")
    controls = clause_inventory(prior, read_ref(prior["heads"]))
    return {"config": config, "manifest": manifest, "replay": replay, "new_train": new_train,
        "tuning": {"old": old_tuning, "new": new_tuning}, "sources": sources,
        "boundary_parent": config["boundary_parent"], "clause_controls": controls}


class CyclingRows:
    """Deterministic shuffled epochs with exact quotas, including wraparound."""
    def __init__(self, rows, rng):
        require(type(rows) is list and bool(rows), "nonempty replay pool required")
        self.rows, self.rng, self.order, self.position = rows, rng, [], 0

    def take(self, count):
        require(type(count) is int and count > 0, "positive batch quota required")
        selected = []
        while len(selected) < count:
            if self.position == len(self.order):
                self.order = list(range(len(self.rows))); self.rng.shuffle(self.order); self.position = 0
            take = min(count - len(selected), len(self.order) - self.position)
            selected.extend(self.rows[i] for i in self.order[self.position:self.position + take])
            self.position += take
        return selected


def batch_schedule(replay, new_train, curriculum, seed, steps=600):
    require(curriculum in CURRICULA and seed in SEEDS and type(steps) is int and 1 <= steps <= 600,
        "declared curriculum, seed, and update budget required")
    rng = random.Random(seed)
    old = CyclingRows(replay, rng); new = CyclingRows(new_train, rng)
    for step in range(1, steps + 1):
        left = old.take(12 if curriculum == "replay_only" else 6)
        right = [] if curriculum == "replay_only" else new.take(6)
        yield left + right, {"steps": step, "old_ids": [row["candidate_id"] for row in left],
            "new_ids": [row["candidate_id"] for row in right]}


def evaluate_tuning(checkpoint, tuning, sources, folder, stem):
    decoder = boundary.ClauseBoundaryDecoder(read_ref(checkpoint))
    fields = {}
    for panel in ("old", "new"):
        generation = clauses.decode_all(decoder, sources["tuning_" + panel])
        metrics = clauses.evaluate(generation, tuning[panel])
        fields["tuning_" + panel] = write(folder / f"{stem}-tuning-{panel}.json", {"generation": generation, "metrics": metrics})
        fields[panel + "_supported_exact"] = metrics.get("exact_supported_segmentation", 0)
        fields[panel + "_decision_exact"] = metrics.get("document_decision_exact", 0)
        fields[panel + "_unsupported_accepted"] = metrics.get("unsupported_accepted", 0)
    return fields


def training_job(job):
    import torch
    torch.set_num_threads(1)
    folder = Path(job["folder"]); folder.mkdir()
    parent = read_ref(job["parent"])
    _, network = boundary.restore(parent)
    initial_state_sha = digest(parent["model_state"])
    optimizer = torch.optim.Adam(network.parameters(), lr=boundary.CONFIG["learning_rate"])
    curriculum, seed = job["curriculum"], job["seed"]
    training_manifest = {"curriculum": curriculum, "original_replay_sha256": digest(job["replay"]),
        "new_train_sha256": digest(job["new_train"]) if curriculum == "expanded" else None,
        "old_quota": 12 if curriculum == "replay_only" else 6, "new_quota": 0 if curriculum == "replay_only" else 6,
        "sampler_seed": seed, "batch_size": 12, "additional_optimizer_updates": 600,
        "sampler": "shared_random.Random(seed); lazy_shuffle_range_at_pool_exhaustion; exact_quota_wraparound; old_then_new; no_batch_shuffle"}
    tuning_manifest = {key: digest(value) for key, value in job["tuning"].items()}
    stages, losses, batches, step_seconds = [], [], [], []
    started = time.monotonic(); training_seconds = 0.
    for chunk, receipt in batch_schedule(job["replay"], job["new_train"], curriculum, seed):
        step = receipt["steps"]; update_started = time.monotonic()
        require(time.monotonic() - started < 600., "bounded total trial time exhausted")
        ids, features, lengths, labels, scopes, mask = boundary.tensor_batch(torch, chunk, labels=True)
        network.train(); optimizer.zero_grad(set_to_none=True)
        boundary_logits, scope_logits = network(ids, features, lengths)
        eligible = mask & scopes.bool()[:, None]
        require(bool(eligible.any()), "batch must contain supported boundary supervision")
        boundary_loss = torch.nn.functional.binary_cross_entropy_with_logits(boundary_logits[eligible], labels[eligible],
            pos_weight=torch.tensor(12.))
        scope_loss = torch.nn.functional.cross_entropy(scope_logits, scopes, weight=torch.tensor([3., 1.]))
        loss = boundary_loss + scope_loss
        require(bool(torch.isfinite(loss)), "nonfinite boundary curriculum objective")
        loss.backward(); torch.nn.utils.clip_grad_norm_(network.parameters(), 5.); optimizer.step()
        losses.append(float(loss.detach())); batches.append(receipt)
        elapsed = time.monotonic() - update_started; training_seconds += elapsed; step_seconds.append(elapsed)
        require(time.monotonic() - started <= 600., "bounded total trial time exhausted")
        if step in STEPS:
            cp = boundary.checkpoint(network, steps=parent["optimizer_steps"] + step,
                training_manifest_sha256=digest(training_manifest), tuning_manifest_sha256=digest(tuning_manifest))
            checkpoint = write(folder / f"checkpoint-{step}.json", cp)
            stage = {"steps": step, "cumulative_optimizer_steps": parent["optimizer_steps"] + step, "checkpoint": checkpoint,
                **evaluate_tuning(checkpoint, job["tuning"], job["sources"], folder, f"stage-{step}")}
            stage["eligible"] = stage["old_supported_exact"] >= job["parent_old_supported_exact"] - 1 and stage["new_unsupported_accepted"] == 0
            stages.append(stage)
            require(time.monotonic() - started <= 600., "bounded total trial time exhausted")
            print(json.dumps({"phase": "trained_stage", "curriculum": curriculum, "seed": seed, "steps": step,
                "old_supported_exact": stage["old_supported_exact"], "new_supported_exact": stage["new_supported_exact"],
                "new_unsupported_accepted": stage["new_unsupported_accepted"], "eligible": stage["eligible"]}), flush=True)
    selected = select_stage(stages, job["parent_old_supported_exact"])
    record = {"name": f"{curriculum}-{seed}", "curriculum": curriculum, "seed": seed, "initial": job["parent"],
        "initial_model_state_sha256": initial_state_sha, "shared_pretrained_initialization": True,
        "independent_model_initializations": False, "seed_controls_minibatch_order_only": True,
        "training_manifest": training_manifest, "tuning_manifest": tuning_manifest,
        "training_manifest_sha256": digest(training_manifest), "tuning_manifest_sha256": digest(tuning_manifest),
        "stages": stages, "parent_old_supported_exact": job["parent_old_supported_exact"],
        "selection": "candidate" if selected else "parent_fallback_no_acceptable_replacement",
        "selected_steps": selected["steps"] if selected else 0,
        "checkpoint": selected["checkpoint"] if selected else job["parent"],
        "losses": losses, "batches": batches, "batch_schedule_sha256": digest(batches),
        "executed_optimizer_updates": len(losses), "inherited_optimizer_steps": parent["optimizer_steps"],
        "final_cumulative_optimizer_steps": parent["optimizer_steps"] + len(losses),
        "optimizer_reset": True, "optimizer_resumption_supported": False,
        "torch_threads": torch.get_num_threads(), "training_step_seconds": step_seconds,
        "optimizer_training_seconds": training_seconds, "elapsed_seconds_including_stage_tuning": time.monotonic() - started,
        "maximum_total_trial_seconds": 600,
        "changed_parameter_names": sorted(key for key in parent["model_state"] if parent["model_state"][key] != cp["model_state"][key]),
        "fresh_targets_opened": False, "regression_targets_opened": False, **FALSE}
    require(len(losses) == len(batches) == 600 and record["changed_parameter_names"], "all600 updates and changed parameters required")
    report = write(folder / "training-frozen.json", record)
    return {key: record[key] for key in ("name", "curriculum", "seed", "initial", "checkpoint", "selection", "selected_steps",
        "stages", "parent_old_supported_exact", "executed_optimizer_updates")} | {"training_report": report}


def model_inventory(selections, controls, parent):
    require(len(selections) == 6 and {(row["curriculum"], row["seed"]) for row in selections} ==
        {(curriculum, seed) for curriculum in CURRICULA for seed in SEEDS}, "all six boundary training trials required")
    require(set(controls) == {(architecture, seed) for architecture in ARCHITECTURES for seed in SEEDS},
        "all six frozen clause controls required")
    lookup = {(row["curriculum"], row["seed"]): row for row in selections}
    models = []
    for policy in ("parent", *CURRICULA):
        for architecture in ARCHITECTURES:
            for seed in SEEDS:
                control = controls[(architecture, seed)]
                trial = None if policy == "parent" else lookup[(policy, seed)]
                head = "parent" if trial is None else trial["name"]
                models.append({"name": f"{policy}_{architecture}-{seed}", "arm": f"{policy}_{architecture}",
                    "architecture": architecture, "seed": seed, "boundary_policy": policy, "boundary_head": head,
                    "boundary_checkpoint": parent if trial is None else trial["checkpoint"],
                    "boundary_selected_steps": 0 if trial is None else trial["selected_steps"],
                    "boundary_selection": "unchanged_parent" if trial is None else trial["selection"],
                    "checkpoint": control["checkpoint"], "decoder_kind": "mixed", "enabled": architecture == "grounding",
                    "clause_source_model": control["name"], "clause_curriculum": "temporal_augmented",
                    "clause_selected_steps": 800, "clause_optimizer_updates": 0})
    return sorted(models, key=lambda row: row["name"])


def generation_job(job):
    import torch
    torch.set_num_threads(1)
    item = job["item"]
    decoder = retention.load_decoder(item["checkpoint"], item["decoder_kind"])
    folder = Path(job["folder"]); folder.mkdir()
    documents = {panel: write(folder / f"{panel}-generation.json",
        retention.generate_documents(decoder, job["boundaries"][panel], rows)) for panel, rows in job["sources"].items()}
    print(json.dumps({"phase": "generated", "model": item["name"], "boundary_selection": item["boundary_selection"]}), flush=True)
    return item["name"], documents


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(type(args.workers) is int and 1 <= args.workers <= 3, "one to three CPU workers required")
    inputs = load_config(args.config)
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in
        (retention, clauses, boundary, clauses.compose, dimensions, mixed, corpus, sys.modules[__name__])}
    plan_ref = write(output / "plan.json", {"schema": SCHEMA, "config": ref(args.config), "producer_pins": pins,
        "curricula": list(CURRICULA), "seeds": list(SEEDS), "additional_stage_steps": list(STEPS),
        "boundary_parent": inputs["boundary_parent"], "boundary_config": deepcopy(boundary.CONFIG),
        "shared_pretrained_initialization": True, "seed_controls_minibatch_order_only": True,
        "optimizer_reset": True, "optimizer_resumption_supported": False,
        "batch_quotas": {"replay_only": {"old": 12, "new": 0}, "expanded": {"old": 6, "new": 6}},
        "maximum_total_trial_seconds": 600, "threads_per_worker": 1, "workers": args.workers,
        "loss": {"boundary_positive_weight": 12., "scope_class_weights": [3., 1.], "gradient_clip_norm": 5.},
        "source_counts": COUNTS, "old_supported_retention_tolerance": 1, "new_guard_false_acceptance_tolerance": 0,
        "selection": "old_supported>=parent-1 and new_guard_acceptance=0; rank new_supported,old_decision,earliest_additional_step; no eligible keeps unqualified parent fallback",
        "fresh_targets_opened": False, "regression_targets_opened": False, **FALSE})
    sources_ref = write(output / "source-inputs.json", inputs["sources"])
    parent_tuning = evaluate_tuning(inputs["boundary_parent"], inputs["tuning"], inputs["sources"], output, "parent")
    jobs = [{"curriculum": curriculum, "seed": seed, "parent": inputs["boundary_parent"], "replay": inputs["replay"],
        "new_train": inputs["new_train"], "tuning": inputs["tuning"],
        "sources": {key: inputs["sources"][key] for key in ("tuning_old", "tuning_new")},
        "parent_old_supported_exact": parent_tuning["old_supported_exact"],
        "folder": str(output / f"training-{curriculum}-{seed}")} for curriculum in CURRICULA for seed in SEEDS]
    selections = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(training_job, job) for job in jobs]):
            selections.append(future.result())
    selections.sort(key=lambda row: row["name"])
    selection_ref = write(output / "selections-frozen.json", {"trials": selections, "parent_tuning": parent_tuning,
        "plan": plan_ref, "executed_optimizer_updates": sum(row["executed_optimizer_updates"] for row in selections),
        "fresh_targets_opened": False, "regression_targets_opened": False, **FALSE})
    heads = [{"name": "parent", "checkpoint": inputs["boundary_parent"], "selection": "unchanged_parent", "selected_steps": 0}] + [
        {key: row[key] for key in ("name", "checkpoint", "selection", "selected_steps", "curriculum", "seed", "training_report")}
        for row in selections]
    heads_ref = write(output / "boundary-heads-frozen.json", heads)
    boundaries, boundary_refs = {}, {}
    for head in heads:
        decoder = boundary.ClauseBoundaryDecoder(read_ref(head["checkpoint"]))
        boundaries[head["name"]] = {}; boundary_refs[head["name"]] = {}
        for panel, rows in inputs["sources"].items():
            generation = clauses.decode_all(decoder, rows)
            boundaries[head["name"]][panel] = generation
            boundary_refs[head["name"]][panel] = write(output / f"{head['name']}-{panel}-boundaries.json", generation)
    models = model_inventory(selections, inputs["clause_controls"], inputs["boundary_parent"])
    models_ref = write(output / "models-frozen.json", models)
    jobs = [{"item": item, "sources": inputs["sources"], "boundaries": boundaries[item["boundary_head"]],
        "folder": str(output / item["name"])} for item in models]
    document_files = {}
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(generation_job, job) for job in jobs]):
            name, documents = future.result(); document_files[name] = documents
    require(all(sha(file) == wanted for file, wanted in pins.items()), "boundary curriculum producer source drift")
    require(load_config(args.config) == inputs, "boundary curriculum inputs changed during execution")
    result = {"schema": SCHEMA, "plan": plan_ref, "sources": sources_ref, "boundary_heads": heads_ref,
        "heads": models_ref, "models": models, "boundaries": boundary_refs, "selections": selection_ref,
        "document_files": document_files, "all_training_selection_and_generation_complete": True,
        "fresh_targets_opened": False, "regression_targets_opened": False, "executed_optimizer_updates": 3600,
        "clause_optimizer_updates": 0, "training_executed": True,
        "parent_fallbacks": [row["name"] for row in selections if row["selection"] != "candidate"], **FALSE}
    write(output / "generation-frozen.json", result)
    print(json.dumps({"phase": "frozen", "models": len(models), "optimizer_updates": 3600,
        "boundary_heads": len(heads), "parent_fallbacks": result["parent_fallbacks"]}), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
