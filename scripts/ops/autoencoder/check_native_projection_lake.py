#!/usr/bin/env python3
"""Exercise every emitted projection and real Lake libraries in four modalities.

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


def run(output, lake):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as targets
    from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import build_native_family_lake
    from ipfs_datasets_py.logic.formalization.autoencoder.projection_validation_contract import (
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
        report = targets.prepare_family_training_targets_v3(domain, **inputs)
        execution = build_native_family_lake(report, source_inputs=inputs, lake_executable=lake,
                                            output_directory=output / domain)
        receipt = execution.to_dict()
        observation = validate_projection_report(report, lake_execution=execution)
        policy = evaluate_projection_training_batch([observation], domain_id=domain)
        result = {"domain_id": domain, "library": receipt["library"],
                  "native_report_sha256": report["report_sha256"],
                  "wall_seconds": time.monotonic() - started,
                  "projections": receipt["per_projection"], "lake": receipt.get("execution"),
                  "batch_validation": policy,
                  "fixture_scope": "authored typed models and supplied formulas; source meaning unverified"}
        (output / domain / "native-targets.json").write_text(json.dumps(report, indent=2) + "\n")
        results[domain] = result
        print(json.dumps({"domain": domain, "library": receipt["library"],
            "passed_projections": sum(row["lake_status"] == "passed" for row in receipt["per_projection"]),
            "total_projections": len(receipt["per_projection"]),
            "wall_seconds": result["wall_seconds"]}), flush=True)
    summary = {"schema": "four-modality-native-projection-check/v1", "results": results,
        "source_tree": str(ROOT), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "all_named_formula_cases_passed": all(
            all(any(row["projection_id"] == domain + "/native_formula/" + requirement + "/v3"
                    and row["lake_status"] == "passed" for row in result["projections"])
                for requirement in FORMULAS) for domain, result in results.items()),
        "training_executed": False, "admitted": False, "qualified": False,
        "source_semantics_verified": False, "constitution_formalized": False,
        "download_calls": 0, "cache_scope": "fresh process and fresh Lake workspace per modality"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True, help="Installed native Lake executable; not the Elan downloader shim")
    args = parser.parse_args()
    summary = run(args.output, args.lake)
    raise SystemExit(0 if summary["all_named_formula_cases_passed"] else 1)
