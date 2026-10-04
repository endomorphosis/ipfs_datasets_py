#!/usr/bin/env python3
"""Summarize a completed, frozen decoder comparison as auditable JSON.

References are opened only after verifying the completed comparison and every
frozen checkpoint. Counts describe authored compositions, without statistical
independence or statutory semantic qualification claims.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
ARMS = ("source_ce", "source_facets", "hybrid_ce", "hybrid_facets")
CONTROLS = ("zero_latent", "rotated_latent", "disabled_latent", "unprojected_latent", "raw_embedding")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        allow_nan=False, ensure_ascii=True).encode()).hexdigest()


def read(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= 128 * 1024**2, "missing or oversized input: " + str(path))

    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON value: " + value)

    return json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=invalid)


def reference(path):
    return {"path": str(Path(path).resolve()), "sha256": sha(path)}


def frozen_run(directory):
    """Authenticate completion before any sealed-reference access."""
    frozen_path = directory / "frozen-heads.json"
    require(frozen_path.is_file(), "all branch checkpoints must be frozen before references are opened")
    summary_path, plan_path = directory / "summary.json", directory / "plan.json"
    summary, plan = read(summary_path), read(plan_path)
    require(summary["plan_sha256"] == sha(plan_path), "plan digest differs")
    require(summary["frozen_heads"]["sha256"] == sha(frozen_path), "frozen checkpoint manifest differs")
    require(summary["new_challenge_target_access_after_all_training"] is True, "completed freeze boundary missing")
    frozen = read(frozen_path)
    expected = {(arm, seed) for arm in ARMS for seed in plan["seeds"]}
    require(len(frozen) == len(expected) and {(r["arm"], r["seed"]) for r in frozen} == expected,
            "frozen branch coverage differs")
    for row in frozen:
        name = row["arm"] + "-" + str(row["seed"])
        require(sha(directory / name / "checkpoint.json") == row["checkpoint"]["sha256"],
                "frozen checkpoint bytes differ: " + name)
    actual = {(r["arm"], r["seed"]) for r in summary["runs"] if "arm" in r}
    require(actual == expected and len(summary["runs"]) == len(expected) + 2,
            "completed evaluation coverage differs")
    return summary, plan, frozen


def validate_ir(value):
    require(type(value) is dict and set(value) == {"rules"} and type(value["rules"]) is list
            and len(value["rules"]) == 1, "single-rule canonical output required")
    rule = value["rules"][0]
    require(type(rule) is dict and set(rule) == set(FACETS), "canonical rule fields differ")
    require(rule["modality"] in ("O", "P", "F"), "unsupported modality")
    require(all(type(rule[k]) is str for k in ("actor", "action", "object")), "invalid canonical atom")
    require(all(type(rule[k]) is list and all(type(v) is str for v in rule[k])
                for k in ("conditions", "exceptions", "temporal")), "invalid qualifier list")
    return rule


def summarize_rows(rows):
    counts = Counter()
    facets = Counter({key: 0 for key in FACETS})
    qualifiers = {field: Counter() for field in ("exceptions", "temporal")}
    for row in rows:
        counts[row["status"]] += 1
        counts["exact"] += int(row["exact"])
        facets.update(key for key, passed in row["facets"].items() if passed)
        for field in qualifiers:
            for direction in ("dropped", "extra"):
                atoms = row["qualifier_errors"][field][direction]
                qualifiers[field][direction + "_atoms"] += len(atoms)
                qualifiers[field][direction + "_rows"] += bool(atoms)
    return {"count": len(rows), "exact": counts["exact"], "decoded": counts["decoded"],
            "abstained": counts["abstained"], "exact_fraction": counts["exact"] / len(rows) if rows else None,
            "facet_correct": dict(facets), "qualifier_errors_on_decoded_outputs":
                {field: dict(counts) for field, counts in qualifiers.items()}}


def model_metrics(directory, name, filename, challenge, targets):
    path = directory / name / filename
    report = read(path)
    predictions, recorded = report["generation"]["rows"], report["metrics"]["rows"]
    require(len(predictions) == len(recorded) == len(challenge), "prediction coverage differs: " + name)
    rows = []
    for source, prediction, metric in zip(challenge, predictions, recorded):
        require(metric["id"] == source["id"] and prediction["source_sha256"] == source["source_sha256"],
                "prediction/source identity differs: " + name)
        require(prediction.get("target_access") is False and prediction.get("teacher_forcing") is False,
                "free generation receipt missing")
        status = prediction["status"]
        require(status in ("decoded", "abstained"), "unknown prediction status")
        canonical = prediction.get("canonical_ir")
        require(status != "abstained" or canonical is None, "abstention carries candidate")
        expected = targets[source["id"]]
        actual = validate_ir(canonical) if status == "decoded" else None
        target = validate_ir(expected)
        exact = actual is not None and canonical == expected
        facets = {field: actual is not None and actual[field] == target[field] for field in FACETS}
        require(metric["exact"] == exact and metric["facets"] == facets, "recorded metrics disagree with predictions")
        errors = {}
        for field in ("exceptions", "temporal"):
            # Abstention is reported separately, rather than counted as an
            # emitted rule silently dropping all reference qualifiers.
            missing = Counter(target[field]) - Counter(actual[field]) if actual is not None else Counter()
            extra = Counter(actual[field]) - Counter(target[field]) if actual is not None else Counter()
            errors[field] = {"dropped": list(missing.elements()), "extra": list(extra.elements())}
        rows.append({"id": source["id"], "family_group": source["family_group"],
            "actor_action_group": source["actor_action_group"], "status": status, "exact": exact,
            "facets": facets, "qualifier_errors": errors,
            "candidate_sha256": digest(canonical) if canonical is not None else None})
    metrics = summarize_rows(rows)
    require(metrics["exact"] == report["metrics"]["exact"] and metrics["decoded"] == report["metrics"]["decoded"],
            "aggregate metrics differ")
    groups = {}
    for field in ("family_group", "actor_action_group"):
        grouped = defaultdict(list)
        for row in rows:
            grouped[row[field]].append(row)
        groups[field] = {group: summarize_rows(items) for group, items in sorted(grouped.items())}
    return {"artifact": reference(path), **metrics, "groups": groups, "rows": rows}


def paired(left, right):
    """Descriptive paired comparison; correlated rows are not independent trials."""
    require([r["id"] for r in left["rows"]] == [r["id"] for r in right["rows"]], "paired identities differ")
    improved = [b["id"] for a, b in zip(left["rows"], right["rows"]) if not a["exact"] and b["exact"]]
    regressed = [b["id"] for a, b in zip(left["rows"], right["rows"]) if a["exact"] and not b["exact"]]
    changed = sum(a["candidate_sha256"] != b["candidate_sha256"] for a, b in zip(left["rows"], right["rows"]))
    groups = {}
    for grouping in ("family_group", "actor_action_group"):
        groups[grouping] = {group: {"count": stats["count"], "left_exact": stats["exact"],
            "right_exact": right["groups"][grouping][group]["exact"],
            "exact_gain": right["groups"][grouping][group]["exact"] - stats["exact"]}
            for group, stats in left["groups"][grouping].items()}
    return {"count": left["count"], "left_exact": left["exact"], "right_exact": right["exact"],
        "exact_gain": right["exact"] - left["exact"], "improved_count": len(improved),
        "regressed_count": len(regressed), "improved_ids": improved, "regressed_ids": regressed,
        "changed_candidate_count": changed,
        "facet_gains": {field: right["facet_correct"][field] - left["facet_correct"][field] for field in FACETS},
        "groups": groups, "independent_rows_assumed": False, "significance_test_performed": False}


def dataset_transfer(directory, name, sources):
    path = directory / name / "dataset-transfer.json"
    report = read(path)
    rows = report["generation"]["rows"]
    require(len(rows) == len(sources), "dataset transfer source coverage differs")
    statuses, reasons = Counter(), Counter()
    for source, prediction in zip(sources, rows):
        require(prediction["source_sha256"] == source["source_sha256"], "dataset transfer source binding differs")
        require(prediction.get("target_access") is False and prediction.get("teacher_forcing") is False,
                "dataset transfer free generation evidence missing")
        require(prediction["status"] in ("decoded", "abstained"), "unknown dataset transfer status")
        statuses[prediction["status"]] += 1
        if prediction["status"] == "abstained":
            require(prediction.get("canonical_ir") is None, "abstention carries candidate")
            reasons[prediction.get("reason")] += 1
        else:
            validate_ir(prediction["canonical_ir"])
    require(statuses["decoded"] == report["metrics"]["decoded"]
            and statuses["abstained"] == report["metrics"]["abstained"], "dataset transfer metrics differ")
    return {"artifact": reference(path), "count": len(rows), "decoded": statuses["decoded"],
            "abstained": statuses["abstained"], "abstention_reasons": dict(reasons),
            "semantic_accuracy": None, "reason": "no independently reviewed statutory references"}


def representability(plan, corpus, challenge_targets):
    """Measure codec ceilings for the exact saved baselines, without decoding."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as codec_module

    parents = {}
    for name, key in (("existing_source", "source_checkpoint"), ("existing_latent", "latent_package")):
        ref = plan[key]
        require(sha(ref["path"]) == ref["sha256"], "baseline checkpoint bytes differ")
        payload = read(ref["path"])
        parents[name] = payload if name == "existing_source" else payload["formula_checkpoint"]
    results = {}
    for name, parent in parents.items():
        codec = parent["codec"]
        codec_module.validate_codec(codec)
        panels = {}
        for panel in ("train", "development", "tuning", "heldout", "regression", "challenge"):
            rows, errors, atoms = [], Counter(), Counter()
            for source in corpus["splits"][panel]:
                target = challenge_targets[source["id"]] if panel == "challenge" else source["canonical_ir"]
                encodable, reason, missing = True, None, []
                try:
                    codec_module.encode_target(codec, target)
                except ValueError as error:
                    encodable, reason = False, str(error)
                    errors[reason] += 1
                    rule = validate_ir(target)
                    for field in FACETS:
                        values = rule[field] if field in ("conditions", "exceptions", "temporal") else [rule[field]]
                        for value in values:
                            if codec_module._atom(field, value) not in codec["target_vocabulary"]:
                                atoms[(field, value)] += 1
                                missing.append({"field": field, "value": value})
                source_ok = None
                if name == "existing_source":
                    try:
                        codec_module.encode_source(codec, source["source_text"])
                        source_ok = True
                    except ValueError:
                        source_ok = False
                rows.append({"id": source["id"], "target_representable": encodable,
                    "source_tokenizable": source_ok, "reason": reason, "missing_atoms": missing})
            target_count = sum(row["target_representable"] for row in rows)
            reachable = sum(row["target_representable"] and row["source_tokenizable"] is not False for row in rows)
            panels[panel] = {"count": len(rows), "target_representable_count": target_count,
                "target_unrepresentable_count": len(rows) - target_count,
                "exact_match_ceiling_given_codec": reachable,
                "target_rejection_reasons": dict(errors),
                "missing_typed_atoms": [{"field": field, "value": value, "occurrences": count}
                    for (field, value), count in sorted(atoms.items())], "rows": rows}
        results[name] = {"schema": parent["schema"], "codec_sha256": digest(codec),
            "source_vocabulary_size": len(codec["source_vocabulary"]),
            "target_vocabulary_size": len(codec["target_vocabulary"]),
            "source_token_codec_used_in_inference": name == "existing_source", "panels": panels}
    return {"models": results, "training_executed": False,
        "scope": "exact saved codec and length limits; representability is necessary but insufficient for faithful generation",
        "baseline_comparison_controlled_for_training_data_or_capacity": False,
        "baseline_interpretation": "saved source and latent baselines differ in training data, capacity and vocabulary; their raw scores do not isolate architecture"}


def summarize(directory, *, corpus_path=None, target_path=None):
    directory = Path(directory).resolve()
    summary, plan, frozen = frozen_run(directory)
    corpus_path = Path(corpus_path) if corpus_path else directory.parent / "prepared/corpus.json"
    target_path = Path(target_path) if target_path else directory.parent / "prepared/sealed-evaluation-targets.json"
    require(sha(corpus_path) == plan["corpus_sha256"], "source corpus digest differs")
    corpus = read(corpus_path)
    challenge = corpus["splits"]["challenge"]
    require(all("canonical_ir" not in row for row in challenge), "challenge references must remain separate")
    require(sha(target_path) == plan["challenge_targets_sha256"], "sealed target digest differs")
    # The completed summary and all frozen checkpoint hashes were verified above.
    refs = read(target_path)["targets"]
    require(len(refs) == len(challenge) and len({r["id"] for r in refs}) == len(refs), "reference coverage differs")
    refs = {row["id"]: row for row in refs}
    require(set(refs) == {row["id"] for row in challenge}, "reference identities differ")
    for source in challenge:
        ref = refs[source["id"]]
        require(source["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest()
                == ref["source_sha256"], "reference source binding differs")
        require(source["canonical_target_sha256"] == ref["canonical_target_sha256"]
                == digest(ref["canonical_ir"]), "reference canonical hash differs")
    targets = {key: row["canonical_ir"] for key, row in refs.items()}
    codec_audit = representability(plan, corpus, targets)
    models = {entry["name"]: model_metrics(directory, entry["name"], "challenge.json", challenge, targets)
              for entry in summary["runs"]}
    other_panels = {entry["name"]: {panel: entry["scores"][panel]
                    for panel in ("heldout", "regression", "tuning")} for entry in summary["runs"]}
    transfer = {name: dataset_transfer(directory, name, corpus["splits"]["oov"]) for name in models}
    by_arm, comparisons, sensitivity = {}, {}, {}
    for arm in ARMS:
        records = [{"seed": seed, **{key: value for key, value in models[f"{arm}-{seed}"].items()
                     if key not in ("rows", "groups")}} for seed in plan["seeds"]]
        by_arm[arm] = {"seeds": records,
            "mean_exact": sum(r["exact"] for r in records) / len(records),
            "minimum_exact": min(r["exact"] for r in records), "maximum_exact": max(r["exact"] for r in records)}
    pairs = {"architecture_token_ce": ("source_ce", "hybrid_ce"),
             "architecture_facet_balanced": ("source_facets", "hybrid_facets"),
             "loss_source": ("source_ce", "source_facets"),
             "loss_hybrid": ("hybrid_ce", "hybrid_facets")}
    for label, (left, right) in pairs.items():
        comparisons[label] = [{"seed": seed, "left": left, "right": right,
            **paired(models[f"{left}-{seed}"], models[f"{right}-{seed}"])} for seed in plan["seeds"]]
    replay = [{"seed": seed, **paired(models["existing_source"], models[f"source_ce-{seed}"])}
              for seed in plan["seeds"]]
    for arm in ("hybrid_ce", "hybrid_facets"):
        for seed in plan["seeds"]:
            name = f"{arm}-{seed}"
            sensitivity[name] = {}
            for control in CONTROLS:
                controlled = model_metrics(directory, name, "challenge-" + control + ".json", challenge, targets)
                sensitivity[name][control] = {"control_metrics": {k: v for k, v in controlled.items() if k != "rows"},
                    "normal_to_control": paired(models[name], controlled)}
    sensitivity["existing_latent"] = {}
    for control in ("zero_latent", "rotated_latent"):
        controlled = model_metrics(directory, "existing_latent", "challenge-" + control + ".json", challenge, targets)
        sensitivity["existing_latent"][control] = {
            "control_metrics": {k: v for k, v in controlled.items() if k != "rows"},
            "normal_to_control": paired(models["existing_latent"], controlled)}
    step_counts = {f"{r['arm']}-{r['seed']}": r["optimizer_steps"] for r in frozen}
    return {"schema": "legal-decoder-comparison-summary/v1", "inputs": {
            "summary": reference(directory / "summary.json"), "plan": reference(directory / "plan.json"),
            "frozen_heads": reference(directory / "frozen-heads.json"), "corpus": reference(corpus_path),
            "sealed_targets": reference(target_path)},
        "frozen_checkpoints_verified_before_reference_access": True,
        "challenge_count": len(challenge), "family_group_count": len({r["family_group"] for r in challenge}),
        "actor_action_group_count": len({r["actor_action_group"] for r in challenge}),
        "training_steps": step_counts, "requested_steps_per_branch": plan["new_steps_per_arm"],
        "all_branches_completed_equal_requested_steps": all(v == plan["new_steps_per_arm"] for v in step_counts.values()),
        "models": models, "arms": by_arm, "paired_comparisons": comparisons,
        "other_panel_recorded_metrics": other_panels, "dataset_transfer": transfer,
        "baseline_target_representability": codec_audit,
        "continued_training_with_development_vs_original_source": replay, "latent_sensitivity": sensitivity,
        "interpretation": {
            "label_scope": "authored synthetic object swaps and qualifier compositions; no independently reviewed statutory labels",
            "data_comparison": "original source vs continued source includes both extra optimizer updates and new development data; neither contribution is isolated",
            "loss_comparison": "facet-balanced vs token CE within the same enabled/disabled latent branch and seed",
            "architecture_comparison": "enabled vs disabled latent residual within the same loss and seed; verify matched optimizer counts",
            "saved_baseline_comparison": "old source and latent models have different training data, capacity and vocabularies; raw old-model scores do not isolate architecture",
            "inherited_parameters": "entire source decoder plus frozen learned latent residual projection; latent GRU and output head are not fused",
            "latent_input_scope": "published Legal384 learned projection includes source parser features; raw-embedding and unprojected-latent interventions occur at inference only",
            "intervention_scope": "substituting a differently distributed vector at inference measures sensitivity; it does not isolate the training benefit of learned projection or parser features",
            "qualifier_error_scope": "exact string-multiset differences on decoded single rules; abstentions reported separately; no semantic equivalence inference",
            "uncertainty_scope": "descriptive paired seed and group counts; minimal pairs and actor/action groups are correlated; no independent-row significance claim",
            "checkpoint_selection": "all predeclared branches reported; no winner promoted"},
        "training_executed": False, "admitted": False, "qualified": False,
        "statutory_semantic_accuracy_verified": False, "promotion_performed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory")
    parser.add_argument("--corpus")
    parser.add_argument("--challenge-targets")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = summarize(args.run_directory, corpus_path=args.corpus, target_path=args.challenge_targets)
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(Path(args.output).resolve()), "sha256": sha(args.output),
                      "challenge_count": report["challenge_count"],
                      "matched_steps": report["all_branches_completed_equal_requested_steps"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
