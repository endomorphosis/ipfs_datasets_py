"""Tests for deterministic Legal IR proof obligations."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
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


def _document() -> ModalIRDocument:
    text = "The agency shall provide notice unless emergency conditions exist within 30 days."
    return ModalIRDocument(
        document_id="doc-1",
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
                    source_id="doc-1",
                    start_char=0,
                    end_char=len(text),
                    citation="1 U.S.C. 1",
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


def test_generate_legal_ir_obligations_covers_all_core_view_families() -> None:
    obligations = generate_legal_ir_proof_obligations(_document())
    kinds = {obligation.kind for obligation in obligations}
    statements = "\n".join(obligation.statement for obligation in obligations)

    assert {
        "modal_well_formedness",
        "provenance_preservation",
        "deontic_polarity",
        "exception_scope_precedence",
        "temporal_event_consistency",
        "decompiler_round_trip_signature",
        "knowledge_graph_edge_typing",
    } <= kinds
    assert {obligation.schema_version for obligation in obligations} == {
        LEGAL_IR_OBLIGATION_SCHEMA_VERSION
    }
    assert "The agency shall provide notice" not in statements
    assert all(obligation.obligation_id.startswith("lir-obligation-") for obligation in obligations)
    assert any(obligation.legal_ir_view == "deontic.ir" for obligation in obligations)
    assert any(obligation.legal_ir_view == "TDFOL.prover" for obligation in obligations)
    assert any(obligation.legal_ir_view == "knowledge_graphs.neo4j_compat" for obligation in obligations)


def test_generate_legal_ir_obligations_is_stable() -> None:
    first = [obligation.to_dict() for obligation in generate_legal_ir_proof_obligations(_document())]
    second = [obligation.to_dict() for obligation in generate_legal_ir_proof_obligations(_document())]

    assert first == second


def test_generate_legal_ir_obligations_reports_empty_formula_documents() -> None:
    document = ModalIRDocument(
        document_id="empty",
        source="unit",
        normalized_text="No modal cues here.",
    )

    obligations = generate_legal_ir_proof_obligations(document)

    assert len(obligations) == 1
    assert obligations[0].kind == "modal_formula_presence"
    assert obligations[0].legal_ir_view == "modal.frame_logic"
