"""Tests for LegalIR backend conformance promotion gates."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning import (
    DEFAULT_LEGAL_IR_BACKEND_TARGETS,
    LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION,
    LegalIRBackendConformanceConfig,
    LegalIRBackendConformanceDiagnosticType,
    LegalIRBackendFeature,
    LegalIRBackendTarget,
    LegalIRBackendUnsupportedDiagnostic,
    LegalIRProofObligation,
    legal_ir_backend_capabilities_manifest,
    legal_ir_backend_conformance_gate,
    validate_legal_ir_backend_conformance,
)


OBLIGATION_IDS = ("po-deontic", "po-temporal", "po-kg")


def _obligations() -> tuple[LegalIRProofObligation, ...]:
    return (
        LegalIRProofObligation(
            obligation_id="po-deontic",
            statement="agency must provide notice",
            kind="deontic_polarity",
            legal_ir_view="deontic.ir",
            logic_family="deontic",
        ),
        LegalIRProofObligation(
            obligation_id="po-temporal",
            statement="notice is due within 30 days",
            kind="temporal_event_consistency",
            legal_ir_view="TDFOL.prover",
            logic_family="temporal",
        ),
        LegalIRProofObligation(
            obligation_id="po-kg",
            statement="agency notice edge is typed",
            kind="knowledge_graph_edge_typing",
            legal_ir_view="knowledge_graphs.neo4j_compat",
            logic_family="frame",
        ),
    )


def _full_projection_payloads() -> dict[str, dict[str, object]]:
    obligation_semantics = list(OBLIGATION_IDS)
    provenance = ["prov:doc-1:span-0-42"]
    return {
        LegalIRBackendTarget.FRAME_LOGIC.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.FRAME_LOGIC.value: ["frame:f1|actor|agency"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
                LegalIRBackendFeature.PROVENANCE.value: provenance,
            },
        },
        LegalIRBackendTarget.DEONTIC.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.DEONTIC.value: [
                    "O(agency,provide_notice,within_30_days)"
                ],
                LegalIRBackendFeature.EXCEPTION_SCOPE.value: ["unless:emergency"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
                LegalIRBackendFeature.PROVENANCE.value: provenance,
            },
        },
        LegalIRBackendTarget.TDFOL.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.TDFOL.value: [
                    "deadline(provide_notice,within_30_days)"
                ],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
            },
        },
        LegalIRBackendTarget.KG.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.KNOWLEDGE_GRAPH.value: [
                    "agency|must_provide|notice"
                ],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
                LegalIRBackendFeature.PROVENANCE.value: provenance,
            },
        },
        LegalIRBackendTarget.CEC.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.CEC.value: ["event:provide_notice_due_30"],
                LegalIRBackendFeature.COUNTEREXAMPLE.value: ["cex:none"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
            },
        },
        LegalIRBackendTarget.EXTERNAL_PROVER.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.EXTERNAL_PROOF.value: ["proof:unsat:all"],
                LegalIRBackendFeature.COUNTEREXAMPLE.value: ["cex:none"],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
            },
        },
        LegalIRBackendTarget.DECOMPILER.value: {
            "proof_obligation_ids": obligation_semantics,
            "semantics": {
                LegalIRBackendFeature.DECOMPILER_ROUND_TRIP.value: [
                    "round_trip:preserved"
                ],
                LegalIRBackendFeature.OBLIGATION_PRESERVATION.value: obligation_semantics,
                LegalIRBackendFeature.PROVENANCE.value: provenance,
            },
        },
    }


def test_backend_conformance_accepts_full_suite_with_shared_obligation_semantics() -> None:
    report = validate_legal_ir_backend_conformance(
        _full_projection_payloads(),
        obligations=_obligations(),
    )
    payload = report.to_dict()

    assert report.schema_version == LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION
    assert report.promotion_allowed is True, payload
    assert report.block_reasons == ()
    assert payload["hard_promotion_gate"] is True
    assert set(payload["projections"]) == set(DEFAULT_LEGAL_IR_BACKEND_TARGETS)
    assert payload["coverage_by_feature"]["obligation_preservation"]["covered"] is True
    assert payload["coverage_by_feature"]["obligation_preservation"][
        "supporting_backend_count"
    ] == len(DEFAULT_LEGAL_IR_BACKEND_TARGETS)
    assert payload["coverage_by_feature"]["deontic"]["emitted_backends"] == [
        "deontic"
    ]


def test_backend_capability_manifest_records_all_required_targets_and_features() -> None:
    manifest = legal_ir_backend_capabilities_manifest()

    assert manifest["schema_version"] == LEGAL_IR_BACKEND_CONFORMANCE_SCHEMA_VERSION
    assert manifest["backend_targets"] == list(DEFAULT_LEGAL_IR_BACKEND_TARGETS)
    assert set(manifest["features"]) >= {
        "frame_logic",
        "deontic",
        "tdfol",
        "knowledge_graph",
        "cec",
        "external_proof",
        "decompiler_round_trip",
        "obligation_preservation",
    }
    assert set(manifest["capabilities"]["external_prover"]) >= {
        "external_proof",
        "obligation_preservation",
    }


def test_typed_unsupported_diagnostic_prevents_silent_drop_block() -> None:
    payloads = _full_projection_payloads()
    payloads["tdfol"] = {
        "proof_obligation_ids": ["po-deontic", "po-temporal"],
        "semantics": {
            "tdfol": ["deadline(provide_notice,within_30_days)"],
            "obligation_preservation": ["po-deontic", "po-temporal"],
        },
        "unsupported_diagnostics": [
            LegalIRBackendUnsupportedDiagnostic(
                backend="tdfol",
                feature="obligation_preservation",
                reason_code="kg_edge_not_expressible_in_tdfol",
                obligation_ids=("po-kg",),
            ).to_dict()
        ],
    }

    report = validate_legal_ir_backend_conformance(
        payloads,
        obligations=_obligations(),
    )

    assert report.promotion_allowed is True, report.to_dict()
    tdfol_coverage = report.coverage_by_feature["obligation_preservation"].to_dict()
    assert "tdfol" in tdfol_coverage["unsupported_backends"]
    assert all(
        diagnostic.code != LegalIRBackendConformanceDiagnosticType.SILENT_OBLIGATION_DROP.value
        for diagnostic in report.diagnostics
    )


def test_silent_obligation_drop_blocks_promotion() -> None:
    payloads = _full_projection_payloads()
    payloads["decompiler"] = {
        "proof_obligation_ids": ["po-deontic", "po-temporal"],
        "semantics": {
            "decompiler_round_trip": ["round_trip:preserved"],
            "obligation_preservation": ["po-deontic", "po-temporal"],
            "provenance": ["prov:doc-1:span-0-42"],
        },
    }

    report = validate_legal_ir_backend_conformance(
        payloads,
        obligations=_obligations(),
    )

    assert report.promotion_allowed is False
    assert any(
        reason == "silent_obligation_drop:decompiler:obligation_preservation:po-kg"
        for reason in report.block_reasons
    )
    coverage = report.coverage_by_feature["obligation_preservation"].to_dict()
    assert coverage["missing_obligation_ids_by_backend"]["decompiler"] == ["po-kg"]


def test_shared_semantic_divergence_blocks_promotion() -> None:
    payloads = _full_projection_payloads()
    payloads["external_prover"]["semantics"]["counterexample"] = ["cex:notice_false"]

    report = validate_legal_ir_backend_conformance(
        payloads,
        obligations=_obligations(),
    )

    assert report.promotion_allowed is False
    assert any(
        reason == "shared_semantics_mismatch:cec:external_prover:counterexample"
        for reason in report.block_reasons
    )
    counterexample = report.coverage_by_feature["counterexample"].to_dict()
    assert counterexample["mismatch_backend_pairs"] == [["cec", "external_prover"]]


def test_dictionary_gate_reports_missing_required_backend_and_can_scope_policy() -> None:
    partial = {"deontic": _full_projection_payloads()["deontic"]}
    blocked = legal_ir_backend_conformance_gate(partial, obligations=_obligations())

    assert blocked["promotion_allowed"] is False
    assert "missing_backend:frame_logic" in blocked["block_reasons"]

    scoped = legal_ir_backend_conformance_gate(
        partial,
        obligations=_obligations(),
        config=LegalIRBackendConformanceConfig(
            required_backends=("deontic",),
            required_features=("deontic", "exception_scope", "obligation_preservation", "provenance"),
        ),
    )

    assert scoped["promotion_allowed"] is True, scoped
