"""Focused tests for judicial disposition formula normalization."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_records,
)
from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_normative_elements,
)


def test_judicial_disposition_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall enter a judgment on the claim.",
            "enter a judgment on the claim",
            "O(∀x (Clerk(x) → AdjudicateClaim(x)))",
            "EnterJudgmentClaim",
        ),
        (
            "The Court shall issue an order of dismissal.",
            "issue an order of dismissal",
            "O(∀x (Court(x) → Dismiss(x)))",
            "IssueOrderDismissal",
        ),
        (
            "The officer shall record a disposition of the appeal.",
            "record a disposition of the appeal",
            "O(∀x (Officer(x) → DisposeAppeal(x)))",
            "RecordDispositionAppeal",
        ),
        (
            "The judge shall make a finding of probable cause.",
            "make a finding of probable cause",
            "O(∀x (Judge(x) → FindProbableCause(x)))",
            "MakeFindingProbableCause",
        ),
        (
            "The board shall render a decision on the application.",
            "render a decision on the application",
            "O(∀x (Board(x) → DecideApplication(x)))",
            "RenderDecisionApplication",
        ),
    ]

    norms = []
    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        report = validate_ir_with_provers(norm)
        action_span = element["field_spans"]["action"]
        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["included_formula_slots"] == ["actor", "modality", "action"]
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        "judicial_disposition_duty",
        "judicial_disposition_duty",
        "judicial_disposition_duty",
        "judicial_disposition_duty",
        "judicial_disposition_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Clerk(x) → AdjudicateClaim(x)))",
        "O(∀x (Court(x) → Dismiss(x)))",
        "O(∀x (Officer(x) → DisposeAppeal(x)))",
        "O(∀x (Judge(x) → FindProbableCause(x)))",
        "O(∀x (Board(x) → DecideApplication(x)))",
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


def test_judicial_disposition_slice_preserves_unresolved_numbered_exception_gate():
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
