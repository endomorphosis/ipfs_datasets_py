"""Tests for Legal IR Hammer obligation coverage and counterexample minimization."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerPremise,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LegalIRHammerConfig,
    run_legal_ir_hammer,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer_coverage import (
    LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION,
    REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES,
    LegalIRHammerCoverageWaiver,
    build_legal_ir_hammer_coverage_report,
    coverage_report_from_hammer_report,
    minimize_verified_counterexample,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    LegalIRProofObligation,
    generate_legal_ir_proof_obligations,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrameLogic,
    ModalIRFrameLogicTriple,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _proved_backend(name: str = "z3"):
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend=name,
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="unsat",
            raw_output="unsat",
        )

    return CallableHammerBackendRunner(name, "smt-lib", _run)


def _unsupported_backend(name: str = "custom"):
    def _run(translation, timeout_seconds):
        raise AssertionError("unsupported translations must not reach a backend")

    return CallableHammerBackendRunner(name, "unsupported-format", _run)


def _document() -> ModalIRDocument:
    text = "The agency shall provide notice unless emergency conditions exist within 30 days."
    return ModalIRDocument(
        document_id="coverage-doc-1",
        source="unit",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="shall",
                    label="shall",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["agency", "notice"],
                    role="obligation",
                ),
                provenance=ModalIRProvenance(
                    source_id="coverage-doc-1",
                    start_char=0,
                    end_char=len(text),
                ),
                conditions=["within 30 days"],
                exceptions=["emergency conditions exist"],
            )
        ],
        frame_logic=ModalIRFrameLogic(
            triples=[
                ModalIRFrameLogicTriple(
                    subject="f1",
                    predicate="actor",
                    object="agency",
                )
            ]
        ),
    )


def test_hammer_report_includes_complete_contract_field_family_coverage_matrix() -> None:
    document = _document()
    obligations = generate_legal_ir_proof_obligations(document)
    report = run_legal_ir_hammer(
        document,
        obligations=obligations,
        config=LegalIRHammerConfig(max_premises=64, timeout_seconds=1, parallel_workers=1),
        backends=[_proved_backend()],
    )
    coverage = report.coverage_report

    assert coverage is not None
    assert coverage.schema_version == LEGAL_IR_HAMMER_COVERAGE_SCHEMA_VERSION
    assert coverage.promotion_allowed is True
    assert coverage.block_reasons == ()
    assert set(REQUIRED_LEGAL_IR_HAMMER_COVERAGE_FAMILIES) <= set(
        coverage.coverage_by_family
    )
    assert coverage.covered_family_count == coverage.required_family_count
    assert coverage.unsupported_translations
    assert coverage.promotion_allowed is True

    matrix = [cell.to_dict() for cell in coverage.matrix]
    assert all(cell["covered"] for cell in matrix if cell["has_obligation"])
    assert any(
        cell["contract_id"] == "legal-ir-view/deontic/v1"
        and cell["field_path"] == "operator"
        and cell["behavior_family"] == "well_formedness"
        and cell["has_executable_trusted_route"]
        for cell in matrix
    )
    assert any(
        cell["contract_id"] == "legal-ir-view/deontic/v1"
        and cell["field_path"] == "provenance_ids"
        and cell["behavior_family"] == "provenance"
        for cell in matrix
    )
    assert any(
        cell["behavior_family"] == "cross_view_consistency"
        and cell["obligation_family"] == "cross_view_deontic_preservation"
        for cell in matrix
    )
    assert report.to_dict()["metadata"]["coverage_promotion_allowed"] is True


def test_coverage_report_rebuilds_from_serialized_hammer_report_records() -> None:
    report = run_legal_ir_hammer(
        _document(),
        config=LegalIRHammerConfig(max_premises=64, timeout_seconds=1, parallel_workers=1),
        backends=[_proved_backend()],
    )

    rebuilt = coverage_report_from_hammer_report(report.to_dict())

    assert rebuilt.promotion_allowed is True
    assert rebuilt.obligation_count == report.obligation_count
    assert rebuilt.covered_family_count == rebuilt.required_family_count
    assert any(
        cell.behavior_family == "round_trip" and cell.has_executable_trusted_route
        for cell in rebuilt.matrix
    )
    assert all(
        "modal_formula_presence" not in obligation_id
        for cell in rebuilt.matrix
        for obligation_id in cell.obligation_ids
    )


def test_coverage_report_rebuild_prefers_report_obligations_over_source_document() -> None:
    document = _document()
    report = run_legal_ir_hammer(
        document,
        config=LegalIRHammerConfig(
            max_obligations=2,
            max_premises=32,
            timeout_seconds=1,
            parallel_workers=1,
        ),
        backends=[_proved_backend()],
    )

    rebuilt = coverage_report_from_hammer_report(
        report.to_dict(),
        sample_or_document=document,
        required_families=("well_formedness", "provenance"),
    )

    assert report.obligation_count == 2
    assert rebuilt.obligation_count == 2
    assert sum(cell.obligation_count for cell in rebuilt.matrix) == 2


def test_unsupported_translation_is_recorded_separately_and_blocks_promotion() -> None:
    obligation = LegalIRProofObligation(
        obligation_id="lir-obligation-unsupported-temporal",
        statement="temporal_conditions_have_event_order(f1)",
        kind="temporal_event_consistency",
        legal_ir_view="TDFOL.prover",
        logic_family="temporal",
        formula_id="f1",
        metadata={"obligation_family": "temporal_anchor"},
    )
    report = run_legal_ir_hammer(
        {"document_id": "unsupported-doc", "formulas": []},
        obligations=[obligation],
        premises=[HammerPremise("temporal_anchor", "temporal_conditions_have_event_order(f1)")],
        config=LegalIRHammerConfig(max_premises=4, timeout_seconds=1, parallel_workers=1),
        backends=[_unsupported_backend()],
    )
    coverage = coverage_report_from_hammer_report(
        report,
        obligations=[obligation],
        required_families=("temporal",),
    )

    assert coverage.promotion_allowed is False
    assert "required_family_without_trusted_route_or_waiver:temporal" in coverage.block_reasons
    assert coverage.unsupported_translations
    assert all(item.behavior_family == "temporal" for item in coverage.unsupported_translations)
    assert any(item.route == "smt_atp_portfolio" for item in coverage.unsupported_translations)
    assert any(item.translation_record_id for item in coverage.unsupported_translations)
    assert all(
        unsupported["reason"] != "backend_counterexample"
        for unsupported in coverage.to_dict()["unsupported_translations"]
    )


def test_approved_waiver_allows_promotion_when_required_family_route_is_absent() -> None:
    obligation = LegalIRProofObligation(
        obligation_id="lir-obligation-waived-graph",
        statement="kg_edge_typed(subject:a, predicate:rel, object:b)",
        kind="knowledge_graph_edge_typing",
        legal_ir_view="knowledge_graphs.neo4j_compat",
        logic_family="frame",
        formula_id="frame-triple-1",
        metadata={"obligation_family": "knowledge_graph_endpoint_typing"},
    )
    coverage = build_legal_ir_hammer_coverage_report(
        {"document_id": "waiver-doc"},
        obligations=[obligation],
        required_families=("graph",),
        waivers=[
            LegalIRHammerCoverageWaiver(
                waiver_id="waiver-graph-route-2026-07",
                behavior_family="graph",
                reason_code="native_graph_backend_temporarily_unavailable",
                approved_by="formal-verification-owner",
            )
        ],
    )

    assert coverage.promotion_allowed is True
    assert coverage.block_reasons == ()
    graph_cells = [cell for cell in coverage.matrix if cell.behavior_family == "graph"]
    assert graph_cells
    assert any(cell.waived for cell in graph_cells)


def test_counterexample_minimizer_preserves_verified_result_without_persisting_witness() -> None:
    counterexample = {
        "verified": True,
        "verifier": "deterministic_contract_validator",
        "counterexample_type": "contract_failure",
        "result": "contract_failure",
        "witness": {
            "failing_fields": ["operator", "conditions", "irrelevant"],
            "irrelevant_slot": "can_be_removed",
            "nested": {"needed": "operator", "noise": "remove_me"},
        },
        "debug_trace": ["drop", "all", "of", "this"],
    }

    def _verifier(candidate):
        witness = candidate.get("witness", {})
        fields = set(witness.get("failing_fields", ()))
        nested = witness.get("nested", {})
        if {"operator", "conditions"} <= fields and nested.get("needed") == "operator":
            return {"result": "contract_failure"}
        return {"result": "not_a_counterexample"}

    minimized = minimize_verified_counterexample(counterexample, verifier=_verifier)
    payload = minimized.to_dict()

    assert minimized.result_preserved is True
    assert minimized.changed is True
    assert minimized.minimized_size_bytes < minimized.original_size_bytes
    assert "debug_trace" in minimized.removed_paths
    assert payload["verified"] is True
    assert "can_be_removed" not in str(payload)
