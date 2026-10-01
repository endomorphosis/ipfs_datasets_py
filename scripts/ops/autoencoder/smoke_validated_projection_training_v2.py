#!/usr/bin/env python3
"""Real Lake-to-training smoke on closed authored LegalIR declarations.

This small integration case is not a corpus benchmark or decoder fidelity test.
Broader modality panels must pass their own complete gate before strict training.
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
from check_native_projection_lake_v2 import FORMULAS


def run(output, lake, *, java_executable=None, tla2tools_jar=None):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v4 as targets
    from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v2 import build_native_family_lake
    from ipfs_datasets_py.logic.formalization.autoencoder.projection_validation_contract_v2 import validate_projection_report
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule, CanonicalRoundTripIR
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_validated_v2 import (
        train_validated_family_projection_autoencoder, infer_validated_family_projection_autoencoder)

    require_workspace_logic_tree()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    observations = []
    handles = []
    projection_sets = []
    started = time.monotonic()
    for index in range(3):
        document = CanonicalRoundTripIR((CanonicalRule("O", "agency" + str(index), "submit", "report" + str(index)),))
        inputs = {"document": document, "source_text": f"Authored native declaration fixture {index}."}
        source = targets.supplemental_source_ref("legal_ir", **inputs)
        inputs["formula_inputs"] = [NativeFormulaEvidence(key, value, source) for key, value in FORMULAS.items()]
        report = targets.prepare_family_training_targets_v4("legal_ir", **inputs)
        if len(report["requested_families"]) != 40 or len(report["family_inventory"]) != 40:
            raise ValueError("complete catalog must remain requested before applicability review")
        projection_ids = {row["projection_id"] for row in report["projections"]}
        if len(projection_ids) != 9:
            raise ValueError("expected all nine Legal native and explicit-formula projections")
        projection_sets.append(projection_ids)
        (output / f"source-{index}-prepared-targets.json").write_text(json.dumps(report, indent=2) + "\n")
        handle = build_native_family_lake(report, source_inputs=inputs, lake_executable=lake,
                                         output_directory=output / f"source-{index}",
                                         java_executable=java_executable, tla2tools_jar=tla2tools_jar)
        handles.append(handle)
        present = {row["logic_family"] for row in report["projections"]}
        reviews = [{"family_id": row["family_id"], "source_digest": report["source_digest"],
            "disposition": "inapplicable",
            "reason": "Closed authored integration fixture declares only the supplied native fragments; no additional model is specified.",
            "evidence_refs": [f"urn:authored-native-projection-smoke:v2:{index}"]}
            for row in report["family_inventory"] if row["family_id"] not in present]
        observation = validate_projection_report(report, lake_execution=handle, applicability_review=reviews)
        observations.append(observation)
        (output / f"source-{index}" / "targets.json").write_text(json.dumps(report, indent=2) + "\n")
        (output / f"source-{index}" / "validation.json").write_text(json.dumps(observation.to_dict(), indent=2) + "\n")
    preparation = time.monotonic() - started
    trained = train_validated_family_projection_autoencoder(observations[:2], observations[2:],
        domain_id="legal_ir", output_dir=output / "checkpoint", epochs=2, minibatch_size=2,
        latent_width=8, max_seconds=30)
    inferred = infer_validated_family_projection_autoencoder(trained["descriptor"], observations[2:])
    expected_ids = projection_sets[2]
    evidence = {
        "two_optimizer_steps_executed": trained["report"]["training_executed"] is True
            and trained["report"]["optimizer_steps"] == 2,
        "all_nine_tuning_projection_losses_present":
            set(trained["report"]["after"]["projections"]) == expected_ids,
        "all_eighteen_training_projection_occurrences_covered":
            {(row["row"], row["projection_id"]) for row in trained["report"]["training_coverage"]["projections"]
             if row["has_coverage"]} == {
                 (index, name) for index, names in enumerate(projection_sets[:2]) for name in names},
        "all_nine_inference_projection_losses_present": set(inferred["projections"]) == expected_ids,
        "all_emitted_projections_have_loss": inferred["loss_coverage"]["all_emitted_projections_have_loss"] is True
            and inferred["loss_coverage"]["projection_occurrences"] == 9
            and inferred["loss_coverage"]["rows_per_projection"] == {name: 1 for name in expected_ids},
    }
    result = {"schema": "live-projection-training-smoke/v2", "trained": trained,
        "tools": {"lake": str(lake), "java_executable": java_executable, "tla2tools_jar": tla2tools_jar},
        "source_tree": str(ROOT), "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "integration_checks": evidence, "integration_passed": all(evidence.values()),
        "inference": inferred, "native_preparation_and_Lake_seconds": preparation,
        "total_wall_seconds": time.monotonic() - started, "source_count": 3,
        "scope": "two authored training sources, one tuning source; not heldout or natural-language fidelity",
        "admitted": False, "qualified": False, "formalized": False,
        "constitution_formalized": False, "download_calls": 0}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"training_executed": trained["report"]["training_executed"],
        "optimizer_steps": trained["report"]["optimizer_steps"],
        "integration_passed": result["integration_passed"],
        "wall_seconds": result["total_wall_seconds"]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    parser.add_argument("--java-executable", help="Installed Java executable used by the native SANY checker")
    parser.add_argument("--tla2tools-jar", help="Existing local tla2tools.jar; no downloads")
    args = parser.parse_args()
    fresh_output = not Path(args.output).exists()
    try:
        result = run(args.output, args.lake, java_executable=args.java_executable, tla2tools_jar=args.tla2tools_jar)
    except Exception:
        output = Path(args.output)
        if fresh_output and output.is_dir():
            with (output / "failure.txt").open("x") as stream:
                stream.write(traceback.format_exc())
        raise
    raise SystemExit(0 if result["integration_passed"] else 1)
