"""Tests for modal IR canonical serialization."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrame,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _formula(formula_id: str = "f1") -> ModalIRFormula:
    return ModalIRFormula(
        formula_id=formula_id,
        operator=ModalIROperator(
            family="deontic",
            system="D",
            symbol="O",
            label="obligation",
        ),
        predicate=ModalIRPredicate(
            name="provide_notice",
            arguments=["agency", "applicant"],
            role="duty",
        ),
        provenance=ModalIRProvenance(
            source_id="us-code-title-5-section-1",
            start_char=4,
            end_char=42,
            citation="5 U.S.C. 1",
        ),
        conditions=["within_30_days"],
        exceptions=["unless_waived"],
        metadata={"clause_role": "rule"},
    )


def test_modal_ir_document_serializes_to_stable_json() -> None:
    document = ModalIRDocument(
        document_id="sample-1",
        source="us_code",
        normalized_text="The agency must provide notice.",
        formulas=[_formula()],
        frame_candidates=[
            ModalIRFrame(
                frame_id="administrative_notice",
                score=2.5,
                matched_terms=["notice", "agency"],
                explanation="Matched notice and agency cues.",
            )
        ],
        metadata={"title": "5", "section": "1"},
    )

    rendered = document.to_json()
    parsed = json.loads(rendered)

    assert parsed["document_id"] == "sample-1"
    assert parsed["formulas"][0]["operator"]["family"] == "deontic"
    assert parsed["frame_candidates"][0]["matched_terms"] == ["agency", "notice"]
    assert rendered == document.to_json()


def test_modal_ir_hash_is_independent_of_input_order_for_sorted_fields() -> None:
    first = ModalIRDocument(
        document_id="sample-1",
        source="us_code",
        normalized_text="The agency must provide notice.",
        formulas=[_formula("f2"), _formula("f1")],
        frame_candidates=[
            ModalIRFrame(frame_id="b", score=0.5, matched_terms=["z", "a"]),
            ModalIRFrame(frame_id="a", score=0.8, matched_terms=["notice"]),
        ],
    )
    second = ModalIRDocument(
        document_id="sample-1",
        source="us_code",
        normalized_text="The agency must provide notice.",
        formulas=[_formula("f1"), _formula("f2")],
        frame_candidates=[
            ModalIRFrame(frame_id="a", score=0.8, matched_terms=["notice"]),
            ModalIRFrame(frame_id="b", score=0.5, matched_terms=["a", "z"]),
        ],
    )

    assert first.to_json() == second.to_json()
    assert first.canonical_hash() == second.canonical_hash()
