#!/usr/bin/env python3
"""Replay frozen dimensional source-copy experiments and compile before scoring.

This is an exposed authored regression corpus. Exact numerical inference replay of outputs and recorded diagnostics,
source-copy checks and experimental calendar compilation are separate evidence;
none proves statutory meaning. No optimizer or source-encoder replay is claimed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_open_vocabulary_experiment as runner
from scripts.ops.legal_ir import summarize_legal_native_conditioning_experiment as semantic
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
from scripts.ops.legal_ir.compare_legal_decoder_architectures import require, score, sha, write
from scripts.ops.legal_ir.run_legal_span_retrieval_experiment import digest

SCHEMA = "legal-open-vocabulary-independent-analysis/v1"
ARMS = {"source_only": 0, "trained384": 384, "native768": 768}
SEEDS = (1729, 1730, 1731)
COUNTS = {"train": 1152, "tuning": 96, "challenge": 192, "oov": 45}
CONTROLS = ("disabled", "zero", "cross_family")
FALSE = {"qualified": False, "admitted": False, "semantic_correctness_verified": False,
         "production_ready": False, "independent_holdout": False,
         "optimizer_trajectory_replayed": False, "source_encoder_reexecuted": False}


def reference(ref, *, parse=True):
    require(type(ref) is dict and set(ref) in ({"path", "sha256"}, {"path", "sha256", "bytes"},
            {"path", "sha256", "bytes", "schema"}), "closed artifact reference required")
    require(sha(ref["path"]) == ref["sha256"], "artifact hash differs: " + ref["path"])
    if "bytes" in ref:
        require(Path(ref["path"]).stat().st_size == ref["bytes"], "artifact byte count differs")
    value = runner.read(ref["path"]) if parse else None
    if parse and "schema" in ref:
        require(value.get("schema") == ref["schema"], "checkpoint reference schema differs")
    return value


def source_only(rows):
    return [{key: row[key] for key in ("id", "source_text", "source_sha256", "family_group") if key in row}
            for row in rows]


def model_items(plan, heads):
    expected = {(arm, seed) for arm in ARMS for seed in SEEDS}
    require(len(heads) == 9 and {(r["arm"], r["seed"]) for r in heads} == expected,
            "complete nine selected heads required")
    for item in heads:
        require(item["name"] == f"{item['arm']}-{item['seed']}" and item["dimension"] == ARMS[item["arm"]]
            and item["latent_enabled"] is (item["dimension"] > 0), "model arm/dimension identity differs")
        require(all(item[key] is False for key in runner.FALSE), "selected head grants unsupported authority")
    return heads + [{"name": f"parent_source-{seed}", "arm": "parent_source", "seed": seed,
        "dimension": 384, "checkpoint": plan["parents"][str(seed)], "latent_enabled": False} for seed in SEEDS]


def generation_inventory(frozen, normal, items):
    require(frozen["schema"] == "legal-open-vocabulary-generation-freeze/v1"
        and frozen["all_generation_complete"] is True
        and frozen["challenge_targets_read_in_this_execution"] is False
        and frozen["independent_holdout"] is False, "complete pre-reference generation freeze required")
    names = {r["name"] for r in items}
    require(len(names) == 12 and set(frozen["files"]) == set(normal) == names, "twelve-model generation inventory differs")
    total = 0
    for item in items:
        name = item["name"]
        panels = {"tuning", "challenge", "oov"}
        if item["latent_enabled"]:
            panels |= {f"challenge_{control}_context" for control in CONTROLS}
        require(set(frozen["files"][name]) == panels and set(normal[name]) == {"tuning", "challenge", "oov"},
                "complete model intervention inventory required")
        require(all(normal[name][panel] == frozen["files"][name][panel] for panel in normal[name]),
                "normal generation changed after first freeze")
        total += sum(COUNTS["challenge" if panel.startswith("challenge") else panel] for panel in panels)
    require(total == 7452, "full numerical generation denominator differs")
    return total


def verify_swap(sources, contexts, swapped):
    require(len(sources) == len(contexts) == len(swapped), "swap row coverage differs")
    by_id = {r["id"]: r for r in sources}
    native = {r["id"]: r for r in contexts}
    require(len(by_id) == len(native) == len(sources) and set(by_id) == set(native), "swap source identities differ")
    donors = []
    for source, row in zip(sources, swapped):
        donor_id = row["donor_id"]
        require(donor_id in by_id, "unknown cross-family donor")
        donor, vector = by_id[donor_id], native[donor_id]
        require(row["id"] == source["id"] and row["source_sha256"] == source["source_sha256"]
            and row["receiving_family_group"] == source["family_group"], "swap receiver differs")
        require(donor["family_group"] != source["family_group"] and donor["source_sha256"] != source["source_sha256"]
            and row["donor_family_group"] == donor["family_group"]
            and row["donor_source_sha256"] == donor["source_sha256"], "swap is not source-disjoint and cross-family")
        require(row["context"] == vector["context"] and row["context_sha256"] == vector["context_sha256"]
            and row["donor_native_stage_receipt"] == vector["native_stage_receipt"], "swap vector/producer donor differs")
        donors.append(donor_id)
    require(len(set(donors)) == len(sources), "donor permutation duplicates or drops a source")
    require(swapped == runner.cross_family_contexts(sources, contexts), "predeclared deterministic donor permutation differs")


def verify_generation(generation, sources, contexts, *, dimension, control):
    require(set(generation) == {"reports", "rows", "control", "dimension", "control_receipts", "generation_inputs_contained_references"}
        and generation["control"] == control and generation["dimension"] == dimension
        and generation["generation_inputs_contained_references"] is False, "closed source-only generation contract differs")
    require(len(generation["rows"]) == len(sources), "generation row coverage differs")
    require([row for report in generation["reports"] for row in report["rows"]] == generation["rows"],
            "top-level predictions differ from inference reports")
    receipts = []
    copied = 0
    for index, (source, prediction) in enumerate(zip(sources, generation["rows"])):
        require(hashlib.sha256(source["source_text"].encode()).hexdigest() == source["source_sha256"], "source text hash differs")
        copied += semantic.assert_source_copy(prediction, source)
        vector = [] if contexts is None else contexts[index]["context"]
        effective = [0.] * dimension if control == "zero" else vector
        require(prediction["latent_sha256"] == digest(effective), "prediction effective context differs")
        if contexts is not None:
            context = contexts[index]
            require(context["id"] == source["id"] and context["source_sha256"] == source["source_sha256"]
                and digest(vector) == context["context_sha256"] and len(vector) == dimension, "source/context binding differs")
            receipts.append({"id": source["id"], "source_sha256": source["source_sha256"],
                "supplied_context_sha256": digest(vector), "effective_context_sha256": digest(effective),
                "context_disabled": control == "disabled", "donor_id": context.get("donor_id"),
                "donor_source_sha256": context.get("donor_source_sha256"), "target_access": False})
    require(generation["control_receipts"] == receipts, "context control receipt differs")
    return copied


def replay_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as old
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as new
    item = job["item"]
    module, cls = (old, old.SpanContinuationDecoder) if item["arm"] == "parent_source" else (new, new.DimensionalSpanDecoder)
    checkpoint = module.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"])
    decoder = cls(checkpoint)
    expected = reference(job["generation"])
    if job.get("stage_tuning"):
        expected = expected["generation"]
    actual = runner.generate(decoder, job["sources"], job["contexts"], dimension=item["dimension"], control=job["control"])
    require(actual == expected and digest(actual) == digest(expected), "fresh model output/recorded-diagnostic replay differs: " + job["name"])
    return {"name": job["name"], "checkpoint": item["checkpoint"], "generation": job["generation"],
        "source_only_inputs_sha256": digest(job["sources"]), "context_inputs_sha256": digest(job["contexts"]),
        "rows": len(job["sources"]), "exact_full_generation_and_recorded_diagnostics": True,
        "generation_payload_sha256": digest(actual), "fresh_model_loaded": True,
        "challenge_references_read": False, "stage_tuning": job.get("stage_tuning", False), **FALSE}


def verify_training(plan, heads, corpus, contexts, contracts, generation_files):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as old
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as new
    previous = reference(plan["parent_run"])
    parents = {}
    for seed in SEEDS:
        records = [row for row in previous["runs"] if row["name"] == f"source_only-{seed}"]
        require(len(records) == 1 and records[0]["checkpoint"] == plan["parents"][str(seed)], "source parent selection differs")
        ref = plan["parents"][str(seed)]
        reference(ref, parse=False)
        parent = old.load_checkpoint(ref["path"], expected_sha256=ref["sha256"])
        require(parent["base_checkpoint"]["config"]["seed"] == seed and parent["base_checkpoint"]["config"]["latent_enabled"] is False,
                "same-seed source-only parent required")
        parents[seed] = parent
    evidence, extra_jobs, common = [], [], {}
    for item in heads:
        name, arm, seed, dimension = (item[k] for k in ("name", "arm", "seed", "dimension"))
        context = contexts.get(arm)
        contract = contracts.get(arm)
        parent = parents[seed]
        train = runner.training_rows(corpus["splits"]["train"], context["train"] if context else None)
        tune = runner.training_rows(corpus["splits"]["tuning"], context["tuning"] if context else None)
        initial = new.build_checkpoint(parent["base_checkpoint"], train, tune, latent_dimension=dimension,
            latent_enabled=dimension > 0, seed=seed, context_contract=contract, learning_rate=.001, batch_size=12)
        require(item["source_parent_wrapper"] == plan["parents"][str(seed)]
            and item["source_parent_base_sha256"] == digest(parent["base_checkpoint"])
            and item["historical_parent_optimizer_updates"] == parent["source_parent_optimizer_steps"] + parent["base_checkpoint"]["progress"]["optimizer_steps"]
            and item["context_contract"] == contract, "parent lineage/context contract differs")
        require(item["initial_model_sha256"] == new.initial_model_digest(initial)
            and item["initial_source_model_sha256"] == new.initial_source_model_digest(initial), "initial copied source tensors or zero-output adapter differ")
        common.setdefault(seed, set()).add(item["initial_source_model_sha256"])
        parity = reference(item["initialization_parity"])
        require(parity["count"] == 96 and parity["parent"] == plan["parents"][str(seed)]
            and parity["source_model_sha256"] == item["initial_source_model_sha256"]
            and parity["exact_source_predictions_and_logits"] is True
            and runner.prediction_payload(parity["initial_predictions"]) == runner.prediction_payload(parity["parent_predictions"]),
                "saved initialization source-prediction parity differs")
        stages = item["stages"]
        require(len(stages) == 2 and [r["new_optimizer_steps"] for r in stages] == [400, 800]
            and item["total_new_training_steps"] == 800, "two complete equal-budget stages required")
        predecessor = initial
        audited_stages = []
        for stage in stages:
            reference(stage["checkpoint"], parse=False)
            cp = new.load_checkpoint(stage["checkpoint"]["path"], expected_sha256=stage["checkpoint"]["sha256"])
            require(cp["parent_checkpoint_sha256"] == digest(predecessor)
                and new.optimizer_steps(cp) == stage["new_optimizer_steps"], "continuation chain/step count differs")
            for key in ("config", "context_contract", "source_parent_checkpoint_sha256", "initial_model_state_sha256", "initial_source_model_sha256",
                        "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count"):
                require(cp[key] == initial[key], "stage changed fitting/source manifest: " + key)
            report = reference(stage["training_report"])
            require(report["checkpoint_sha256"] == digest(cp) and report["optimizer_steps"] == 400
                and report["new_optimizer_steps_total"] == stage["new_optimizer_steps"] and len(report["batch_losses"]) == 400
                and report["training_executed"] is True and report["stopped_reason"] == "step_limit"
                and len(set(report["changed_parameter_names"])) == len(report["changed_parameter_names"])
                and sorted(report["changed_parameter_names"]) == sorted(key for key in cp["model_state"] if cp["model_state"][key] != predecessor["model_state"][key]),
                    "stage training report/checkpoint differs")
            tuning = reference(stage["tuning_evaluation"])
            sources = corpus["splits"]["tuning"]
            verify_generation(tuning["generation"], source_only(sources), context["tuning"] if context else None, dimension=dimension, control="source")
            metrics = score(tuning["generation"]["rows"], sources, sources)
            require(metrics == tuning["metrics"] and stage["tuning_exact"] == metrics["exact"] and stage["tuning_count"] == 96,
                    "tuning selection score differs")
            audited_stages.append({"steps": stage["new_optimizer_steps"], "exact": metrics["exact"], "count": 96})
            if stage["checkpoint"] == item["checkpoint"]:
                require(tuning["generation"] == reference(generation_files[name]["tuning"]), "selected-stage tuning differs from frozen generation")
            else:
                extra_jobs.append({"name": name + "/alternate-stage-tuning", "item": {**item, "checkpoint": stage["checkpoint"]},
                    "sources": source_only(sources), "contexts": context["tuning"] if context else None, "control": "source",
                    "generation": stage["tuning_evaluation"], "stage_tuning": True})
            predecessor = cp
        selected = max(stages, key=lambda row: (row["tuning_exact"], -row["new_optimizer_steps"]))
        require(item["checkpoint"] == selected["checkpoint"] and item["selected_new_steps"] == selected["new_optimizer_steps"]
            and item["selection_tuning_exact"] == selected["tuning_exact"], "checkpoint was not chosen by tuning with earliest-stage tie")
        evidence.append({"name": name, "stages": audited_stages, "selected_new_steps": item["selected_new_steps"],
            "initial_source_model_sha256": item["initial_source_model_sha256"], "fitting_manifest_verified": True,
            "checkpoint_chain_verified": True, "optimizer_trajectory_replayed": False})
    require(all(len(values) == 1 for values in common.values()) and len(extra_jobs) == 9, "matched initialization or alternate-stage coverage differs")
    return evidence, extra_jobs


def build_accounting(selection, receipts, exact_by_id):
    inventory = [r["candidate"]["candidate_id"] for r in selection["rows"]] + [r["candidate_id"] for r in selection["excluded"]]
    all_ids = set(inventory)
    require(len(inventory) == len(all_ids) and selection["supported_count"] == len(selection["rows"]), "duplicate or miscounted selection rows")
    require(len(all_ids) == selection["source_count"] and set(exact_by_id) == all_ids, "full build/reference denominator differs")
    supported = [r["candidate"]["candidate_id"] for r in selection["rows"]]
    attempted = [identity for receipt in receipts for identity in receipt["candidate_ids"]]
    require(attempted == supported and len(set(attempted)) == len(attempted), "compiled batch coverage/order differs")
    built = {identity for receipt in receipts if receipt["build_passed"] for identity in receipt["candidate_ids"]}
    count = selection["source_count"]
    exact = sum(exact_by_id.values())
    return {"count": count, "decoded": selection["decoded_count"], "abstained": count - selection["decoded_count"],
        "supported": len(supported), "excluded": len(selection["excluded"]), "built": len(built),
        "exact": exact, "built_exact": sum(exact_by_id[i] for i in built),
        "built_reference_mismatch": sum(not exact_by_id[i] for i in built),
        "actual_lake_build_executed": any(r["backend_executed"] for r in receipts),
        "build_invocations": sum(r["backend_executed"] for r in receipts), "exclusion_counts": selection["exclusion_counts"]}


def run(args):
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    require(1 <= args.workers <= 3 and 0 < args.timeout_seconds <= 60, "bounded workers/build timeout required")
    directory, output = Path(args.run_directory).resolve(), Path(args.output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan_ref = runner.file_ref(directory / "plan.json")
    plan = reference(plan_ref)
    require(plan["schema"] == runner.SCHEMA and plan["arms"] == ARMS and plan["seeds"] == list(SEEDS)
        and plan["counts"] == COUNTS and plan["stage_steps"] == 400 and plan["stages"] == 2
        and plan["controls"] == ["source", *CONTROLS]
        and all(plan[key] is False for key in runner.FALSE), "matched predeclared experiment plan differs")
    pins = dict(plan["producer_pins"])
    for module in (runner, semantic, calendar, calendar_summary, gate, sys.modules[__name__]):
        pins[str(Path(module.__file__).resolve())] = sha(module.__file__)
    require(all(sha(path) == wanted for path, wanted in plan["producer_pins"].items()), "producer pin drift")
    for ref in plan["input_closure"]:
        reference(ref, parse=False)
    reference(plan["targets"], parse=False)  # Byte commitment only; no challenge JSON parsing.
    corpus = reference(plan["corpus"])
    runner.verify_source_inputs(corpus)
    splits = corpus["splits"]
    require({k: len(v) for k, v in splits.items()} == COUNTS, "complete source corpus required")
    prepared = {split: source_only(rows) for split, rows in splits.items()}
    require(runner.read(directory / "prepared-inputs.json") == prepared, "prepared source-only records differ")
    manifest, contexts, contracts, context_refs, inspection = runner.load_context_manifest(
        plan["context_manifest"]["path"], plan["context_manifest"]["sha256"], corpus)
    pins.update(manifest["producer_pins"])
    require(inspection == reference(plan["native_context_inspection"]), "authentic native producer inspection differs")
    heads_ref, frozen_ref = runner.file_ref(directory / "frozen-heads.json"), runner.file_ref(directory / "generation-frozen.json")
    heads, frozen = reference(heads_ref), reference(frozen_ref)
    require(reference(frozen["frozen_heads"]) == heads, "frozen selected heads differ")
    items = model_items(plan, heads)
    normal = reference(frozen["normal_generation_freeze"])
    generation_inventory(frozen, normal, items)
    evidence, jobs = verify_training(plan, heads, corpus, contexts, contracts, frozen["files"])
    training_ref = write(output / "training-selection-audit.json", evidence)
    generations = {}
    for item in items:
        name = item["name"]
        generations[name] = {}
        swapped = None
        if item["latent_enabled"]:
            swapped = runner.read(directory / name / "cross-family-contexts.json")
            verify_swap(prepared["challenge"], contexts[item["arm"]]["challenge"], swapped)
        for panel, ref in frozen["files"][name].items():
            split = "challenge" if panel.startswith("challenge") else panel
            control = next((c for c in CONTROLS if panel == f"challenge_{c}_context"), "source")
            context = contexts[item["arm"]][split] if item["latent_enabled"] else None
            if item["arm"] == "parent_source":
                context = [{"id": row["id"], "source_sha256": row["source_sha256"], "context": row["embedding"],
                    "context_sha256": digest(row["embedding"])} for row in splits[split]]
            if control == "cross_family":
                context = swapped
            generation = reference(ref)
            verify_generation(generation, prepared[split], context, dimension=item["dimension"], control=control)
            generations[name][panel] = generation
            jobs.append({"name": name + "/" + panel, "item": item, "sources": prepared[split],
                "contexts": context, "control": control, "generation": ref})
    require(len(jobs) == 63 and sum(len(j["sources"]) for j in jobs) == 8316, "complete fresh replay inventory differs")
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            receipt = future.result()
            replays.append(receipt)
            print({"phase": "numerical_replay", "panel": receipt["name"], "rows": receipt["rows"]}, flush=True)
    replay_ref = write(output / "numerical-replay-frozen.json", {"schema": SCHEMA, "plan": plan_ref, "generations": frozen_ref,
        "rows": 8316, "main_generation_rows": 7452, "alternate_stage_tuning_rows": 864,
        "panels": sorted(replays, key=lambda r: r["name"]), "challenge_references_opened": False,
        "initialization_numerical_parity_replayed": False, "initialization_tensor_reconstruction_verified": True, **FALSE})
    selections = {}
    for item in items:
        name = item["name"]
        selected = calendar.select_candidates(prepared["challenge"], generations[name]["challenge"]["rows"],
            toolchain=args.toolchain, policy=calendar.POLICY)
        source_by_id = {r["id"]: r for r in prepared["challenge"]}
        pred_by_id = dict(zip(source_by_id, generations[name]["challenge"]["rows"]))
        for entry in selected["rows"]:
            identity = entry["candidate"]["candidate_id"]
            calendar_summary.verify_entry(source_by_id[identity], pred_by_id[identity], entry)
        require(selected["source_count"] == len(selected["rows"]) + len(selected["excluded"]) == 192,
                "reference-free selection dropped rows")
        selections[name] = selected
    selection_ref = write(output / "selections-frozen.json", {"models": selections, "source_count": 2304,
        "interpretation_policy": calendar.POLICY, "canonical_references_used_for_selection": False,
        "semantic_scores_used_for_selection": False, "source_semantics_verified": False})
    builds = {}
    for item in items:
        name = item["name"]
        entries = selections[name]["rows"]
        builds[name] = []
        for start in range(0, len(entries), gate.MAX_ROWS):
            batch = entries[start:start + gate.MAX_ROWS]
            destination = output / "builds" / name / f"batch-{start // gate.MAX_ROWS:02d}"
            receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=args.timeout_seconds, output_directory=destination).to_dict()
            ref = {"path": str(destination / "qualified-receipt.json"), "sha256": sha(destination / "qualified-receipt.json")}
            require(calendar_summary.verify_receipt(ref, batch) == receipt, "persisted compiler receipt replay differs")
            builds[name].append({"candidate_ids": [r["candidate"]["candidate_id"] for r in batch], "receipt": ref,
                "build_passed": receipt["build_passed"], "backend_executed": receipt["backend_executed"],
                "command": receipt["command"], "manifest_coverage_passed": receipt["manifest_coverage_passed"]})
        print({"phase": "actual_lake_builds", "name": name, "supported": len(entries), "batches": len(builds[name])}, flush=True)
    build_ref = write(output / "builds-frozen.json", {"schema": SCHEMA, "numerical_replay": replay_ref,
        "selections": selection_ref, "models": builds, "challenge_references_opened": False,
        "canonical_references_used_for_selection": False, "policy": calendar.POLICY, **FALSE})
    # Challenge references and runner score artifacts become visible only here.
    payload = reference(plan["targets"])
    targets = {r["id"]: r for r in payload["targets"]}
    require(len(targets) == len(payload["targets"]) == 192 and set(targets) == {r["id"] for r in splits["challenge"]},
            "complete authored challenge target inventory required")
    references = []
    for source in splits["challenge"]:
        target = targets[source["id"]]
        require(target["source_sha256"] == source["source_sha256"] and digest(target["canonical_ir"]) ==
            target["canonical_target_sha256"] == source["canonical_target_sha256"], "challenge target source commitment differs")
        references.append({"id": source["id"], "source_text": source["source_text"], "canonical_ir": target["canonical_ir"]})
    completed_ref = runner.file_ref(directory / "summary.json")
    completed = reference(completed_ref)
    require(reference(completed["plan"]) == plan and reference(completed["frozen_heads"]) == heads
        and reference(completed["generation_frozen"]) == frozen
        and completed["challenge_targets_read_after_all_training_selection_and_generation"] is True
        and completed["evaluation_cohort_previously_exposed"] is True, "completed run references/scope differ")
    reported = {r["name"]: r for r in completed["runs"]}
    require(len(reported) == len(completed["runs"]) == 12 and set(reported) == set(generations), "reported model coverage differs")
    known = semantic.shared.training_atoms(splits["train"])
    measures, results = {}, []
    for item in items:
        name = item["name"]
        require(all(reported[name][key] == value for key, value in item.items()), "summary changed frozen selected head")
        measures[name], scores = {}, {}
        for panel, generation in generations[name].items():
            challenge = panel.startswith("challenge")
            split = "challenge" if challenge else panel
            if panel == "oov":
                counts = Counter(r["status"] for r in generation["rows"])
                metric = {"count": 45, "decoded": counts["decoded"], "abstained": counts["abstained"], "semantic_accuracy": None}
                filename, key = "dataset-transfer", "dataset_transfer"
            else:
                gold = references if challenge else splits["tuning"]
                metric = score(generation["rows"], splits[split], gold)
                filename = key = panel
                measures[name][panel] = semantic.evaluate(generation["rows"], splits[split], {r["id"]: r["canonical_ir"] for r in gold}, known)
            persisted = runner.read(directory / name / (filename + ".json"))
            require(persisted == {"generation": generation, "metrics": metric}
                and reported[name]["scores"][key] == {k: v for k, v in metric.items() if k != "rows"},
                    "posthoc persisted scores differ from frozen predictions")
            scores[panel] = {k: v for k, v in metric.items() if k != "rows"}
        require(set(reported[name]["scores"]) == {"dataset_transfer" if k == "oov" else k for k in scores}, "summary score panel inventory differs")
        exact_by_id = {r["id"]: r["exact"] for r in measures[name]["challenge"]["rows"]}
        accounting = build_accounting(selections[name], builds[name], exact_by_id)
        changes = {}
        normal_rows = generations[name]["challenge"]["rows"]
        for control in CONTROLS:
            panel = f"challenge_{control}_context"
            if panel not in generations[name]:
                continue
            rows = generations[name][panel]["rows"]
            changes[control] = {"count": len(rows), "canonical_output_changed": sum(
                (a["status"], a["canonical_ir"]) != (b["status"], b["canonical_ir"]) for a, b in zip(normal_rows, rows)),
                "full_prediction_record_changed": sum(a != b for a, b in zip(normal_rows, rows)),
                "recorded_span_diagnostics_changed": sum(a.get("span_diagnostics") != b.get("span_diagnostics") for a, b in zip(normal_rows, rows)),
                "exact_delta_vs_source": scores[panel]["exact"] - scores["challenge"]["exact"]}
        results.append({"name": name, "arm": item["arm"], "seed": item["seed"], "dimension": item["dimension"],
            "selected_new_steps": item.get("selected_new_steps", 0), "scores": scores, "builds": accounting,
            "controls": changes, "challenge_facets": {k: v for k, v in measures[name]["challenge"].items() if k != "rows"}})
    details_ref = write(output / "authored-reference-details.json", measures)
    comparisons = []
    for seed in SEEDS:
        pairs = [(f"source_only-{seed}", f"parent_source-{seed}"),
                 (f"trained384-{seed}", f"source_only-{seed}"), (f"native768-{seed}", f"source_only-{seed}")]
        for left, right in pairs:
            a = {r["id"]: r["exact"] for r in measures[left]["challenge"]["rows"]}
            b = {r["id"]: r["exact"] for r in measures[right]["challenge"]["rows"]}
            comparisons.append({"left": left, "right": right, "count": 192,
                "left_only_correct": sum(a[i] and not b[i] for i in a), "right_only_correct": sum(b[i] and not a[i] for i in a),
                "both_correct": sum(a[i] and b[i] for i in a), "both_wrong": sum(not a[i] and not b[i] for i in a)})
    totals = {}
    for role in ("new_selected", "unchanged_parents"):
        group = [r for r in results if (r["arm"] == "parent_source") is (role == "unchanged_parents")]
        totals[role] = {key: sum(r["builds"][key] for r in group) for key in
            ("count", "decoded", "abstained", "supported", "excluded", "built", "exact", "built_exact", "built_reference_mismatch", "build_invocations")}
        totals[role]["models"] = len(group)
    require(totals["new_selected"]["count"] == 1728 and totals["unchanged_parents"]["count"] == 576, "challenge accounting denominator differs")
    require(all(sha(path) == wanted for path, wanted in pins.items()), "implementation changed during independent analysis")
    training_refs = [ref for item in heads for stage in item["stages"] for ref in
        (stage["checkpoint"], stage["training_report"], stage["tuning_evaluation"])]
    for ref in [plan_ref, heads_ref, frozen_ref, *context_refs, *training_refs, plan["targets"], completed_ref,
                *[ref for panels in frozen["files"].values() for ref in panels.values()]]:
        reference(ref, parse=False)
    result = {"schema": SCHEMA, "plan": plan_ref, "completed_run": completed_ref, "producer_pins": pins,
        "training_selection": training_ref, "numerical_replay": replay_ref, "frozen_builds": build_ref,
        "authored_reference_details": details_ref, "models": results, "totals": totals, "paired_comparisons": comparisons,
        "main_generation_rows_replayed": 7452, "alternate_stage_tuning_rows_replayed": 864,
        "total_inference_rows_replayed": 8316, "all_frozen_outputs_and_recorded_diagnostics_replayed_exactly": True,
        "challenge_targets_opened_after_replay_and_build_freeze": True, "evaluation_cohort_previously_exposed": True,
        "statutory_oov_has_semantic_gold": False, "source_embeddings_authenticated_from_pinned_native_receipts": True,
        "interpretation_policy": calendar.POLICY, "actual_lake_build_executed": any(
            r["backend_executed"] for receipts in builds.values() for r in receipts),
        "compiled_artifacts_scope": "native compiler produced olean hashes; temporary build artifacts cleaned by bounded backend",
        "scope": "Exposed authored single-rule source-copy regression and literal OOV spans; calendar semantics explicitly caller-declared; compilation does not establish source meaning",
        **FALSE}
    write(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--lake-executable", required=True)
    parser.add_argument("--toolchain", default="leanprover/lean4:v4.34.1")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--workers", type=int, default=3)
    run(parser.parse_args())
