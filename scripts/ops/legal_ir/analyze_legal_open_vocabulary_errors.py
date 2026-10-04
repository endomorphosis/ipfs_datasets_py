#!/usr/bin/env python3
"""Posthoc diagnostics for frozen errors; never repair predictions or retrain."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.run_legal_open_vocabulary_experiment import file_ref, read, require, digest
from scripts.ops.legal_ir.compare_legal_decoder_architectures import score
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span

ARMS = ("source_only", "trained384", "native768")
SEEDS = (1729, 1730, 1731)


def bound(ref):
    actual = file_ref(ref["path"])
    require(actual["sha256"] == ref["sha256"] and ("bytes" not in ref or actual["bytes"] == ref["bytes"]),
            "input artifact bytes differ")
    return read(ref["path"])


def actor_boundary(source, reference, predicted):
    left, right = reference["actor"]
    guessed = predicted["actor"]
    start, end = guessed["char_start"], guessed["char_end"]
    if (start, end) == (left, right):
        return {"kind": "correct_actor_span"}
    if start == left and end > right:
        return {"kind": "actor_end_includes_following_modal_words", "extra_text": source[right:end],
                "reference_char_range": [left, right], "predicted_char_range": [start, end]}
    if start > left and end == right:
        return {"kind": "actor_start_drops_name_prefix", "omitted_text": source[left:start],
                "reference_char_range": [left, right], "predicted_char_range": [start, end]}
    return {"kind": "other_actor_boundary_error", "reference_char_range": [left, right],
            "predicted_char_range": [start, end]}


def analyze(directory, *, prior_directory=None):
    directory = Path(directory).resolve()
    summary_ref = file_ref(directory / "summary.json")
    summary = bound(summary_ref)
    require(summary["evaluation_cohort_previously_exposed"] is True
        and summary["challenge_targets_read_after_all_training_selection_and_generation"] is True,
        "completed explicitly exposed regression required")
    plan = bound(summary["plan"])
    frozen = bound(summary["generation_frozen"])
    require(frozen["all_generation_complete"] is True and frozen["challenge_targets_read_in_this_execution"] is False,
            "pre-score complete generation freeze required")
    corpus, payload = bound(plan["corpus"]), bound(plan["targets"])
    inputs = corpus["splits"]["challenge"]
    targets = {row["id"]: row for row in payload["targets"]}
    require(len(targets) == len(inputs) == 192, "complete authored challenge required")
    references = []
    for row in inputs:
        target = targets[row["id"]]
        require(row["source_sha256"] == target["source_sha256"] and
            digest(target["canonical_ir"]) == row["canonical_target_sha256"] == target["canonical_target_sha256"],
            "target source/hash binding differs")
        references.append({"id": row["id"], "source_text": row["source_text"], "canonical_ir": target["canonical_ir"]})
        for field, location in target["source_spans"].items():
            expected = target["canonical_ir"]["rules"][0][field]
            spans = location if field in ("conditions", "exceptions", "temporal") else [location]
            values = expected if isinstance(expected, list) else [expected]
            require(len(spans) == len(values), "authored span cardinality differs")
            require(all(row["source_text"][start:end] == value for (start, end), value in zip(spans, values)),
                    "authored span does not exactly slice source")
    audit = span.audit_examples(references)
    require(audit["all_supported"] is True, "challenge contains unrepresentable reference")
    by_model, by_case, metric_refs = {}, {}, []
    for arm in ARMS:
        for seed in SEEDS:
            name = f"{arm}-{seed}"
            generation_ref = frozen["files"][name]["challenge"]
            generation = bound(generation_ref)
            scores_ref = file_ref(directory / name / "challenge.json")
            saved = bound(scores_ref)
            recomputed = score(generation["rows"], inputs, references)
            require(saved["generation"] == generation and saved["metrics"] == recomputed,
                    "generation or recomputed error accounting differs")
            metric_refs.append(scores_ref)
            errors = []
            for index, result in enumerate(recomputed["rows"]):
                if result["exact"]:
                    continue
                source, prediction = inputs[index], generation["rows"][index]
                target = targets[source["id"]]
                require(prediction["status"] == "decoded", "unexpected abstention in residual error set")
                diagnostics = prediction["span_diagnostics"]
                for field, value in diagnostics["facets"].items():
                    if value["present"]:
                        require(source["source_text"][value["char_start"]:value["char_end"]] == value["text"],
                                "prediction span is not copied from exact source")
                facets = [field for field, correct in result["facets"].items() if not correct]
                identity = (seed, source["id"])
                case = by_case.setdefault(identity, {
                    "seed": seed, "id": source["id"], "source_sha256": source["source_sha256"],
                    "family_group": source["family_group"], "template_id": source["template_id"],
                    "qualifier_pattern": source["qualifier_pattern"], "source_text": source["source_text"],
                    "reference": target["canonical_ir"], "reference_source_spans": target["source_spans"],
                    "reference_is_exactly_representable": True,
                    "modality_surface_cues": [{"text": match.group(), "char_start": match.start(), "char_end": match.end()}
                        for match in re.finditer(r"\b(?:is allowed to|may)\b", source["source_text"])],
                    "cue_scope": "Literal authored-fixture surface cues, not independent statutory interpretation.",
                    "actor_error": actor_boundary(source["source_text"], target["source_spans"], diagnostics["facets"]),
                    "models": {},
                })
                logits = dict(zip(span.MODALITIES, diagnostics["modality_logits"]))
                expected_modality = target["canonical_ir"]["rules"][0]["modality"]
                actual_modality = prediction["canonical_ir"]["rules"][0]["modality"]
                case["models"][arm] = {"checkpoint": next(row["checkpoint"] for row in summary["runs"] if row["name"] == name),
                    "generation": generation_ref, "prediction": prediction["canonical_ir"], "facet_errors": facets,
                    "predicted_source_spans": diagnostics["facets"], "source_tokens": diagnostics["tokens"],
                    "modality_logits": logits,
                    "selected_modality_minus_reference_logit": logits[actual_modality] - logits[expected_modality],
                    "reference_and_prediction_roundtrip_supported": True}
                errors.append({"id": source["id"], "predicted": prediction["canonical_ir"], "facet_errors": facets})
            by_model[name] = {"seed": seed, "arm": arm, "count":192, "exact":recomputed["exact"], "errors":errors}
    require(all(by_model[f"source_only-{seed}"]["errors"] == by_model[f"{arm}-{seed}"]["errors"]
                for seed in SEEDS for arm in ARMS), "error identities or canonical predictions differ across arms")
    cases = [by_case[key] for key in sorted(by_case)]
    per_arm = {}
    for arm in ARMS:
        rows = [item for item in by_model.values() if item["arm"] == arm]
        errors = [error for row in rows for error in row["errors"]]
        per_arm[arm] = {"evaluations":sum(row["count"] for row in rows), "errors":len(errors),
            "unique_error_source_ids":len({error["id"] for error in errors}),
            "errors_by_seed":{str(row["seed"]):len(row["errors"]) for row in rows},
            "facet_error_counts":dict(Counter(field for error in errors for field in error["facet_errors"]))}
    require(all(item["errors"] == 5 and item["unique_error_source_ids"] == 5 for item in per_arm.values()),
            "unexpected residual error set")
    prior = None
    if prior_directory is not None:
        comparisons = []
        for seed in SEEDS:
            path = Path(prior_directory) / f"trained384-{seed}" / "challenge.json"
            ref = file_ref(path); previous = bound(ref)
            actual = score(previous["generation"]["rows"], inputs, references)
            require(actual == previous["metrics"], "prior challenge metrics differ")
            old_errors = [{"id": row["id"], "predicted": previous["generation"]["rows"][i]["canonical_ir"],
                "facet_errors":[field for field, correct in row["facets"].items() if not correct]}
                for i, row in enumerate(actual["rows"]) if not row["exact"]]
            comparisons.append({"seed":seed,"prior":ref,"same_error_ids_and_predictions":old_errors == by_model[f"trained384-{seed}"]["errors"]})
        prior = comparisons
    return {"schema":"legal-open-vocabulary-posthoc-error-analysis/v1", "status":"completed_diagnostic_only",
        "implementation":file_ref(Path(__file__)), "span_expressibility_checker":file_ref(Path(span.__file__)),
        "summary":summary_ref, "generation_freeze":summary["generation_frozen"], "corpus":plan["corpus"],
        "authored_references":plan["targets"], "verified_metric_artifacts":metric_refs,
        "per_arm":per_arm, "unique_error_cases":cases,
        "counts":{"model_source_seed_errors_all_arms":sum(item["errors"] for item in per_arm.values()),
            "source_seed_error_pairs_ignoring_arm":len(cases), "unique_error_source_ids":len({row["id"] for row in cases}),
            "unique_error_source_texts":len({row["source_sha256"] for row in cases}),
            "families_with_errors":len({row["family_group"] for row in cases})},
        "same_error_ids_facets_and_predictions_across_arms":True,
        "reference_expressibility":{"rows":len(references),"supported":len(audit["accepted_ids"]),"unsupported":audit["rejected_rows"]},
        "diagnosis":{"actor_end_includes_modal_words":2,"actor_start_drops_name_prefix":2,
            "permission_predicted_as_obligation":2,"rows_with_both_actor_and_modality_error":1,
            "other_facet_errors":0,"grammar_or_vocabulary_ceiling_caused_these_errors":False,
            "scope":"The five authored single-rule references are valid exact source-copy targets; failures are pointer selection and modality classification. This says nothing about unsupported multi-rule/statutory semantics."},
        "prior_native384_comparison":prior,
        "next_experiment_proposals":[
            {"name":"actor_boundary_curriculum","training_design":"Use new actor names and organizational noun phrases with varying lengths; pair identical modal/action frames with actor-prefix and actor-suffix minimal contrasts. Include preposed conditions and citation prefixes.",
             "evaluation_design":"Reserve fresh actor lexemes and organizational suffix combinations by family. Report actor-start and actor-end accuracy separately, including prefix omission and modal-token inclusion."},
            {"name":"modality_and_actor_attachment","training_design":"Create new balanced O/P/F contrasts using may, is allowed to, must, shall and prohibition phrases, controlling actor length and qualifier load. Explore a source-grounded modality span head or joint boundary/modality constraint with explicit ambiguous/quoted-cue abstentions.",
             "evaluation_design":"Freeze lexical/structural split before training; hold out new surface constructions, not only new names. Measure permission-to-obligation confusions under condition/exception/deadline combinations."},
            {"name":"calibration_without_challenge_tuning","training_design":"Calibrate any confidence-based abstention threshold on separate tuning examples only. Current actor error margins are low, but one wrong modality has a substantial logit lead, so confidence alone is not a complete repair.",
             "evaluation_design":"Report exact accuracy, coverage and selective error together on a fresh frozen test. Do not choose thresholds, checkpoints, prompts or synthetic labels to fix these five observed rows."},
        ],
        "observed_challenge_rows_added_to_training":False, "predictions_repaired":False, "models_retrained":False,
        "metrics_changed":False, "independent_holdout":False, "independent_legal_review":False,
        "gold_targets_created":False, "source_semantics_verified":False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",required=True,type=Path)
    parser.add_argument("--prior-directory",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    report=analyze(args.directory,prior_directory=args.prior_directory)
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(report,stream,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False);stream.write("\n")
    print(json.dumps({"output":file_ref(args.output),"counts":report["counts"],"per_arm":report["per_arm"]}))
