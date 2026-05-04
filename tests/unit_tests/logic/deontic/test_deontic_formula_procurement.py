"""Focused tests for procurement and award formula normalization."""

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_records,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_procurement_solicitation_award_duties_export_operative_predicates():
    examples = [
        (
            "The Bureau shall conduct procurement of the supplies.",
            "conduct procurement of the supplies",
            "O(∀x (Bureau(x) → ProcureSupplies(x)))",
            "ConductProcurementSupplies",
        ),
        (
            "The Clerk shall issue a solicitation for the bids.",
            "issue a solicitation for the bids",
            "O(∀x (Clerk(x) → SolicitBids(x)))",
            "IssueSolicitationBids",
        ),
        (
            "The Director shall make an award of the contract.",
            "make an award of the contract",
            "O(∀x (Director(x) → AwardContract(x)))",
            "MakeAwardContract",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        action_span = element["field_spans"]["action"]

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False


def test_procurement_selection_opening_and_administration_export_operative_predicates():
    examples = [
        (
            "The Board shall make a selection of the vendor.",
            "make a selection of the vendor",
            "O(∀x (Board(x) → SelectVendor(x)))",
            "MakeSelectionVendor",
        ),
        (
            "The Bureau shall conduct bid opening for the proposals.",
            "conduct bid opening for the proposals",
            "O(∀x (Bureau(x) → OpenProposals(x)))",
            "ConductBidOpeningProposals",
        ),
        (
            "The Officer shall perform contract administration of the agreement.",
            "perform contract administration of the agreement",
            "O(∀x (Officer(x) → AdministerAgreement(x)))",
            "PerformContractAdministrationAgreement",
        ),
    ]

    norms = []
    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        action_span = element["field_spans"]["action"]
        report = validate_ir_with_provers(norm)

        norms.append(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["text"][action_span[0]:action_span[1]] == action
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
        "procurement_contracting_duty",
        "procurement_contracting_duty",
        "procurement_contracting_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Board(x) → SelectVendor(x)))",
        "O(∀x (Bureau(x) → OpenProposals(x)))",
        "O(∀x (Officer(x) → AdministerAgreement(x)))",
    ]
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_procurement_slice_preserves_unresolved_numbered_exception_repair_gate():
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


def test_rulemaking_enactment_amendment_and_repeal_export_operative_predicates():
    examples = [
        (
            "The Commission shall initiate rulemaking for the safety standard.",
            "initiate rulemaking for the safety standard",
            "O(∀x (Commission(x) → MakeRuleSafetyStandard(x)))",
            "InitiateRulemakingSafetyStandard",
        ),
        (
            "The Council shall approve enactment of the ordinance.",
            "approve enactment of the ordinance",
            "O(∀x (Council(x) → EnactOrdinance(x)))",
            "ApproveEnactmentOrdinance",
        ),
        (
            "The Board shall adopt an amendment to the rule.",
            "adopt an amendment to the rule",
            "O(∀x (Board(x) → AmendRule(x)))",
            "AdoptAmendmentRule",
        ),
        (
            "The Council shall effectuate a repeal of the regulation.",
            "effectuate a repeal of the regulation",
            "O(∀x (Council(x) → RepealRegulation(x)))",
            "EffectuateRepealRegulation",
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
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False
        assert report.syntax_valid is True
        assert report.proof_ready is True
        assert report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        "rulemaking_legislative_duty",
        "rulemaking_legislative_duty",
        "rulemaking_legislative_duty",
        "rulemaking_legislative_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        "O(∀x (Commission(x) → MakeRuleSafetyStandard(x)))",
        "O(∀x (Council(x) → EnactOrdinance(x)))",
        "O(∀x (Board(x) → AmendRule(x)))",
        "O(∀x (Council(x) → RepealRegulation(x)))",
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


def test_rulemaking_slice_preserves_unresolved_numbered_exception_repair_gate():
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
