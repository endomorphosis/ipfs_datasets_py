"""Tests for proof-carrying LegalIR artifact envelopes."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    HAMMER_GUIDANCE_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION,
    LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION,
    HammerGuidanceArtifact,
    LegalIRBuildDigest,
    LegalIRPassKind,
    LegalIRPassSpec,
    LegalIRProofArtifactError,
    LegalIRProofObligation,
    LegalIRProofVerificationPolicy,
    LegalIRSourceMapBuilder,
    LegalIRTransformationKind,
    assert_legal_ir_proof_carrying_artifact_valid,
    build_legal_ir_build_manifest,
    build_legal_ir_proof_carrying_artifact,
    legal_ir_proof_carrying_artifact,
    load_legal_ir_proof_carrying_artifact,
    save_legal_ir_proof_carrying_artifact,
    validate_legal_ir_proof_carrying_artifact,
)


SOURCE_TEXT = "The agency shall disclose records within 30 days."
LEGAL_IR_OUTPUTS = {
    "deontic": {"rule_ids": ["rule-disclose"], "text_omitted": True},
    "tdfol": {"formula_ids": ["formula-disclose"]},
}


def _stable_hash(value) -> str:
    return __import__("hashlib").sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _obligation() -> LegalIRProofObligation:
    return LegalIRProofObligation(
        obligation_id="po-disclose",
        statement="notice_disclosure_obligation(formula_disclose)",
        kind="deontic_polarity",
        legal_ir_view="deontic.ir",
        logic_family="deontic",
        sample_id="sample-proof-carrying",
        formula_id="formula-disclose",
    )


def _source_map():
    builder = LegalIRSourceMapBuilder(source_map_id="map-proof-carrying")
    builder.add_source_document(
        "doc-proof-carrying",
        SOURCE_TEXT,
        citation="42 U.S.C. 1983(a)",
    )
    span = builder.add_span(
        "doc-proof-carrying",
        0,
        len(SOURCE_TEXT),
        transformation_step_id="compiler.parse_norm",
    )
    builder.add_node(
        "formula-disclose",
        node_kind="compiler_formula",
        span_ids=(span.span_id,),
        emitted_fact="formula-disclose",
        transformation_step_id="compiler.emit_formula",
    )
    builder.add_derived_node(
        "translation-disclose",
        node_kind="hammer_translation",
        derived_from_node_ids=("formula-disclose",),
        transformation_step="hammer.translate",
        transform_kind=LegalIRTransformationKind.HAMMER,
    )
    builder.add_derived_node(
        "receipt-disclose",
        node_kind="hammer_receipt",
        derived_from_node_ids=("translation-disclose",),
        transformation_step="hammer.reconstruct",
        transform_kind=LegalIRTransformationKind.HAMMER,
    )
    return builder.to_source_map()


def _translation() -> dict[str, object]:
    return {
        "artifact_sha256": "1" * 64,
        "artifact_size_bytes": 31,
        "input_formula_id": "formula-disclose",
        "obligation_id": "po-disclose",
        "schema_version": LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
        "success": True,
        "surface": "smt-lib",
        "target_format": "smt-lib",
        "translation_id": "translation-disclose",
    }


def _receipt() -> dict[str, object]:
    return {
        "backend": "z3",
        "backend_proved": True,
        "backend_statuses": {"z3": "proved"},
        "checker": "fake-lean-kernel",
        "input_formula_id": "formula-disclose",
        "native_reconstruction": True,
        "native_reconstruction_verified": True,
        "obligation_id": "po-disclose",
        "outcome": "native_reconstruction",
        "receipt_id": "receipt-disclose",
        "reconstruction_status": "verified",
        "schema_version": LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
        "translation_failed": False,
        "translation_record_ids": ["translation-disclose"],
        "translation_succeeded": True,
        "trust_reason": "native_reconstruction_verified",
        "trust_status": "trusted",
        "trusted": True,
    }


def _guidance(*, proved: bool = True, trusted: bool = True) -> HammerGuidanceArtifact:
    return HammerGuidanceArtifact(
        guidance_id="guidance-disclose",
        obligation_id="po-disclose",
        trusted=trusted,
        legal_ir_view="deontic.ir",
        logic_family="deontic",
        target_component="deontic.ir",
        goal_name="po-disclose",
        goal_statement_hash="2" * 64,
        proved=proved,
        proof_checked=True,
        backend_statuses={"z3": "proved" if proved else "unknown"},
        selected_premises=["premise-disclose"],
        reconstruction_status="verified" if proved else "",
        proof_obligation_ids=["po-disclose"],
        failure_reason="" if proved else "unknown",
        rejection_reasons=[] if proved else ["unknown"],
        schema_version=HAMMER_GUIDANCE_SCHEMA_VERSION,
    )


def _manifest(output_sha256: str):
    return build_legal_ir_build_manifest(
        sources={
            "doc-proof-carrying": {
                "source_id": "doc-proof-carrying",
                "text": SOURCE_TEXT,
                "schema_version": "legal-ir-source-document-v1",
            }
        },
        compiler_commit="compiler-commit-proof-carrying",
        passes=(
            LegalIRPassSpec(
                pass_id="legal_ir.test_emit",
                title="Emit LegalIR test views",
                kind=LegalIRPassKind.COMPILER,
                order=1,
                declared_inputs=("normalized_document",),
                declared_outputs=("legal_ir_outputs",),
            ),
        ),
        proof_tools={"lean": {"tool": "lean", "version": "4.12.0"}, "z3": "4.13.3"},
        outputs=(
            LegalIRBuildDigest(
                artifact_id="legal-ir-outputs",
                sha256=output_sha256,
                role="output",
                schema_version=LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION,
            ),
        ),
        metadata={"legal_ir_output_sha256": output_sha256},
    )


def _policy() -> LegalIRProofVerificationPolicy:
    return LegalIRProofVerificationPolicy(
        policy_id="strict-test-policy",
        require_trusted_proofs=True,
        require_native_reconstruction=True,
        require_native_reconstruction_verified=True,
        require_route_results=True,
        accepted_compiler_commits=("compiler-commit-proof-carrying",),
    )


def _artifact():
    output_sha = _stable_hash(LEGAL_IR_OUTPUTS)
    return build_legal_ir_proof_carrying_artifact(
        legal_ir_outputs=LEGAL_IR_OUTPUTS,
        proof_obligations=(_obligation(),),
        hammer_guidance_artifacts=(_guidance(),),
        translation_records=(_translation(),),
        reconstruction_receipts=(_receipt(),),
        route_results=(
            {
                "obligation_id": "po-disclose",
                "proved": True,
                "schema_version": "legal-ir-proof-router-v1",
                "status": "proved",
                "stop_reason": "trust_satisfied",
                "trust_satisfied": True,
            },
        ),
        unsupported_diagnostics=(
            {
                "backend": "tdfol",
                "feature": "counterexample",
                "message": "Counterexample extraction is delegated to CEC.",
                "reason_code": "counterexample_not_emitted_by_tdfol",
            },
        ),
        source_map=_source_map(),
        build_manifest=_manifest(output_sha),
        verification_policy=_policy(),
        metadata={"task_id": "PORTAL-LIR-HAMMER-095"},
    )


def test_artifact_packages_all_evidence_and_validates_for_consumers(tmp_path) -> None:
    artifact = _artifact()
    payload = artifact.to_dict()

    assert payload["schema_version"] == LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION
    assert payload["verification_policy"]["schema_version"] == (
        LEGAL_IR_PROOF_VERIFICATION_POLICY_SCHEMA_VERSION
    )
    assert payload["proof_obligations"][0]["obligation_id"] == "po-disclose"
    assert payload["hammer_guidance_artifacts"][0]["guidance_id"] == "guidance-disclose"
    assert payload["translation_records"][0]["translation_id"] == "translation-disclose"
    assert payload["reconstruction_receipts"][0]["receipt_id"] == "receipt-disclose"
    assert payload["unsupported_diagnostics"][0]["valid"] is True
    assert payload["source_map"]["source_map_id"] == "map-proof-carrying"
    assert payload["build_manifest"]["compiler_commit"] == "compiler-commit-proof-carrying"
    assert payload["evidence_bindings"][0]["proved"] is True
    assert payload["evidence_bindings"][0]["trusted"] is True
    assert payload["evidence_bindings"][0]["native_reconstruction_verified"] is True
    assert payload["evidence_bindings"][0]["source_traceable"] is True
    assert validate_legal_ir_proof_carrying_artifact(artifact).valid
    assert legal_ir_proof_carrying_artifact(
        legal_ir_outputs=LEGAL_IR_OUTPUTS,
        proof_obligations=(_obligation(),),
        hammer_guidance_artifacts=(_guidance(),),
        translation_records=(_translation(),),
        reconstruction_receipts=(_receipt(),),
        route_results=payload["route_results"],
        source_map=_source_map(),
        build_manifest=_manifest(_stable_hash(LEGAL_IR_OUTPUTS)),
        verification_policy=_policy(),
    )["legal_ir_output_sha256"] == payload["legal_ir_output_sha256"]

    path = tmp_path / "proof-carrying.json"
    save_legal_ir_proof_carrying_artifact(artifact, path)
    loaded = load_legal_ir_proof_carrying_artifact(path, validate=True)
    assert loaded.to_dict() == payload


def test_consumer_rejects_stale_payload_and_manifest_expectations() -> None:
    payload = _artifact().to_dict()
    payload["legal_ir_outputs"]["deontic"]["rule_ids"].append("rule-added-after-proof")

    result = validate_legal_ir_proof_carrying_artifact(
        payload,
        expected_build_manifest_sha256="0" * 64,
    )

    assert not result.valid
    assert {
        "legal_ir_output_sha256_mismatch",
        "package_sha256_mismatch",
        "stale_build_manifest",
    } <= {diagnostic.code for diagnostic in result.diagnostics}


def test_consumer_rejects_missing_receipts_translations_and_stale_bindings() -> None:
    payload = _artifact().to_dict()
    payload["translation_records"] = []
    payload["reconstruction_receipts"] = []

    result = validate_legal_ir_proof_carrying_artifact(payload)

    assert not result.valid
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "translation_record_missing" in codes
    assert "hammer_receipt_missing" in codes
    assert "native_reconstruction_missing" in codes
    assert "native_reconstruction_not_verified" in codes
    assert "stale_evidence_binding" in codes


def test_consumer_rejects_incompatible_and_failed_proof_evidence() -> None:
    payload = _artifact().to_dict()
    payload["hammer_guidance_artifacts"][0]["proved"] = False
    payload["hammer_guidance_artifacts"][0]["trusted"] = False
    payload["hammer_guidance_artifacts"][0]["failure_reason"] = "unknown"
    payload["hammer_guidance_artifacts"][0]["rejection_reasons"] = ["unknown"]
    payload["hammer_guidance_artifacts"][0]["reconstruction_status"] = ""
    payload["translation_records"][0]["schema_version"] = "legal-ir-hammer-translation-v0"
    payload["reconstruction_receipts"][0]["backend_proved"] = False
    payload["reconstruction_receipts"][0]["native_reconstruction"] = False
    payload["reconstruction_receipts"][0]["native_reconstruction_verified"] = False
    payload["reconstruction_receipts"][0]["trusted"] = False
    payload["reconstruction_receipts"][0]["reconstruction_status"] = ""
    payload["reconstruction_receipts"][0]["trust_reason"] = "backend_proof_missing"
    payload["route_results"][0]["proved"] = False
    payload["route_results"][0]["status"] = "unknown"
    payload["route_results"][0]["trust_satisfied"] = False

    result = validate_legal_ir_proof_carrying_artifact(payload)

    assert not result.valid
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "incompatible_component_schema_version" in codes
    assert "proof_failed" in codes
    assert "proof_not_trusted" in codes
    assert "reconstruction_status_missing" in codes
    with pytest.raises(LegalIRProofArtifactError):
        assert_legal_ir_proof_carrying_artifact_valid(payload)


def test_consumer_rejects_invalid_unsupported_diagnostics() -> None:
    payload = _artifact().to_dict()
    payload["unsupported_diagnostics"] = [
        {
            "backend": "tdfol",
            "feature": "tdfol",
            "obligation_ids": ["po-disclose"],
            "reason_code": "",
        }
    ]

    result = validate_legal_ir_proof_carrying_artifact(payload)

    assert not result.valid
    assert "invalid_unsupported_diagnostic" in {
        diagnostic.code for diagnostic in result.diagnostics
    }
