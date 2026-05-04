"""Tests for deterministic parser capability profile families."""

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


def test_capability_profiles_classify_administrative_formula_families():
    examples = [
        (
            "The Treasurer shall make an assessment of the fee.",
            "O(∀x (Treasurer(x) → AssessFee(x)))",
            "financial_administration_duty",
        ),
        (
            "The Commission shall order apportionment of the costs.",
            "O(∀x (Commission(x) → ApportionCosts(x)))",
            "financial_administration_duty",
        ),
        (
            "The Clerk shall make a referral of the complaint.",
            "O(∀x (Clerk(x) → ReferComplaint(x)))",
            "case_routing_duty",
        ),
        (
            "The Director shall grant a waiver of the fee.",
            "O(∀x (Director(x) → WaiveFee(x)))",
            "administrative_relief_duty",
        ),
        (
            "The Registrar shall record registration of the vehicle.",
            "O(∀x (Registrar(x) → RegisterVehicle(x)))",
            "registration_lifecycle_duty",
        ),
        (
            "The Clerk shall make an indexing of the record.",
            "O(∀x (Clerk(x) → IndexRecord(x)))",
            "records_information_processing_duty",
        ),
        (
            "The Agency shall provide translation of the notice.",
            "O(∀x (Agency(x) → TranslateNotice(x)))",
            "records_information_processing_duty",
        ),
        (
            "The Clerk shall provide transcription of the hearing.",
            "O(∀x (Clerk(x) → TranscribeHearing(x)))",
            "records_information_processing_duty",
        ),
    ]

    norms = []
    for text, expected_formula, _ in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        formula_record = build_deontic_formula_record_from_ir(norm)
        prover_report = validate_ir_with_provers(norm)
        norms.append(norm)

        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert formula_record["formula"] == expected_formula
        assert formula_record["proof_ready"] is True
        assert formula_record["requires_validation"] is False
        assert formula_record["repair_required"] is False
        assert prover_report.syntax_valid is True
        assert prover_report.proof_ready is True
        assert prover_report.valid_target_count == 5

    capability_records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in capability_records] == [
        family for _, _, family in examples
    ]
    assert [record["formula"] for record in capability_records] == [
        formula for _, formula, _ in examples
    ]
    assert all(record["checked_slots"] == ["actor", "modality", "action"] for record in capability_records)
    assert all(record["grounded_slots"] == ["actor", "modality", "action"] for record in capability_records)
    assert all(record["missing_slots"] == [] for record in capability_records)
    assert all(record["ungrounded_slots"] == [] for record in capability_records)
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["formula_proof_ready"] is True for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_capability_profile_slice_preserves_unresolved_numbered_exception_gate():
    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    blocked_norm = LegalNormIR.from_parser_element(blocked)
    blocked_records = build_deterministic_parser_capability_profile_records([blocked_norm])

    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
    assert blocked_records[0]["capability_family"] == "procedural_event_duty"
    assert blocked_records[0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert blocked_records[0]["formula_proof_ready"] is False
    assert blocked_records[0]["requires_validation"] is True
    assert blocked_records[0]["repair_required"] is True
