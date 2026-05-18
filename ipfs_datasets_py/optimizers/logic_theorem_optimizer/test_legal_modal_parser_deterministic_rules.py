"""Deterministic parser regressions for citation-bound U.S. Code edge cases."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser import (  # noqa: E402
    LegalModalParser,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    ModalLogicFamily,
)


def _missing_modal_formula_count(result) -> int:
    return sum(
        1
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type == "missing_modal_formula"
    )


def _has_adaptive_explicit_pair(
    result,
    *,
    predicted_family: str,
    target_family: str,
) -> bool:
    return any(
        ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.metadata.get("predicted_family") == predicted_family
        and ambiguity.metadata.get("target_family") == target_family
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        for ambiguity in result.ambiguities
    )


def test_parser_recovers_article_prefixed_commission_heading() -> None:
    parser = LegalModalParser()

    modal_ir = parser.parse(
        "The Election Assistance Commission",
        document_id="us-code-2-121f-6dce78c9ec9c6d4b",
        citation="2 U.S.C. 121f",
    )

    assert len(modal_ir.formulas) == 1
    formula = modal_ir.formulas[0]
    assert formula.operator.family == ModalLogicFamily.FRAME.value
    assert formula.metadata.get("fallback_rule") == "uscode_heading_without_section_reference_v1"


def test_parser_recovers_terms_and_conditions_heading() -> None:
    parser = LegalModalParser()

    modal_ir = parser.parse(
        "The terms and conditions",
        document_id="us-code-16-820-e78ad24dbc049dea",
        citation="16 U.S.C. 820",
    )

    assert len(modal_ir.formulas) == 1
    formula = modal_ir.formulas[0]
    assert formula.operator.family == ModalLogicFamily.FRAME.value
    assert formula.metadata.get("fallback_rule") == "uscode_heading_without_section_reference_v1"


def test_parser_recovers_standalone_establishment_clause() -> None:
    parser = LegalModalParser()

    modal_ir = parser.parse(
        "There is established in the Department of Health and Human Services an office for policy coordination.",
        document_id="us-code-42-290aa-a8d1719e0c2a8388",
        citation="42 U.S.C. 290aa",
    )

    assert len(modal_ir.formulas) == 1
    formula = modal_ir.formulas[0]
    assert formula.operator.family == ModalLogicFamily.FRAME.value
    assert formula.metadata.get("fallback_rule") == "uscode_declarative_statement_v1"
    assert formula.metadata.get("statement_hint") == "establishment_clause"


def test_compiler_spacy_backend_no_longer_emits_missing_formula_for_regression_cases() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    cases = [
        (
            "us-code-2-121f-6dce78c9ec9c6d4b",
            "2 U.S.C. 121f",
            "The Election Assistance Commission",
        ),
        (
            "us-code-42-290aa-a8d1719e0c2a8388",
            "42 U.S.C. 290aa",
            "There is established in the Department of Health and Human Services an office for policy coordination.",
        ),
        (
            "us-code-16-820-e78ad24dbc049dea",
            "16 U.S.C. 820",
            "The terms and conditions",
        ),
    ]

    for document_id, citation, text in cases:
        result = compiler.compile(
            text,
            document_id=document_id,
            citation=citation,
        )
        assert result.modal_ir.formulas, document_id
        assert _missing_modal_formula_count(result) == 0, document_id


def test_compiler_emits_explicit_frame_to_conditional_and_temporal_adaptive_pairs() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    conditional_result = compiler.compile(
        "As provided in section 3, this authority applies.",
        document_id="compiler-ambiguity-frame-conditional",
    )
    assert _has_adaptive_explicit_pair(
        conditional_result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    )

    temporal_result = compiler.compile(
        "For the period beginning on January 1, 2030, this authority applies.",
        document_id="compiler-ambiguity-frame-temporal",
    )
    assert _has_adaptive_explicit_pair(
        temporal_result,
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.TEMPORAL.value,
    )


def test_compiler_emits_explicit_conditional_normative_to_epistemic_adaptive_pair() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "In the event that the Secretary determines eligibility, this authority applies.",
        document_id="compiler-ambiguity-conditional-epistemic",
    )
    assert _has_adaptive_explicit_pair(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.EPISTEMIC.value,
    )
