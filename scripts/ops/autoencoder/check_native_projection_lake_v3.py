#!/usr/bin/env python3
"""Exercise v5 targets and real Lake/SANY checks in all four modalities.

The inputs are authored integration fixtures, never federal-law gold data. Each
source explicitly carries eight additional formal declarations. Their exact
source join is reproducible; their meaning is not inferred from source prose.
Missing native lowerings and unreviewed applicability remain blocking evidence.
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

FORMULAS = {
    "FOL": "forall x. Person(x) -> Reports(x)",
    "DFOL": "forall x. O(Reports(x))",
    "TFOL": "forall x. □(Reports(x))",
    "TDFOL": "forall x. O(□(Reports(x)))",
    "CEC": "K(Officer,Happens(Submit,Time))",
    "DCEC": "O(K(Officer,Happens(Submit,Time)))",
    "frame_logic": "alice[role -> officer].",
    "propositional": "p and q",
}


def run(output, lake, *, java_executable=None, tla2tools_jar=None):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v5 as targets
    from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v3 import build_native_family_lake
    from ipfs_datasets_py.logic.formalization.autoencoder.projection_validation_contract_v3 import (
        validate_projection_report, evaluate_projection_training_batch)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as fixtures

    require_workspace_logic_tree()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for domain in fixtures.DOMAINS:
        started = time.monotonic()
        inputs = fixtures.source_inputs(fixtures.rows(domain, "train")[0])
        source = targets.supplemental_source_ref(domain, **inputs)
        inputs["formula_inputs"] = [NativeFormulaEvidence(key, value, source) for key, value in FORMULAS.items()]
        report = targets.prepare_family_training_targets_v5(domain, **inputs)
        if len(report["family_inventory"]) != 40 or len(report["requested_families"]) != 40:
            raise ValueError("the complete forty-family request must remain visible")
        (output / (domain + "-prepared-targets.json")).write_text(json.dumps(report, indent=2) + "\n")
        execution = build_native_family_lake(report, source_inputs=inputs, lake_executable=lake,
                                            output_directory=output / domain,
                                            java_executable=java_executable, tla2tools_jar=tla2tools_jar)
        receipt = execution.to_dict()
        if {row["projection_id"] for row in receipt["per_projection"]} != {
                row["projection_id"] for row in report["projections"]}:
            raise ValueError("native build receipt omitted a projection")
        observation = validate_projection_report(report, lake_execution=execution)
        policy = evaluate_projection_training_batch([observation], domain_id=domain)
        result = {"domain_id": domain, "library": receipt["library"],
                  "native_report_sha256": report["report_sha256"],
                  "wall_seconds": time.monotonic() - started,
                  "projections": receipt["per_projection"], "lake": receipt.get("execution"),
                  "requested_families": report["requested_families"],
                  "family_inventory": report["family_inventory"],
                  "all_emitted_projections_passed": bool(receipt["per_projection"]) and all(
                      row["lake_status"] == "passed" and row["parser_status"] == "passed"
                      for row in receipt["per_projection"]),
                  "build_receipt_path": str(output / domain / "receipt.json"),
                  "superseded_tla_observation_count": len(report.get("superseded_tla_observations", [])),
                  "batch_validation": policy,
                  "fixture_scope": "authored typed models and supplied formulas; source meaning unverified"}
        (output / domain / "native-targets.json").write_text(json.dumps(report, indent=2) + "\n")
        (output / domain / "validation.json").write_text(json.dumps(observation.to_dict(), indent=2) + "\n")
        (output / domain / "batch-validation.json").write_text(json.dumps(policy, indent=2) + "\n")
        results[domain] = result
        print(json.dumps({"domain": domain, "library": receipt["library"],
            "passed_projections": sum(row["lake_status"] == "passed" and row["parser_status"] == "passed"
                                      for row in receipt["per_projection"]),
            "total_projections": len(receipt["per_projection"]),
            "wall_seconds": result["wall_seconds"]}), flush=True)
    summary = {"schema": "four-modality-native-projection-check/v3", "results": results,
        "tools": {"lake": str(lake), "java_executable": java_executable,
                  "tla2tools_jar": tla2tools_jar},
        "expected_modality_count": 4, "expected_explicit_formula_case_count": 32,
        "complete_modality_matrix_executed": set(results) == set(fixtures.DOMAINS) and len(results) == 4,
        "source_tree": str(ROOT), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "all_named_formula_cases_passed": all(
            all(any(row["projection_id"] == domain + "/native_formula/" + requirement + "/v3"
                    and row["lake_status"] == "passed" and row["parser_status"] == "passed"
                    for row in result["projections"])
                for requirement in FORMULAS) for domain, result in results.items()),
        "all_emitted_projections_passed": all(result["all_emitted_projections_passed"] for result in results.values()),
        "all_modality_training_gates_passed": all(
            result["batch_validation"]["strict_training_allowed"] for result in results.values()),
        "training_executed": False, "admitted": False, "qualified": False,
        "source_semantics_verified": False, "constitution_formalized": False,
        "download_calls": 0, "cache_scope": "fresh process and fresh Lake workspace per modality"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True, help="Installed native Lake executable; not the Elan downloader shim")
    parser.add_argument("--java-executable", help="Installed Java executable used by the native SANY checker")
    parser.add_argument("--tla2tools-jar", help="Existing local tla2tools.jar; no downloads")
    args = parser.parse_args()
    fresh_output = not Path(args.output).exists()
    try:
        summary = run(args.output, args.lake, java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar)
    except Exception:
        output = Path(args.output)
        if fresh_output and output.is_dir():
            with (output / "failure.txt").open("x") as stream:
                stream.write(traceback.format_exc())
        raise
    # This matrix is an integration diagnostic. Unsupported rows remain visible
    # and block strict training even when all 32 explicit formula cases pass.
    raise SystemExit(0 if summary["complete_modality_matrix_executed"] and summary["all_named_formula_cases_passed"] else 1)
