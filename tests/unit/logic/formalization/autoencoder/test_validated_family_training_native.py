"""Opt-in real Lake → strict gate → four-tensor training integration.

Set IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE to an installed native Lake binary.
These authored source-bound declarations are not natural-language inference,
independent federal-law gold, or a claim of semantic model qualification.
"""
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as native
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake as lake
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract as policy
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR, CanonicalRule
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated as trainer

FORMULAS = {
    "FOL": "forall x. Person(x) -> Reports(x)", "DFOL": "forall x. O(Reports(x))",
    "TFOL": "forall x. □(Reports(x))", "TDFOL": "forall x. O(□(Reports(x)))",
    "CEC": "K(Officer,Happens(Submit,Time))", "DCEC": "O(K(Officer,Happens(Submit,Time)))",
    "frame_logic": "alice[role -> officer].", "propositional": "p and q",
}


def test_real_native_lake_input_gates_then_numerical_training(tmp_path):
    executable = os.environ.get("IPFS_DATASETS_NATIVE_LAKE_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("requires explicitly selected installed native Lake; no download or shim fallback")
    executable = Path(executable)
    assert executable.is_absolute() and executable.is_file()
    observations, receipts = [], []
    for index in range(3):
        inputs = {"document": CanonicalRoundTripIR((CanonicalRule(
            "O", "agency" + str(index), "submit", "report" + str(index)),)),
            "source_text": "Authored native declaration fixture " + str(index) + "."}
        source = native.supplemental_source_ref("legal_ir", **inputs)
        inputs["formula_inputs"] = [NativeFormulaEvidence(key, value, source) for key, value in FORMULAS.items()]
        report = native.prepare_family_training_targets_v3("legal_ir", **inputs)
        execution = lake.build_native_family_lake(report, source_inputs=inputs, lake_executable=str(executable),
            output_directory=tmp_path / ("lake-" + str(index)))
        receipt = lake.verify_native_family_lake(execution, report)
        assert len(receipt["per_projection"]) == 9
        assert all(row["lake_status"] == "passed" for row in receipt["per_projection"])
        families = {row["logic_family"] for row in report["projections"]}
        reviews = [{"family_id": family, "source_digest": report["source_digest"],
            "disposition": "inapplicable",
            "reason": "Closed authored integration fixture declares only supplied native fragments; no other model supplied.",
            "evidence_refs": ["urn:authored-native-projection-smoke:v1:" + str(index)]}
            for family in policy.domain_projection_policy("legal_ir")["family_inventory"] if family not in families]
        observations.append(policy.validate_projection_report(report, lake_execution=execution, applicability_review=reviews))
        receipts.append(receipt)
    fitted = trainer.train_validated_family_projection_autoencoder(observations[:2], observations[2:],
        domain_id="legal_ir", output_dir=tmp_path / "head", epochs=2, latent_width=2, minibatch_size=2, denoising=0)
    report = fitted["report"]
    assert report["training_gate_passed"] and report["optimizer_steps"] == 2
    assert report["loss_coverage"]["training"]["projection_occurrences"] == 18
    assert report["loss_coverage"]["tuning"]["projection_occurrences"] == 9
    assert not any(report[key] for key in ("admitted", "qualified", "formalized", "source_semantics_verified", "roundtrip_ok"))
    inferred = trainer.infer_validated_family_projection_autoencoder(fitted["descriptor"], observations[2:])
    assert set(inferred["projections"]) == set(report["loss_coverage"]["tuning"]["rows_per_projection"])
    assert not inferred["formulas_generated"] and not inferred["source_text_decoded"]
