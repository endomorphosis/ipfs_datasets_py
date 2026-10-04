#!/usr/bin/env python3
"""Post-qualification facet/temporal analysis; never changes fitting or selection."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import audit_legal_grounding_experiment as evidence

FIELDS = evidence.FIELDS
require, read_ref, ref, raw = evidence.require, evidence.read_ref, evidence.ref, evidence.raw


def facet_state(prediction, wanted, field):
    if prediction["status"] == "abstained":
        return "abstained"
    actual = prediction["canonical_ir"]["rules"][0][field]
    if actual == wanted:
        return "correct"
    if not actual:
        return "missing"
    if not wanted:
        return "spurious"
    return "wrong_value"


def temporal_layout(target):
    rule = target["canonical_ir"]["rules"][0]
    if not rule["temporal"]:
        return "absent"
    coordinates = target.get("facet_spans")
    if coordinates is None:
        return "present_coordinates_unavailable"
    temporal, actor = coordinates["temporal"], coordinates["actor"]
    if temporal[1] <= actor[0]:
        return "before_actor"
    if temporal[0] >= actor[1]:
        return "after_actor"
    return "overlapping_actor_invalid"


def layout_exposure(matches):
    if set(matches) & {"earlier_train", "new_train"}:
        return "matched_admitted_training_surface"
    if set(matches) & {"earlier_tuning", "new_tuning"}:
        return "matched_tuning_surface_only"
    if matches:
        return "matched_exposed_challenge_surface_only"
    return "unmatched_exact_surface_not_proven_inherited_novel"


def panel_errors(predictions, sources, targets, *, constructions=None):
    require(len(predictions) == len(sources) == len(targets), "complete panel denominators required")
    by_id = {r["id"]: r for r in targets}
    require(set(by_id) == {r["id"] for r in sources} and len(by_id) == len(targets), "reference identities differ")
    rows, counts, states, groups = [], Counter(), {f: Counter() for f in ("modality", *FIELDS)}, {}
    for prediction, source in zip(predictions, sources):
        target = by_id[source["id"]]
        require(target.get("source_text", source["source_text"]) == source["source_text"], "target/source differs")
        evidence.verify_prediction(prediction, source)
        rule = target["canonical_ir"]["rules"][0]
        exact = prediction["status"] == "decoded" and prediction["canonical_ir"] == target["canonical_ir"]
        counts["count"] += 1
        counts[prediction["status"]] += 1
        counts["exact"] += exact
        failure = {field: facet_state(prediction, rule[field], field) for field in states}
        for field, state in failure.items():
            states[field][state] += 1
        position = temporal_layout(target)
        construction = constructions[source["id"]]["construction"] if constructions else "unavailable"
        exposure = layout_exposure(constructions[source["id"]]["matching_pools"]) if constructions else "unavailable"
        for name in ("temporal:" + position, "construction:" + construction, "exposure:" + exposure):
            group = groups.setdefault(name, {"count": 0, "exact": 0, "abstained": 0, "temporal_states": Counter()})
            group["count"] += 1
            group["exact"] += exact
            group["abstained"] += prediction["status"] == "abstained"
            group["temporal_states"][failure["temporal"]] += 1
        coordinates = target.get("facet_spans")
        actor_coordinates = None
        if coordinates:
            info = prediction.get("span_diagnostics", {}).get("facets", {}).get("actor", {})
            actor_coordinates = {"start_exact": info.get("char_start") == coordinates["actor"][0],
                "end_exact": info.get("char_end") == coordinates["actor"][1],
                "diagnostic_from_abstained_output": prediction["status"] == "abstained"}
        rows.append({"id": source["id"], "exact": exact, "status": prediction["status"],
            "reason": prediction.get("reason"), "facet_states": failure, "temporal_layout": position,
            "construction": construction, "surface_exposure": exposure, "actor_coordinate_diagnostics": actor_coordinates})
    return {**{key: counts[key] for key in ("count", "decoded", "abstained", "exact")},
        "facet_states": {f: dict(v) for f, v in states.items()},
        "groups": {name: {**v, "temporal_states": dict(v["temporal_states"])} for name, v in groups.items()}, "rows": rows}


def compare_rows(left, right):
    require([r["id"] for r in left] == [r["id"] for r in right], "paired source ordering differs")
    outcomes = Counter((a["exact"], b["exact"]) for a, b in zip(left, right))
    return {"count": len(left), "left_only_correct": outcomes[True, False], "right_only_correct": outcomes[False, True],
        "both_correct": outcomes[True, True], "both_wrong": outcomes[False, False]}


def analyze(run_directory, qualification_directory, output):
    run, qualification = Path(run_directory).resolve(), Path(qualification_directory).resolve()
    require((qualification / "summary.json").is_file() and (qualification / "builds-frozen.json").is_file(),
        "completed qualification and builds required before reference access")
    frozen_ref, summary_ref, build_ref = ref(run / "generation-frozen.json"), ref(qualification / "summary.json"), ref(qualification / "builds-frozen.json")
    frozen, summary = read_ref(frozen_ref), read_ref(summary_ref)
    require(all(summary["generation_freeze"][k] == frozen_ref[k] for k in ("path", "sha256")), "qualified generation freeze differs")
    require(all(summary["builds"][k] == build_ref[k] for k in ("path", "sha256")), "qualified build freeze differs")
    read_ref(build_ref)
    plan = read_ref(frozen["plan"])
    config = read_ref(plan["config"])
    manifest = read_ref(config["corpus_manifest"])
    sources = read_ref(frozen["sources"])
    # Fresh annotations and their construction membership are first opened here.
    fresh = read_ref(manifest["artifacts"]["challenge_targets"])
    exposure = read_ref(manifest["artifacts"]["exposure_audit"])
    evidence.verify_coordinate_targets(fresh, manifest["semantics"]["trigger_meanings"])
    old = read_ref(config["earlier_regression_targets"])
    if isinstance(old, dict):
        old = old["targets"]
    exposed = read_ref(config["exposed_regression_targets"])
    targets = {"fresh": fresh, "earlier_regression": old, "exposed_regression": exposed}
    selections = []
    for head in read_ref(frozen["heads"]):
        threshold = head["parent_tuning_exact"]["earlier"] - 1
        eligible = [s for s in head["stages"] if s["tuning_earlier_exact"] >= threshold]
        chosen = max(eligible, key=lambda s: (s["tuning_new_exact"], s["tuning_earlier_exact"], -s["steps"])) if eligible else None
        require(head["selected_steps"] == (chosen["steps"] if chosen else 0), "retention selection differs")
        require(head["selection"] == ("candidate" if chosen else "parent_fallback"), "retention fallback differs")
        require(head["checkpoint"] == (chosen["checkpoint"] if chosen else head["parent"]), "retention selected checkpoint differs")
        selections.append({"name": head["name"], "earlier_tuning_threshold": threshold, "selected_steps": head["selected_steps"],
            "selection": head["selection"], "eligible_steps": [s["steps"] for s in eligible]})
    layouts = {row["id"]: row for row in exposure["rows"]}
    result_models = {}
    for model in frozen["models"]:
        name = model["name"]
        result_models[name] = {"arm": model["arm"], "seed": model["seed"], "selection": model["selection"],
            "decoder_kind": model["decoder_kind"], "selected_steps": model["selected_steps"], "panels": {}}
        for panel in targets:
            generation = read_ref(frozen["files"][name][panel])
            result_models[name]["panels"][panel] = panel_errors(generation["rows"], sources[panel], targets[panel],
                constructions=layouts if panel == "fresh" else None)
    comparisons = []
    for seed in plan["seeds"]:
        for left, right in ((f"mixed_grounding-{seed}", f"mixed_continuation-{seed}"),
                            (f"mixed_grounding-{seed}", f"parent-{seed}"), (f"mixed_continuation-{seed}", f"parent-{seed}")):
            for panel in targets:
                comparisons.append({"left": left, "right": right, "panel": panel,
                    **compare_rows(result_models[left]["panels"][panel]["rows"], result_models[right]["panels"][panel]["rows"])})
    aggregate = {}
    for arm in ("parent", "mixed_continuation", "mixed_grounding"):
        group = [m for m in result_models.values() if m["arm"] == arm]
        aggregate[arm] = {}
        for panel in targets:
            total = {k: sum(m["panels"][panel][k] for m in group) for k in ("count", "decoded", "abstained", "exact")}
            total["facet_states"] = {f: dict(sum((Counter(m["panels"][panel]["facet_states"][f]) for m in group), Counter())) for f in ("modality", *FIELDS)}
            keys = set().union(*(m["panels"][panel]["groups"] for m in group))
            total["groups"] = {}
            for key in sorted(keys):
                entries = [m["panels"][panel]["groups"][key] for m in group if key in m["panels"][panel]["groups"]]
                total["groups"][key] = {**{k: sum(e[k] for e in entries) for k in ("count", "exact", "abstained")},
                    "temporal_states": dict(sum((Counter(e["temporal_states"]) for e in entries), Counter()))}
            aggregate[arm][panel] = total
    replay_design = read_ref(config["prior_replay_design"])
    prior_summary_ref = replay_design["evidence"]["current_qualification"]
    prior_summary = read_ref(prior_summary_ref)
    prior_generation = read_ref(prior_summary["generation_freeze"])
    prior_plan = read_ref(prior_generation["plan"])
    prior_config = read_ref(prior_plan["config"])
    prior_old_sources = read_ref(prior_config["regression_sources"])["challenge"]
    prior_new_sources = read_ref(prior_config["challenge_sources"])
    for earlier_sources, current_panel in ((prior_old_sources, "earlier_regression"), (prior_new_sources, "exposed_regression")):
        require([{k: r[k] for k in ("id", "source_text")} for r in earlier_sources] ==
                [{k: r[k] for k in ("id", "source_text")} for r in sources[current_panel]], "prior study source panel differs")
    require(prior_config["regression_targets"]["sha256"] == config["earlier_regression_targets"]["sha256"] and
        prior_config["challenge_targets"]["sha256"] == config["exposed_regression_targets"]["sha256"], "prior comparison target commits differ")
    prior_comparisons = []
    for current_arm, prior_arm in (("mixed_continuation", "source_continuation"), ("mixed_grounding", "trigger_grounding")):
        for current_panel, prior_panel in (("earlier_regression", "regression"), ("exposed_regression", "challenge")):
            earlier_score = prior_summary["totals"][prior_arm][prior_panel]
            current_score = aggregate[current_arm][current_panel]
            require(earlier_score["count"] == current_score["count"], "same-source historical comparison denominator differs")
            prior_comparisons.append({"current_arm": current_arm, "prior_arm": prior_arm, "panel": current_panel,
                "count": current_score["count"], "prior_exact": earlier_score["exact"], "current_exact": current_score["exact"],
                "exact_change": current_score["exact"] - earlier_score["exact"],
                "scope": "Same exposed source/reference panel, different fitting data exposure and domain weighting; descriptive cross-study comparison."})
    report = {"schema": "legal-mixed-replay-posthoc-errors/v1", "analyzer": ref(__file__),
        "generation_freeze": frozen_ref, "qualification": summary_ref, "build_freeze": build_ref,
        "models": result_models, "aggregates": aggregate, "paired_changes": comparisons,
        "selection_compliance": selections, "prior_new_only_study": prior_summary_ref,
        "same_source_prior_study_comparisons": prior_comparisons,
        "fit_exposure_per_model": {"both_studies_optimizer_updates": 800,
            "prior_new_only_examples": {"earlier": 0, "new": 9600}, "mixed_examples": {"earlier": 4800, "new": 4800},
            "equal_domain_weighting_in_mixed_objective": True},
        "targets_opened_after_qualification_build_freeze": True, "training_performed": False,
        "selections_or_outputs_changed": False, "qualified": False,
        "limitations": ["Fresh144 sources and exposed192/150 sources are separate cohorts.",
            "Repeated seeds reuse the same source sentences.", "Parent fallback remains attributed to its trial policy; no fallback is called a trained model gain.",
            "Exact role-masked layouts only partly characterize prior construction exposure.",
            "Actor-coordinate diagnostics on abstentions are separate from exact successful outputs.",
            "Passing earlier-tuning retention is a selection condition, not an independent retention guarantee.",
            "This posthoc grouping informs future experiments; it does not justify repairing or refitting this challenge."]}
    with Path(output).open("xb") as stream:
        stream.write(raw(report))
    print(json.dumps(ref(output), sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--qualification-directory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analyze(args.run_directory, args.qualification_directory, args.output)


if __name__ == "__main__":
    main()
