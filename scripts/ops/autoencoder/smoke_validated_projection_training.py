#!/usr/bin/env python3
"""Real Lake-to-training smoke on closed authored LegalIR declarations.

This small integration case is not a corpus benchmark or decoder fidelity test.
Broader modality panels must pass their own complete gate before strict training.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from check_native_projection_lake import FORMULAS


def run(output, lake):
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as targets
    from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import build_native_family_lake
    from ipfs_datasets_py.logic.formalization.autoencoder.projection_validation_contract import validate_projection_report
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule, CanonicalRoundTripIR
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_validated import (
        train_validated_family_projection_autoencoder, infer_validated_family_projection_autoencoder)

    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    observations = []
    handles = []
    started = time.monotonic()
    for index in range(3):
        document = CanonicalRoundTripIR((CanonicalRule("O", "agency" + str(index), "submit", "report" + str(index)),))
        inputs = {"document": document, "source_text": f"Authored native declaration fixture {index}."}
        source = targets.supplemental_source_ref("legal_ir", **inputs)
        inputs["formula_inputs"] = [NativeFormulaEvidence(key, value, source) for key, value in FORMULAS.items()]
        report = targets.prepare_family_training_targets_v3("legal_ir", **inputs)
        handle = build_native_family_lake(report, source_inputs=inputs, lake_executable=lake,
                                         output_directory=output / f"source-{index}")
        handles.append(handle)
        present = {row["logic_family"] for row in report["projections"]}
        reviews = [{"family_id": row["family_id"], "source_digest": report["source_digest"],
            "disposition": "inapplicable",
            "reason": "Closed authored integration fixture declares only the supplied native fragments; no additional model is specified.",
            "evidence_refs": [f"urn:authored-native-projection-smoke:v1:{index}"]}
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
    result = {"schema": "live-projection-training-smoke/v1", "trained": trained,
        "inference": inferred, "native_preparation_and_Lake_seconds": preparation,
        "total_wall_seconds": time.monotonic() - started, "source_count": 3,
        "scope": "two authored training sources, one tuning source; not heldout or natural-language fidelity",
        "admitted": False, "qualified": False, "formalized": False,
        "constitution_formalized": False, "download_calls": 0}
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"training_executed": trained["report"]["training_executed"],
        "optimizer_steps": trained["report"]["optimizer_steps"],
        "wall_seconds": result["total_wall_seconds"]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    args = parser.parse_args()
    run(args.output, args.lake)
