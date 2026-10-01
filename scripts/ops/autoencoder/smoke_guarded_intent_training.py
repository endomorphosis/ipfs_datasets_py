#!/usr/bin/env python3
"""Three authored guarded Intent sources and a preserved false-guard diagnostic.

This exercises source-bound finite-model declarations, actual native checks,
two structural optimizer steps and gated tuning inference. It does not infer
state truth, train a source decoder, or measure independent reconstruction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "source_semantics_verified": False, "source_decoder_trained": False,
         "constitution_formalized": False, "download_calls": 0}


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _checks(receipt, report):
    if {r["projection_id"] for r in receipt["per_projection"]} != {r["projection_id"] for r in report["projections"]}:
        raise ValueError("native receipt omitted an active projection")
    return bool(receipt["per_projection"]) and all(row["parser_status"] == "passed"
        and row["lake_status"] == "passed" and row["semantic_lowering_supported"] is True
        for row in receipt["per_projection"])


def run(output, lake, *, java_executable=None, tla2tools_jar=None):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v4 import build_native_family_lake
    from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v4 as policy
    from ipfs_datasets_py.logic.intent_ir.formalize import guarded_workflow
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_guarded_intent_panel as panel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v4 import (
        train_validated_family_projection_autoencoder, infer_validated_family_projection_autoencoder)
    require_workspace_logic_tree()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    source_hashes = {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                     for path in (__file__, panel.__file__)}
    try:
        # This diagnostic is excluded from both fitting and tuning. All supplied
        # initial states remain represented; no false valuation is filtered out.
        negative = panel.prepare_case(0, include_false_precondition=True)
        inputs, report = negative["source_inputs"], negative["report"]
        graph = guarded_workflow.guarded_workflow_graph(inputs["document"], inputs["context"]["state"]["workflow"], 4)
        _write(output / "false-precondition-fixture.json", negative["fixture"])
        _write(output / "false-precondition-targets.json", report)
        _write(output / "false-precondition-graph.json", graph)
        handle = build_native_family_lake(report, source_inputs=inputs, lake_executable=lake,
            java_executable=java_executable, tla2tools_jar=tla2tools_jar, output_directory=output / "false-precondition-native")
        receipt = handle.to_dict()
        observation = policy.validate_projection_report(report, lake_execution=handle,
            applicability_review=panel.applicability_reviews(report, 0))
        _write(output / "false-precondition-native" / "validation.json", observation.to_dict())
        negative_gate = policy.evaluate_projection_training_batch([observation], domain_id="intent_ir", target_reports=[report])
        _write(output / "false-precondition-gate.json", negative_gate)
        failed_preconditions = [row for row in graph["deadlocks"] if row["reason"] == "precondition_false"]
        expected_guarded = {"intent_ir/guarded/" + name + "/v1" for name in ("state", "workflow", "action_contract", "tla_plus")}
        guarded_targets = [row for row in report["projections"] if row["projection_id"] in expected_guarded]
        guarded_observations = [row for row in observation.to_dict()["projection_observations"] if row["projection_id"] in expected_guarded]
        guarded_rejection = (len(guarded_targets) == len(guarded_observations) == 4
            and all(row["ready_for_training"] is False for row in guarded_targets)
            and all(row["validated"] is False and "native_target_not_ready" in row["blocking_reasons"] for row in guarded_observations))
        diagnostic = {"all_native_projections_passed": _checks(receipt, report),
            "initial_valuation_count": graph["initial_valuation_count"], "configuration_count": len(graph["configurations"]),
            "deadlock_count": len(graph["deadlocks"]), "false_precondition_count": len(failed_preconditions),
            "deadlock_free": graph["deadlock_free"], "strict_training_allowed": negative_gate["strict_training_allowed"],
            "all_four_guarded_targets_rejected_before_training": guarded_rejection,
            "excluded_from_training_and_tuning": True, "model_checker_executed": False,
            "diagnostic_scope": "exhaustive native finite-state enumeration and live strict-gate rejection; no TLC or source execution", **FALSE}
        diagnostic["expected_failure_preserved"] = (graph["initial_valuation_count"] == 2 and len(failed_preconditions) == 1
            and graph["deadlock_free"] is False and negative_gate["strict_training_allowed"] is False and guarded_rejection)
        _write(output / "diagnostic-summary.json", diagnostic)
        observations, handles, reports, cases = [], [], [], []
        for index in range(3):
            started = time.monotonic()
            case = panel.prepare_case(index)
            report = case["report"]
            if len(report["requested_families"]) != 40 or len(report["family_inventory"]) != 40:
                raise ValueError("the complete forty-family inventory is required")
            _write(output / f"source-{index}-targets.json", report)
            _write(output / f"source-{index}-fixture.json", case["fixture"])
            handle = build_native_family_lake(report, source_inputs=case["source_inputs"], lake_executable=lake,
                java_executable=java_executable, tla2tools_jar=tla2tools_jar, output_directory=output / f"source-{index}")
            handles.append(handle)
            receipt = handle.to_dict()
            reviews = panel.applicability_reviews(report, index)
            observation = policy.validate_projection_report(report, lake_execution=handle, applicability_review=reviews)
            _write(output / f"source-{index}" / "applicability-review.json", reviews)
            _write(output / f"source-{index}" / "validation.json", observation.to_dict())
            observations.append(observation); reports.append(report)
            cases.append({"index": index, "split": "train" if index < 2 else "tuning",
                "report_sha256": report["report_sha256"], "source_digest": report["source_digest"],
                "projection_count": len(report["projections"]), "wall_seconds": time.monotonic() - started,
                "lake_status": receipt.get("execution", {}).get("status"),
                "lake_command": receipt.get("execution", {}).get("command"),
                "all_projection_checks_passed": _checks(receipt, report),
                "additional_syntax_checks": [{"projection_id": row["projection_id"], "checks": row["additional_syntax_checks"]}
                    for row in receipt["per_projection"] if row.get("additional_syntax_checks")],
                "supplied_initial_ready_truth": True, "source_meaning_verified": False})
        native_seconds = time.monotonic() - start
        training_gate = policy.evaluate_projection_training_batch(observations[:2], domain_id="intent_ir", target_reports=reports[:2])
        tuning_gate = policy.evaluate_projection_training_batch(observations[2:], domain_id="intent_ir", target_reports=reports[2:])
        _write(output / "training-gate.json", training_gate); _write(output / "tuning-gate.json", tuning_gate)
        trained = train_validated_family_projection_autoencoder(observations[:2], observations[2:], domain_id="intent_ir",
            output_dir=output / "checkpoint", epochs=2, minibatch_size=2, latent_width=8, max_seconds=60)
        inferred = infer_validated_family_projection_autoencoder(trained["descriptor"], observations[2:])
        _write(output / "training.json", trained); _write(output / "inference.json", inferred)
        expected_train = {(index, row["projection_id"]) for index, report in enumerate(reports[:2]) for row in report["projections"]}
        expected_tune = {row["projection_id"] for row in reports[2]["projections"]}
        coverage = trained["report"]["training_coverage"]
        checks = {"false_precondition_diagnostic_preserved": diagnostic["expected_failure_preserved"],
            "all_positive_native_checks_passed": all(case["all_projection_checks_passed"] for case in cases),
            "training_gate_passed": training_gate["strict_training_allowed"],
            "tuning_gate_passed": tuning_gate["strict_training_allowed"],
            "two_optimizer_steps": trained["report"]["training_executed"] is True and trained["report"]["optimizer_steps"] == 2,
            "all_training_projections_have_loss": not coverage["untrained_projection_ids"] and
                {(row["row"], row["projection_id"]) for row in coverage["projections"] if row["has_coverage"]} == expected_train,
            "all_tuning_projections_have_loss": set(trained["report"]["after"]["projections"]) == expected_tune,
            "all_inference_projections_have_loss": set(inferred["projections"]) == expected_tune and
                inferred["loss_coverage"]["rows_per_projection"] == {name: 1 for name in expected_tune},
            "eight_supplied_formulas_retained": all({"intent_ir/native_formula/" + key + "/v3" for key in panel.FORMULAS}
                <= {row["projection_id"] for row in report["projections"]} for report in reports)}
        if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in source_hashes.items()):
            raise ValueError("runner or authored fixture source changed during smoke")
        summary = {"schema": "guarded-intent-native-training-smoke/v1", "integration_passed": all(checks.values()),
            "checks": checks, "sources": cases, "source_hashes": source_hashes,
            "native_and_diagnostic_seconds": native_seconds, "total_wall_seconds": time.monotonic() - start,
            "diagnostic": diagnostic, "training_rows": 2, "tuning_rows": 1, "optimizer_steps": trained["report"]["optimizer_steps"],
            "initial_tuning_objective": trained["report"]["before"]["objective"],
            "selected_tuning_objective": trained["report"]["after"]["objective"], "selected_epoch": trained["report"]["selected_epoch"],
            "scope": "authored finite assumptions and exact source-bound predicate/effect joins; not source inference, heldout fidelity or 8D/384D decoder training",
            "tools": {"lake": str(lake), "java_executable": java_executable, "tla2tools_jar": tla2tools_jar},
            "external_model_checker_executed": False, **FALSE}
        _write(output / "summary.json", summary)
        return summary
    except Exception:
        (output / "failure.txt").write_text(traceback.format_exc())
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    parser.add_argument("--java-executable")
    parser.add_argument("--tla2tools-jar")
    args = parser.parse_args()
    result = run(args.output, args.lake, java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar)
    print(json.dumps({"integration_passed": result["integration_passed"], "optimizer_steps": result["optimizer_steps"],
        "total_wall_seconds": result["total_wall_seconds"]}), flush=True)
    raise SystemExit(0 if result["integration_passed"] else 1)
