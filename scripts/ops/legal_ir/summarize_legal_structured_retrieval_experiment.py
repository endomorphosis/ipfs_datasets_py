#!/usr/bin/env python3
"""Independent post-freeze analysis of selected structured-retrieval heads.

Challenge targets are parsed only after every stage checkpoint, tuning selector,
selected checkpoint, and final generation commitment has been verified. Parent
comparisons measure the combined effect of new data and continued training.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_span_retrieval_experiment as shared

require, read, sha, digest, verify_ref = shared.require, shared.read, shared.sha, shared.digest, shared.verify_ref
ARMS = ("source_only", "dense_joint", "profile_joint", "profile_random")
MODALITIES = ("O", "P", "F")


def select_stage(stages):
    require(len(stages) == 2 and len({row["new_optimizer_steps"] for row in stages}) == 2,
            "exactly two distinct stages required")
    return sorted(stages, key=lambda row: (-row["tuning_exact"], row["new_optimizer_steps"]))[0]


def verify_generation(payload, checkpoint_sha256, *, base_sha256=None):
    require(payload["generation_inputs_contained_references"] is False, "generation received query targets")
    rows = []
    for report in payload["reports"]:
        require(report["target_access"] is False and report["teacher_forcing"] is False,
                "teacher forcing or target access during generation")
        require(report["checkpoint_sha256"] == checkpoint_sha256, "generation checkpoint differs")
        if base_sha256 is not None:
            require(report["base_checkpoint_sha256"] == base_sha256, "inner checkpoint differs")
        rows.extend(report["rows"])
    require(rows == payload["rows"], "generation wrapper rows differ")


def verify_child(checkpoint, parent, parent_ref, stage, initial_model_sha256):
    require(checkpoint["schema"] == "warm-start-span-legal-formula-checkpoint/v1", "continuation wrapper required")
    require(checkpoint["source_parent_checkpoint"] == parent
            and checkpoint["source_parent_checkpoint_sha256"] == parent_ref["sha256"] == digest(parent),
            "embedded source parent differs")
    require(checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] == 800,
            "parent update history differs")
    require(checkpoint["initial_model_state_sha256"] == initial_model_sha256 == digest(parent["model_state"]),
            "warm start model tensors differ")
    provenance = checkpoint["initialization"]
    require(provenance["all_parent_model_tensors_copied"] is True
            and provenance["parent_optimizer_moments_transferred"] is False, "warm start initialization differs")
    base = checkpoint["base_checkpoint"]
    require(base["progress"]["optimizer_steps"] == stage["new_optimizer_steps"], "stage optimizer count differs")
    for field in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        require(base["config"][field] == parent["config"][field], "inherited architecture differs")
    require(base["config"]["learning_rate"] == .001 and base["config"]["batch_size"] == 12,
            "continuation optimization configuration differs")
    require(digest(checkpoint["context_contract"]) == checkpoint["context_contract_sha256"], "context contract hash differs")
    initial_base = copy.deepcopy(base)
    initial_base.update(model_state=copy.deepcopy(parent["model_state"]),
        optimizer_state={"schema": "adam-default-betas-eps/v1", "parameters": {}},
        progress={"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}, parent_checkpoint_sha256=None)
    require(digest(initial_base) == checkpoint["initial_base_checkpoint_sha256"], "initial optimizer boundary differs")
    initial_outer = copy.deepcopy(checkpoint)
    initial_outer.update(base_checkpoint=initial_base, parent_checkpoint_sha256=None)
    return base, initial_outer


def verify_completion(directory):
    """Tuning references are visible; sealed challenge JSON remains unopened."""
    directory = Path(directory).resolve()
    require((directory / "summary.json").is_file(), "completed summary required before challenge target access")
    summary, plan = read(directory / "summary.json"), read(directory / "plan.json")
    require(sha(directory / "plan.json") == summary["plan_sha256"], "plan hash differs")
    require(summary["challenge_targets_read_after_all_training_selection_and_generation"] is True,
            "training/selection/generation ordering was not established")
    require(set(plan["arms"]) == set(ARMS) and plan["seeds"] == [1729, 1730, 1731]
            and plan["stage_count"] == 2, "declared four-arm three-seed design required")
    require(plan["total_updates_per_branch"] == 2 * plan["stage_steps"], "equal full budgets required")
    for path, wanted in plan["producer_pins"].items():
        require(sha(path) == wanted, "frozen producer implementation changed")
    corpus = read(verify_ref(plan["corpus"]))
    require(all("canonical_ir" not in row and "source_spans" not in row for row in corpus["splits"]["challenge"]),
            "challenge inference inputs contain references")
    prior = read(verify_ref(plan["parent_run_summary"]))
    observer_path = directory.parent / "stage-evidence-observation.json"
    observer = read(observer_path)
    require(observer["schema"] == "structured-stage-evidence-observer/v1"
            and Path(observer["run_directory"]).resolve() == directory, "stage observer receipt differs")
    observations = observer["observations"]
    parents = {}
    for seed in plan["seeds"]:
        ref = plan["parents"][str(seed)]
        parent = read(verify_ref(ref))
        known = [item for item in prior["runs"] if item["name"] == f"source_only-{seed}"]
        require(len(known) == 1 and known[0]["checkpoint"]["sha256"] == ref["sha256"], "parent differs from completed preceding run")
        require(parent["config"]["seed"] == seed and parent["config"]["latent_enabled"] is False,
                "source-only same-seed parent required")
        parents[str(seed)] = parent
    frozen = read(verify_ref(summary["frozen_heads"]))
    generation_freeze = read(verify_ref(summary["generation_frozen"]))
    verify_ref(summary["retriever_checkpoint"])
    expected_heads = {f"{arm}-{seed}" for arm in ARMS for seed in plan["seeds"]}
    expected_models = expected_heads | {f"parent_source-{seed}" for seed in plan["seeds"]}
    require(len(frozen) == 12 and {item["name"] for item in frozen} == expected_heads, "selected head coverage differs")
    require(set(generation_freeze) == expected_models and len(summary["runs"]) == 15
            and {item["name"] for item in summary["runs"]} == expected_models, "all fifteen model results required")
    known_atoms = shared.training_atoms(corpus["splits"]["train"])
    tuning_sources = corpus["splits"]["tuning"]
    tuning_refs = {row["id"]: row["canonical_ir"] for row in tuning_sources}
    stage_audit, model_refs, initial_by_seed = {}, {}, {}
    for item in frozen:
        name, seed = item["name"], item["seed"]
        require(name == f"{item['arm']}-{seed}" and item["arm"] in ARMS, "selected head identity differs")
        require(item["source_parent"] == plan["parents"][str(seed)], "branch source-parent reference differs")
        require(item["total_new_training_steps"] == plan["total_updates_per_branch"], "branch budget differs")
        require(item == read(directory / name / "selection.json"), "stored selection record differs from frozen record")
        expected_steps = [plan["stage_steps"], 2 * plan["stage_steps"]]
        require([stage["new_optimizer_steps"] for stage in item["stages"]] == expected_steps,
                "both chronological stages must be present")
        before = initial_by_seed.setdefault(seed, item["initial_model_sha256"])
        require(before == item["initial_model_sha256"], "matched branches did not share initial tensors")
        previous, stages, children = None, [], {}
        for stage in item["stages"]:
            path = verify_ref(stage["checkpoint"])
            checkpoint = read(path)
            base, initial = verify_child(checkpoint, parents[str(seed)], plan["parents"][str(seed)], stage, item["initial_model_sha256"])
            require(checkpoint["context_contract"] == item["context_contract"]
                    and base["config"]["latent_enabled"] is item["latent_enabled"], "branch context contract differs")
            if previous is None:
                require(checkpoint["parent_checkpoint_sha256"] == digest(initial), "first stage did not follow warm-start boundary")
            else:
                require(checkpoint["parent_checkpoint_sha256"] == digest(previous)
                        and base["parent_checkpoint_sha256"] == digest(previous["base_checkpoint"]),
                        "second stage did not continue first-stage weights and optimizer lineage")
            training_path = str(directory / name / f"training-{stage['new_optimizer_steps']}.json")
            evaluation_path = str(directory / name / f"tuning-{stage['new_optimizer_steps']}.json")
            require(training_path in observations and evaluation_path in observations, "stage evidence lacks supplementary observer hash")
            training = read(verify_ref(observations[training_path]))
            require(training["checkpoint_sha256"] == stage["checkpoint"]["sha256"]
                    and training["optimizer_steps"] == plan["stage_steps"]
                    and training["continuation_optimizer_steps_total"] == stage["new_optimizer_steps"],
                    "stage training receipt differs")
            evaluation = read(verify_ref(observations[evaluation_path]))
            verify_generation(evaluation["generation"], stage["checkpoint"]["sha256"], base_sha256=digest(base))
            measured = shared.evaluate(evaluation["generation"]["rows"], tuning_sources, tuning_refs, known_atoms)
            require(measured["count"] == stage["tuning_count"] == len(tuning_sources)
                    and measured["exact"] == evaluation["metrics"]["exact"] == stage["tuning_exact"],
                    "stored stage tuning exact differs from independently measured count")
            stages.append({"new_optimizer_steps": stage["new_optimizer_steps"], "tuning_exact": measured["exact"],
                           "tuning_count": measured["count"], "checkpoint_sha256": stage["checkpoint"]["sha256"],
                           "training_evidence_observed_before_generation_freeze": observations[training_path]["generation_and_summary_absent_before_and_after"],
                           "tuning_evidence_observed_before_generation_freeze": observations[evaluation_path]["generation_and_summary_absent_before_and_after"]})
            children[stage["new_optimizer_steps"]] = checkpoint
            previous = checkpoint
        selected = select_stage(item["stages"])
        require(selected["new_optimizer_steps"] == item["selected_new_steps"]
                and selected["checkpoint"] == item["checkpoint"]
                and selected["tuning_exact"] == item["selection_tuning_exact"], "selected stage violates tuning-only earlier-tie rule")
        stage_audit[name] = {"stages": stages, "selected_new_steps": item["selected_new_steps"],
                            "total_new_steps_trained": item["total_new_training_steps"], "tuning_selection_verified": True}
        model_refs[name] = {"checkpoint": item["checkpoint"],
                            "base_sha256": digest(children[item["selected_new_steps"]]["base_checkpoint"])}
    for seed in plan["seeds"]:
        model_refs[f"parent_source-{seed}"] = {"checkpoint": plan["parents"][str(seed)], "base_sha256": None}
    models = {item["name"]: item for item in summary["runs"]}
    generations = {}
    for name in sorted(expected_models):
        item, reference = models[name], model_refs[name]
        require(item["checkpoint"] == reference["checkpoint"], "summary model checkpoint differs")
        panels = {"tuning", "challenge", "oov"}
        if item["latent_enabled"]:
            panels |= {"challenge_disabled_context", "challenge_cross_family_context"}
            if item["context_mode"].startswith("profile"):
                panels.add("challenge_cyclic_modality_context")
        require(set(generation_freeze[name]) == panels, "generation/intervention coverage differs")
        generations[name] = {}
        for panel in sorted(panels):
            payload = read(directory / name / (panel + "-generation.json"))
            require(digest(payload) == generation_freeze[name][panel], "frozen generation digest differs")
            verify_generation(payload, reference["checkpoint"]["sha256"], base_sha256=reference["base_sha256"])
            generations[name][panel] = payload
    return summary, plan, corpus, frozen, generations, stage_audit, observer


def profile_id(ir):
    rule = ir["rules"][0]
    return 8 * MODALITIES.index(rule["modality"]) + 4 * bool(rule["conditions"]) + 2 * bool(rule["exceptions"]) + bool(rule["temporal"])


def assert_close(left, right, message, tolerance=1e-14):
    require(len(left) == len(right) and all(math.isfinite(value) for value in left)
            and max((abs(a - b) for a, b in zip(left, right)), default=0) <= tolerance, message)


def verify_profile_contexts(rows, retrieval, sources, training):
    require(len(rows) == len(retrieval) == len(sources), "profile query coverage differs")
    known = {row["id"]: row for row in training}
    for row, native, source in zip(rows, retrieval, sources):
        require(row["id"] == source["id"] and row["source_sha256"] == source["source_sha256"], "profile source binding differs")
        require(row["query_family_group"] == source.get("family_group", "oov-" + source["id"])
                and row["query_target_access"] is False and row["query_target_values_embedded"] is False,
                "profile query family or target boundary differs")
        require(row["retrieval_record_sha256"] == digest(native) and row["retrieved_ids"] == native["retrieved_ids"]
                and row["original_retrieval_weights"] == native["weights"], "profile retrieval provenance differs")
        require(row["index_sha256"] == row["training_index_sha256"] == native["index_sha256"], "profile index identity differs")
        mass = math.fsum(native["weights"])
        weights = [weight / mass for weight in native["weights"]]
        assert_close(row["weights"], weights, "profile weights differ")
        profiles = [profile_id(known[identifier]["canonical_ir"]) for identifier in native["retrieved_ids"]]
        require(row["neighbor_profile_ids"] == profiles, "retrieved training AST profiles differ")
        histogram = [math.fsum(weight for weight, found in zip(weights, profiles) if found == index) for index in range(24)]
        histogram = [value / math.fsum(histogram) for value in histogram]
        expected = [value / 4 for value in histogram for _ in range(16)]
        assert_close(row["context"], expected, "explicit descriptor differs from training AST histogram")
        assert_close(row["profile_distribution"], histogram, "profile histogram diagnostic differs")
        require(digest(row["context"]) == row["context_sha256"], "profile context digest differs")


def verify_cross_family(rows, ordinary, sources):
    require(len(rows) == len(ordinary) == len(sources), "cross-family coverage differs")
    inputs = {row["id"]: row for row in sources}
    contexts = {row["id"]: row for row in ordinary}
    donors = []
    for row, receiver, original in zip(rows, sources, ordinary):
        donor_id = row["donor_query_id"]
        require(donor_id in inputs, "unknown intervention donor")
        donor, context = inputs[donor_id], contexts[donor_id]
        require(row["id"] == receiver["id"] and row["source_sha256"] == receiver["source_sha256"]
                and row["query_family_group"] == receiver["family_group"], "intervention receiver binding differs")
        require(row["donor_source_sha256"] == donor["source_sha256"]
                and row["donor_family_group"] == donor["family_group"] != receiver["family_group"], "intervention donor family/source differs")
        require(row["context"] == context["context"] and row["context_sha256"] == row["donor_context_sha256"] == context["context_sha256"]
                and row["receiver_original_context_sha256"] == original["context_sha256"], "intervention context donor binding differs")
        for field, value in context.items():
            if field not in {"id", "source_sha256", "query_family_group"}:
                require(row[field] == value, "donor retrieval metadata differs")
        donors.append(donor_id)
    require(len(set(donors)) == len(sources) and set(donors) == set(inputs), "intervention is not a donor bijection")


def verify_cyclic(rows, ordinary, sources):
    require(len(rows) == len(ordinary) == len(sources), "cyclic intervention coverage differs")
    for row, original, source in zip(rows, ordinary, sources):
        require(row["id"] == source["id"] and row["source_sha256"] == source["source_sha256"]
                and row["original_context_receipt"] == original
                and row["original_context_sha256"] == digest(original["context"]), "cyclic source/provenance binding differs")
        old = [4 * original["context"][16 * index] for index in range(24)]
        old = [value / math.fsum(old) for value in old]
        shifted = [0.] * 24
        for index, value in enumerate(old):
            shifted[((index // 8 + 1) % 3) * 8 + index % 8] = value
        shifted = [value / math.fsum(shifted) for value in shifted]
        expected = [value / 4 for value in shifted for _ in range(16)]
        assert_close(row["context"], expected, "cyclic intervention changed more than modality classes")
        assert_close(row["profile_distribution"], shifted, "cyclic profile diagnostic differs")
        require(row["context_sha256"] == digest(row["context"]), "cyclic context hash differs")


def summarize(directory, output):
    directory = Path(directory).resolve()
    summary, plan, corpus, frozen, generations, stage_audit, observer = verify_completion(directory)
    splits, training = corpus["splits"], corpus["splits"]["train"]
    # First challenge target JSON read, after 24 stage and 15 model commitments.
    target_payload = read(verify_ref(plan["challenge_targets"]))
    target_rows = {row["id"]: row for row in target_payload["targets"]}
    require(len(target_rows) == len(target_payload["targets"]) == len(splits["challenge"]), "target coverage differs")
    for source in splits["challenge"]:
        target = target_rows[source["id"]]
        require(target["source_sha256"] == source["source_sha256"]
                and digest(target["canonical_ir"]) == target["canonical_target_sha256"] == source["canonical_target_sha256"],
                "challenge target commitment differs")
    references = {"challenge": {key: row["canonical_ir"] for key, row in target_rows.items()},
                  "tuning": {row["id"]: row["canonical_ir"] for row in splits["tuning"]}}
    contexts = {mode: read(directory / f"contexts-{mode}.json") for mode in ("dense_joint", "profile_joint", "profile_random")}
    random_retrieval = read(directory / "retrieval-random.json")
    for split, sources in splits.items():
        shared.check_retrieval(contexts["dense_joint"][split], sources, training, "joint")
        shared.check_retrieval(random_retrieval[split], sources, training, "random")
        verify_profile_contexts(contexts["profile_joint"][split], contexts["dense_joint"][split], sources, training)
        verify_profile_contexts(contexts["profile_random"][split], random_retrieval[split], sources, training)
    known, runs = shared.training_atoms(training), {}
    recorded = {item["name"]: item for item in summary["runs"]}
    for name, panels in generations.items():
        item, results = recorded[name], {}
        mode = item["context_mode"]
        for panel, payload in panels.items():
            split = "challenge" if panel.startswith("challenge") else panel
            source_rows, context_rows = splits[split], contexts[mode][split]
            if panel.endswith("cross_family_context"):
                context_rows = read(directory / name / "cross-family-contexts.json")
                verify_cross_family(context_rows, contexts[mode][split], source_rows)
            elif panel.endswith("cyclic_modality_context"):
                context_rows = read(directory / name / "cyclic-modality-contexts.json")
                verify_cyclic(context_rows, contexts[mode][split], source_rows)
            require(len(payload["rows"]) == len(source_rows) == len(context_rows), "generation context coverage differs")
            for prediction, context in zip(payload["rows"], context_rows):
                require(prediction["latent_sha256"] == digest(context["context"]), "generated context differs from recorded intervention")
                expected_enabled = item["latent_enabled"] and not panel.endswith("disabled_context")
                require(prediction["latent_input_enabled"] is expected_enabled, "context enabled flag differs")
            if split == "oov":
                counts, reasons, copied = Counter(), Counter(), 0
                for prediction, source in zip(payload["rows"], source_rows):
                    copied += shared.assert_source_copy(prediction, source)
                    counts[prediction["status"]] += 1
                    if prediction["status"] == "abstained":
                        reasons[prediction["reason"]] += 1
                results[panel] = {"count": len(source_rows), **dict(counts), "abstention_reasons": dict(reasons),
                                  "copied_spans_verified": copied, "semantic_accuracy": None}
                continue
            results[panel] = shared.evaluate(payload["rows"], source_rows, references[split], known)
            require(results[panel]["exact"] == item["scores"][panel]["exact"], "independent exact differs from runner")
            if panel.startswith("challenge_"):
                results[panel]["paired_with_normal_context"] = shared.paired(results[panel], results["challenge"])
                results[panel]["prediction_changed_count"] = sum(
                    (left["status"], left["canonical_ir"]) != (right["status"], right["canonical_ir"])
                    for left, right in zip(payload["rows"], panels["challenge"]["rows"]))
        runs[name] = {"arm": item["arm"], "seed": item["seed"], "panels": results}
    comparisons, parent_diagnostics = {}, {}
    for seed in plan["seeds"]:
        challenge = {arm: runs[f"{arm}-{seed}"]["panels"]["challenge"] for arm in ARMS}
        comparisons[str(seed)] = {"profile_joint_vs_" + arm: shared.paired(challenge["profile_joint"], challenge[arm])
                                   for arm in ("source_only", "dense_joint", "profile_random")}
        comparisons[str(seed)].update({arm + "_vs_source_only": shared.paired(challenge[arm], challenge["source_only"])
                                      for arm in ("dense_joint", "profile_random")})
        parent_diagnostics[str(seed)] = shared.paired(challenge["source_only"], runs[f"parent_source-{seed}"]["panels"]["challenge"])
    retrieval = {mode: shared.retrieval_relevance(rows, splits["challenge"], references["challenge"], training)
                 for mode, rows in (("joint", contexts["dense_joint"]["challenge"]), ("random", random_retrieval["challenge"]))}
    for mode, evidence in retrieval.items():
        for metric in ("top1_profile_match", "top3_any_profile_match", "top1_modality_match"):
            require(evidence[metric] == summary["retrieval_relevance"][mode].get(metric, 0), "retrieval metric differs")
    report = {"schema": "legal-structured-retrieval-independent-analysis/v1",
        "run_summary": {"path": str(directory / "summary.json"), "sha256": sha(directory / "summary.json")},
        "analyzer": {"path": str(Path(__file__).resolve()), "sha256": sha(__file__)},
        "shared_analyzer": {"path": str(Path(shared.__file__).resolve()), "sha256": sha(shared.__file__)},
        "verification": {"stage_checkpoints": 24, "selected_heads": 12, "parent_heads": 3,
            "generation_panels": sum(len(panels) for panels in generations.values()),
            "all_checkpoint_and_generation_hashes_verified": True, "all_stage_tuning_scores_independently_recomputed": True,
            "tuning_only_earlier_stage_tie_selection_verified": True, "source_parent_snapshots_and_continuation_links_verified": True,
            "challenge_target_access_after_all_freeze_checks": True, "retrieval_context_and_donor_bindings_verified": True},
        "stage_evidence_observer": {"path": str(directory.parent / "stage-evidence-observation.json"),
            "sha256": sha(directory.parent / "stage-evidence-observation.json"),
            "observed_artifacts": observer["observed_artifact_count"],
            "observed_before_generation_freeze": sum(item["generation_and_summary_absent_before_and_after"] for item in observer["observations"].values()),
            "scope": observer["scope"]},
        "stage_selection": stage_audit, "runs": runs, "paired_comparisons_per_seed": comparisons,
        "continued_source_vs_parent_diagnostic": parent_diagnostics, "retrieval_relevance": retrieval,
        "interpretation": {"label_origin": corpus["label_origin"], "challenge_family_count": 8,
            "family_cluster_scope": "24 correlated examples per family; no IID significance or confidence claim",
            "parent_comparison_scope": "new corpus, more updates, and new optimizer together; not an isolated architecture comparison",
            "selected_stage_scope": "both stages trained for all arms; selected deployed update count may differ through tuning-only selection",
            "stage_evidence_hash_scope": "runner freezes stage checkpoint hashes and tuning counts; supplementary observer independently freezes stage training/evaluation bytes with observation timing",
            "selected_context_ablation_scope": "intervene on selected trained checkpoint, keeping source fixed",
            "profile_scope": "24 modality/qualifier-presence probabilities, not a full AST or trained autoencoder",
            "new_challenge_scope": "new entities and values; all grammar combinations exposed in training",
            "oov_semantic_accuracy": None, "qualified": False, "admitted": False, "production_ready": False}}
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(Path(output).resolve()), "sha256": sha(output), "stage_checkpoints": 24,
            "challenge_exact": {name: item["panels"]["challenge"]["exact"] for name, item in runs.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.run_directory, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
