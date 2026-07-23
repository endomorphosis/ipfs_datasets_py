"""Focused tests for accessibility and accommodation formula normalization."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_records,
)
from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_accessibility_and_accommodation_duties_export_operative_predicates():
    examples = [
        (
            "The agency shall make a reasonable accommodation for the applicant.",
            "make a reasonable accommodation for the applicant",
            [17, 66],
            "O(∀x (Agency(x) → AccommodateApplicant(x)))",
            "MakeReasonableAccommodationApplicant",
        ),
        (
            "The department shall provide auxiliary aids for the participant.",
            "provide auxiliary aids for the participant",
            [21, 63],
            "O(∀x (Department(x) → ProvideAuxiliaryAidParticipant(x)))",
            "ProvideAuxiliaryAidsParticipant",
        ),
        (
            "The Bureau shall make accessibility modifications to the entrance.",
            "make accessibility modifications to the entrance",
            [17, 65],
            "O(∀x (Bureau(x) → ModifyAccessibilityEntrance(x)))",
            "MakeAccessibilityModificationsEntrance",
        ),
        (
            "The office shall prepare a language access plan for the program.",
            "prepare a language access plan for the program",
            [17, 63],
            "O(∀x (Office(x) → PlanLanguageAccessProgram(x)))",
            "PrepareLanguageAccessPlanProgram",
        ),
        (
            "The Clerk shall provide accessible formats for the notices.",
            "provide accessible formats for the notices",
            [16, 58],
            "O(∀x (Clerk(x) → FormatAccessiblyNotices(x)))",
            "ProvideAccessibleFormatsNotices",
        ),
        (
            "The court shall provide sign language interpretation for the hearing.",
            "provide sign language interpretation for the hearing",
            [16, 68],
            "O(∀x (Court(x) → InterpretSignLanguageHearing(x)))",
            "ProvideSignLanguageInterpretationHearing",
        ),
    ]

    norms = []
    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert element["text"][action_span[0] : action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        "accessibility_accommodation_duty",
        "accessibility_accommodation_duty",
        "accessibility_accommodation_duty",
        "accessibility_accommodation_duty",
        "accessibility_accommodation_duty",
        "accessibility_accommodation_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, _, expected_formula, _ in examples
    ]
    assert all(
        record["checked_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(
        record["grounded_slots"] == ["actor", "modality", "action"]
        for record in capability_records
    )
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_accessibility_slice_preserves_unresolved_numbered_exception_repair_gate():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    blocked_norm = LegalNormIR.from_parser_element(blocked)
    blocked_record = build_deontic_formula_record_from_ir(blocked_norm)

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert blocked_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert blocked_record["proof_ready"] is False
    assert blocked_record["requires_validation"] is True
    assert blocked_record["repair_required"] is True
    assert blocked_record["deterministic_resolution"] == {}
    assert "cross_reference_requires_resolution" in blocked_record["blockers"]
    assert "exception_requires_scope_review" in blocked_record["blockers"]
