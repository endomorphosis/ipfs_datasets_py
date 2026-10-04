#!/usr/bin/env python3
"""Independently audit a completed span/retrieval experiment after generation.

The challenge target file is not parsed until all planned heads, all ordinary
and intervention predictions, and the runner's completion summary are verified.
Scores describe authored examples; no statutory semantic accuracy is inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
SPAN_FIELDS = FIELDS[1:]
QUALIFIERS = FIELDS[4:]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    require(Path(path).stat().st_size <= 64 * 1024**2, "artifact exceeds 64MiB")
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid)


def verify_ref(ref):
    path = Path(ref["path"])
    require(sha(path) == ref["sha256"], "artifact hash differs: " + str(path))
    if "bytes" in ref:
        require(path.stat().st_size == ref["bytes"], "artifact size differs")
    return path


def generation_path(directory, name, panel):
    stem = "challenge-" + panel.removeprefix("challenge_") if panel.startswith("challenge_") else panel
    return directory / name / (stem + "-generation.json")


def verify_completion(directory):
    """No challenge target JSON access occurs anywhere in this prerequisite."""
    directory = Path(directory).resolve()
    require((directory / "summary.json").is_file(), "completion summary required before target access")
    summary = read(directory / "summary.json")
    plan = read(directory / "plan.json")
    require(sha(directory / "plan.json") == summary["plan_sha256"], "experiment plan changed")
    require(summary["challenge_targets_read_after_all_training_and_generation"] is True,
            "runner did not establish generation-before-target ordering")
    expected = {f"{arm}-{seed}" for arm in plan["arms"] for seed in plan["seeds"]}
    require(len(expected) == 12 and len(plan["arms"]) == 4 and len(plan["seeds"]) == 3,
            "analysis requires all twelve declared heads")
    frozen = read(verify_ref(summary["frozen_heads"]))
    generation_freeze = read(verify_ref(summary["generation_frozen"]))
    require(len(frozen) == len(expected) and {item["name"] for item in frozen} == expected,
            "frozen checkpoint coverage differs")
    require(set(generation_freeze) == expected and {item["name"] for item in summary["runs"]} == expected
            and len(summary["runs"]) == len(expected), "completed run coverage differs")
    verify_ref(summary["retriever_checkpoint"])
    for path, wanted in plan["producer_pins"].items():
        require(sha(path) == wanted, "frozen experiment implementation changed")
    initials, generations = {}, {}
    for item in frozen:
        checkpoint = read(verify_ref(item["checkpoint"]))
        require(checkpoint["progress"]["optimizer_steps"] == item["optimizer_steps"] == plan["decoder_steps"],
                "unequal optimizer budgets")
        require(item["arm"] in plan["arms"] and item["seed"] in plan["seeds"]
                and item["name"] == f"{item['arm']}-{item['seed']}", "head identity differs")
        previous = initials.setdefault(item["seed"], item["initial_model_sha256"])
        require(previous == item["initial_model_sha256"], "matched arm initialization differs")
        expected_panels = {"tuning", "challenge", "oov"}
        if item["latent_enabled"]:
            expected_panels |= {"challenge_" + control for control in plan["interventions"]}
        require(set(generation_freeze[item["name"]]) == expected_panels, "prediction panel coverage differs")
        generations[item["name"]] = {}
        for panel in sorted(expected_panels):
            payload = read(generation_path(directory, item["name"], panel))
            require(digest(payload) == generation_freeze[item["name"]][panel], "frozen generation changed")
            require(payload["generation_inputs_contained_references"] is False, "query references entered generation")
            report_rows = []
            for report in payload["reports"]:
                require(report["target_access"] is False and report["teacher_forcing"] is False,
                        "target access during inference")
                require(report["checkpoint_sha256"] == item["checkpoint"]["sha256"], "generation used different checkpoint")
                report_rows.extend(report["rows"])
            require(report_rows == payload["rows"], "generation envelope rows differ")
            generations[item["name"]][panel] = payload
    return summary, plan, frozen, generations


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
            require(type(value) is str and bool(value), "required source atom missing")
            atoms = [value]
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


def training_atoms(training):
    values = {field: set() for field in FIELDS}
    for row in training:
        rule = row["canonical_ir"]["rules"][0]
        for field in FIELDS:
            values[field].update(rule[field] if field in QUALIFIERS else [rule[field]])
    return values


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


def paired(candidate, baseline):
    require([row["id"] for row in candidate["rows"]] == [row["id"] for row in baseline["rows"]], "paired identities differ")
    counts, family_deltas = Counter(), Counter()
    for left, right in zip(candidate["rows"], baseline["rows"]):
        key = "both_correct" if left["exact"] and right["exact"] else "candidate_only_correct" if left["exact"] else "baseline_only_correct" if right["exact"] else "neither_correct"
        counts[key] += 1
        family_deltas[left["family_group"]] += int(left["exact"]) - int(right["exact"])
    return {"candidate_exact": candidate["exact"], "baseline_exact": baseline["exact"],
            "exact_delta": candidate["exact"] - baseline["exact"], **dict(counts),
            "family_exact_deltas": dict(family_deltas), "independent_example_assumption": False}


def profile(ir):
    rule = ir["rules"][0]
    return [rule["modality"], *[bool(rule[field]) for field in QUALIFIERS]]


def check_retrieval(payload, sources, training, mode):
    require(len(payload) == len(sources), "retrieval query coverage differs")
    known = {row["id"]: row for row in training}
    for query, result in zip(sources, payload):
        require(result["id"] == query["id"] and result["source_sha256"] == query["source_sha256"], "retrieval source differs")
        require(result["query_target_access"] is False and result["excluded_same_family"] is True
                and result["mode"] == mode, "retrieval exclusion or target boundary differs")
        ids, weights = result["retrieved_ids"], result["weights"]
        require(len(ids) == len(set(ids)) == len(weights) == 3 and set(ids) <= set(known), "retrieved ids not three distinct training rows")
        require(all(identifier != query["id"] and known[identifier]["source_sha256"] != query["source_sha256"]
                    and known[identifier]["family_group"] != query.get("family_group") for identifier in ids),
                "retrieval query or family leaked into index results")
        require(all(math.isfinite(weight) and weight >= 0 for weight in weights) and abs(sum(weights) - 1) < 1e-6,
                "invalid context mixture weights")
        require(digest(result["context"]) == result["context_sha256"], "retrieval context hash differs")
        expected = [sum(weight * known[identifier]["formal_embedding"][i] for identifier, weight in zip(ids, weights))
                    for i in range(384)]
        require(len(result["context"]) == 384 and max(abs(a - b) for a, b in zip(expected, result["context"])) < 2e-7,
                "retrieved context does not mix recorded training formal vectors")


def retrieval_relevance(payload, sources, references, training):
    known, counts, rows, families = {row["id"]: row for row in training}, Counter(), [], defaultdict(Counter)
    for source, result in zip(sources, payload):
        wanted = profile(references[source["id"]])
        profiles = [profile(known[identifier]["canonical_ir"]) for identifier in result["retrieved_ids"]]
        values = {"top1_profile_match": profiles[0] == wanted, "top3_any_profile_match": wanted in profiles,
                  "top1_modality_match": profiles[0][0] == wanted[0]}
        counts.update(values)
        families[source["family_group"]].update(values)
        families[source["family_group"]]["count"] += 1
        rows.append({"id": source["id"], "family_group": source["family_group"], "target_profile": wanted,
                     "retrieved_ids": result["retrieved_ids"], "retrieved_profiles": profiles, **values})
    return {"count": len(rows), **dict(counts), "rows": rows,
            "families": {key: dict(value) for key, value in families.items()},
            "scope": "modality and qualifier presence only; not semantic equivalence or paper Recall@K"}


def summarize(directory, output):
    directory = Path(directory).resolve()
    summary, plan, frozen, generated = verify_completion(directory)
    corpus = read(verify_ref(plan["corpus"]))
    splits, training = corpus["splits"], corpus["splits"]["train"]
    # This is the first access to challenge target JSON, after every freeze above.
    target_payload = read(verify_ref(plan["challenge_targets"]))
    targets = {row["id"]: row for row in target_payload["targets"]}
    require(len(targets) == len(target_payload["targets"]) == len(splits["challenge"]), "challenge target coverage differs")
    for row in splits["challenge"]:
        target = targets[row["id"]]
        require(target["source_sha256"] == row["source_sha256"] and
                digest(target["canonical_ir"]) == target["canonical_target_sha256"] == row["canonical_target_sha256"],
                "challenge target commitment differs")
    references = {"challenge": {key: row["canonical_ir"] for key, row in targets.items()},
                  "tuning": {row["id"]: row["canonical_ir"] for row in splits["tuning"]}}
    known, runs = training_atoms(training), {}
    contexts = {mode: read(directory / ("retrieval-" + mode + ".json")) for mode in ("raw", "joint", "random")}
    for mode, panels in contexts.items():
        require(set(panels) == set(splits), "retrieval partition coverage differs")
        for split, rows in panels.items():
            check_retrieval(rows, splits[split], training, mode)
    recorded_runs = {item["name"]: item for item in summary["runs"]}
    for item in frozen:
        name, results = item["name"], {}
        for panel, payload in generated[name].items():
            split = "challenge" if panel.startswith("challenge") else panel
            rows = splits[split]
            require(len(payload["rows"]) == len(rows), "prediction count differs")
            vectors = [row["context"] for row in contexts[item["context_mode"]][split]]
            if panel.endswith("zero_context"):
                vectors = [[0.] * 384 for _ in vectors]
            elif panel.endswith("rotated_context"):
                vectors = vectors[1:] + vectors[:1]
            for prediction, vector in zip(payload["rows"], vectors):
                require(prediction["latent_sha256"] == digest(vector), "generation context differs from retrieval or intervention")
            if split == "oov":
                counts, reasons, copied = Counter(), Counter(), 0
                for prediction, source in zip(payload["rows"], rows):
                    copied += assert_source_copy(prediction, source)
                    counts[prediction["status"]] += 1
                    if prediction["status"] == "abstained":
                        reasons[prediction["reason"]] += 1
                results[panel] = {"count": len(rows), **dict(counts), "abstention_reasons": dict(reasons),
                                  "copied_spans_verified": copied, "semantic_accuracy": None}
                continue
            results[panel] = evaluate(payload["rows"], rows, references[split], known)
            recorded = recorded_runs[name]["scores"][panel]
            require(results[panel]["exact"] == recorded["exact"], "independent exact score differs from runner")
            if panel.startswith("challenge_"):
                results[panel]["paired_with_normal_context"] = paired(results[panel], results["challenge"])
                results[panel]["prediction_changed_count"] = sum(
                    (left["status"], left["canonical_ir"]) != (right["status"], right["canonical_ir"])
                    for left, right in zip(payload["rows"], generated[name]["challenge"]["rows"]))
        runs[name] = {"arm": item["arm"], "seed": item["seed"], "panels": results}
    comparisons, retrieval_comparisons = {}, {}
    for seed in plan["seeds"]:
        baseline = runs[f"source_only-{seed}"]["panels"]["challenge"]
        comparisons[str(seed)] = {arm: paired(runs[f"{arm}-{seed}"]["panels"]["challenge"], baseline)
                                  for arm in plan["arms"] if arm != "source_only"}
        retrieval_comparisons[str(seed)] = {
            "joint_vs_raw": paired(runs[f"joint_retrieval-{seed}"]["panels"]["challenge"],
                                   runs[f"raw_retrieval-{seed}"]["panels"]["challenge"]),
            "joint_vs_random": paired(runs[f"joint_retrieval-{seed}"]["panels"]["challenge"],
                                      runs[f"random_retrieval-{seed}"]["panels"]["challenge"]),
            "raw_vs_random": paired(runs[f"raw_retrieval-{seed}"]["panels"]["challenge"],
                                    runs[f"random_retrieval-{seed}"]["panels"]["challenge"])}
    relevance = {mode: retrieval_relevance(panels["challenge"], splits["challenge"], references["challenge"], training)
                 for mode, panels in contexts.items()}
    for mode, result in relevance.items():
        for metric in ("top1_profile_match", "top3_any_profile_match", "top1_modality_match"):
            require(result[metric] == summary["retrieval_relevance"][mode].get(metric, 0), "retrieval score differs from runner")
    report = {"schema": "legal-span-retrieval-independent-analysis/v1",
        "run_summary": {"path": str(directory / "summary.json"), "sha256": sha(directory / "summary.json")},
        "analyzer": {"path": str(Path(__file__).resolve()), "sha256": sha(__file__)},
        "prerequisites": {"all_twelve_heads_verified": True, "all_generation_digests_verified": True,
                          "challenge_target_access_after_completion": True, "context_mixtures_and_generation_binding_verified": True},
        "runs": runs, "paired_with_source_only_per_seed": comparisons,
        "paired_between_retrieval_arms_per_seed": retrieval_comparisons, "retrieval_relevance": relevance,
        "interpretation": {"label_origin": corpus["label_origin"], "independently_reviewed": False,
            "challenge_rows": len(splits["challenge"]), "challenge_families": len({row["family_group"] for row in splits["challenge"]}),
            "family_cluster_scope": "24 correlated template/modality examples per value family; no IID confidence interval or significance claim",
            "novelty_denominator": "rows with nonempty canonical field containing a value absent from train; empty optional fields excluded",
            "qualifier_errors": "dropped/added/wrong-value count decoded rows only; abstentions with present gold counted separately",
            "context_intervention_scope": "rotating adjacent rows is a local swap, often within the same authored value family",
            "oov_semantic_accuracy": None, "retriever_seed_variance_evaluated": False,
            "qualified": False, "admitted": False, "production_ready": False}}
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(Path(output).resolve()), "sha256": sha(output),
            "heads": len(runs), "challenge_exact": {name: item["panels"]["challenge"]["exact"] for name, item in runs.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.run_directory, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
