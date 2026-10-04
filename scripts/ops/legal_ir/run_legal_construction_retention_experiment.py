#!/usr/bin/env python3
"""Select historical checkpoints with an added document retention gate.

This experiment performs zero optimizer updates. Single and document tuning
labels may select an existing checkpoint; fresh and regression targets remain
sealed throughout selection and generation. Baseline fallbacks preserve their
actual checkpoint and curriculum identities.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_temporal_curriculum_experiment as historical
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition

require, read, sha, write, digest = historical.require, historical.read, historical.sha, historical.write, historical.digest
ref, read_ref, source_rows, generate = historical.ref, historical.read_ref, historical.source_rows, historical.generate
score, target_metadata = historical.score, historical.target_metadata
SCHEMA = "legal-construction-retention-experiment/v1"
SEEDS = (1729, 1730, 1731)
ARCHITECTURES = ("continuation", "grounding")
ARMS = {f"{policy}_{architecture}": {"selection_policy": policy, "architecture": architecture,
    "enabled": architecture == "grounding"} for policy in ("prior", "document_retained") for architecture in ARCHITECTURES}
TUNING_PANELS = ("earlier", "prior_new", "temporal")
NORMAL_PANELS = ("tuning_earlier", "tuning_prior_new", "tuning_temporal", "fresh",
    "seen_layout_anchor", "earlier_regression", "exposed_regression", "mixed_regression", "temporal_regression")
DOCUMENT_PANELS = ("document_tuning", "fresh_documents", "exposed_documents")
FALSE = {**historical.FALSE, "training_executed": False}


def select_retained_stage(stages, parent_tuning_exact, document_reference_exact):
    require(type(parent_tuning_exact) is int and 0 <= parent_tuning_exact <= 96,
        "bounded source parent tuning count required")
    require(type(document_reference_exact) is int and 0 <= document_reference_exact <= 72,
        "bounded baseline document tuning count required")
    require(type(stages) is list and len(stages) == 2 and {row["steps"] for row in stages} == {400, 800},
        "both historical candidate stages required")
    bounds = {"earlier": 96, "prior_new": 96, "temporal": 120, "document": 72}
    for stage in stages:
        require(type(stage["steps"]) is int and all(type(stage["tuning_" + name + "_exact"]) is int
            and 0 <= stage["tuning_" + name + "_exact"] <= bound for name, bound in bounds.items()),
            "valid complete tuning counts required")
    eligible = [row for row in stages if row["tuning_earlier_exact"] >= parent_tuning_exact - 1
        and row["tuning_document_exact"] >= document_reference_exact - 1]
    return max(eligible, key=lambda row: (row["tuning_temporal_exact"], row["tuning_document_exact"],
        row["tuning_prior_new_exact"], row["tuning_earlier_exact"], -row["steps"])) if eligible else None


def validate_document_reference(stage, parent_tuning_exact):
    require(stage["steps"] == 800 and stage["tuning_earlier_exact"] >= parent_tuning_exact - 1,
        "protocol error: baseline document reference fails earlier retention")


def score_document_tuning(generation, references):
    """Whole-document exactness counts bad boundaries and rule counts as errors."""
    rows = generation["rows"]
    targets = {row["candidate_id"]: row for row in references}
    require(len(rows) == len(references) == len(targets) and
        len({row["candidate_id"] for row in rows}) == len(rows) and
        {row["candidate_id"] for row in rows} == set(targets), "complete document tuning denominator required")
    result = {key: 0 for key in ("count", "supported", "unsupported", "exact", "decision_exact",
        "canonical_rule_list_exact", "occurrence_boundaries_exact", "composed", "abstained", "unsupported_accepted")}
    details = []
    for row in rows:
        reference = targets[row["candidate_id"]]
        require(reference["source_sha256"] == row["source_sha256"] and type(reference["supported"]) is bool,
            "document tuning source or supported flag differs")
        supported = reference["supported"]
        actual = row["composition"]["source_rule_list"] if row["composition"] is not None else None
        expected = [clause["rule"] for clause in reference["clauses"]] if supported else None
        composed = actual is not None
        canonical_exact = bool(supported and composed and actual == expected)
        plan_clauses = row["composition"].get("source_plan", {}).get("clauses", []) if composed else []
        actual_intervals = [(clause.get("char_start"), clause.get("char_end")) for clause in plan_clauses]
        expected_intervals = [(clause["char_start"], clause["char_end"]) for clause in reference["clauses"]] if supported else []
        boundaries_exact = bool(supported and composed and actual_intervals == expected_intervals)
        exact = canonical_exact and boundaries_exact
        decision_exact = exact or (not supported and not composed)
        for key, amount in {"count": 1, "supported": supported, "unsupported": not supported, "exact": exact,
            "decision_exact": decision_exact, "canonical_rule_list_exact": canonical_exact,
            "occurrence_boundaries_exact": boundaries_exact, "composed": composed, "abstained": not composed,
            "unsupported_accepted": not supported and composed}.items():
            result[key] += amount
        details.append({"id": row["candidate_id"], "supported": supported, "exact": exact,
            "decision_exact": decision_exact, "canonical_rule_list_exact": canonical_exact,
            "occurrence_boundaries_exact": boundaries_exact, "composed": composed, "segmentation_status": row["segmentation_status"],
            "predicted_rule_count": len(actual) if composed else None,
            "reference_rule_count": len(expected) if supported else None})
    return {**result, "rows": details, "wrong_boundaries_or_rule_counts_retained_as_errors": True}


def generate_documents(decoder, boundary_generation, sources):
    return {"rows": clauses.integrate(boundary_generation, sources, decoder),
        "target_access": False, "references_supplied": False, "training_executed": False}


def load_decoder(checkpoint, decoder_kind="mixed"):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(decoder_kind in ("mixed", "parent"), "unsupported decoder kind")
    module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if decoder_kind == "parent" else (mixed, mixed.MixedReplayDecoder)
    return cls(module.load_checkpoint(checkpoint["path"], expected_sha256=checkpoint["sha256"]))


def historical_inventory(frozen, heads):
    require(frozen["schema"] == historical.SCHEMA and frozen["all_training_selection_and_generation_complete"] is True
        and frozen["challenge_targets_opened"] is frozen["regression_targets_opened"] is False,
        "complete historical model generation freeze required")
    expected = {f"{arm}-{seed}" for arm in historical.ARMS for seed in SEEDS}
    require(len(heads) == 12 and {row["name"] for row in heads} == expected,
        "complete historical architecture/curriculum checkpoint bank required")
    models = {row["name"]: row for row in frozen["models"]}
    require(len(frozen["models"]) == len(models) == 15 and set(models) == expected | {f"parent-{seed}" for seed in SEEDS},
        "complete historical selected model inventory required")
    trials = {}
    for head in heads:
        require(head == models[head["name"]] and [row["steps"] for row in head["stages"]] == [400, 800],
            "historical model/stage binding differs")
        settings = historical.ARMS[head["arm"]]
        require(head["name"] == f"{head['arm']}-{head['seed']}" and head["architecture"] == settings["architecture"]
            and head["curriculum"] == settings["curriculum"] and head["requested_enabled"] is settings["enabled"]
            and head["parent"] == models[f"parent-{head['seed']}"]["checkpoint"], "historical trial provenance differs")
        chosen = historical.select_retained_stage(head["stages"], head["parent_tuning_exact"]["earlier"])
        require(chosen is not None and head["selection"] == "candidate" and head["decoder_kind"] == "mixed"
            and head["selected_steps"] == chosen["steps"] == 800 and head["checkpoint"] == chosen["checkpoint"]
            and head["enabled"] is settings["enabled"], "historical baseline/control must retain its selected 800-step checkpoint")
        trials[head["name"]] = head
    parents = {seed: models[f"parent-{seed}"] for seed in SEEDS}
    require(all(row["decoder_kind"] == "parent" and row["selection"] == "unchanged_parent" and row["enabled"] is False
        for row in parents.values()), "unchanged historical source parents required")
    return trials, parents


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_construction_retention_corpus as corpus
    config = read(path)
    regressions = ("earlier", "exposed", "mixed", "temporal")
    target_keys = {name + "_regression_targets" for name in regressions} | {"exposed_document_targets"}
    keys = {"schema", "corpus_manifest", "prior_generation", "prior_document_generation", "study_design", "producer_files",
        "exposed_document_sources", *target_keys, *{name + "_regression_sources" for name in regressions}}
    require(type(config) is dict and set(config) == keys and config["schema"] == "legal-construction-retention-run-config/v1",
        "closed construction retention configuration required")
    for key in keys - {"schema", "producer_files"} - target_keys:
        read_ref(config[key], parse=False)
    for key in target_keys:
        target_metadata(config[key])
    for reference in config["producer_files"]:
        read_ref(reference, parse=False)
    loaded = corpus.load_selection_inputs(config["corpus_manifest"]["path"])
    manifest, tuning = loaded["manifest"], loaded["tuning"]
    require(set(tuning) == set(TUNING_PANELS) and [len(tuning[name]) for name in TUNING_PANELS] == [96, 96, 120],
        "unchanged complete single tuning panels required")
    for name in ("challenge_targets", "anchor_targets", "document_challenge_targets"):
        target_metadata(manifest["artifacts"][name])
    document_tuning = loaded["document_tuning"]
    require(len(document_tuning) == 96 and sum(row["supported"] is True for row in document_tuning) == 72
        and sum(row["supported"] is False for row in document_tuning) == 24, "complete declared document tuning inventory required")
    sources = {"tuning_" + name: source_rows(tuning[name]) for name in TUNING_PANELS}
    require(all(not {"canonical_ir", "facet_spans", "trigger_span"} & set(row)
        for name in ("fresh_sources", "anchor_sources") for row in loaded[name]), "fresh generation source contains targets")
    sources["fresh"] = source_rows(loaded["fresh_sources"])
    sources["seen_layout_anchor"] = source_rows(loaded["anchor_sources"])
    for name in regressions:
        payload = read_ref(config[name + "_regression_sources"])
        rows = payload["challenge"] if name == "earlier" else payload
        require(all(not {"canonical_ir", "facet_spans", "trigger_span"} & set(row) for row in rows),
            "single generation source contains targets")
        sources[name + "_regression"] = source_rows(rows)
    require([len(sources[name]) for name in NORMAL_PANELS] == [96, 96, 120, 180, 30, 192, 150, 144, 180],
        "complete single generation inventories required")
    documents = {"document_tuning": clauses.source_rows(document_tuning),
        "fresh_documents": loaded["fresh_document_sources"], "exposed_documents": read_ref(config["exposed_document_sources"])}
    for rows in documents.values():
        require(len(rows) == 96 and all(set(row) == {"candidate_id", "source_text", "source_sha256"} for row in rows),
            "closed source-only document panels required")
        require(all(row["source_sha256"] == boundary.text_sha(row["source_text"]) for row in rows), "document source hash differs")
    seen_ids, seen_texts = set(), set()
    for rows in [*sources.values(), *documents.values()]:
        ids = {row.get("id", row.get("candidate_id")) for row in rows}
        texts = {row["source_sha256"] for row in rows}
        require(len(ids) == len(texts) == len(rows) and not ids & seen_ids and not texts & seen_texts,
            "selection and generation source panels overlap")
        seen_ids |= ids; seen_texts |= texts
    prior = read_ref(config["prior_generation"])
    historical_plan = read_ref(prior["plan"])
    require(all(sha(file) == wanted for file, wanted in historical_plan["producer_pins"].items()), "historical producer source drift")
    trials, parents = historical_inventory(prior, read_ref(prior["heads"]))
    prior_sources = read_ref(prior["sources"])
    require(all(sources["tuning_" + name] == prior_sources["tuning_" + name] for name in TUNING_PANELS),
        "common single tuning sources changed")
    old_documents = read_ref(config["prior_document_generation"])
    require(old_documents["all_models_completed"] is True and old_documents["reference_targets_opened"] is False,
        "complete historical document generation freeze required")
    document_plan = read_ref(old_documents["plan"])
    require(all(sha(file) == wanted for file, wanted in document_plan["producer_pins"].items()),
        "historical document producer source drift")
    require(document_plan["source_documents"] == config["exposed_document_sources"], "exposed document source commitment differs")
    return {"config": config, "manifest": manifest, "tuning": tuning, "document_tuning": document_tuning,
        "sources": sources, "document_sources": documents, "historical": prior, "trials": trials, "parents": parents,
        "boundary_checkpoint": document_plan["boundary_checkpoint"]}


def evaluate_stage(job, historical_stage, decoder, folder, stem):
    result = {"steps": historical_stage["steps"], "checkpoint": historical_stage["checkpoint"],
        "historical_training_report": historical_stage["training_report"], "new_optimizer_steps": 0}
    for panel in TUNING_PANELS:
        source = job["sources"]["tuning_" + panel]
        generation = generate(decoder, source)
        historical_tune = read_ref(historical_stage["tuning_" + panel])
        require(generation == historical_tune["generation"], "historical single tuning numerical replay differs")
        metric = score(generation["rows"], source, job["tuning"][panel])
        require(metric == historical_tune["metrics"] and metric["exact"] == historical_stage["tuning_" + panel + "_exact"],
            "historical single tuning targets or scores changed")
        result["tuning_" + panel] = write(folder / f"{stem}-tuning-{panel}.json", {"generation": generation, "metrics": metric})
        result["tuning_" + panel + "_exact"] = metric["exact"]
    documents = generate_documents(decoder, job["boundaries"]["document_tuning"], job["document_sources"]["document_tuning"])
    metric = score_document_tuning(documents, job["document_tuning"])
    result["document_tuning"] = write(folder / f"{stem}-document-tuning.json", {"generation": documents, "metrics": metric})
    result["tuning_document_exact"] = metric["exact"]
    return result


def selection_job(job):
    import torch
    torch.set_num_threads(1)
    folder = Path(job["folder"]); folder.mkdir()
    baseline, temporal = job["baseline"], job["temporal"]
    reference_stage = evaluate_stage(job, baseline["stages"][1], load_decoder(baseline["checkpoint"]), folder, "baseline-800")
    parent_exact = job["parent_tuning_exact"]
    validate_document_reference(reference_stage, parent_exact)
    stages = []
    for stage in temporal["stages"]:
        measured = evaluate_stage(job, stage, load_decoder(stage["checkpoint"]), folder, f"temporal-{stage['steps']}")
        measured["earlier_retention_eligible"] = measured["tuning_earlier_exact"] >= parent_exact - 1
        measured["document_retention_eligible"] = measured["tuning_document_exact"] >= reference_stage["tuning_document_exact"] - 1
        measured["retention_eligible"] = measured["earlier_retention_eligible"] and measured["document_retention_eligible"]
        stages.append(measured)
    selected = select_retained_stage(stages, parent_exact, reference_stage["tuning_document_exact"])
    result = {"architecture": job["architecture"], "seed": job["seed"], "parent": temporal["parent"],
        "temporal_source_trial": temporal["name"], "baseline_source_trial": baseline["name"],
        "prior_checkpoint": temporal["checkpoint"], "parent_tuning_earlier_exact": parent_exact,
        "document_reference_checkpoint": baseline["checkpoint"], "document_reference": reference_stage,
        "stages": stages, "selection": "candidate" if selected else "baseline_fallback",
        "selected_steps": selected["steps"] if selected else 800,
        "checkpoint": selected["checkpoint"] if selected else baseline["checkpoint"],
        "selected_curriculum": "temporal_augmented" if selected else "baseline", "new_optimizer_steps": 0,
        "fresh_targets_opened": False, "regression_targets_opened": False, **FALSE}
    reference = write(folder / "selection.json", result)
    print(json.dumps({"phase": "selected", "architecture": job["architecture"], "seed": job["seed"],
        "selection": result["selection"], "steps": result["selected_steps"],
        "baseline_document_exact": reference_stage["tuning_document_exact"],
        "candidate_document_exact": [row["tuning_document_exact"] for row in stages]}), flush=True)
    return {**result, "selection_record": reference}


def model_inventory(selections, parents):
    require(len(selections) == 6 and {(row["architecture"], row["seed"]) for row in selections} == {
        (architecture, seed) for architecture in ARCHITECTURES for seed in SEEDS}, "all six selection trials required")
    models = []
    for trial in selections:
        for policy in ("prior", "document_retained"):
            prior = policy == "prior"
            architecture, seed = trial["architecture"], trial["seed"]
            models.append({"name": f"{policy}_{architecture}-{seed}", "arm": f"{policy}_{architecture}",
                "architecture": architecture, "seed": seed, "selection_policy": policy,
                "selection": "prior_selected" if prior else trial["selection"], "decoder_kind": "mixed",
                "checkpoint": trial["prior_checkpoint"] if prior else trial["checkpoint"],
                "selected_steps": 800 if prior else trial["selected_steps"],
                "curriculum": "temporal_augmented" if prior else trial["selected_curriculum"],
                "requested_enabled": architecture == "grounding", "enabled": architecture == "grounding",
                "parent": trial["parent"], "document_reference_checkpoint": trial["document_reference_checkpoint"],
                "selection_record": trial["selection_record"], "new_optimizer_steps": 0,
                "source_trial_name": trial["temporal_source_trial"] if prior or trial["selection"] == "candidate" else trial["baseline_source_trial"],
                "historical_trial_executed_steps": 800})
    models += [{"name": f"parent-{seed}", "arm": "parent", "architecture": "parent", "curriculum": "parent", "seed": seed,
        "checkpoint": parents[seed]["checkpoint"], "decoder_kind": "parent", "selection": "unchanged_parent",
        "selection_policy": "unchanged_parent", "requested_enabled": False, "enabled": False,
        "selected_steps": 0, "new_optimizer_steps": 0} for seed in SEEDS]
    return sorted(models, key=lambda row: row["name"])


def generation_job(job):
    import torch
    torch.set_num_threads(1)
    item = job["item"]; decoder = load_decoder(item["checkpoint"], item["decoder_kind"])
    folder = Path(job["folder"]); folder.mkdir()
    files, document_files = {}, {}
    for panel in NORMAL_PANELS:
        files[panel] = write(folder / f"{panel}-generation.json", generate(decoder, job["sources"][panel], parent=item["decoder_kind"] == "parent"))
    if item["enabled"]:
        files["fresh_disabled"] = write(folder / "fresh-disabled-generation.json", generate(decoder, job["sources"]["fresh"], ablation="disabled"))
    for panel in DOCUMENT_PANELS:
        document_files[panel] = write(folder / f"{panel}-generation.json", generate_documents(decoder, job["boundaries"][panel], job["document_sources"][panel]))
    print(json.dumps({"phase": "generated", "model": item["name"], "selection": item["selection"]}), flush=True)
    return item["name"], files, document_files


def run(args):
    import torch
    torch.set_num_threads(1)
    from scripts.ops.legal_ir import prepare_legal_construction_retention_corpus as corpus
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(type(args.workers) is int and 1 <= args.workers <= 3, "one to three inference workers required")
    inputs = load_config(args.config)
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in (historical, historical.previous,
        historical.previous.shared, sys.modules[score.__module__], clauses, boundary, composition, dimensions, mixed, corpus, sys.modules[__name__])}
    plan_ref = write(output / "plan.json", {"schema": SCHEMA, "config": ref(args.config), "arms": ARMS,
        "seeds": list(SEEDS), "candidate_steps": [400, 800], "producer_pins": pins,
        "counts": {key: len(value) for key, value in inputs["sources"].items()},
        "document_counts": {key: len(value) for key, value in inputs["document_sources"].items()},
        "boundary_checkpoint": inputs["boundary_checkpoint"], "executed_optimizer_updates": 0,
        "earlier_retention_tolerance": 1, "document_retention_tolerance": 1,
        "document_reference": "same_architecture_seed_baseline_curriculum_selected800",
        "selection": "eligible earlier>=sourceparent-1 and document>=baseline800-1; maximize temporal, document, prior_new, earlier, then earliest step; no eligible means baseline800 fallback",
        "fresh_targets_opened": False, "regression_targets_opened": False,
        "scope": "Selection-only comparison on frozen checkpoint bank; document tuning is not independent evidence; no optimizer updates", **FALSE})
    source_ref = write(output / "source-inputs.json", inputs["sources"])
    document_source_ref = write(output / "document-source-inputs.json", inputs["document_sources"])
    boundary_decoder = boundary.ClauseBoundaryDecoder(read_ref(inputs["boundary_checkpoint"]))
    boundaries = {panel: clauses.decode_all(boundary_decoder, rows) for panel, rows in inputs["document_sources"].items()}
    boundary_refs = {panel: write(output / f"{panel}-boundaries.json", generation) for panel, generation in boundaries.items()}
    parent_scores, parent_files = {}, {}
    for seed in SEEDS:
        parent = inputs["parents"][seed]
        decoder = load_decoder(parent["checkpoint"], "parent")
        parent_scores[seed], parent_files[str(seed)] = {}, {}
        for panel in TUNING_PANELS:
            sources = inputs["sources"]["tuning_" + panel]
            generation = generate(decoder, sources, parent=True)
            require(generation == read_ref(inputs["historical"]["files"][f"parent-{seed}"]["tuning_" + panel]),
                "historical unchanged parent tuning replay differs")
            metric = score(generation["rows"], sources, inputs["tuning"][panel])
            parent_scores[seed][panel] = metric["exact"]
            parent_files[str(seed)][panel] = write(output / f"parent-{seed}-tuning-{panel}.json", {"generation": generation, "metrics": metric})
    jobs = [{"architecture": architecture, "seed": seed, "baseline": inputs["trials"][f"baseline_{architecture}-{seed}"],
        "temporal": inputs["trials"][f"temporal_augmented_{architecture}-{seed}"],
        "parent_tuning_exact": parent_scores[seed]["earlier"], "tuning": inputs["tuning"], "document_tuning": inputs["document_tuning"],
        "sources": inputs["sources"], "document_sources": inputs["document_sources"], "boundaries": boundaries,
        "folder": str(output / f"selection-{architecture}-{seed}")} for architecture in ARCHITECTURES for seed in SEEDS]
    selections = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(selection_job, job) for job in jobs]):
            selections.append(future.result())
    selections.sort(key=lambda row: (row["architecture"], row["seed"]))
    selection_ref = write(output / "selections-frozen.json", {"trials": selections, "parent_tuning": parent_files,
        "boundaries": boundary_refs, "plan": plan_ref, "fresh_targets_opened": False, "regression_targets_opened": False,
        "executed_optimizer_updates": 0, **FALSE})
    models = model_inventory(selections, inputs["parents"])
    heads_ref = write(output / "heads-frozen.json", models)
    files, document_files = {}, {}
    jobs = [{"item": item, "sources": inputs["sources"], "document_sources": inputs["document_sources"],
        "boundaries": boundaries, "folder": str(output / item["name"])} for item in models]
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(generation_job, job) for job in jobs]):
            name, singles, documents = future.result(); files[name] = singles; document_files[name] = documents
    require(all(sha(file) == wanted for file, wanted in pins.items()), "selection or generation producer source drift")
    require(load_config(args.config) == inputs, "selection inputs changed during execution")
    result = {"schema": SCHEMA, "plan": plan_ref, "sources": source_ref, "document_sources": document_source_ref,
        "boundaries": boundary_refs, "selections": selection_ref, "heads": heads_ref, "models": models,
        "files": files, "document_files": document_files, "all_selection_and_generation_complete": True,
        "challenge_targets_opened": False, "regression_targets_opened": False,
        "executed_optimizer_updates": 0, "baseline_fallbacks": [row["name"] for row in models if row["selection"] == "baseline_fallback"], **FALSE}
    write(output / "generation-frozen.json", result)
    print(json.dumps({"phase": "frozen", "models": len(models), "optimizer_updates": 0, "fallbacks": result["baseline_fallbacks"]}), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    main()
