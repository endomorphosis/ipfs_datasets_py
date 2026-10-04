"""Baseline modal-family coverage for the legal parser roadmap.

These tests intentionally separate what works today from the modal-parser work
still planned in ``MODAL_LEGAL_PARSER_IMPROVEMENT_PLAN.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_translation import (
    FormulaFormalism,
    TDFOLFormulaTranslator,
    UnifiedFormulaTranslator,
)


@dataclass(frozen=True)
class ModalFamilyCase:
    family: str
    text: str
    expected_formalism: FormulaFormalism


DEONTIC_CASES = [
    ModalFamilyCase(
        family="deontic_obligation",
        text="The agency must provide written notice before termination.",
        expected_formalism=FormulaFormalism.TDFOL,
    ),
    ModalFamilyCase(
        family="deontic_permission",
        text="The applicant may request a hearing within 30 days.",
        expected_formalism=FormulaFormalism.TDFOL,
    ),
    ModalFamilyCase(
        family="deontic_prohibition",
        text="The contractor is prohibited from disclosing confidential records.",
        expected_formalism=FormulaFormalism.TDFOL,
    ),
]


PENDING_MODAL_CASES = [
    ModalFamilyCase(
        family="alethic",
        text="It is legally necessary that the filing be signed.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
    ModalFamilyCase(
        family="temporal",
        text="The permit expires after the agency issues a final order.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
    ModalFamilyCase(
        family="epistemic",
        text="The secretary finds that the applicant knew of the violation.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
    ModalFamilyCase(
        family="doxastic",
        text="The officer reasonably believes that the person intends to flee.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
    ModalFamilyCase(
        family="dynamic_action",
        text="If the tenant files an appeal, the court stays enforcement.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
    ModalFamilyCase(
        family="conditional_normative",
        text="Unless the agency grants an exception, the applicant must reapply.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
    ModalFamilyCase(
        family="frame",
        text="A housing voucher is a benefit administered by the public housing agency.",
        expected_formalism=FormulaFormalism.MODAL,
    ),
]


@pytest.mark.parametrize("case", DEONTIC_CASES, ids=lambda case: case.family)
def test_deontic_baseline_translates_without_llm(case: ModalFamilyCase) -> None:
    translator = TDFOLFormulaTranslator()
    translator.reasoner_available = True
    translator.reasoner = type("NoopReasoner", (), {"parse": lambda *_args, **_kwargs: None})()

    result = translator.translate_to_tdfol(case.text, context={"domain": "legal"})

    assert result.success is True
    assert result.formalism == case.expected_formalism
    assert result.formula is not None
    assert result.metadata["parser"] == "neurosymbolic"


@pytest.mark.parametrize("case", DEONTIC_CASES, ids=lambda case: case.family)
def test_deontic_baseline_auto_detects_tdfol(case: ModalFamilyCase) -> None:
    translator = UnifiedFormulaTranslator()

    assert translator._detect_formalism(case.text) == case.expected_formalism


@pytest.mark.xfail(
    reason="Pending modal registry/parser: non-deontic modal families still collapse to generic TDFOL/default handling.",
    strict=False,
)
@pytest.mark.parametrize("case", PENDING_MODAL_CASES, ids=lambda case: case.family)
def test_pending_non_deontic_modal_families_need_explicit_profiles(case: ModalFamilyCase) -> None:
    translator = UnifiedFormulaTranslator()

    assert translator._detect_formalism(case.text) == case.expected_formalism
