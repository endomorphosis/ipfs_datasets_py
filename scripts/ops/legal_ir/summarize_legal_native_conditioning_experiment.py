#!/usr/bin/env python3
"""Independently verify completed native-conditioning experiments before scoring.

No sealed challenge target is opened until every checkpoint, tuning selection,
native vector/context binding and frozen generation has been checked. Numeric
models are not rerun: native computation remains backed by pinned producer
receipts, not a cryptographic proof. Statutory OOV outputs have no gold accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import re
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_span_retrieval_experiment as shared
from scripts.ops.legal_ir import run_legal_native_conditioning_experiment as runner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as native

require, sha, digest, verify_ref = shared.require, shared.sha, shared.digest, shared.verify_ref
ARMS = ("source_only", "raw384", "core384", "trained384")
SEEDS = (1729, 1730, 1731)
FIELDS, SPAN_FIELDS, QUALIFIERS = shared.FIELDS, shared.SPAN_FIELDS, shared.QUALIFIERS


def assert_source_copy(prediction, source):
    """Check copied outputs independently of learned model code and references."""
    text = source["source_text"]
    require(prediction["source_sha256"] == hashlib.sha256(text.encode()).hexdigest(), "prediction source binding differs")
    require(prediction["target_access"] is False and prediction["teacher_forcing"] is False, "reference-conditioned prediction")
    require(prediction["status"] in {"decoded", "abstained"}, "unknown prediction status")
    if prediction["status"] == "abstained":
        require(prediction["canonical_ir"] is None and not prediction["formal_outputs"], "abstention emitted a canonical rule")
        return 0
    ir = prediction["canonical_ir"]
    require(set(ir) == {"rules"} and len(ir["rules"]) == 1, "closed single-rule canonical output required")
    rule = ir["rules"][0]
    require(set(rule) == set(FIELDS) and rule["modality"] in {"O", "P", "F"}, "invalid canonical rule fields")
    tokens = [{"text": match.group(), "start": match.start(), "end": match.end()}
              for match in re.finditer(r"\w+|[^\w\s]", text)]
    diagnostics = prediction["span_diagnostics"]
    require(diagnostics["tokens"] == tokens, "reported source tokens differ")
    require(set(diagnostics["facets"]) == set(SPAN_FIELDS), "span diagnostics incomplete")
    occupied, copied = set(), 0
    for field in SPAN_FIELDS:
        info, value = diagnostics["facets"][field], rule[field]
        if field in QUALIFIERS:
            require(type(value) is list and len(value) <= 1, "qualifier span bound exceeded")
            atoms = value
        else:
            require(type(value) is str and (bool(value) or field == "object"), "required source atom missing")
            atoms = [value] if value else []
        require(info["present"] is bool(atoms), "presence diagnostic differs")
        if not atoms:
            require(all(info[key] is None for key in ("token_start", "token_end_inclusive", "char_start", "char_end", "text")),
                    "absent qualifier reports a copied span")
            continue
        left, right = info["token_start"], info["token_end_inclusive"]
        require(type(left) is int and type(right) is int and 0 <= left <= right < len(tokens), "token offsets invalid")
        start, end = tokens[left]["start"], tokens[right]["end"]
        require(info["char_start"] == start and info["char_end"] == end
                and info["text"] == text[start:end] == atoms[0], "copied atom differs from exact source span")
        positions = set(range(left, right + 1))
        require(not occupied & positions, "copied field spans overlap")
        occupied |= positions
        copied += 1
    outputs = prediction["formal_outputs"]
    require(len(outputs) == 1 and outputs[0]["family"] == "deontic" and outputs[0]["payload"] == rule,
            "formal payload lost canonical fields")
    require(json.loads(prediction["formula_text"]) == ir, "display text differs from canonical AST")
    return copied



def evaluate(predictions, sources, references, known):
    require(len(predictions) == len(sources) == len(references), "analysis row coverage differs")
    counts, facets, novelty = Counter(), Counter(), {field: Counter() for field in SPAN_FIELDS}
    qualifier_errors = {field: Counter() for field in QUALIFIERS}
    families, details = defaultdict(Counter), []
    for prediction, source in zip(predictions, sources):
        expected = references[source["id"]]
        copied = assert_source_copy(prediction, source)
        gold = expected["rules"][0]
        decoded = prediction["status"] == "decoded"
        candidate = prediction["canonical_ir"]["rules"][0] if decoded else None
        exact = decoded and prediction["canonical_ir"] == expected
        counts["count"] += 1
        counts[prediction["status"]] += 1
        counts["exact"] += exact
        counts["copied_spans_verified"] += copied
        group = families[source["family_group"]]
        group["count"] += 1
        group["exact"] += exact
        group["decoded"] += decoded
        correct = {}
        new_fields = []
        for field in FIELDS:
            correct[field] = bool(decoded and candidate[field] == gold[field])
            facets[field] += correct[field]
            if field in SPAN_FIELDS:
                atoms = gold[field] if field in QUALIFIERS else [gold[field]]
                is_new = bool(atoms) and any(atom not in known[field] for atom in atoms)
                if is_new:
                    new_fields.append(field)
                    novelty[field]["support"] += 1
                    novelty[field]["correct"] += correct[field]
                    novelty[field]["decoded"] += decoded
            if field in QUALIFIERS:
                count = qualifier_errors[field]
                count["gold_present"] += bool(gold[field])
                if not decoded:
                    count["abstained_with_gold_present"] += bool(gold[field])
                else:
                    count["dropped"] += bool(gold[field]) and not bool(candidate[field])
                    count["added"] += not bool(gold[field]) and bool(candidate[field])
                    count["wrong_value_when_both_present"] += bool(gold[field]) and bool(candidate[field]) and gold[field] != candidate[field]
        details.append({"id": source["id"], "family_group": source["family_group"], "exact": exact,
                        "status": prediction["status"], "facet_correct": correct, "unseen_target_fields": new_fields})
    return {**dict(counts), "facet_correct": dict(facets),
            "unseen_target_facet_accuracy": {field: dict(value) for field, value in novelty.items()},
            "qualifier_errors": {field: dict(value) for field, value in qualifier_errors.items()},
            "family_clusters": {field: dict(value) for field, value in families.items()},
            "fully_correct_families": sum(value["exact"] == value["count"] for value in families.values()),
            "family_count": len(families), "rows": details}



def read(path):
    # The genuine 1485-row, three-stage receipt bundle is approximately77MiB.
    require(Path(path).stat().st_size <= 128 * 1024**2, "artifact exceeds128MiB")
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid)


def verify_coverage(summary, frozen, generation_freeze):
    heads = {f"{arm}-{seed}" for arm in ARMS for seed in SEEDS}
    models = heads | {f"parent_source-{seed}" for seed in SEEDS}
    require(type(frozen) is list and len(frozen) == len(heads) and
        {r["name"] for r in frozen} == heads, "complete unique selected-head coverage required")
    require(type(summary["runs"]) is list and len(summary["runs"]) == len(models) and
        {r["name"] for r in summary["runs"]} == models and set(generation_freeze) == models,
        "all12 selected and3 parent models required")
    return models


def verify_context_records(records, sources, vectors, stage):
    require(len(records) == len(sources), "native context coverage differs")
    for record, source in zip(records, sources):
        require(set(record) == {"id", "source_sha256", "context", "context_sha256", "native_stage_receipt"},
                "closed native context required")
        expected = vectors[source["id"]]["stages"][stage]
        require(record["id"] == source["id"] and record["source_sha256"] == source["source_sha256"] and
            record["context"] == expected["vector"] and record["context_sha256"] == digest(expected["vector"])
            and record["native_stage_receipt"] == expected["receipt"], "context differs from authentic recorded stage")


def verify_child(checkpoint, parent, stage, item, expected_contract, manifests):
    """Validate ancestry and reconstruct the initial optimizer boundary."""
    require(checkpoint["schema"] == "warm-start-span-legal-formula-checkpoint/v1", "continuation wrapper required")
    require(checkpoint["source_parent_checkpoint"] == parent and
        checkpoint["source_parent_checkpoint_sha256"] == digest(parent) == item["source_parent_base_sha256"],
        "embedded source parent differs")
    require(checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0,
            "source parent optimizer count differs")
    require(checkpoint["initial_model_state_sha256"] == item["initial_model_sha256"] == digest(parent["model_state"]),
            "copied source-parent tensor identity differs")
    provenance = checkpoint["initialization"]
    require(provenance["all_parent_model_tensors_copied"] is True and
            provenance["parent_optimizer_moments_transferred"] is False, "warm-start boundary differs")
    require(checkpoint["context_contract"] == item["context_contract"] == expected_contract and
            checkpoint["context_contract_sha256"] == digest(expected_contract), "context contract differs")
    base = checkpoint["base_checkpoint"]
    require(base["progress"]["optimizer_steps"] == stage["new_optimizer_steps"], "stage optimizer count differs")
    for field in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale", "latent_dimension"):
        require(base["config"][field] == parent["config"][field], "inherited architecture differs")
    require(base["config"]["latent_enabled"] is item["latent_enabled"] and
        base["config"]["learning_rate"] == .001 and base["config"]["batch_size"] == 12,
        "branch optimization or enabled configuration differs")
    for split, prefix in (("train", "training"), ("tuning", "tuning")):
        require(base[prefix + "_count"] == manifests[split]["count"] and
                base[prefix + "_manifest_sha256"] == manifests[split]["sha256"], "training/tuning source-vector manifest differs")
    initial_base = copy.deepcopy(base)
    initial_base.update(model_state=copy.deepcopy(parent["model_state"]),
        optimizer_state={"schema": "adam-default-betas-eps/v1", "parameters": {}},
        progress={"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}, parent_checkpoint_sha256=None)
    require(digest(initial_base) == checkpoint["initial_base_checkpoint_sha256"], "initial optimizer boundary differs")
    initial = copy.deepcopy(checkpoint)
    initial.update(base_checkpoint=initial_base, parent_checkpoint_sha256=None)
    return base, initial


def verify_generation(payload, checkpoint, sources, contexts, *, control, enabled):
    require(payload["generation_inputs_contained_references"] is False and payload["control"] == control,
            "generation reference access or control differs")
    require(type(payload["reports"]) is list and payload["reports"], "generation report coverage required")
    flat = []
    for report in payload["reports"]:
        require(report["target_access"] is False and report["teacher_forcing"] is False,
                "generation used reference access")
        require(report["checkpoint_sha256"] == digest(checkpoint) and
            report["base_checkpoint_sha256"] == digest(checkpoint["base_checkpoint"]) and
            report["source_parent_checkpoint_sha256"] == checkpoint["source_parent_checkpoint_sha256"] and
            report["context_contract_sha256"] == checkpoint["context_contract_sha256"],
            "generation model/context lineage differs")
        require(report["latent_ablation"] == ("disabled" if control == "disabled_context" else "none"),
                "generation intervention differs")
        flat.extend(report["rows"])
    require(flat == payload["rows"] and len(flat) == len(sources) == len(contexts), "generation row coverage differs")
    for prediction, source, context in zip(flat, sources, contexts):
        assert_source_copy(prediction, source)
        require(context["id"] == source["id"] and context["source_sha256"] == source["source_sha256"],
                "generation context/source join differs")
        require(prediction["latent_sha256"] == digest(context["context"]) and
                prediction["latent_input_enabled"] is (enabled and control != "disabled_context"),
                "generation vector or enabled flag differs")


def verify_completion(directory):
    """Complete pre-scoring verification; no sealed target file is opened here."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as continuation
    directory = Path(directory).resolve()
    require((directory / "summary.json").is_file(), "completed summary required before sealed target access")
    summary, plan = read(directory / "summary.json"), read(directory / "plan.json")
    require(summary["schema"] == plan["schema"] == "legal-native-conditioning-experiment/v1" and
        sha(directory / "plan.json") == summary["plan_sha256"], "experiment plan/schema differs")
    require(summary["challenge_targets_read_after_all_training_selection_and_generation"] is True and
            summary["representation_is_native_source_not_retrieved_profile"] is True, "completion ordering/origin differs")
    require(plan["arms"] == {k: list(v) for k, v in runner.ARMS.items()} and
        plan["seeds"] == list(SEEDS) and plan["stages"] == 2 and plan["stage_steps"] in (400, 800),
        "declared matched four-arm three-seed design differs")
    for path, wanted in plan["producer_pins"].items():
        require(sha(path) == wanted, "frozen producer changed: " + path)
    require(plan["producer_pins"][str(Path(runner.__file__).resolve())] == sha(runner.__file__) and
            plan["producer_pins"][str(Path(native.__file__).resolve())] == sha(native.__file__), "required producer pin missing")
    corpus = read(verify_ref(plan["corpus"]))
    runner.verify_source_inputs(corpus)
    splits = corpus["splits"]
    require(plan["counts"] == {k: len(v) for k, v in splits.items()}, "plan row counts differ")
    require(plan["preparation"] == corpus["frozen_plan"] and
            plan["targets"]["sha256"] == corpus["sealed_targets"]["sha256"], "preparation or target commitment differs")
    preparation = read(verify_ref(plan["preparation"]))
    for key in ("preparer", "rendering"):
        verify_ref(preparation[key])
    prior = read(verify_ref(plan["parent_run"]))
    package = read(verify_ref(plan["package"]))
    frozen = read(verify_ref(summary["frozen_heads"]))
    generation_freeze = read(verify_ref(summary["generation_frozen"]))
    expected_models = verify_coverage(summary, frozen, generation_freeze)
    require(summary["native_vectors"] == read(directory / "native-vector-manifest.json") and
            set(summary["native_vectors"]) == {"all"}, "native vector manifest differs")
    bundle = read(verify_ref(summary["native_vectors"]["all"]))
    sources = [{k: row[k] for k in ("id", "source_text")} for rows in splits.values() for row in rows]
    for stage in native.STAGES:
        native.stage_rows(bundle, stage=stage, sources=sources)
    require(bundle["package"]["sha256"] == plan["package"]["sha256"] and
        bundle["package"]["core_binding"] == package["core_binding"] and
        bundle["package"]["core_state_sha256"] == digest(package["core_state"]) and
        bundle["package"]["formula_checkpoint_sha256"] == digest(package["formula_checkpoint"]),
        "conditioning package/core/projection identity differs")
    receipt_refs = [{k: r[k] for k in ("path", "sha256", "bytes")} for r in corpus["embedding_receipts"]]
    index = native._native_index(receipt_refs, lambda ref: corpus["source_paths"][ref["sha256"]])
    vectors = {r["id"]: r for r in bundle["rows"]}
    contexts = {mode: read(directory / f"contexts-{mode}.json") for mode in native.STAGES}
    for split, rows in splits.items():
        for row in rows:
            raw = vectors[row["id"]]["stages"]["raw384"]
            require(raw["vector"] == row["embedding"], "raw384 differs from exact corpus embedding")
            matches = index.get((row["source_sha256"], row["source_text"]), [])
            require(any(v == raw["vector"] and evidence == raw["receipt"]["evidence"]["native"]
                        for v, evidence in matches), "raw384 source/encoder evidence differs from retained native receipt")
        for mode in contexts:
            require(set(contexts[mode]) == set(splits), "context split coverage differs")
            verify_context_records(contexts[mode][split], rows, vectors, mode)
    del index, vectors, bundle
    expected_prepared = {split: [{k: r[k] for k in ("id", "source_text", "source_sha256", "family_group") if k in r}
                                for r in rows] for split, rows in splits.items()}
    require(read(directory / "prepared-inputs.json") == expected_prepared, "source-only prepared inputs differ")
    training_hash = digest([{k: r[k] for k in ("id", "source_sha256")} for r in splits["train"]])
    contracts, manifests = {}, {}
    for mode in contexts:
        contracts[mode] = {"dimension": 384, "representation_id": "actual_frozen_legal_ir/" + mode + "/v1",
            "producer_sha256": digest({"native": sha(native.__file__), "package": plan["package"]["sha256"], "stage": mode}),
            "training_index_sha256": training_hash}
        manifests[mode] = {split: {"count": len(splits[split]),
            "sha256": digest(runner.fitting_rows(splits[split], contexts[mode][split]))} for split in ("train", "tuning")}
    parents, checkpoints, stages_audit = {}, {}, {}
    for seed in SEEDS:
        ref = plan["parents"][str(seed)]
        parent = read(verify_ref(ref))
        continuation.validate_checkpoint(parent)
        old = [r for r in prior["runs"] if r["name"] == f"source_only-{seed}"]
        require(len(old) == 1 and old[0]["checkpoint"] == ref and
            parent["base_checkpoint"]["config"]["seed"] == seed and
            parent["base_checkpoint"]["config"]["latent_enabled"] is False, "source-only parent differs")
        parents[seed] = parent
        checkpoints[f"parent_source-{seed}"] = parent
    known, initials = shared.training_atoms(splits["train"]), {}
    tune_refs = {r["id"]: r["canonical_ir"] for r in splits["tuning"]}
    for item in frozen:
        name, seed, mode = item["name"], item["seed"], item["context_mode"]
        require(name == f"{item['arm']}-{seed}" and seed in SEEDS and
            [item["latent_enabled"], mode] == list(runner.ARMS[item["arm"]]), "branch identity differs")
        require(item == read(directory / name / "selection.json") and
            item["source_parent_wrapper"] == plan["parents"][str(seed)], "selection or source-parent reference differs")
        parent = parents[seed]["base_checkpoint"]
        require(item["historical_parent_optimizer_updates"] ==
            parents[seed]["source_parent_optimizer_steps"] + parent["progress"]["optimizer_steps"], "historical update count differs")
        require(item["total_new_training_steps"] == 2 * plan["stage_steps"] and
            [s["new_optimizer_steps"] for s in item["stages"]] == [plan["stage_steps"], 2 * plan["stage_steps"]],
            "complete equal stage budgets required")
        require(initials.setdefault(seed, item["initial_model_sha256"]) == item["initial_model_sha256"],
                "same-seed initial tensors differ")
        previous, selected_cp, audit = None, None, []
        for stage in item["stages"]:
            cp = read(verify_ref(stage["checkpoint"]))
            continuation.validate_checkpoint(cp)
            base, initial = verify_child(cp, parent, stage, item, contracts[mode], manifests[mode])
            require(cp["parent_checkpoint_sha256"] == digest(initial if previous is None else previous),
                    "stage outer optimizer lineage differs")
            require(base["parent_checkpoint_sha256"] == digest((initial if previous is None else previous)["base_checkpoint"]),
                    "stage inner optimizer lineage differs")
            training = read(verify_ref(stage["training_report"]))
            require(training["checkpoint_sha256"] == stage["checkpoint"]["sha256"] and
                training["base_checkpoint_sha256"] == digest(base) and
                training["optimizer_steps"] == plan["stage_steps"] and
                training["continuation_optimizer_steps_total"] == stage["new_optimizer_steps"] and
                training["training_executed"] is True, "stage training report differs")
            evaluation = read(verify_ref(stage["tuning_evaluation"]))
            verify_generation(evaluation["generation"], cp, splits["tuning"], contexts[mode]["tuning"],
                              control="normal", enabled=item["latent_enabled"])
            measured = evaluate(evaluation["generation"]["rows"], splits["tuning"], tune_refs, known)
            require(measured["exact"] == evaluation["metrics"]["exact"] == stage["tuning_exact"] and
                measured["count"] == stage["tuning_count"] == len(splits["tuning"]), "stage tuning score differs")
            audit.append({"new_optimizer_steps": stage["new_optimizer_steps"], "tuning_exact": measured["exact"],
                          "checkpoint": stage["checkpoint"], "training_report": stage["training_report"],
                          "tuning_evaluation": stage["tuning_evaluation"]})
            if stage["new_optimizer_steps"] == item["selected_new_steps"]:
                selected_cp = cp
            previous = cp
        selected = runner.select_stage(item["stages"])
        require(selected["new_optimizer_steps"] == item["selected_new_steps"] and selected["checkpoint"] == item["checkpoint"]
            and selected["tuning_exact"] == item["selection_tuning_exact"], "tuning-only earlier-tie selection differs")
        checkpoints[name] = selected_cp
        stages_audit[name] = {"stages": audit, "selected_new_steps": item["selected_new_steps"],
            "total_new_steps_trained": item["total_new_training_steps"], "initial_model_sha256": item["initial_model_sha256"]}
    records = {r["name"]: r for r in summary["runs"]}
    heads = {r["name"]: r for r in frozen}
    generations = {}
    for name in sorted(expected_models):
        item, cp = records[name], checkpoints[name]
        if name in heads:
            require({k: item[k] for k in heads[name]} == heads[name], "summary differs from frozen selected model")
        else:
            require(item["arm"] == "parent_source" and item["name"] == f"parent_source-{item['seed']}" and
                item["checkpoint"] == plan["parents"][str(item["seed"])] and item["context_mode"] == "raw384" and
                item["latent_enabled"] is False, "parent model identity differs")
        require(item["checkpoint"]["sha256"] == digest(cp), "selected checkpoint identity differs")
        panels = {"tuning", "challenge", "oov"}
        if item["latent_enabled"]:
            panels |= {"challenge_disabled_context", "challenge_cross_family_context"}
        require(set(generation_freeze[name]) == panels, "frozen generation/intervention coverage differs")
        generations[name] = {}
        for panel in sorted(panels):
            split = "challenge" if panel.startswith("challenge") else panel
            context = contexts[item["context_mode"]][split]
            control = "disabled_context" if panel.endswith("disabled_context") else "normal"
            if panel.endswith("cross_family_context"):
                queries = [{k: r[k] for k in ("id", "source_text", "embedding", "family_group")} for r in splits[split]]
                expected = runner.native_cross_family_contexts(queries, context)
                require(read(directory / name / "cross-family-contexts.json") == expected,
                        "cross-family donor permutation or stage receipt differs")
                context, control = expected, "cross_family_context"
            payload = read(directory / name / (panel + "-generation.json"))
            require(digest(payload) == generation_freeze[name][panel], "frozen generation differs")
            verify_generation(payload, cp, splits[split], context, control=control, enabled=item["latent_enabled"])
            generations[name][panel] = payload
    return summary, plan, corpus, generations, stages_audit


def _measure(predictions, sources, references, known):
    result = evaluate(predictions, sources, references, known)
    for key in ("decoded", "abstained", "exact", "count"):
        result.setdefault(key, 0)
    result["exact_fraction"] = result["exact"] / result["count"]
    result["facet_errors"] = {f: result["count"] - result["facet_correct"].get(f, 0) for f in shared.FIELDS}
    return result


def summarize(directory, output):
    directory = Path(directory).resolve()
    summary, plan, corpus, generations, stage_audit = verify_completion(directory)
    # The only sealed-reference read occurs after every verification above.
    targets = read(verify_ref(plan["targets"]))
    rows = targets["targets"]
    by_id = {r["id"]: r for r in rows}
    splits = corpus["splits"]
    require(len(by_id) == len(rows) == len(splits["challenge"]) and
        set(by_id) == {r["id"] for r in splits["challenge"]}, "complete unique challenge targets required")
    for source in splits["challenge"]:
        target = by_id[source["id"]]
        require(target["source_sha256"] == source["source_sha256"] and
            digest(target["canonical_ir"]) == target["canonical_target_sha256"] == source["canonical_target_sha256"],
            "challenge target source/content commitment differs")
    references = {"challenge": {k: r["canonical_ir"] for k, r in by_id.items()},
                  "tuning": {r["id"]: r["canonical_ir"] for r in splits["tuning"]}}
    known, models = shared.training_atoms(splits["train"]), {}
    recorded = {r["name"]: r for r in summary["runs"]}
    for name, panels in generations.items():
        measured = {}
        for panel in sorted(panels):
            split = "challenge" if panel.startswith("challenge") else panel
            payload = panels[panel]
            metric_file = directory / name / ("dataset-transfer.json" if panel == "oov" else panel + ".json")
            persisted = read(metric_file)
            require(persisted["generation"] == payload, "scored generation differs from freeze")
            metric_key = "dataset_transfer" if panel == "oov" else panel
            require({k: v for k, v in persisted["metrics"].items() if k != "rows"} == recorded[name]["scores"][metric_key],
                    "summary metric differs from stored evaluation")
            if panel == "oov":
                counts = Counter(r["status"] for r in payload["rows"])
                reasons = Counter(r.get("reason") for r in payload["rows"] if r["status"] == "abstained")
                measured[panel] = {"count": len(payload["rows"]), "decoded": counts["decoded"],
                    "abstained": counts["abstained"], "abstention_reasons": dict(reasons), "semantic_accuracy": None,
                    "reviewed_references_available": False}
                require(all(measured[panel][k] == persisted["metrics"][k] for k in
                    ("count", "decoded", "abstained", "semantic_accuracy")), "OOV counts or accuracy scope differs")
                continue
            measured[panel] = _measure(payload["rows"], splits[split], references[split], known)
            require(all(measured[panel][k] == persisted["metrics"][k] for k in ("count", "decoded", "abstained", "exact"))
                and all(measured[panel]["facet_correct"].get(f, 0) == persisted["metrics"]["facets"].get(f, 0)
                        for f in shared.FIELDS), "independent exact/facet scores differ from runner")
            if panel.startswith("challenge_"):
                measured[panel]["paired_with_normal"] = shared.paired(measured[panel], measured["challenge"])
                measured[panel]["prediction_changed_count"] = sum(
                    (a["status"], a["canonical_ir"]) != (b["status"], b["canonical_ir"])
                    for a, b in zip(payload["rows"], panels["challenge"]["rows"]))
        item = recorded[name]
        models[name] = {"arm": item["arm"], "seed": item["seed"], "panels": measured}
    paired, parents = {}, {}
    for seed in SEEDS:
        challenge = {a: models[f"{a}-{seed}"]["panels"]["challenge"] for a in ARMS}
        paired[str(seed)] = {a + "_vs_source_only": shared.paired(challenge[a], challenge["source_only"])
                            for a in native.STAGES}
        paired[str(seed)].update({"trained384_vs_" + a: shared.paired(challenge["trained384"], challenge[a])
                                 for a in ("raw384", "core384")})
        parents[str(seed)] = shared.paired(challenge["source_only"], models[f"parent_source-{seed}"]["panels"]["challenge"])
    aggregates = {arm: {"exact_by_seed": {str(s): models[f"{arm}-{s}"]["panels"]["challenge"]["exact"] for s in SEEDS},
        "mean_exact": sum(models[f"{arm}-{s}"]["panels"]["challenge"]["exact"] for s in SEEDS) / len(SEEDS),
        "count_per_seed": len(splits["challenge"])} for arm in (*ARMS, "parent_source")}
    report = {"schema": "legal-native-conditioning-independent-analysis/v1",
        "run_summary": {"path": str(directory / "summary.json"), "sha256": sha(directory / "summary.json")},
        "analyzer": {"path": str(Path(__file__).resolve()), "sha256": sha(__file__)},
        "shared_analyzer": {"path": str(Path(shared.__file__).resolve()), "sha256": sha(shared.__file__)},
        "verification": {"stage_checkpoints_verified": 24, "selected_models_verified": 12, "parent_models_verified": 3,
            "all_stage_tuning_scores_recomputed": True, "tuning_only_earliest_tie_selection_verified": True,
            "same_seed_initial_tensors_verified": True, "equal_total_optimizer_budgets_verified": True,
            "training_and_tuning_source_vector_manifests_verified": True, "native_source_receipts_and_stage_chains_verified": True,
            "source_bound_generation_and_interventions_verified": True, "sealed_target_read_after_all_checks": True,
            "numeric_model_replay_performed": False, "runtime_computation_proven": False,
            "generation_panels": sum(len(v) for v in generations.values())},
        "stage_selection": stage_audit, "models": models, "aggregates": aggregates,
        "paired_comparisons_per_seed": paired, "continued_source_vs_parent": parents,
        "interpretation": {"label_origin": plan["label_scope"],
            "architecture_scope": "same-seed frozen source weights and equal total new training budgets; only declared conditioning stage/enabled state varies",
            "selection_scope": "both stages trained for every branch; tuning-only selected update counts may differ",
            "latent_scope": "actual native GTE384, parser-derived sparse-core projection, or saved learned residual projection; no repeated-profile descriptors",
            "control_scope": "disabled and cross-family interventions measure reliance of a fixed selected model; distribution-changing interventions do not prove training benefit",
            "parent_scope": "combined effect of new training data, updates and reset optimizer; not isolated architecture gain",
            "statistical_scope": "paired per seed and source family; correlated clauses and three seeds do not justify independent-row significance",
            "legal_scope": "authored diagnostic targets; no independently reviewed statutory semantic accuracy or proof of legal correctness",
            "source_copy_scope": "copied spans and facets checked; exact AST equality is distinct from legal semantic equivalence"},
        "source_semantics_verified": False, "qualified": False, "admitted": False, "training_executed": False}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(output.resolve()), "sha256": sha(output), "aggregates": aggregates}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.run_directory, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
