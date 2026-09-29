"""Summarize already-audited native refinement receipts without model/proof calls.

Comparative row claims require identical materialized and logical parent states,
training/validation samples, and model settings. Unequal parents are explicit
noncomparisons. This program never mutates checkpoints, registries, or audits.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_bytes())


def descriptor(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def checked_audit(path):
    audit = read(path)
    if audit.get("passed") is not True or audit.get("failures"):
        raise ValueError("summary requires a passing completed native audit")
    cycle_ref = audit["cycle"]
    if descriptor(cycle_ref["path"]) != cycle_ref:
        raise ValueError("cycle changed after native audit")
    if descriptor(audit["command"]["path"]) != audit["command"]:
        raise ValueError("command receipt changed after native audit")
    return audit


def summarize(args):
    audited = checked_audit(args.audit)
    compared = checked_audit(args.comparison_audit) if args.comparison_audit else None
    root = Path(audited["cycle"]["path"]).parents[2]
    rows = []
    for key, record in sorted(audited["rows"].items()):
        ref = record["worker_receipt"]
        path = root / "artifacts" / ref["sha256"][:2] / ref["sha256"]
        actual = descriptor(path)
        if actual["sha256"] != ref["sha256"] or actual["bytes"] != ref["bytes"]:
            raise ValueError("worker receipt changed after native audit")
        worker = read(path)
        refinement_stages = {}
        in_refinement = False
        for event in worker["training_report"].get("projection_profile", {}).get("events", []):
            stage = event.get("stage", "")
            if stage == "hard_example_selection":
                in_refinement = False
            if stage == "composed_refinement_training_baseline":
                in_refinement = True
            if in_refinement and (stage.startswith("composed_refinement_") or stage == "projection_update_batch"):
                refinement_stages[stage] = refinement_stages.get(stage, 0.0) + event["seconds"]
        epochs = []
        for epoch in worker["training_report"]["epoch_reports"]:
            attempts = [entry for entry in epoch["candidate_reports"] if entry.get("composed_refinement") is True]
            summarized = []
            for attempt in attempts:
                summarized.append({key: attempt[key] for key in (
                    "update", "base_selected_update", "refinement_attempt", "accepted",
                    "strict_accepted", "acceptance_source", "holdout_evaluated",
                    "effective_learning_rate", "objective_delta", "validation_objective_delta_required",
                    "training_before", "training_after", "training_reconstruction_delta",
                    "rejection_reasons", "pareto_regressions", "selected_candidate_regressions",
                ) if key in attempt})
            epochs.append({"epoch": epoch["epoch"], "accepted": epoch["accepted"],
                           "selected_update": epoch.get("selected_update"),
                           "refinement_attempt_count": len(attempts),
                           "eligible_refinement_count": sum(entry["accepted"] for entry in attempts),
                           "selected_refinement": next((entry for entry in summarized if entry["update"] == epoch.get("selected_update")), None),
                           "attempts": summarized})
        comparison = None
        if compared is not None:
            prior = compared["rows"].get(key)
            fields = ("base", "base_identity", "samples", "validation_samples", "model_config")
            mismatches = [field for field in fields if prior is None or prior[field] != record[field]]
            if compared["core_sources"] != audited["core_sources"]:
                mismatches.append("core_sources")
            prior_config = dict(prior["training_config"]) if prior else {}
            current_config = dict(record["training_config"])
            prior_config.pop("projection_max_composed_refinement_attempts", None)
            current_config.pop("projection_max_composed_refinement_attempts", None)
            if prior_config != current_config:
                mismatches.append("training_config_except_explicit_refinement_budget")
            comparison = {"eligible": not mismatches, "mismatched_fields": mismatches,
                          "scope": "identical parent state and samples; explicit refinement policy differs" if not mismatches else "no cross-parent or mismatched-input improvement claim"}
            if not mismatches:
                comparison.update({"before_qualified": prior["qualified"], "after_qualified": record["qualified"],
                                   "before_status": prior["status"], "after_status": record["status"],
                                   "before_candidate": prior["candidate"], "after_candidate": record["candidate"],
                                   "before_training_seconds": prior["training_seconds"], "after_training_seconds": record["training_seconds"],
                                   "training_seconds_delta": record["training_seconds"] - prior["training_seconds"],
                                   "before_metric_gates": [{"split": row["split"], **row["metric_gate"]} for row in prior["qualification_rows"]],
                                   "after_metric_gates": [{"split": row["split"], **row["metric_gate"]} for row in record["qualification_rows"]]})
        rows.append({"sample_key": key, "source_text": record["source_text"], "lane": record["lane"],
                     "base": record["base"], "base_identity": record["base_identity"], "candidate": record["candidate"],
                     "qualified": record["qualified"], "status": record["status"], "gates": record["gates"],
                     "epochs": epochs, "comparison": comparison,
                     "training_seconds": record["training_seconds"], "worker_seconds": record["worker_wall_seconds"],
                     "profiled_refinement_stage_seconds": refinement_stages,
                     "profiled_refinement_nonoverlapping_seconds": sum(refinement_stages.values()),
                     "profile_scope": "Observed refinement evaluation and update-batch phases only; excludes nested update-head phases to avoid double counting, and is not total trial wall time.",
                     "numeric_lake_scope": [{"split": row["split"], "source_text": row["source"]["text"],
                                             "proofs": row["lean"]} for row in record["qualification_rows"]]})
    return {"schema": "native-composed-refinement-summary/v1", "audit": descriptor(args.audit),
            "run_command": audited["command"],
            "comparison_run_command": compared["command"] if compared else None,
            "comparison_audit": descriptor(args.comparison_audit) if args.comparison_audit else None,
            "configuration": audited["configuration"], "native_counts": audited["counts"],
            "wall_seconds": audited["wall_seconds"],
            "comparison_wall_seconds": compared["wall_seconds"] if compared else None,
            "speed_comparison_eligible": False,
            "speed_scope": "Optimizer policy and candidate results differ; these route timings are observations, not a speed parity result.",
            "selected_refinement_count": sum(epoch["selected_refinement"] is not None for row in rows for epoch in row["epochs"]),
            "rows": rows, "scope": "Synthetic fixture optimization only. Repeated tuning rows are not an independent canary. Embedding metrics retain the existing target-aware reconstruction projection. Six family syntax projections do not establish semantic equivalence or complete cognitive/event semantics. Lake evidence proves the recorded source-locked numeric pattern only.",
            "admitted": False, "formalized": False, "constitution_formalized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--comparison-audit", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"selected_refinement_count": result["selected_refinement_count"], "counts": result["native_counts"]}))


if __name__ == "__main__":
    main()
