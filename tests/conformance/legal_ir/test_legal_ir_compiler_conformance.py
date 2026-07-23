"""End-to-end LegalIR compiler conformance release gate.

This suite intentionally composes the public compiler surfaces and the
productization gates built in PORTAL-LIR-HAMMER-084/095/096/097/098.  It is a
single, deterministic conformance gate for compile, proof, decompile, semantic
diff, diagnostics, reproducibility, external benchmark isolation, hard
negatives, source maps, backend conformance, and CLI/API behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    DEFAULT_LEGAL_IR_BACKEND_TARGETS,
    HAMMER_GUIDANCE_SCHEMA_VERSION,
    LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION,
    LEGAL_IR_COMPILER_API_SCHEMA_VERSION,
    LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
    LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION,
    LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION,
    LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION,
    LegalIRBackendFeature,
    LegalIRBackendTarget,
    LegalIRCompilerExitCode,
    LegalIRCompilerOptions,
    LegalIRPassKind,
    LegalIRPassSpec,
    LegalIRProofVerificationPolicy,
    LegalIRSourceMap,
    build_legal_ir_build_manifest,
    build_legal_ir_diagnostic_report,
    build_legal_ir_proof_carrying_artifact,
    compile_legal_ir,
    decompile_legal_ir,
    default_legal_ir_api_passes,
    diff_legal_ir,
    export_legal_ir_artifact,
    legal_ir_backend_capabilities_manifest,
    legal_ir_backend_conformance_gate,
    legal_ir_lsp_diagnostics,
    validate_legal_ir,
    validate_legal_ir_backend_conformance,
    validate_legal_ir_proof_carrying_artifact,
    validate_legal_ir_source_map,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    TRAINING_OPERATION,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_external_benchmark import (
    EXTERNAL_BENCHMARK_HARD_GUARDRAIL,
    EXTERNAL_EVALUATION_OPERATION,
    LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION,
    LegalIRExternalBenchmarkPolicyError,
    evaluate_external_legal_expert_benchmark,
    external_benchmark_split_manifest,
    load_external_expert_benchmark_packets,
    require_external_benchmark_evaluation_only,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
    SEMANTICS_CHANGING,
    TARGET_DETERMINISTIC_IR,
    TrustedNegativeCandidate,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
    HARD_NEGATIVE_FAMILIES,
    LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION,
    LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION,
    SOURCE_COPY_SPAN,
    VERIFIED_COUNTEREXAMPLE,
    build_legal_ir_hard_negative_curriculum,
    hard_negative_training_effect_gate,
)


ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "scripts" / "ops" / "legal_ir" / "legal_ir_compile.py"
REPORT = ROOT / "docs" / "implementation" / "reports" / "LEGAL_IR_COMPILER_CONFORMANCE_REPORT.md"
EXTERNAL_FIXTURE = ROOT / "tests" / "fixtures" / "legal_ir" / "external_expert_benchmark.jsonl"
SOURCE_TEXT = "The agency shall disclose records within 30 days."
SOURCE = {
    "citation": "42 U.S.C. 1983(a)",
    "raw_document": SOURCE_TEXT,
    "source_document_id": "doc-conformance",
}


REQUIRED_CAPABILITIES = (
    "compile",
    "proof-carrying artifacts",
    "decompile",
    "semantic diff",
    "diagnostics",
    "reproducibility",
    "external benchmark isolation",
    "hard negatives",
    "source maps",
    "backend conformance",
    "CLI/API behavior",
)


def _stable_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@pytest.fixture(scope="module")
def compiled_artifact() -> dict[str, Any]:
    result = compile_legal_ir(
        SOURCE,
        options=LegalIRCompilerOptions(include_lsp_diagnostics=True, max_workers=1),
    )
    payload = result.to_dict()
    assert payload["schema_version"] == LEGAL_IR_COMPILER_API_SCHEMA_VERSION
    assert payload["payload"]["schema_version"] == LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION
    assert payload["exit_code"] == LegalIRCompilerExitCode.OK.value
    assert payload["lsp_diagnostics"] == []
    return payload


@pytest.fixture(scope="module")
def proof_carrying_payload(compiled_artifact: dict[str, Any]) -> dict[str, Any]:
    compiled = compiled_artifact["payload"]["compiled"]
    proof_obligations = compiled["proof_obligations"]
    obligation = proof_obligations[0]
    obligation_id = obligation["obligation_id"]
    formula_id = obligation["formula_id"]
    legal_ir_outputs = compiled["legal_ir_outputs"]
    output_sha = _stable_hash(legal_ir_outputs)
    source_map = LegalIRSourceMap.from_dict(compiled["source_map"])

    manifest = build_legal_ir_build_manifest(
        sources={
            SOURCE["source_document_id"]: {
                "schema_version": "legal-ir-source-document-v1",
                "source_id": SOURCE["source_document_id"],
                "text": SOURCE_TEXT,
            }
        },
        compiler_commit="portal-lir-hammer-099-conformance",
        passes=default_legal_ir_api_passes(),
        proof_tools={"lean": "synthetic-kernel-checked", "z3": "synthetic-unsat"},
        outputs=(
            {
                "artifact_id": "legal-ir-conformance-output",
                "role": "output",
                "schema_version": LEGAL_IR_COMPILER_ARTIFACT_SCHEMA_VERSION,
                "sha256": output_sha,
            },
        ),
        metadata={"legal_ir_output_sha256": output_sha, "suite": "PORTAL-LIR-HAMMER-099"},
    )
    proof_artifact = build_legal_ir_proof_carrying_artifact(
        legal_ir_outputs=legal_ir_outputs,
        proof_obligations=proof_obligations,
        hammer_guidance_artifacts=(
            {
                "backend_statuses": {"z3": "proved"},
                "goal_name": obligation_id,
                "goal_statement_hash": _stable_hash(obligation["statement"]),
                "guidance_id": f"guidance-{obligation_id}",
                "legal_ir_view": obligation["legal_ir_view"],
                "logic_family": obligation["logic_family"],
                "obligation_id": obligation_id,
                "proof_checked": True,
                "proof_obligation_ids": [obligation_id],
                "proved": True,
                "reconstruction_status": "verified",
                "schema_version": HAMMER_GUIDANCE_SCHEMA_VERSION,
                "selected_premises": ["premise-disclosure-authority"],
                "target_component": obligation["legal_ir_view"],
                "trusted": True,
            },
        ),
        translation_records=(
            {
                "artifact_sha256": "1" * 64,
                "artifact_size_bytes": 51,
                "input_formula_id": formula_id,
                "obligation_id": obligation_id,
                "schema_version": LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
                "success": True,
                "surface": "smt-lib",
                "target_format": "smt-lib",
                "translation_id": f"translation-{obligation_id}",
            },
        ),
        reconstruction_receipts=(
            {
                "backend": "z3",
                "backend_proved": True,
                "backend_statuses": {"z3": "proved"},
                "checker": "synthetic-lean-kernel",
                "input_formula_id": formula_id,
                "native_reconstruction": True,
                "native_reconstruction_verified": True,
                "obligation_id": obligation_id,
                "outcome": "native_reconstruction",
                "receipt_id": f"receipt-{obligation_id}",
                "reconstruction_status": "verified",
                "schema_version": LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
                "translation_failed": False,
                "translation_record_ids": [f"translation-{obligation_id}"],
                "translation_succeeded": True,
                "trust_reason": "native_reconstruction_verified",
                "trust_status": "trusted",
                "trusted": True,
            },
        ),
        route_results=(
            {
                "obligation_id": obligation_id,
                "proved": True,
                "schema_version": "legal-ir-proof-router-v1",
                "status": "proved",
                "stop_reason": "trust_satisfied",
                "trust_satisfied": True,
            },
        ),
        source_map=source_map,
        build_manifest=manifest,
        verification_policy=LegalIRProofVerificationPolicy(
            policy_id="portal-lir-hammer-099-conformance",
            require_trusted_proofs=True,
            require_native_reconstruction=True,
            require_native_reconstruction_verified=True,
            require_route_results=True,
            accepted_compiler_commits=("portal-lir-hammer-099-conformance",),
        ),
        metadata={"task_id": "PORTAL-LIR-HAMMER-099"},
    )
    return proof_artifact.to_dict()


def test_compile_proof_decompile_diff_source_maps_and_reproducibility(
    compiled_artifact: dict[str, Any],
    proof_carrying_payload: dict[str, Any],
) -> None:
    compiled = compiled_artifact["payload"]["compiled"]
    source_map_payload = compiled_artifact["source_map"]

    assert compiled["proof_obligations"][0]["statement"] == SOURCE_TEXT
    assert compiled["legal_ir_outputs"]["deontic"]["obligation_ids"]
    assert source_map_payload["schema_version"] == LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION
    assert validate_legal_ir_source_map(source_map_payload).valid

    decompiled = decompile_legal_ir(compiled_artifact)
    assert decompiled.exit_code == LegalIRCompilerExitCode.OK.value
    assert decompiled.payload["decompiled_text"] == SOURCE_TEXT
    assert decompiled.payload["lossless"] is True

    proof_validation = validate_legal_ir_proof_carrying_artifact(proof_carrying_payload)
    assert proof_validation.valid, proof_validation.to_dict()
    exported = export_legal_ir_artifact(proof_carrying_payload)
    assert exported.exit_code == LegalIRCompilerExitCode.OK.value
    assert exported.payload["artifact_kind"] == "proof_carrying"
    assert exported.payload["artifact"]["schema_version"] == LEGAL_IR_PROOF_CARRYING_ARTIFACT_SCHEMA_VERSION

    modified = {
        "obligations": [
            *compiled["obligations"],
            {
                "conditions": ["denial issued"],
                "obligation_id": "obl-notice",
                "operator": "shall",
                "proof_status": {"status": "unknown"},
                "statement": "The agency shall notify requesters after denial.",
            },
        ]
    }
    semantic_diff = diff_legal_ir({"obligations": compiled["obligations"]}, modified)
    assert semantic_diff.exit_code == LegalIRCompilerExitCode.OK.value
    assert semantic_diff.payload["schema_version"] == LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION
    assert semantic_diff.payload["changed"] is True
    assert "obligation_added" in semantic_diff.payload["change_kinds"]

    repeat = compile_legal_ir(SOURCE).to_dict()
    assert repeat["metadata"]["compile_digest"] == compiled_artifact["metadata"]["compile_digest"]
    assert repeat["payload"]["deterministic_output_order"] == [
        "legal_ir.api.ingest",
        "legal_ir.api.lower",
        "legal_ir.api.explain",
    ]
    assert repeat["payload"]["compiled"] == compiled


def test_diagnostics_are_structured_lsp_ready_and_fail_closed(
    compiled_artifact: dict[str, Any],
) -> None:
    invalid = {
        "diagnostics": [
            {
                "diagnostic_type": "unresolved_symbol",
                "message": "Missing scoped agency definition.",
                "source_node_ids": [compiled_artifact["source_map"]["nodes"][0]["node_id"]],
            },
        ],
        "unsupported_diagnostics": [
            {
                "backend": "cec",
                "feature": "counterexample",
                "message": "CEC counterexample export is not available for this projection.",
                "reason_code": "counterexample_not_emitted_by_cec",
            }
        ],
        "source_map": compiled_artifact["source_map"],
    }

    report = build_legal_ir_diagnostic_report(invalid, source_map=compiled_artifact["source_map"])
    assert report.schema_version == LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION
    assert {"symbol", "unsupported_backend_feature"} <= set(report.families)
    assert report.error_count == 1
    assert report.warning_count == 1

    validation = validate_legal_ir(
        invalid,
        options=LegalIRCompilerOptions(include_lsp_diagnostics=True),
    )
    assert validation.exit_code == LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    lsp = legal_ir_lsp_diagnostics(validation)
    assert {item["source"] for item in lsp} == {"legal-ir-compiler"}
    assert {item["code"] for item in lsp} >= {
        "legal_ir.symbol.unresolved",
        "legal_ir.backend.unsupported_feature",
    }

    proof_readiness = export_legal_ir_artifact(compiled_artifact)
    assert proof_readiness.exit_code == LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    assert proof_readiness.payload["artifact_kind"] == "compiler_artifact"
    assert proof_readiness.payload["artifact"]["proof_ready"] is False
    assert proof_readiness.diagnostics.error_count


def test_external_benchmark_isolation_and_hard_negative_curriculum_gate() -> None:
    packets = load_external_expert_benchmark_packets(EXTERNAL_FIXTURE)
    manifest = external_benchmark_split_manifest(packets)
    assert manifest.guard_result().passed is True
    assert manifest.metadata["hard_guardrail"] == EXTERNAL_BENCHMARK_HARD_GUARDRAIL

    require_external_benchmark_evaluation_only(
        packets,
        operation=EXTERNAL_EVALUATION_OPERATION,
    )
    with pytest.raises(LegalIRExternalBenchmarkPolicyError):
        require_external_benchmark_evaluation_only(packets, operation=TRAINING_OPERATION)

    predictions = [
        {
            "candidate_ir": packet.reference_ir,
            "citations": [{"citation": citation.citation} for citation in packet.citations],
            "decompiled_text": packet.decompiler_expectations.expected_reading,
            "packet_id": packet.packet_id,
            "predicted_ir_families": list(packet.expected_ir_families),
            "proof_obligations": [
                {"obligation_id": obligation.obligation_id}
                for obligation in packet.proof_obligations
            ],
            "round_trip_success": True,
        }
        for packet in packets
    ]
    benchmark = evaluate_external_legal_expert_benchmark(
        packets,
        predictions,
        internal_canary_metrics={"canary_acceptance_rate": 0.25},
    )
    assert benchmark.schema_version == LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION
    assert benchmark.accepted is True
    assert benchmark.to_dict()["separate_from_internal_canary_metrics"] is True
    assert "canary_acceptance_rate" not in benchmark.to_dict()["external_validity"]

    source_record = {
        "citation": "5 U.S.C. 552",
        "reference_ir": {
            "citation": "5 U.S.C. 552",
            "rules": [
                {
                    "actor": "agency",
                    "action": "provide",
                    "exception": "emergency conditions exist",
                    "modality": "obligation",
                    "object": "notice",
                }
            ],
            "temporal": "within 30 days",
        },
        "sample_id": "lir-hard-negative-conformance",
        "semantic_family": "deontic",
        "text": "The agency shall provide notice unless emergency conditions exist within 30 days.",
        "trusted": True,
        "verification": {"verified": True, "verified_by": ["hammer_positive_obligation"]},
    }
    counterexample = TrustedNegativeCandidate(
        candidate_id="lir-hard-negative-conformance-counterexample",
        label="semantic_non_equivalence",
        minimal_counterexample={"rules": [{"modality": "permission", "object": "notice"}]},
        mutated_payload_sha256="sha256-mutated",
        relation=SEMANTICS_CHANGING,
        source_mutation_id="mutation-conformance",
        source_text_sha256="sha256-source",
        target=TARGET_DETERMINISTIC_IR,
        verification={
            "semantic_similarity": 0.42,
            "verified": True,
            "verified_by": ["metamorphic_metric_oracle", "hammer_obligation_delta"],
        },
    )
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[counterexample],
        source_records=[source_record],
        model_negatives=[
            {
                "candidate_ir": {"rules": [{"modality": "permission"}]},
                "negative_family": VERIFIED_COUNTEREXAMPLE,
                "reference_ir": source_record["reference_ir"],
                "sample_id": "unverified-model-negative",
                "trusted": False,
            }
        ],
    )
    assert curriculum.schema_version == LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION
    assert curriculum.ready_for_training is True
    assert set(curriculum.covered_negative_families) == set(HARD_NEGATIVE_FAMILIES)
    assert curriculum.by_family(SOURCE_COPY_SPAN)
    assert any(
        rejected.reason == "unverified_model_negative_not_training_label"
        for rejected in curriculum.rejected_candidates
    )

    baseline_scores = {example.example_id: 0.94 for example in curriculum.examples}
    trained_scores = {example.example_id: 0.25 for example in curriculum.examples}
    effect = hard_negative_training_effect_gate(
        curriculum,
        baseline_scores=baseline_scores,
        trained_scores=trained_scores,
        trusted_positive_obligations=[
            {
                "after_obligation_equivalence": 0.99,
                "before_obligation_equivalence": 1.0,
                "obligation_id": "trusted-positive-obligation",
                "trusted": True,
                "verification": {"proof_checked": True},
            }
        ],
    )
    assert effect["schema_version"] == LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION
    assert effect["accepted"] is True
    assert effect["hard_negative_guard_passed"] is True


def test_backend_conformance_gate_accepts_full_suite_and_blocks_hard_negatives() -> None:
    obligation_ids = ("po-deontic", "po-temporal", "po-kg")
    obligations = (
        {
            "kind": "deontic_polarity",
            "legal_ir_view": "deontic.ir",
            "logic_family": "deontic",
            "obligation_id": "po-deontic",
            "statement": "agency must provide notice",
        },
        {
            "kind": "temporal_event_consistency",
            "legal_ir_view": "TDFOL.prover",
            "logic_family": "temporal",
            "obligation_id": "po-temporal",
            "statement": "notice is due within 30 days",
        },
        {
            "kind": "knowledge_graph_edge_typing",
            "legal_ir_view": "knowledge_graphs.neo4j_compat",
            "logic_family": "frame",
            "obligation_id": "po-kg",
            "statement": "agency notice edge is typed",
        },
    )
    projections = {
        LegalIRBackendTarget.FRAME_LOGIC.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.FRAME_LOGIC.value: ["frame:f1|actor|agency"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
                LegalIRBackendFeature.PROVENANCE.value: ["prov:doc:0-42"],
            },
        },
        LegalIRBackendTarget.DEONTIC.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.DEONTIC.value: ["O(agency,provide_notice,within_30_days)"],
                LegalIRBackendFeature.EXCEPTION_SCOPE.value: ["unless:emergency"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
                LegalIRBackendFeature.PROVENANCE.value: ["prov:doc:0-42"],
            },
        },
        LegalIRBackendTarget.TDFOL.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.TDFOL.value: ["deadline(provide_notice,within_30_days)"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
            },
        },
        LegalIRBackendTarget.KG.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.KNOWLEDGE_GRAPH.value: ["agency|must_provide|notice"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
                LegalIRBackendFeature.PROVENANCE.value: ["prov:doc:0-42"],
            },
        },
        LegalIRBackendTarget.CEC.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.CEC.value: ["event:provide_notice_due_30"],
                LegalIRBackendFeature.COUNTEREXAMPLE.value: ["cex:none"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
            },
        },
        LegalIRBackendTarget.EXTERNAL_PROVER.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.COUNTEREXAMPLE.value: ["cex:none"],
                LegalIRBackendFeature.EXTERNAL_PROOF.value: ["proof:unsat:all"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
            },
        },
        LegalIRBackendTarget.DECOMPILER.value: {
            "proof_obligation_ids": obligation_ids,
            "semantics": {
                LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value: ["round_trip:preserved"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_ids,
                LegalIRBackendFeature.PROVENANCE.value: ["prov:doc:0-42"],
            },
        },
    }

    manifest = legal_ir_backend_capabilities_manifest()
    assert manifest["schema_version"] == LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION
    assert manifest["backend_targets"] == list(DEFAULT_LEGAL_IR_BACKEND_TARGETS)

    report = validate_legal_ir_backend_conformance(projections, obligations=obligations)
    assert report.promotion_allowed is True, report.to_dict()
    assert report.coverage_by_feature["obligation_preservation"].covered is True

    blocked = dict(projections)
    blocked["decompiler"] = {
        "proof_obligation_ids": ["po-deontic", "po-temporal"],
        "semantics": {
            LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value: ["round_trip:preserved"],
            LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: ["po-deontic", "po-temporal"],
            LegalIRBackendFeature.PROVENANCE.value: ["prov:doc:0-42"],
        },
    }
    hard_negative = legal_ir_backend_conformance_gate(blocked, obligations=obligations)
    assert hard_negative["promotion_allowed"] is False
    assert "silent_obligation_drop:decompiler:obligation_preservation:po-kg" in hard_negative["block_reasons"]


def test_cli_and_api_surfaces_have_identical_json_contracts(
    tmp_path: Path,
    compiled_artifact: dict[str, Any],
) -> None:
    source_path = tmp_path / "source.json"
    output_path = tmp_path / "compiled.json"
    source_path.write_text(json.dumps(SOURCE), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "compile",
            "--input",
            str(source_path),
            "--output",
            str(output_path),
            "--lsp",
            "--compact",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == LegalIRCompilerExitCode.OK.value, completed.stderr
    cli_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert cli_payload["schema_version"] == LEGAL_IR_COMPILER_API_SCHEMA_VERSION
    assert cli_payload["operation"] == "compile"
    assert cli_payload["payload"]["compiled"] == compiled_artifact["payload"]["compiled"]
    assert cli_payload["metadata"]["compile_digest"] == compiled_artifact["metadata"]["compile_digest"]

    validation_path = tmp_path / "validation.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "validate",
            "--input",
            str(output_path),
            "--output",
            str(validation_path),
            "--compact",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == LegalIRCompilerExitCode.OK.value, completed.stderr
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["payload"]["valid"] is True
    assert validation["payload"]["source_map_validation"]["valid"] is True

    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps({"obligations": []}), encoding="utf-8")
    after_path.write_text(
        json.dumps({"obligations": compiled_artifact["payload"]["compiled"]["obligations"]}),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "diff",
            "--before",
            str(before_path),
            "--after",
            str(after_path),
            "--compact",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    diff_payload = json.loads(completed.stdout)
    assert completed.returncode == LegalIRCompilerExitCode.OK.value
    assert diff_payload["payload"]["changed"] is True
    assert diff_payload["payload"]["schema_version"] == LEGAL_IR_SEMANTIC_DIFF_SCHEMA_VERSION


def test_conformance_report_publishes_capability_matrix() -> None:
    text = REPORT.read_text(encoding="utf-8")

    assert "PORTAL-LIR-HAMMER-099" in text
    assert "Required Capabilities" in text
    assert "Optional Capabilities" in text
    assert "Unsupported Capabilities" in text
    assert "Failed Capabilities" in text
    for capability in REQUIRED_CAPABILITIES:
        assert capability in text
    assert "No failed capabilities are recorded" in text
    assert "python -m pytest tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py -q" in text


def test_conformance_suite_rejects_untracked_pass_mutation() -> None:
    source_map_pass = LegalIRPassSpec(
        pass_id="legal_ir.conformance.bad_source_map_mutation",
        title="Bad source map mutation",
        kind=LegalIRPassKind.COMPILER,
        order=5,
        declared_inputs=("raw_document",),
        declared_outputs=("source_map",),
    )
    result = compile_legal_ir(SOURCE, passes=(source_map_pass,), pass_functions={})

    assert result.exit_code == LegalIRCompilerExitCode.DIAGNOSTIC_ERROR.value
    assert result.diagnostics.error_count >= 1
    diagnostics = [diagnostic.to_dict() for diagnostic in result.diagnostics.diagnostics]
    assert any(
        "protected_output_requires_proof_or_diagnostic" in diagnostic["message"]
        and "source_map" in diagnostic["message"]
        for diagnostic in diagnostics
    )
