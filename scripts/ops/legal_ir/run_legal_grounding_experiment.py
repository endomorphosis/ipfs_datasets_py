#!/usr/bin/env python3
"""Frozen, matched actor/modal grounding study with separate qualification.

Authored construction holdouts are engineering evidence, not statutory gold.
Training and generation never open challenge targets. Qualification replays all
recorded generations and compiles predictions before opening those targets.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_open_vocabulary_experiment as shared
from scripts.ops.legal_ir.compare_legal_decoder_architectures import score

require, read, sha, write, digest = shared.require, shared.read, shared.sha, shared.write, shared.digest
SCHEMA = "legal-coordinate-grounding-experiment/v1"
SEEDS = (1729, 1730, 1731)
ARMS = {"source_continuation": False, "trigger_grounding": True}
STAGE_STEPS = 400
FALSE = {"qualified": False, "production_ready": False, "semantic_correctness_verified": False,
         "all_logic_families_supported": False, "statutory_gold_available": False}


def ref(path):
    return shared.file_ref(path)


def read_ref(reference, *, parse=True):
    require(type(reference) is dict and set(reference) in ({"path", "sha256"},
        {"path", "sha256", "bytes"}, {"path", "sha256", "bytes", "schema"}), "closed artifact reference required")
    require(sha(reference["path"]) == reference["sha256"], "artifact hash differs: " + reference["path"])
    if "bytes" in reference:
        require(Path(reference["path"]).stat().st_size == reference["bytes"], "artifact size differs")
    value = read(reference["path"]) if parse else None
    if parse and "schema" in reference:
        require(value["schema"] == reference["schema"], "artifact schema differs")
    return value


def source_rows(rows):
    result = []
    require(type(rows) is list and len(rows) > 0, "nonempty source inventory required")
    for row in rows:
        text = row["source_text"]
        hashed = hashlib.sha256(text.encode()).hexdigest()
        require(row.get("source_sha256", hashed) == hashed, "source hash differs")
        result.append({"id": row["id"], "source_text": text, "source_sha256": hashed})
    require(len({r["id"] for r in result}) == len(result), "duplicate source identities")
    return result


def verify_splits(training, tuning, challenge):
    groups = [source_rows(rows) for rows in (training, tuning, challenge)]
    ids, texts = set(), set()
    for group in groups:
        local_ids, local_texts = {r["id"] for r in group}, {r["source_sha256"] for r in group}
        require(len(local_texts) == len(group) and not ids & local_ids and not texts & local_texts,
            "duplicate or overlapping corpus sources")
        ids |= local_ids
        texts |= local_texts
    require(all(not {"canonical_ir", "trigger_span", "facet_spans"} & set(row) for row in challenge),
        "challenge generation inputs contain targets")
    return groups


def generate(decoder, sources, *, parent=False, ablation="none"):
    require(ablation in ("none", "disabled") and not (parent and ablation != "none"), "invalid intervention")
    reports, rows = [], []
    for start in range(0, len(sources), 128):
        texts = [r["source_text"] for r in sources[start:start + 128]]
        report = decoder.decode_formal_logic(texts) if parent else decoder.decode_formal_logic(texts, trigger_ablation=ablation)
        require(report["target_access"] is False and report["teacher_forcing"] is False, "source-only inference required")
        reports.append(report)
        rows.extend(report["rows"])
    require(len(rows) == len(sources), "generation coverage differs")
    for source, prediction in zip(sources, rows):
        require(source["source_sha256"] == prediction["source_sha256"], "prediction/source differs")
    return {"reports": reports, "rows": rows, "ablation": ablation, "target_access": False}


def comparable(generation):
    fields = ("source_sha256", "status", "canonical_ir", "reason", "span_diagnostics")
    return [{k: row[k] for k in fields if k in row} for row in generation["rows"]]


def select_stage(stages):
    require(bool(stages) and len({s["steps"] for s in stages}) == len(stages), "unique training stages required")
    return max(stages, key=lambda s: (s["tuning_exact"], -s["steps"]))


def fit_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    parent = dimensions.load_checkpoint(job["parent"]["path"], expected_sha256=job["parent"]["sha256"])
    require(parent["config"]["seed"] == job["seed"] and parent["config"]["latent_dimension"] == 0,
        "same-seed source-only parent required")
    cp = grounding.build_checkpoint(parent, job["training"], job["tuning"],
        trigger_enabled=job["enabled"], learning_rate=.001, batch_size=12)
    sources = source_rows(job["tuning"])
    original = generate(dimensions.DimensionalSpanDecoder(parent), sources, parent=True)
    initial = generate(grounding.GroundedSpanDecoder(cp), sources)
    require(comparable(original) == comparable(initial), "initial source logits differ from parent")
    folder = Path(job["folder"])
    folder.mkdir()
    initialization = write(folder / "initialization.json", {"parent": job["parent"],
        "checkpoint_sha256": digest(cp), "source_state_sha256": digest(parent["model_state"]),
        "parent_generation": original, "initial_generation": initial, "all_tuning_predictions_equal": True})
    stages = []
    for ordinal in (1, 2):
        previous = digest(cp)
        trained = grounding.train_decoder(cp, job["training"], job["tuning"], max_steps=STAGE_STEPS, max_seconds=600)
        cp = trained["checkpoint"]
        steps = grounding.optimizer_steps(cp)
        require(steps == ordinal * STAGE_STEPS, "incomplete matched optimizer budget")
        checkpoint = grounding.save_checkpoint(cp, folder / f"checkpoint-{steps}.json")
        report = write(folder / f"training-{steps}.json", trained["report"])
        generation = generate(grounding.GroundedSpanDecoder(cp), sources)
        metric = score(generation["rows"], sources, job["tuning"])
        tuning = write(folder / f"tuning-{steps}.json", {"generation": generation, "metrics": metric})
        stages.append({"steps": steps, "checkpoint": checkpoint, "previous_checkpoint_sha256": previous,
            "training_report": report, "tuning_generation": tuning, "tuning_exact": metric["exact"]})
        print(json.dumps({"phase": "trained", "arm": job["arm"], "seed": job["seed"],
            "steps": steps, "tuning_exact": metric["exact"]}), flush=True)
    selected = select_stage(stages)
    return {"name": f"{job['arm']}-{job['seed']}", "arm": job["arm"], "seed": job["seed"],
        "enabled": job["enabled"], "parent": job["parent"], "initialization": initialization,
        "stages": stages, "checkpoint": selected["checkpoint"], "selected_steps": selected["steps"],
        "executed_steps": 2 * STAGE_STEPS}


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_grounding_curriculum as curriculum
    config = read(path)
    fields = {"schema", "curriculum_manifest", "training", "tuning", "challenge_sources", "challenge_targets",
        "parent_heads", "regression_sources", "regression_targets", "producer_files"}
    require(set(config) == fields and config["schema"] == "legal-grounding-run-config/v1", "closed run config required")
    for key in fields - {"schema", "producer_files", "challenge_targets", "regression_targets"}:
        read_ref(config[key], parse=False)
    # The corpus freeze already committed these bytes. Fitting checks only the
    # pinned reference metadata; qualification opens and hashes them later.
    for key in ("challenge_targets", "regression_targets"):
        target = config[key]
        require(type(target) is dict and set(target) == {"path", "sha256", "bytes"}
            and type(target["path"]) is str and type(target["sha256"]) is str and len(target["sha256"]) == 64
            and type(target["bytes"]) is int and target["bytes"] > 0, "sealed target reference metadata required")
    for item in config["producer_files"]:
        read_ref(item, parse=False)
    training, tuning, challenge = (read_ref(config[key]) for key in ("training", "tuning", "challenge_sources"))
    manifest, bound_train, bound_tune, bound_sources = curriculum.load_training_inputs(config["curriculum_manifest"]["path"])
    require((training, tuning, challenge) == (bound_train, bound_tune, bound_sources), "run corpus differs from frozen curriculum")
    for name, key in (("train", "training"), ("tuning", "tuning"), ("challenge_sources", "challenge_sources"),
                      ("challenge_targets", "challenge_targets")):
        require(manifest["artifacts"][name]["sha256"] == config[key]["sha256"], "curriculum artifact commitment differs")
    verify_splits(training, tuning, challenge)
    regression = read_ref(config["regression_sources"])["challenge"]
    parents = {item["seed"]: item for item in read_ref(config["parent_heads"]) if item["arm"] == "source_only"}
    require(set(parents) == set(SEEDS), "complete source-only parent seeds required")
    require(not {r["source_sha256"] for r in source_rows(training + tuning + challenge)} &
        {r["source_sha256"] for r in regression}, "new corpus overlaps exposed regression")
    return config, training, tuning, source_rows(challenge), source_rows(regression), parents


def run_training(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    require(1 <= args.workers <= 3, "one to three workers required")
    config, training, tuning, challenge, regression, parents = load_config(args.config)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in
        (shared, grounding, dimensions, sys.modules[__name__])}
    plan = {"schema": SCHEMA, "config": ref(args.config), "arms": ARMS, "seeds": list(SEEDS),
        "stage_steps": STAGE_STEPS, "stages": 2, "learning_rate": .001, "batch_size": 12,
        "counts": {"training": len(training), "tuning": len(tuning), "challenge": len(challenge), "regression": len(regression)},
        "producer_pins": pins, "selection": "maximum tuning exact then earliest checkpoint; all seeds retained",
        "challenge_target_access": False, "scope": "new authored construction holdout plus exposed regression",
        "old_training_replay": False, "baseline": "same selected source-only parent; fresh Adam; identical new curriculum",
        "intervention": "disable learned residuals after training; shared-encoder training effects remain", **FALSE}
    plan_ref = write(output / "plan.json", plan)
    write(output / "source-inputs.json", {"tuning": source_rows(tuning), "challenge": challenge, "regression": regression})
    jobs = [{"arm": arm, "enabled": enabled, "seed": seed, "parent": parents[seed]["checkpoint"],
        "training": training, "tuning": tuning, "folder": str(output / f"{arm}-{seed}")}
        for arm, enabled in ARMS.items() for seed in SEEDS]
    heads = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(fit_job, job) for job in jobs]):
            heads.append(future.result())
    heads.sort(key=lambda r: r["name"])
    head_ref = write(output / "heads-frozen.json", heads)
    items = heads + [{"name": f"parent-{seed}", "arm": "parent", "seed": seed,
        "checkpoint": parents[seed]["checkpoint"], "enabled": False} for seed in SEEDS]
    files = {}
    for item in items:
        parent = item["arm"] == "parent"
        module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if parent else (grounding, grounding.GroundedSpanDecoder)
        cp = module.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"])
        decoder = cls(cp)
        folder = output / item["name"]
        folder.mkdir(exist_ok=True)
        files[item["name"]] = {}
        for panel, sources in (("tuning", source_rows(tuning)), ("challenge", challenge), ("regression", regression)):
            files[item["name"]][panel] = write(folder / f"{panel}-generation.json", generate(decoder, sources, parent=parent))
        if item["enabled"]:
            files[item["name"]]["challenge_disabled"] = write(folder / "challenge-disabled-generation.json",
                generate(decoder, challenge, ablation="disabled"))
    require(all(sha(path) == wanted for path, wanted in pins.items()), "producer changed during fitting")
    load_config(args.config)  # Reverify fitting inputs; target commitments stay metadata only.
    result = {"schema": SCHEMA, "plan": plan_ref, "heads": head_ref, "models": items, "files": files,
        "all_training_selection_and_generation_complete": True, "challenge_targets_opened": False, **FALSE}
    write(output / "generation-frozen.json", result)
    print(json.dumps({"phase": "generation_frozen", "models": len(items), "optimizer_updates": len(heads) * 800}), flush=True)
    return result


def replay_job(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    from scripts.ops.legal_ir.summarize_legal_native_conditioning_experiment import assert_source_copy
    item, expected = job["model"], read_ref(job["generation"])
    if job.get("stage"):
        expected = expected["generation"]
    parent = item["arm"] == "parent"
    module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if parent else (grounding, grounding.GroundedSpanDecoder)
    cp = module.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"])
    actual = generate(cls(cp), job["sources"], parent=parent, ablation=job["ablation"])
    require(actual == expected, "fresh inference replay differs: " + job["name"])
    copied = sum(assert_source_copy(prediction, source) for prediction, source in zip(actual["rows"], job["sources"]))
    return {"name": job["name"], "rows": len(job["sources"]), "copied_facets_verified": copied,
        "generation": job["generation"], "exact_recorded_payload_replay": True, "target_access": False}


def reference_rows(targets, sources):
    if type(targets) is dict:
        targets = targets["targets"]
    require(type(targets) is list, "target list required")
    by_id = {r["id"]: r for r in targets}
    require(len(by_id) == len(targets) == len(sources) and set(by_id) == {r["id"] for r in sources},
        "complete target coverage required")
    result = []
    for source in sources:
        target = by_id[source["id"]]
        require(target.get("source_text", source["source_text"]) == source["source_text"] and
            target.get("source_sha256", source["source_sha256"]) == source["source_sha256"], "target/source binding differs")
        result.append({**target, "source_text": source["source_text"]})
    return result


def metrics(generation, sources, gold):
    result = score(generation["rows"], sources, gold)
    confusion = Counter()
    actor_start = actor_end = actor_both = trigger = 0
    coordinate_count = 0
    for pred, target in zip(generation["rows"], gold):
        wanted = target["canonical_ir"]["rules"][0]["modality"]
        actual = pred["canonical_ir"]["rules"][0]["modality"] if pred["status"] == "decoded" else "abstained"
        confusion[wanted + "->" + actual] += 1
        if "facet_spans" not in target:
            continue
        coordinate_count += 1
        actor = pred.get("span_diagnostics", {}).get("facets", {}).get("actor", {})
        left, right = target["facet_spans"]["actor"]
        start_ok, end_ok = actor.get("char_start") == left, actor.get("char_end") == right
        actor_start += start_ok
        actor_end += end_ok
        actor_both += start_ok and end_ok
        modal = pred.get("grounding_diagnostics", {}).get("trigger", {})
        trigger += [modal.get("char_start"), modal.get("char_end")] == target["trigger_span"]
    result.update(modality_confusion=dict(confusion), coordinate_count=coordinate_count,
        actor_start_exact=actor_start, actor_end_exact=actor_end, actor_span_exact=actor_both,
        trigger_span_exact=trigger)
    return result


def paired(a, b):
    require(len(a["rows"]) == len(b["rows"]) and [r["id"] for r in a["rows"]] == [r["id"] for r in b["rows"]],
        "paired metric identities differ")
    counts = Counter((left["exact"], right["exact"]) for left, right in zip(a["rows"], b["rows"]))
    return {"count": len(a["rows"]), "left_only_correct": counts[True, False],
        "right_only_correct": counts[False, True], "both_correct": counts[True, True], "both_wrong": counts[False, False]}


def run_qualification(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
    from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary
    from scripts.ops.legal_ir.summarize_legal_open_vocabulary_experiment import build_accounting
    require(1 <= args.workers <= 3, "bounded replay workers required")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    directory = Path(args.run_directory)
    frozen_ref = ref(directory / "generation-frozen.json")
    frozen = read_ref(frozen_ref)
    plan = read_ref(frozen["plan"])
    require(frozen["all_training_selection_and_generation_complete"] is True and frozen["challenge_targets_opened"] is False,
        "pre-reference generation freeze required")
    require(plan["arms"] == ARMS and plan["seeds"] == list(SEEDS) and plan["stage_steps"] == 400 and plan["stages"] == 2,
        "predeclared matched plan differs")
    read_ref(plan["config"], parse=False)
    config, training, tuning, challenge, regression, parents = load_config(plan["config"]["path"])
    require(all(sha(path) == value for path, value in plan["producer_pins"].items()), "experiment producer drift")
    panels = {"tuning": source_rows(tuning), "challenge": challenge, "regression": regression, "challenge_disabled": challenge}
    heads = read_ref(frozen["heads"])
    require({r["name"] for r in heads} == {f"{arm}-{seed}" for arm in ARMS for seed in SEEDS} and len(heads) == 6,
        "complete six trained heads required")
    require(len(frozen["models"]) == 9 and set(frozen["files"]) == {r["name"] for r in frozen["models"]}, "complete nine models required")
    require({r["name"] for r in frozen["models"]} == {r["name"] for r in heads} | {f"parent-{s}" for s in SEEDS},
        "model identity inventory differs")
    for item in frozen["models"]:
        if item["arm"] == "parent":
            require(item["name"] == f"parent-{item['seed']}" and item["checkpoint"] == parents[item["seed"]]["checkpoint"]
                and item["enabled"] is False, "unchanged parent attribution differs")
    jobs, audits = [], []
    for head in heads:
        require(head in frozen["models"] and head["enabled"] is ARMS[head["arm"]], "frozen head differs")
        parent = read_ref(head["parent"])
        require(head["parent"] == parents[head["seed"]]["checkpoint"], "parent selection differs")
        cp = grounding.build_checkpoint(parent, training, tuning, trigger_enabled=head["enabled"], learning_rate=.001, batch_size=12)
        initial = read_ref(head["initialization"])
        require(initial["checkpoint_sha256"] == digest(cp) and initial["source_state_sha256"] == digest(parent["model_state"]),
            "initial tensor reconstruction differs")
        require(comparable(initial["parent_generation"]) == comparable(initial["initial_generation"]), "initial parity differs")
        require([stage["steps"] for stage in head["stages"]] == [400, 800] and head["executed_steps"] == 800, "training stages differ")
        for stage in head["stages"]:
            prior = digest(cp)
            cp = grounding.load_checkpoint(stage["checkpoint"]["path"], expected_sha256=stage["checkpoint"]["sha256"])
            require(grounding.optimizer_steps(cp) == stage["steps"] and stage["previous_checkpoint_sha256"] == prior,
                "checkpoint step/chain differs")
            require(cp["parent_checkpoint_sha256"] == prior and cp["training_manifest_sha256"] == digest(training)
                and cp["tuning_manifest_sha256"] == digest(tuning), "checkpoint data/parent binding differs")
            require(cp["source_parent_checkpoint_sha256"] == digest(parent) and cp["config"]["trigger_enabled"] is head["enabled"],
                "trained model source/arm differs")
            report = read_ref(stage["training_report"])
            require(report["optimizer_steps"] == 400 and len(report["batch_losses"]) == 400
                and report["checkpoint_sha256"] == digest(cp), "training execution receipt differs")
            tuned = read_ref(stage["tuning_generation"])
            require(score(tuned["generation"]["rows"], panels["tuning"], tuning) == tuned["metrics"]
                and tuned["metrics"]["exact"] == stage["tuning_exact"], "tuning score differs")
            jobs.append({"name": head["name"] + f"/stage-{stage['steps']}", "model": {**head, "checkpoint": stage["checkpoint"]},
                "sources": panels["tuning"], "generation": stage["tuning_generation"], "ablation": "none", "stage": True})
        selected = select_stage(head["stages"])
        require(selected["checkpoint"] == head["checkpoint"] and selected["steps"] == head["selected_steps"], "tuning selection differs")
        audits.append({"name": head["name"], "selected_steps": head["selected_steps"], "executed_steps": 800,
            "initial_tensors_and_checkpoint_chain_verified": True, "optimizer_trajectory_replayed": False})
    generations = {}
    for item in frozen["models"]:
        expected_panels = {"tuning", "challenge", "regression"} | ({"challenge_disabled"} if item["enabled"] else set())
        require(set(frozen["files"][item["name"]]) == expected_panels, "generation panel inventory differs")
        generations[item["name"]] = {}
        for panel, reference in frozen["files"][item["name"]].items():
            generations[item["name"]][panel] = read_ref(reference)
            jobs.append({"name": item["name"] + "/" + panel, "model": item, "sources": panels[panel],
                "generation": reference, "ablation": "disabled" if panel.endswith("disabled") else "none"})
    replays = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(replay_job, job) for job in jobs]):
            replays.append(future.result())
    replay_ref = write(output / "replay-frozen.json", {"rows": sum(r["rows"] for r in replays),
        "panels": sorted(replays, key=lambda r: r["name"]), "training_audits": audits, "challenge_targets_opened": False})
    selections = {item["name"]: calendar.select_candidates(challenge, generations[item["name"]]["challenge"]["rows"],
        toolchain=args.toolchain, policy=calendar.POLICY) for item in frozen["models"]}
    selections_ref = write(output / "build-selection-frozen.json", {"models": selections, "challenge_targets_opened": False,
        "interpretation_policy": calendar.POLICY})
    builds = {}
    for item in frozen["models"]:
        name = item["name"]
        entries = selections[name]["rows"]
        builds[name] = []
        for start in range(0, len(entries), gate.MAX_ROWS):
            batch = entries[start:start + gate.MAX_ROWS]
            destination = output / "builds" / name / f"batch-{start // gate.MAX_ROWS:02d}"
            receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=60, output_directory=destination).to_dict()
            receipt_ref = ref(destination / "qualified-receipt.json")
            require(calendar_summary.verify_receipt(receipt_ref, batch) == receipt, "compiler receipt replay differs")
            builds[name].append({"candidate_ids": [r["candidate"]["candidate_id"] for r in batch], "receipt": receipt_ref,
                "build_passed": receipt["build_passed"], "backend_executed": receipt["backend_executed"], "command": receipt["command"]})
        print(json.dumps({"phase": "built", "model": name, "supported": len(entries)}), flush=True)
    builds_ref = write(output / "builds-frozen.json", {"models": builds, "selections": selections_ref,
        "replays": replay_ref, "challenge_targets_opened": False})
    # First challenge-reference parse occurs only after all replay/build freezes.
    gold = {"challenge": reference_rows(read_ref(config["challenge_targets"]), challenge),
        "regression": reference_rows(read_ref(config["regression_targets"]), regression), "tuning": tuning}
    gold["challenge_disabled"] = gold["challenge"]
    details, models = {}, []
    for item in frozen["models"]:
        name = item["name"]
        details[name] = {panel: metrics(generation, panels[panel], gold[panel]) for panel, generation in generations[name].items()}
        exact = {r["id"]: r["exact"] for r in details[name]["challenge"]["rows"]}
        controls = {}
        if item["enabled"]:
            a, b = generations[name]["challenge"]["rows"], generations[name]["challenge_disabled"]["rows"]
            controls = {"count": len(a), "canonical_output_changed": sum((x["status"], x["canonical_ir"]) !=
                (y["status"], y["canonical_ir"]) for x, y in zip(a, b)), "recorded_prediction_changed": sum(x != y for x, y in zip(a, b)),
                "normal_exact_minus_disabled": details[name]["challenge"]["exact"] - details[name]["challenge_disabled"]["exact"]}
        models.append({"name": name, "arm": item["arm"], "seed": item["seed"], "selected_steps": item.get("selected_steps", 0),
            "trigger_head_supervised": item["enabled"], "trigger_head_present": item["arm"] != "parent",
            "metrics": {p: {k: v for k, v in measure.items() if k != "rows"} for p, measure in details[name].items()},
            "builds": build_accounting(selections[name], builds[name], exact), "residual_control": controls})
    pairs = []
    for seed in SEEDS:
        for a, b in ((f"trigger_grounding-{seed}", f"source_continuation-{seed}"), (f"source_continuation-{seed}", f"parent-{seed}")):
            for panel in ("challenge", "regression"):
                pairs.append({"left": a, "right": b, "panel": panel, **paired(details[a][panel], details[b][panel])})
    totals = {}
    for arm in ("parent", *ARMS):
        group = [m for m in models if m["arm"] == arm]
        totals[arm] = {panel: {key: sum(m["metrics"][panel][key] for m in group) for key in
            ("count", "decoded", "abstained", "exact", "actor_span_exact", "trigger_span_exact")} for panel in ("challenge", "regression")}
        totals[arm]["builds"] = {key: sum(m["builds"][key] for m in group) for key in
            ("count", "built", "built_exact", "built_reference_mismatch", "build_invocations")}
    result = {"schema": "legal-coordinate-grounding-qualification/v1", "generation_freeze": frozen_ref,
        "replay": replay_ref, "builds": builds_ref, "details": write(output / "scored-details.json", details),
        "models": models, "totals": totals, "paired_comparisons": pairs,
        "replayed_rows": sum(r["rows"] for r in replays), "executed_optimizer_updates": 4800,
        "targets_opened_after_replay_and_build_freeze": True, "interpretation_policy": calendar.POLICY,
        "trigger_metric_scope": "Parent has no trigger head (reported zero is unavailable); continuation head is unsupervised. Only trigger_grounding has supervised trigger accuracy.",
        "scope": "Authored surface-construction holdout and separately labeled exposed regression; no external statutory adjudication", **FALSE}
    require(all(sha(path) == value for path, value in plan["producer_pins"].items()), "producer changed during qualification")
    load_config(plan["config"]["path"])
    write(output / "summary.json", result)
    print(json.dumps({"phase": "qualified_experiment_only", "totals": totals, "replayed_rows": result["replayed_rows"]}), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="phase", required=True)
    train = subs.add_parser("train")
    train.add_argument("--config", required=True)
    evaluate = subs.add_parser("evaluate")
    evaluate.add_argument("--run-directory", required=True)
    evaluate.add_argument("--lake-executable", required=True)
    evaluate.add_argument("--toolchain", default="leanprover/lean4:v4.34.1")
    for sub in (train, evaluate):
        sub.add_argument("--output", required=True)
        sub.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)
    return run_training(args) if args.phase == "train" else run_qualification(args)


if __name__ == "__main__":
    main()
