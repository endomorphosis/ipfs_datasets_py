#!/usr/bin/env python3
"""Post-build attribution of learned boundaries and downstream clause decoding."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_construction_retention_corpus as corpus

boundary = corpus.documents.boundary
require, file_ref, write_new = corpus.require, corpus.file_ref, corpus.write_new
PANELS = ("document_tuning", "fresh_documents", "exposed_documents")


def read_ref(reference):
    require({"path", "sha256"} <= set(reference) <= {"path", "sha256", "bytes"}, "closed artifact reference required")
    payload = Path(reference["path"]).read_bytes()
    require(corpus.sha(payload) == reference["sha256"], "artifact hash differs")
    require("bytes" not in reference or len(payload) == reference["bytes"], "artifact byte count differs")
    return json.loads(payload)


def intervals(clauses):
    return [[c["char_start"], c["char_end"]] for c in clauses]


def boundary_record(source, prediction, reference):
    identity = source["candidate_id"]
    require(identity == prediction["candidate_id"] == reference["candidate_id"], "boundary identity differs")
    require(source["source_sha256"] == prediction["source_sha256"] == reference["source_sha256"] ==
        corpus.sha(source["source_text"].encode()), "boundary source binding differs")
    require(reference["source_text"] == source["source_text"], "reference source text differs")
    tokens = boundary.tokenize(source["source_text"])
    ends = prediction["boundary_token_indices"]
    require(ends == sorted(set(ends)) and all(type(i) is int and 0 <= i < len(tokens) for i in ends), "invalid raw boundary indices")
    raw_intervals, previous = [], 0
    for end in ends:
        raw_intervals.append([tokens[previous]["char_start"], tokens[end]["char_end"]])
        previous = end + 1
    require(prediction["predicted_rule_count"] == len(ends), "raw predicted count differs")
    plan = prediction["plan"]
    require((plan is not None) is (prediction["status"] == "segmented"), "accepted boundary status/plan differs")
    delivered = intervals(plan["clauses"]) if plan else None
    if plan:
        require(plan["source"] == source and delivered == raw_intervals, "delivered plan differs from raw boundaries")
    supported = reference["supported"]
    wanted = intervals(reference["clauses"]) if supported else None
    if not supported:
        require(reference["clauses"] == [], "unsupported reference must not invent flat clauses")
    raw_ends = {c[1] for c in raw_intervals}
    expected_ends = {c[1] for c in wanted} if wanted else set()
    extra = sorted(raw_ends - expected_ends) if supported else None
    missing = sorted(expected_ends - raw_ends) if supported else None
    if not supported:
        error_type = "unsupported_scope_no_reference_segmentation"
    elif not extra and not missing:
        error_type = "exact" if raw_intervals == wanted else "same_ends_different_starts"
    elif extra and missing:
        error_type = "mixed_split_merge_or_shift"
    elif extra:
        error_type = "oversegmented_only"
    else:
        error_type = "undersegmented_only"
    return {"id": identity, "source_sha256": source["source_sha256"], "supported": supported,
        "construction": reference["construction"], "raw_scope_supported": prediction["raw_learned_scope_supported"],
        "status": prediction["status"], "reason": prediction["reason"], "raw_intervals": raw_intervals,
        "reference_intervals": wanted, "delivered_intervals": delivered,
        "raw_terminal_coverage": bool(ends and ends[-1] == len(tokens) - 1),
        "raw_interval_exact": bool(supported and raw_intervals == wanted),
        "delivered_interval_exact": bool(supported and delivered == wanted),
        "raw_predicted_count": len(ends), "reference_count": len(wanted) if supported else None,
        "raw_count_relation": ("equal" if len(ends) == len(wanted) else "too_many" if len(ends) > len(wanted) else "too_few") if supported else None,
        "extra_end_offsets": extra, "missing_end_offsets": missing, "raw_error_type": error_type}


def boundary_counts(rows):
    supported = [r for r in rows if r["supported"]]
    unsupported = [r for r in rows if not r["supported"]]
    return {"documents": len(rows), "supported": len(supported), "unsupported": len(unsupported),
        "supported_raw_interval_exact": sum(r["raw_interval_exact"] for r in supported),
        "supported_delivered_interval_exact": sum(r["delivered_interval_exact"] for r in supported),
        "supported_accepted_plan": sum(r["delivered_intervals"] is not None for r in supported),
        "supported_boundary_abstained": sum(r["delivered_intervals"] is None for r in supported),
        "supported_raw_exact_but_abstained": sum(r["raw_interval_exact"] and r["delivered_intervals"] is None for r in supported),
        "supported_raw_scope_rejected": sum(not r["raw_scope_supported"] for r in supported),
        "supported_terminal_coverage_missing": sum(not r["raw_terminal_coverage"] for r in supported),
        "supported_extra_end_offsets": sum(len(r["extra_end_offsets"]) for r in supported),
        "supported_missing_end_offsets": sum(len(r["missing_end_offsets"]) for r in supported),
        "supported_raw_count_relation": dict(Counter(r["raw_count_relation"] for r in supported)),
        "supported_raw_error_types": dict(Counter(r["raw_error_type"] for r in supported)),
        "supported_rejection_reasons": dict(Counter(r["reason"] for r in supported if r["delivered_intervals"] is None)),
        "unsupported_correctly_rejected": sum(r["delivered_intervals"] is None for r in unsupported),
        "unsupported_accepted_plan": sum(r["delivered_intervals"] is not None for r in unsupported),
        "unsupported_raw_scope_false_positive": sum(r["raw_scope_supported"] for r in unsupported),
        "unsupported_rejection_reasons": dict(Counter(r["reason"] for r in unsupported if r["delivered_intervals"] is None))}


def pipeline_record(prediction, reference, boundary_result):
    require(prediction["candidate_id"] == reference["candidate_id"] == boundary_result["id"] and
        prediction["source_sha256"] == reference["source_sha256"] == boundary_result["source_sha256"], "pipeline source binding differs")
    require(prediction["segmentation_status"] == boundary_result["status"], "pipeline used different boundary status")
    value = prediction["composition"]
    accepted = value is not None
    require((prediction["status"] == "composed") is accepted, "pipeline status/composition differs")
    actual_intervals = intervals(value["source_plan"]["clauses"]) if accepted else None
    if accepted:
        require(actual_intervals == boundary_result["delivered_intervals"], "composition occurrence intervals differ from frozen boundary plan")
    supported = reference["supported"]
    wanted = [r["rule"] for r in reference["clauses"]] if supported else None
    canonical_exact = bool(supported and accepted and value["source_rule_list"] == wanted)
    occurrence_exact = bool(supported and accepted and actual_intervals == intervals(reference["clauses"]))
    joint = canonical_exact and occurrence_exact
    if not supported:
        attribution = "unsupported_falsely_composed" if accepted else "unsupported_correctly_abstained"
    elif boundary_result["delivered_intervals"] is None:
        attribution = "raw_intervals_exact_but_boundary_policy_abstained" if boundary_result["raw_interval_exact"] else "raw_boundary_mismatch_and_rejected"
    elif not boundary_result["delivered_interval_exact"]:
        attribution = "composed_with_wrong_boundaries" if accepted else "decoder_abstained_after_wrong_boundaries"
    elif not accepted:
        attribution = "decoder_abstained_after_exact_boundaries"
    else:
        attribution = "joint_exact" if joint else "canonical_error_after_exact_boundaries"
    return {"id": reference["candidate_id"], "supported": supported, "construction": reference["construction"],
        "composed": accepted, "canonical_exact": canonical_exact, "occurrence_exact": occurrence_exact,
        "joint_exact": joint, "canonical_only_exact": canonical_exact and not occurrence_exact,
        "decision_exact": joint or not supported and not accepted, "attribution": attribution,
        "pipeline_reason": prediction["reason"], "boundary_raw_interval_exact": boundary_result["raw_interval_exact"],
        "boundary_delivered_interval_exact": boundary_result["delivered_interval_exact"]}


def pipeline_counts(rows):
    counts = {"documents": len(rows), "supported": sum(r["supported"] for r in rows),
        "unsupported": sum(not r["supported"] for r in rows), "composed": sum(r["composed"] for r in rows),
        "abstained": sum(not r["composed"] for r in rows),
        **{key: sum(r[key] for r in rows) for key in ("canonical_exact", "occurrence_exact", "joint_exact", "canonical_only_exact", "decision_exact")},
        "attribution": dict(Counter(r["attribution"] for r in rows))}
    require(sum(counts["attribution"].values()) == len(rows), "pipeline attribution dropped outcomes")
    return counts


def same_ref(left, right):
    return Path(left["path"]).resolve() == Path(right["path"]).resolve() and left["sha256"] == right["sha256"]


def analyze(base):
    base = Path(base).resolve()
    summary_ref = file_ref(base / "qualification-01/summary.json")
    summary = read_ref(summary_ref)
    require(summary["fresh_target_and_regression_references_opened_after_replay_and_build_freezes"] is True,
        "completed post-build qualification summary required before target reads")
    builds_ref = file_ref(base / "qualification-01/builds-frozen.json")
    require(same_ref(summary["builds"], builds_ref), "summary build freeze binding differs")
    builds = read_ref(builds_ref)
    require(builds["fresh_and_regression_targets_opened"] is False and len(builds["models"]) == 15 and
        all(set(kinds) == {"single", "anchor", "document"} for kinds in builds["models"].values()), "complete pre-reference build freeze required")
    replay = read_ref(summary["replay"])
    require(same_ref(summary["replay"], builds["replay"]) and same_ref(replay["generation_freeze"], summary["generation_freeze"]), "replay/build/generation linkage differs")
    frozen = read_ref(summary["generation_freeze"])
    require(set(builds["models"]) == {m["name"] for m in frozen["models"]}, "built/generation model inventory differs")
    plan = read_ref(frozen["plan"])
    config = read_ref(plan["config"])
    manifest = read_ref(config["corpus_manifest"])
    # No new target or annotation bytes have been opened above this gate.
    references = {"document_tuning": manifest["artifacts"]["document_tuning_targets"],
        "fresh_documents": manifest["artifacts"]["document_challenge_targets"], "exposed_documents": config["exposed_document_targets"]}
    targets = {panel: read_ref(reference) for panel, reference in references.items()}
    sources = read_ref(frozen["document_sources"])
    qualified_details = read_ref(summary["details"])["document"]
    results, by_id = {}, {}
    for panel in PANELS:
        raw = read_ref(frozen["boundaries"][panel])
        require(len(sources[panel]) == len(targets[panel]) == len(raw["rows"]) == 96, "complete document panel required")
        raw_index = {r["candidate_id"]: r for r in raw["rows"]}
        target_index = {r["candidate_id"]: r for r in targets[panel]}
        require(len(raw_index) == len(target_index) == 96 and set(raw_index) == set(target_index) == {r["candidate_id"] for r in sources[panel]}, "boundary/reference identity coverage differs")
        details = [boundary_record(s, raw_index[s["candidate_id"]], target_index[s["candidate_id"]]) for s in sources[panel]]
        by_id[panel] = {r["id"]: r for r in details}
        results[panel] = {"counts": boundary_counts(details), "rows": details,
            "by_construction": {family: boundary_counts([r for r in details if r["construction"] == family]) for family in sorted({r["construction"] for r in details})}}
    models, aggregate_rows = [], {}
    for model in frozen["models"]:
        result = {"name": model["name"], "arm": model["arm"], "seed": model["seed"], "panels": {}}
        for panel in PANELS:
            generation = read_ref(frozen["document_files"][model["name"]][panel])
            target_index = {r["candidate_id"]: r for r in targets[panel]}
            require(len(generation["rows"]) == 96 and {r["candidate_id"] for r in generation["rows"]} == set(target_index), "pipeline identity coverage differs")
            rows = [pipeline_record(r, target_index[r["candidate_id"]], by_id[panel][r["candidate_id"]]) for r in generation["rows"]]
            counts = pipeline_counts(rows)
            qualified = qualified_details[model["name"]][panel]
            for ours, theirs in {"documents": "count", "supported": "supported", "unsupported": "unsupported", "composed": "composed", "abstained": "abstained", "canonical_exact": "canonical_rule_list_exact", "occurrence_exact": "occurrence_boundaries_exact", "joint_exact": "exact", "decision_exact": "decision_exact"}.items():
                require(counts[ours] == qualified[theirs], "independent pipeline metric differs from qualifier")
            result["panels"][panel] = {"counts": counts, "rows": rows,
                "by_construction": {family: pipeline_counts([r for r in rows if r["construction"] == family]) for family in sorted({r["construction"] for r in rows})}}
            aggregate_rows.setdefault(model["arm"], {}).setdefault(panel, []).extend(rows)
        models.append(result)
    return {"schema": "legal-construction-segmentation-attribution/v1", "analyzer": file_ref(__file__),
        "qualification": summary_ref, "builds": builds_ref, "generation": summary["generation_freeze"],
        "source_documents": frozen["document_sources"], "boundary_predictions": frozen["boundaries"],
        "reference_documents": references, "pipeline_predictions": frozen["document_files"],
        "qualification_details": summary["details"], "post_build_reference_gate_verified": True,
        "boundary_panels": results, "models": models,
        "arm_totals": {arm: {panel: pipeline_counts(rows) for panel, rows in panels.items()} for arm, panels in aggregate_rows.items()},
        "denominators": {"unique_boundary_document_inputs": 288, "unique_supported_documents_per_panel": 72,
            "unique_unsupported_documents_per_panel": 24, "pipeline_model_slots": 15, "pipeline_document_outcomes": 4320,
            "raw_boundaries_scored_even_when_scope_policy_or_clause_decoder_abstains": True},
        "definitions": {"raw_interval_exact": "Intervals induced directly from all predicted end-token indices, before scope and source-policy gates; scored even if no plan was returned.",
            "delivered_interval_exact": "Accepted boundary plan matches all reference occurrence intervals, regardless of subsequent clause decoding or composition.",
            "canonical_exact": "Composed ordered rule list equals the reference rule occurrences, regardless of interval correctness.",
            "joint_exact": "Composed ordered rules and source occurrence intervals are both exact.",
            "wrong_split_merge": "Extra reference-relative end offsets are split errors; missing offsets are merge errors. Both can coexist. Count equality alone does not establish interval correctness."},
        "limitations": ["This is a descriptive posthoc attribution, not a gold-boundary intervention or retraining experiment.",
            "Raw boundary correctness does not override a scope or policy rejection; diagnostic raw intervals are not accepted logical outputs.",
            "Where every fresh document is rejected before clause decoding, fresh document scores cannot distinguish clause decoder architecture quality.",
            "Document tuning is a selection set; exposed documents are regression observations; only the new document panel is fresh.",
            "All model seeds/policies reuse the same document cases and fixed boundary decoder. Arm totals are correlated model-case outcomes, not independent document samples.",
            "Restricted authored cases do not establish statutory correctness or independent scope semantics."],
        "training_performed": False, "production_promotion": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    args = parser.parse_args()
    print(write_new(args.base / "segmentation-analysis.json", analyze(args.base)))


if __name__ == "__main__":
    main()
