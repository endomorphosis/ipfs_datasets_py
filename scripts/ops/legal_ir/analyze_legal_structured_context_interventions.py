#!/usr/bin/env python3
"""Explain which candidate fields changed under frozen context interventions.

This post-run analysis reads predictions and the completed independent analysis;
it never opens challenge canonical target files. Field changes are measured only
where both candidates decoded, with abstention transitions counted separately.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import summarize_legal_span_retrieval_experiment as shared


def field_changes(normal, changed):
    shared.require(len(normal) == len(changed), "intervention prediction count differs")
    transitions, fields, boundaries = Counter(), Counter(), Counter()
    presence, values = Counter(), Counter()
    count = 0
    for baseline, altered in zip(normal, changed):
        shared.require(baseline["source_sha256"] == altered["source_sha256"], "intervention source changed")
        transitions[baseline["status"] + "_to_" + altered["status"]] += 1
        count += (baseline["status"], baseline["canonical_ir"]) != (altered["status"], altered["canonical_ir"])
        if baseline["status"] != "decoded" or altered["status"] != "decoded":
            continue
        original, candidate = baseline["canonical_ir"]["rules"][0], altered["canonical_ir"]["rules"][0]
        for field in shared.FIELDS:
            fields[field] += original[field] != candidate[field]
            if field in shared.SPAN_FIELDS:
                left = baseline["span_diagnostics"]["facets"][field]
                right = altered["span_diagnostics"]["facets"][field]
                boundaries[field] += (left["char_start"], left["char_end"]) != (right["char_start"], right["char_end"])
            if field in shared.QUALIFIERS:
                presence[field] += bool(original[field]) != bool(candidate[field])
                values[field] += bool(original[field]) and bool(candidate[field]) and original[field] != candidate[field]
    return {"count": len(normal), "canonical_output_or_status_changed": count,
            "status_transitions": dict(transitions), "both_decoded_denominator": transitions["decoded_to_decoded"],
            "field_changed_among_both_decoded": {field: fields[field] for field in shared.FIELDS},
            "span_boundary_changed_among_both_decoded": {field: boundaries[field] for field in shared.SPAN_FIELDS},
            "qualifier_presence_changed_among_both_decoded": {field: presence[field] for field in shared.QUALIFIERS},
            "qualifier_value_changed_when_both_present": {field: values[field] for field in shared.QUALIFIERS}}


def analyze(run_directory, analysis_path, output):
    directory = Path(run_directory).resolve()
    previous = shared.read(analysis_path)
    shared.require(Path(previous["run_summary"]["path"]).resolve() == directory / "summary.json", "independent analysis refers to another run")
    summary = shared.read(shared.verify_ref(previous["run_summary"]))
    shared.require(previous["verification"]["all_checkpoint_and_generation_hashes_verified"] is True,
                   "completed independent verification required")
    frozen = shared.read(shared.verify_ref(summary["generation_frozen"]))
    results = {}
    for name, run in previous["runs"].items():
        interventions = [panel for panel in run["panels"] if panel.startswith("challenge_")]
        if not interventions:
            continue
        normal = shared.read(directory / name / "challenge-generation.json")
        shared.require(shared.digest(normal) == frozen[name]["challenge"], "ordinary generation commitment differs")
        results[name] = {}
        for panel in interventions:
            payload = shared.read(directory / name / (panel + "-generation.json"))
            shared.require(shared.digest(payload) == frozen[name][panel], "intervention generation commitment differs")
            changes = field_changes(normal["rows"], payload["rows"])
            measured = run["panels"][panel]
            shared.require(changes["canonical_output_or_status_changed"] == measured["prediction_changed_count"],
                           "changed prediction count differs from independent analysis")
            results[name][panel] = {**changes, "normal_exact": run["panels"]["challenge"]["exact"],
                                   "intervention_exact": measured["exact"],
                                   "exact_delta": measured["paired_with_normal_context"]["exact_delta"]}
    report = {"schema": "legal-structured-context-field-effects/v1", "results": results,
        "independent_analysis": {"path": str(Path(analysis_path).resolve()), "sha256": shared.sha(analysis_path)},
        "analyzer": {"path": str(Path(__file__).resolve()), "sha256": shared.sha(__file__)},
        "scope": {"source_held_fixed": True, "challenge_target_file_read": False,
                  "canonical_field_change_denominator": "both ordinary and intervened candidates decoded",
                  "abstention_handling": "separate status transition counts; partial failed-candidate diagnostics excluded",
                  "causal_scope": "sensitivity of selected checkpoint to supplied context, not an accuracy advantage or legal qualification",
                  "qualified": False, "admitted": False}}
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(Path(output).resolve()), "sha256": shared.sha(output), "models": len(results)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(analyze(args.run_directory, args.analysis, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
