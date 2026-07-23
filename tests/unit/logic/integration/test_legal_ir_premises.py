"""Tests for Legal IR premise export."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    generate_legal_ir_proof_obligations,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_premises import (
    LEGAL_IR_PREMISE_LIBRARY_VERSION,
    default_legal_ir_premises,
    export_legal_ir_premises,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _document() -> ModalIRDocument:
    return ModalIRDocument(
        document_id="doc-1",
        source="unit",
        normalized_text="The agency shall provide notice unless emergency conditions exist.",
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
                    end_char=67,
                ),
                exceptions=["emergency conditions exist"],
            )
        ],
    )


def test_default_legal_ir_premises_have_selection_metadata() -> None:
    premises = default_legal_ir_premises()

    assert any(premise.name == "deontic_norm_polarity_supported" for premise in premises)
    assert all(
        premise.metadata["premise_library_version"] == LEGAL_IR_PREMISE_LIBRARY_VERSION
        for premise in premises
    )
    assert all(premise.metadata["legal_ir_view"] for premise in premises)


def test_export_legal_ir_premises_combines_document_obligation_and_registry_facts() -> None:
    document = _document()
    obligations = generate_legal_ir_proof_obligations(document)
    premises = export_legal_ir_premises(
        document,
        obligations=obligations,
        theorem_registry={
            "theorems": [
                {
                    "theorem_id": "t1",
                    "theorem_name": "notice_exception_scope",
                    "statement": "Exception clauses scope notice obligations.",
                    "legal_ir_view": "deontic.ir",
                    "logic_family": "conditional_normative",
                }
            ]
        },
    )
    names = {premise.name for premise in premises}

    assert "formula_fact_f1" in names
    assert "formula_exception_fact_f1" in names
    assert "compiler_candidate_fact_f1_tdfol_temporal_anchor" in names
    assert "compiler_candidate_fact_f1_dcec_happens" in names
    assert "compiler_candidate_fact_f1_flogic_frame_role" in names
    assert "compiler_candidate_fact_f1_deontic_obligation" in names
    assert "notice_exception_scope" in names
    assert any(name.startswith("obligation_context_lir-obligation-") for name in names)
    assert len(names) == len(premises)
    assert any(
        premise.metadata.get("source_module") == "legal_ir_theorem_registry"
        for premise in premises
    )
    formal_statements = {
        premise.statement
        for premise in premises
        if premise.metadata.get("premise_kind") == "compiler_candidate_fact"
    }
    assert "temporal_anchor(event:provide_notice, time:shall)" in formal_statements
    assert "happens(event:provide_notice, time:shall)" in formal_statements
    assert (
        "frame_role(frame:provide_notice, role:obligation, value:provide_notice)"
        in formal_statements
    )
