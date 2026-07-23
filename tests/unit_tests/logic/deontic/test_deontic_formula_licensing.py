"""Focused tests for licensing and instrument-status formula families."""

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


def test_licensing_credentialing_duties_export_operative_predicates():
    examples = [
        (
            "The Bureau shall conduct licensing of food carts.",
            "conduct licensing of food carts",
            "O(∀x (Bureau(x) → LicenseFoodCarts(x)))",
            "ConductLicensingFoodCarts",
        ),
        (
            "The Director shall approve permitting for temporary events.",
            "approve permitting for temporary events",
            "O(∀x (Director(x) → PermitTemporaryEvents(x)))",
            "ApprovePermittingTemporaryEvents",
        ),
        (
            "The Commission shall provide accreditation of laboratories.",
            "provide accreditation of laboratories",
            "O(∀x (Commission(x) → AccreditLaboratories(x)))",
            "ProvideAccreditationLaboratories",
        ),
        (
            "The Board shall conduct credentialing of inspectors.",
            "conduct credentialing of inspectors",
            "O(∀x (Board(x) → CredentialInspectors(x)))",
            "ConductCredentialingInspectors",
        ),
        (
            "The Director shall issue endorsements for instructors.",
            "issue endorsements for instructors",
            "O(∀x (Director(x) → EndorseInstructors(x)))",
            "IssueEndorsementsInstructors",
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
        "licensing_credentialing_duty",
        "licensing_credentialing_duty",
        "licensing_credentialing_duty",
        "licensing_credentialing_duty",
        "licensing_credentialing_duty",
    ]
    assert [record["formula"] for record in capability_records] == [
        expected_formula for _, _, expected_formula, _ in examples
    ]
    assert all(record["checked_slots"] == ["actor", "modality", "action"] for record in capability_records)
    assert all(record["grounded_slots"] == ["actor", "modality", "action"] for record in capability_records)
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in capability_records)
    assert all(record["requires_validation"] is False for record in capability_records)
    assert all(record["repair_required"] is False for record in capability_records)


def test_instrument_status_duties_export_profile_family():
    examples = [
        (
            "The Board shall order suspension of the license.",
            "order suspension of the license",
            "O(∀x (Board(x) → SuspendLicense(x)))",
            "instrument_status_duty",
        ),
        (
            "The Director shall issue revocation of the permit.",
            "issue revocation of the permit",
            "O(∀x (Director(x) → RevokePermit(x)))",
            "instrument_status_duty",
        ),
        (
            "The Clerk shall effect cancellation of the registration.",
            "effect cancellation of the registration",
            "O(∀x (Clerk(x) → CancelRegistration(x)))",
            "instrument_status_duty",
        ),
        (
            "The Registrar shall make registration of operators.",
            "make registration of operators",
            "O(∀x (Registrar(x) → RegisterOperators(x)))",
            "licensing_credentialing_duty",
        ),
        (
            "The Director shall complete renewal of the license.",
            "complete renewal of the license",
            "O(∀x (Director(x) → RenewLicense(x)))",
            "instrument_status_duty",
        ),
    ]

    norms = []
    for text, action, expected_formula, _ in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        norms.append(norm)

        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert build_deontic_formula_record_from_ir(norm)["proof_ready"] is True
        assert validate_ir_with_provers(norm).syntax_valid is True

    records = build_deterministic_parser_capability_profile_records(norms)

    assert [record["capability_family"] for record in records] == [
        expected_family for _, _, _, expected_family in examples
    ]
    assert [record["formula"] for record in records] == [
        expected_formula for _, _, expected_formula, _ in examples
    ]
    assert all(record["formula_proof_ready"] is True for record in records)
    assert all(record["parser_proof_ready"] is True for record in records)
    assert all(record["source_grounded_slot_rate"] == 1.0 for record in records)


def test_licensing_slice_preserves_unresolved_numbered_exception_repair_gate():
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
