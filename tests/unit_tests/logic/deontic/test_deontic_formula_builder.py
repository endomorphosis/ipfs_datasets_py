"""Tests for deterministic IR-to-formula generation."""

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
    build_deontic_formula_records_from_irs,
    parser_element_to_formula_record,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    build_deontic_formula,
    extract_normative_elements,
)


def test_ir_formula_builder_matches_legacy_wrapper_for_core_norms():
    texts = [
        "The tenant must pay rent monthly.",
        "Emergency repairs are exempt from permit requirements.",
        "This section applies to food carts.",
        'In this section, the term "food cart" means a mobile food vending unit.',
        "The applicant shall obtain a permit unless approval is denied.",
        "The Director shall issue a permit within 10 days after application.",
        "The license is valid for 30 days.",
        "The permit expires one year after issuance.",
    ]

    for text in texts:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)

        assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_ir_formula_builder_uses_slot_details_without_raw_parser_lists():
    element = extract_normative_elements(
        "Subject to approval, the Director shall issue a permit within 10 days after application "
        "unless the application is incomplete."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ Approval(x) ∧ Deadline10DaysAfterApplication(x) "
        "∧ ¬ApplicationIsIncomplete(x) → IssuePermit(x)))"
    )


def test_ir_formula_record_carries_proof_ready_provenance():
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Tenant(x) ∧ PeriodMonthly(x) → PayRentMonthly(x)))"
    assert record["formula_id"].startswith("formula:")
    assert record["source_id"] == element["source_id"]
    assert record["target_logic"] == "deontic"
    assert record["support_span"] == element["support_span"]
    assert record["field_spans"] == element["field_spans"]
    assert record["proof_ready"] is True
    assert record["repair_required"] is False
    assert record["requires_validation"] is False
    assert record["blockers"] == []
    assert record["parser_warnings"] == []
    assert record["omitted_formula_slots"] == {}


def test_ir_formula_builder_uses_detail_only_mental_state_slot():
    element = dict(extract_normative_elements(
        "The inspector shall knowingly approve the discharge."
    )[0])
    element["mental_state"] = ""
    element["action"] = ["approve the discharge"]
    element["action_verb"] = "approve"
    element["action_object"] = "the discharge"
    element["mental_state_details"] = [
        {
            "type": "mens_rea",
            "value": "knowingly",
            "span": [20, 29],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.mental_state == "knowingly"
    assert formula == "O(∀x (Inspector(x) ∧ Knowingly(x) → ApproveDischarge(x)))"

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_duty_assignment_gerunds_export_base_action_predicates():
    examples = [
        (
            "The custodian is responsible for maintaining records.",
            "maintaining records",
            "O(∀x (Custodian(x) → MaintainRecords(x)))",
            "MaintainingRecords",
        ),
        (
            "The officer is accountable for preserving evidence.",
            "preserving evidence",
            "O(∀x (Officer(x) → PreserveEvidence(x)))",
            "PreservingEvidence",
        ),
        (
            "The inspectors are tasked with conducting inspections.",
            "conducting inspections",
            "O(∀x (Inspectors(x) → ConductInspections(x)))",
            "ConductingInspections",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)
        action_span = element["field_spans"]["action"]

        assert norm.modality == "O"
        assert norm.action == action
        assert element["text"][action_span[0]:action_span[1]] == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_submission_light_verb_duty_exports_operative_submit_predicate():
    element = extract_normative_elements(
        "The applicant shall make a submission of the annual report."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "make a submission of the annual report"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [20, 58]
    assert formula == "O(∀x (Applicant(x) → SubmitAnnualReport(x)))"
    assert "MakeSubmission" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False


def test_filing_light_verb_duty_exports_operative_file_predicate():
    element = extract_normative_elements(
        "The licensee shall file a filing of the renewal statement."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "file a filing of the renewal statement"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [19, 57]
    assert formula == "O(∀x (Licensee(x) → FileRenewalStatement(x)))"
    assert "FileFiling" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False


def test_certification_light_verb_duties_export_operative_certify_predicates():
    examples = [
        (
            "The Clerk shall make a certification of the inspection.",
            "make a certification of the inspection",
            [16, 54],
            "O(∀x (Clerk(x) → CertifyInspection(x)))",
            "MakeCertificationInspection",
        ),
        (
            "The Director shall provide certification of the record.",
            "provide certification of the record",
            [19, 54],
            "O(∀x (Director(x) → CertifyRecord(x)))",
            "ProvideCertificationRecord",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_verification_light_verb_duties_export_operative_verify_predicates():
    examples = [
        (
            "The Clerk shall make a verification of the address.",
            "make a verification of the address",
            [16, 50],
            "O(∀x (Clerk(x) → VerifyAddress(x)))",
            "MakeVerificationAddress",
        ),
        (
            "The Auditor shall perform verification of the account.",
            "perform verification of the account",
            [18, 53],
            "O(∀x (Auditor(x) → VerifyAccount(x)))",
            "PerformVerificationAccount",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_approval_light_verb_duties_export_operative_approve_predicates():
    examples = [
        (
            "The Director shall grant approval of the application.",
            "grant approval of the application",
            [19, 52],
            "O(∀x (Director(x) → ApproveApplication(x)))",
            "GrantApprovalApplication",
        ),
        (
            "The Board shall make an approval of the renewal.",
            "make an approval of the renewal",
            [16, 47],
            "O(∀x (Board(x) → ApproveRenewal(x)))",
            "MakeApprovalRenewal",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_authorization_and_accreditation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall grant authorization of the use.",
            "grant authorization of the use",
            [19, 49],
            "O(∀x (Director(x) → AuthorizeUse(x)))",
            "GrantAuthorizationUse",
        ),
        (
            "The Board shall issue accreditation of the program.",
            "issue accreditation of the program",
            [16, 50],
            "O(∀x (Board(x) → AccreditProgram(x)))",
            "IssueAccreditationProgram",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_classification_and_categorization_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make a classification of the application.",
            "make a classification of the application",
            [19, 59],
            "O(∀x (Director(x) → ClassifyApplication(x)))",
            "MakeClassificationApplication",
        ),
        (
            "The Board shall assign categorization of the facility.",
            "assign categorization of the facility",
            [16, 53],
            "O(∀x (Board(x) → CategorizeFacility(x)))",
            "AssignCategorizationFacility",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_transfer_and_conveyance_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make a transfer of the license.",
            "make a transfer of the license",
            "O(∀x (Director(x) → TransferLicense(x)))",
            "MakeTransferLicense",
        ),
        (
            "The Clerk shall effect conveyance of the record.",
            "effect conveyance of the record",
            "O(∀x (Clerk(x) → ConveyRecord(x)))",
            "EffectConveyanceRecord",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_correction_and_adjustment_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make a correction of the record.",
            "make a correction of the record",
            "O(∀x (Clerk(x) → CorrectRecord(x)))",
            "MakeCorrectionRecord",
        ),
        (
            "The Treasurer shall effect adjustment of the fee.",
            "effect adjustment of the fee",
            "O(∀x (Treasurer(x) → AdjustFee(x)))",
            "EffectAdjustmentFee",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_denial_light_verb_duties_export_operative_deny_predicates():
    examples = [
        (
            "The Director shall issue a denial of the application.",
            "issue a denial of the application",
            [19, 52],
            "O(∀x (Director(x) → DenyApplication(x)))",
            "IssueDenialApplication",
        ),
        (
            "The Board shall make a denial of the renewal.",
            "make a denial of the renewal",
            [16, 44],
            "O(∀x (Board(x) → DenyRenewal(x)))",
            "MakeDenialRenewal",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_measurement_light_verb_duty_exports_operative_measure_predicate():
    element = extract_normative_elements(
        "The operator shall conduct measurement of the discharge."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "conduct measurement of the discharge"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [19, 55]
    assert formula == "O(∀x (Operator(x) → MeasureDischarge(x)))"
    assert "ConductMeasurement" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False


def test_remittance_light_verb_duties_export_operative_remit_predicates():
    examples = [
        (
            "The Treasurer shall make a remittance of the fee.",
            "make a remittance of the fee",
            "O(∀x (Treasurer(x) → RemitFee(x)))",
            "MakeRemittanceFee",
        ),
        (
            "The applicant shall submit remittance of the charge.",
            "submit remittance of the charge",
            "O(∀x (Applicant(x) → RemitCharge(x)))",
            "SubmitRemittanceCharge",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_renewal_light_verb_duties_export_operative_renew_predicates():
    examples = [
        (
            "The Clerk shall make a renewal of the license.",
            "make a renewal of the license",
            "O(∀x (Clerk(x) → RenewLicense(x)))",
            "MakeRenewalLicense",
        ),
        (
            "The Director shall grant renewal of the permit.",
            "grant renewal of the permit",
            "O(∀x (Director(x) → RenewPermit(x)))",
            "GrantRenewalPermit",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_rescission_and_withdrawal_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall order rescission of the permit.",
            "order rescission of the permit",
            "O(∀x (Director(x) → RescindPermit(x)))",
            "OrderRescissionPermit",
        ),
        (
            "The Clerk shall make a withdrawal of the application.",
            "make a withdrawal of the application",
            "O(∀x (Clerk(x) → WithdrawApplication(x)))",
            "MakeWithdrawalApplication",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_registration_and_enrollment_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make a registration of the vehicle.",
            "make a registration of the vehicle",
            "O(∀x (Clerk(x) → RegisterVehicle(x)))",
            "MakeRegistrationVehicle",
        ),
        (
            "The Registrar shall complete enrollment of the applicant.",
            "complete enrollment of the applicant",
            "O(∀x (Registrar(x) → EnrollApplicant(x)))",
            "CompleteEnrollmentApplicant",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_instrument_status_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make a revocation of the permit.",
            "make a revocation of the permit",
            "O(∀x (Director(x) → RevokePermit(x)))",
            "MakeRevocationPermit",
        ),
        (
            "The Board shall order suspension of the license.",
            "order suspension of the license",
            "O(∀x (Board(x) → SuspendLicense(x)))",
            "OrderSuspensionLicense",
        ),
        (
            "The Clerk shall effect cancellation of the registration.",
            "effect cancellation of the registration",
            "O(∀x (Clerk(x) → CancelRegistration(x)))",
            "EffectCancellationRegistration",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_abatement_and_remediation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall order abatement of the nuisance.",
            "order abatement of the nuisance",
            "O(∀x (Director(x) → AbateNuisance(x)))",
            "OrderAbatementNuisance",
        ),
        (
            "The operator shall perform remediation of the violation.",
            "perform remediation of the violation",
            "O(∀x (Operator(x) → RemediateViolation(x)))",
            "PerformRemediationViolation",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_notification_and_disclosure_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall provide notification to the applicant.",
            "provide notification to the applicant",
            "O(∀x (Director(x) → NotifyApplicant(x)))",
            "ProvideNotificationApplicant",
        ),
        (
            "The custodian shall make a disclosure of the records.",
            "make a disclosure of the records",
            "O(∀x (Custodian(x) → DiscloseRecords(x)))",
            "MakeDisclosureRecords",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_recommendation_and_referral_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Committee shall make a recommendation of the sanction.",
            "make a recommendation of the sanction",
            "O(∀x (Committee(x) → RecommendSanction(x)))",
            "MakeRecommendationSanction",
        ),
        (
            "The Director shall issue referral of the complaint.",
            "issue referral of the complaint",
            "O(∀x (Director(x) → ReferComplaint(x)))",
            "IssueReferralComplaint",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_docketing_and_calendaring_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make a docketing of the appeal.",
            "make a docketing of the appeal",
            "O(∀x (Clerk(x) → DocketAppeal(x)))",
            "MakeDocketingAppeal",
        ),
        (
            "The Board shall enter calendaring of the hearing.",
            "enter calendaring of the hearing",
            "O(∀x (Board(x) → CalendarHearing(x)))",
            "EnterCalendaringHearing",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_investigation_light_verb_duties_export_operative_investigate_predicates():
    examples = [
        (
            "The Inspector shall conduct an investigation of the complaint.",
            "conduct an investigation of the complaint",
            [20, 61],
            "O(∀x (Inspector(x) → InvestigateComplaint(x)))",
            "ConductInvestigationComplaint",
        ),
        (
            "The Bureau shall open investigation into the discharge.",
            "open investigation into the discharge",
            [17, 54],
            "O(∀x (Bureau(x) → InvestigateDischarge(x)))",
            "OpenInvestigationDischarge",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_evaluation_light_verb_duties_export_operative_evaluate_and_assess_predicates():
    examples = [
        (
            "The Director shall conduct an evaluation of the application.",
            "conduct an evaluation of the application",
            [19, 59],
            "O(∀x (Director(x) → EvaluateApplication(x)))",
            "ConductEvaluationApplication",
        ),
        (
            "The Bureau shall perform an assessment of the fee.",
            "perform an assessment of the fee",
            [17, 49],
            "O(∀x (Bureau(x) → AssessFee(x)))",
            "PerformAssessmentFee",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_determination_light_verb_duties_export_operative_determine_predicates():
    examples = [
        (
            "The Director shall make a determination of the eligibility.",
            "make a determination of the eligibility",
            "O(∀x (Director(x) → DetermineEligibility(x)))",
            "MakeDeterminationEligibility",
        ),
        (
            "The Board shall issue determinations of compliance.",
            "issue determinations of compliance",
            "O(∀x (Board(x) → DetermineCompliance(x)))",
            "IssueDeterminationsCompliance",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_calculation_and_computation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Auditor shall make a calculation of the fee.",
            "make a calculation of the fee",
            "O(∀x (Auditor(x) → CalculateFee(x)))",
            "MakeCalculationFee",
        ),
        (
            "The Treasurer shall perform a computation of the tax.",
            "perform a computation of the tax",
            "O(∀x (Treasurer(x) → ComputeTax(x)))",
            "PerformComputationTax",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_collection_and_compilation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Treasurer shall make a collection of the fee.",
            "make a collection of the fee",
            "O(∀x (Treasurer(x) → CollectFee(x)))",
            "MakeCollectionFee",
        ),
        (
            "The Clerk shall prepare a compilation of the records.",
            "prepare a compilation of the records",
            "O(∀x (Clerk(x) → CompileRecords(x)))",
            "PrepareCompilationRecords",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_delivery_and_distribution_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make a delivery of the notice.",
            "make a delivery of the notice",
            "O(∀x (Clerk(x) → DeliverNotice(x)))",
            "MakeDeliveryNotice",
        ),
        (
            "The Bureau shall complete distribution of the forms.",
            "complete distribution of the forms",
            "O(∀x (Bureau(x) → DistributeForms(x)))",
            "CompleteDistributionForms",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_adoption_and_promulgation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Council shall make an adoption of the rule.",
            "make an adoption of the rule",
            "O(∀x (Council(x) → AdoptRule(x)))",
            "MakeAdoptionRule",
        ),
        (
            "The Bureau shall effect promulgation of the regulation.",
            "effect promulgation of the regulation",
            "O(∀x (Bureau(x) → PromulgateRegulation(x)))",
            "EffectPromulgationRegulation",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_designation_and_appointment_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make a designation of the officer.",
            "make a designation of the officer",
            "O(∀x (Director(x) → DesignateOfficer(x)))",
            "MakeDesignationOfficer",
        ),
        (
            "The Council shall effect appointment of the inspector.",
            "effect appointment of the inspector",
            "O(∀x (Council(x) → AppointInspector(x)))",
            "EffectAppointmentInspector",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_issuance_light_verb_duties_export_operative_issue_predicates():
    examples = [
        (
            "The Director shall make an issuance of the permit.",
            "make an issuance of the permit",
            "O(∀x (Director(x) → IssuePermit(x)))",
            "MakeIssuancePermit",
        ),
        (
            "The Clerk shall effect issuance of the certificate.",
            "effect issuance of the certificate",
            "O(∀x (Clerk(x) → IssueCertificate(x)))",
            "EffectIssuanceCertificate",
        ),
        (
            "The Board shall order the license to be issued.",
            "order the license to be issued",
            "O(∀x (Board(x) → IssueLicense(x)))",
            "OrderLicenseToBeIssued",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_notice_service_light_verb_duties_export_operative_notice_predicates():
    examples = [
        (
            "The Clerk shall give notice of the hearing.",
            "give notice of the hearing",
            [16, 42],
            "O(∀x (Clerk(x) → NoticeHearing(x)))",
            "GiveNoticeHearing",
        ),
        (
            "The Bureau shall provide notice to the applicant.",
            "provide notice to the applicant",
            [17, 48],
            "O(∀x (Bureau(x) → NoticeApplicant(x)))",
            "ProvideNoticeApplicant",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_publication_light_verb_duties_export_operative_publish_predicates():
    examples = [
        (
            "The Clerk shall cause publication of the notice.",
            "cause publication of the notice",
            [16, 47],
            "O(∀x (Clerk(x) → PublishNotice(x)))",
            "CausePublicationNotice",
        ),
        (
            "The Bureau shall cause the notice to be published.",
            "cause the notice to be published",
            [17, 49],
            "O(∀x (Bureau(x) → PublishNotice(x)))",
            "CauseNoticeToBePublished",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_service_light_verb_duties_export_operative_serve_predicates():
    examples = [
        (
            "The Clerk shall make service of the summons.",
            "make service of the summons",
            [16, 43],
            "O(∀x (Clerk(x) → ServeSummons(x)))",
            "MakeServiceSummons",
        ),
        (
            "The Marshal shall effect service on the respondent.",
            "effect service on the respondent",
            [18, 50],
            "O(∀x (Marshal(x) → ServeRespondent(x)))",
            "EffectServiceRespondent",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_plural_measurements_light_verb_duty_exports_operative_measure_predicate():
    element = extract_normative_elements(
        "The inspector shall take measurements of the effluent."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "take measurements of the effluent"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [20, 53]
    assert formula == "O(∀x (Inspector(x) → MeasureEffluent(x)))"
    assert "TakeMeasurements" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_refrain_from_obligation_exports_as_prohibition_formula():
    element = extract_normative_elements(
        "The employee shall refrain from disclosing confidential information."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "refrain from disclosing confidential information"
    assert formula == "F(∀x (Employee(x) → DiscloseConfidentialInformation(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_abstain_from_obligation_exports_as_prohibition_formula():
    element = extract_normative_elements(
        "The permittee shall abstain from operating the facility."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "abstain from operating the facility"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [20, 55]
    assert formula == "F(∀x (Permittee(x) → OperateFacility(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_cease_obligation_exports_as_prohibition_formula():
    element = extract_normative_elements(
        "The operator shall cease discharging pollutants."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "cease discharging pollutants"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [19, 47]
    assert formula == "F(∀x (Operator(x) → DischargePollutants(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_forbear_from_obligation_exports_as_prohibition_formula():
    element = extract_normative_elements(
        "The permittee shall forbear from entering restricted areas."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "forbear from entering restricted areas"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [20, 58]
    assert formula == "F(∀x (Permittee(x) → EnterRestrictedAreas(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False


def test_avoid_gerund_obligation_exports_as_prohibition_formula():
    element = extract_normative_elements(
        "The handler shall avoid contacting the witness."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "avoid contacting the witness"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [18, 46]
    assert formula == "F(∀x (Handler(x) → ContactWitness(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False


def test_direct_gerund_prohibition_exports_base_action_formula():
    element = extract_normative_elements(
        "The permittee is prohibited from operating the facility."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "F"
    assert norm.action == "operating the facility"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [33, 55]
    assert formula == "F(∀x (Permittee(x) → OperateFacility(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_inspection_light_verb_duty_exports_operative_inspect_predicate():
    element = extract_normative_elements(
        "The Bureau shall conduct an inspection of the premises."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "conduct an inspection of the premises"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [17, 54]
    assert formula == "O(∀x (Bureau(x) → InspectPremises(x)))"
    assert "ConductInspection" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_sampling_light_verb_duties_export_operative_sample_predicates():
    examples = [
        (
            "The Inspector shall take a sample of the discharge.",
            "take a sample of the discharge",
            "O(∀x (Inspector(x) → SampleDischarge(x)))",
            "TakeSampleDischarge",
        ),
        (
            "The Bureau shall collect samples from the effluent.",
            "collect samples from the effluent",
            "O(∀x (Bureau(x) → SampleEffluent(x)))",
            "CollectSamplesEffluent",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_testing_light_verb_duties_export_operative_test_predicates():
    examples = [
        (
            "The Inspector shall conduct testing of the effluent.",
            "conduct testing of the effluent",
            "O(∀x (Inspector(x) → TestEffluent(x)))",
            "ConductTestingEffluent",
        ),
        (
            "The Bureau shall perform tests on the meter.",
            "perform tests on the meter",
            "O(∀x (Bureau(x) → TestMeter(x)))",
            "PerformTestsMeter",
        ),
        (
            "The Operator shall run a test of the alarm.",
            "run a test of the alarm",
            "O(∀x (Operator(x) → TestAlarm(x)))",
            "RunTestAlarm",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_monitoring_light_verb_duties_export_operative_monitor_predicates():
    examples = [
        (
            "The Inspector shall conduct monitoring of the discharge.",
            "conduct monitoring of the discharge",
            [20, 55],
            "O(∀x (Inspector(x) → MonitorDischarge(x)))",
            "ConductMonitoringDischarge",
        ),
        (
            "The Bureau shall perform monitoring on the outfall.",
            "perform monitoring on the outfall",
            [17, 50],
            "O(∀x (Bureau(x) → MonitorOutfall(x)))",
            "PerformMonitoringOutfall",
        ),
        (
            "The Operator shall run a monitoring program for the meter.",
            "run a monitoring program for the meter",
            [19, 57],
            "O(∀x (Operator(x) → MonitorMeter(x)))",
            "RunMonitoringProgramMeter",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_payment_light_verb_duty_exports_operative_payment_predicate():
    element = extract_normative_elements(
        "The licensee shall make payment of the renewal fee."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "make payment of the renewal fee"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [19, 50]
    assert formula == "O(∀x (Licensee(x) → PayRenewalFee(x)))"
    assert "MakePayment" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_recordkeeping_light_verb_duty_exports_operative_record_predicate_and_preserves_apply_for():
    element = extract_normative_elements(
        "The Clerk shall make a record of the hearing."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "make a record of the hearing"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [16, 44]
    assert formula == "O(∀x (Clerk(x) → RecordHearing(x)))"
    assert "MakeRecord" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    apply_element = extract_normative_elements(
        "The applicant shall apply for a permit."
    )[0]
    apply_norm = LegalNormIR.from_parser_element(apply_element)
    assert apply_norm.action == "apply for a permit"
    assert build_deontic_formula_from_ir(apply_norm) == (
        "O(∀x (Applicant(x) → ApplyForPermit(x)))"
    )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_coordinated_failure_prohibitions_export_affirmative_duty_formulas():
    examples = [
        (
            "The permittee shall not fail or refuse to submit records.",
            "fail or refuse to submit records",
            "O(∀x (Permittee(x) → SubmitRecords(x)))",
            "FailOrRefuseSubmitRecords",
        ),
        (
            "The licensee shall not failure or refusal to file reports.",
            "failure or refusal to file reports",
            "O(∀x (Licensee(x) → FileReports(x)))",
            "FailureOrRefusalFileReports",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_interference_gerund_prohibitions_export_base_action_formulas():
    examples = [
        (
            "The permittee is prohibited from obstructing inspection.",
            "obstructing inspection",
            "F(∀x (Permittee(x) → ObstructInspection(x)))",
            "ObstructingInspection",
        ),
        (
            "The operator is prohibited from interfering with inspection.",
            "interfering with inspection",
            "F(∀x (Operator(x) → InterfereInspection(x)))",
            "InterferingInspection",
        ),
        (
            "The applicant is prohibited from impeding access.",
            "impeding access",
            "F(∀x (Applicant(x) → ImpedeAccess(x)))",
            "ImpedingAccess",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_direct_interference_prohibitions_export_normalized_action_formulas():
    examples = [
        (
            "No person may interfere with inspection of the premises.",
            "interfere with inspection of the premises",
            "F(∀x (Person(x) → InterfereInspectionPremises(x)))",
            "InterfereWithInspectionPremises",
        ),
        (
            "The permittee shall not obstruct access to the facility.",
            "obstruct access to the facility",
            "F(∀x (Permittee(x) → ObstructAccessFacility(x)))",
            "ObstructAccessToFacility",
        ),
        (
            "The operator may not impede inspection.",
            "impede inspection",
            "F(∀x (Operator(x) → ImpedeInspection(x)))",
            "ImpedeWithInspection",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_facilitation_prohibitions_export_embedded_prohibited_action_formulas():
    examples = [
        (
            "The owner shall not permit discharge of pollutants.",
            "permit discharge of pollutants",
            "F(∀x (Owner(x) → DischargePollutants(x)))",
            "PermitDischargePollutants",
        ),
        (
            "The operator may not allow any person to enter the restricted area.",
            "allow any person to enter the restricted area",
            "F(∀x (Operator(x) → EnterRestrictedArea(x)))",
            "AllowAnyPersonEnterRestrictedArea",
        ),
        (
            "The permittee shall not authorize removal of the records.",
            "authorize removal of the records",
            "F(∀x (Permittee(x) → RemoveRecords(x)))",
            "AuthorizeRemovalRecords",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_causation_prohibitions_export_embedded_prohibited_action_formulas():
    examples = [
        (
            "The owner shall not cause discharge of pollutants.",
            "cause discharge of pollutants",
            "F(∀x (Owner(x) → DischargePollutants(x)))",
            "CauseDischargePollutants",
        ),
        (
            "The operator may not cause any person to enter the restricted area.",
            "cause any person to enter the restricted area",
            "F(∀x (Operator(x) → EnterRestrictedArea(x)))",
            "CauseAnyPersonEnterRestrictedArea",
        ),
        (
            "The permittee shall not result in removal of the records.",
            "result in removal of the records",
            "F(∀x (Permittee(x) → RemoveRecords(x)))",
            "ResultInRemovalRecords",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_coercion_prohibitions_export_embedded_prohibited_action_formulas():
    examples = [
        (
            "The agency shall not require any person to disclose records.",
            "require any person to disclose records",
            "F(∀x (Agency(x) → DiscloseRecords(x)))",
            "RequireAnyPersonDiscloseRecords",
        ),
        (
            "The officer may not compel the applicant to remove signs.",
            "compel the applicant to remove signs",
            "F(∀x (Officer(x) → RemoveSigns(x)))",
            "CompelApplicantRemoveSigns",
        ),
        (
            "The Board shall not direct the permittee to destroy documents.",
            "direct the permittee to destroy documents",
            "F(∀x (Board(x) → DestroyDocuments(x)))",
            "DirectPermitteeDestroyDocuments",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_prevent_entry_obligation_exports_as_prohibition_formula():
    element = extract_normative_elements(
        "The owner shall prevent entry into the restricted area."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "prevent entry into the restricted area"
    assert norm.support_span == norm.source_span
    assert element["field_spans"]["action"] == [16, 54]
    assert formula == "F(∀x (Owner(x) → EnterIntoRestrictedArea(x)))"
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_prohibit_bar_and_block_prevention_duties_export_as_prohibition_formulas():
    examples = [
        (
            "The owner shall prohibit discharge of pollutants.",
            "prohibit discharge of pollutants",
            "F(∀x (Owner(x) → DischargePollutants(x)))",
            "ProhibitDischargePollutants",
        ),
        (
            "The owner shall bar access to the restricted area.",
            "bar access to the restricted area",
            "F(∀x (Owner(x) → AccessRestrictedArea(x)))",
            "BarAccessRestrictedArea",
        ),
        (
            "The operator shall block removal of the records.",
            "block removal of the records",
            "F(∀x (Operator(x) → RemoveRecords(x)))",
            "BlockRemovalRecords",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_compliance_duties_export_embedded_compliance_action_formula():
    examples = [
        (
            "The operator shall ensure compliance with the permit.",
            "ensure compliance with the permit",
            "O(∀x (Operator(x) → ComplyPermit(x)))",
            "EnsureCompliancePermit",
        ),
        (
            "The licensee shall secure compliance with safety standards.",
            "secure compliance with safety standards",
            "O(∀x (Licensee(x) → ComplySafetyStandards(x)))",
            "SecureComplianceSafetyStandards",
        ),
        (
            "The contractor shall maintain compliance with reporting requirements.",
            "maintain compliance with reporting requirements",
            "O(∀x (Contractor(x) → ComplyReportingRequirements(x)))",
            "MaintainComplianceReportingRequirements",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_confidentiality_duties_export_disclosure_prohibition_formulas():
    examples = [
        (
            "The clerk shall keep application records confidential.",
            "keep application records confidential",
            "F(∀x (Clerk(x) → DiscloseApplicationRecords(x)))",
            "KeepApplicationRecordsConfidential",
        ),
        (
            "The agency shall maintain investigation files confidential.",
            "maintain investigation files confidential",
            "F(∀x (Agency(x) → DiscloseInvestigationFiles(x)))",
            "MaintainInvestigationFilesConfidential",
        ),
        (
            "The contractor shall protect confidentiality of client records.",
            "protect confidentiality of client records",
            "F(∀x (Contractor(x) → DiscloseClientRecords(x)))",
            "ProtectConfidentialityClientRecords",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_access_and_availability_duties_export_provide_action_formulas():
    examples = [
        (
            "The agency shall make inspection records available for public inspection.",
            "make inspection records available for public inspection",
            "O(∀x (Agency(x) → ProvideInspectionRecordsPublicInspection(x)))",
            "MakeInspectionRecordsAvailablePublicInspection",
        ),
        (
            "The clerk shall maintain permit files available for review.",
            "maintain permit files available for review",
            "O(∀x (Clerk(x) → ProvidePermitFilesReview(x)))",
            "MaintainPermitFilesAvailableReview",
        ),
        (
            "The custodian shall provide access to registration records.",
            "provide access to registration records",
            "O(∀x (Custodian(x) → ProvideAccessRegistrationRecords(x)))",
            "ProvideAccessToRegistrationRecords",
        ),
    ]

    for text, action, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_transmittal_actions_omit_structured_recipient_from_unary_formula():
    element = dict(extract_normative_elements(
        "The Director shall send notice to the applicant."
    )[0])
    element["action"] = ["send notice to the applicant"]
    element["action_verb"] = "send"
    element["action_object"] = "notice"
    element["action_recipient"] = "applicant"
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action"] = [19, 47]
    field_spans["action_verb"] = [19, 23]
    field_spans["action_object"] = [24, 30]
    field_spans["action_recipient"] = [38, 47]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "send notice to the applicant"
    assert norm.action_object == "notice"
    assert norm.recipient == "applicant"
    assert formula == "O(∀x (Director(x) → SendNotice(x)))"
    assert "SendNoticeApplicant" not in formula
    assert record["formula"] == formula
    assert record["omitted_formula_slots"]["recipients"] == [
        {
            "value": "applicant",
            "field": "recipient",
            "reason": "recipient is preserved in IR but omitted from unary deontic formula consequent",
            "span": [38, 47],
        }
    ]
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_registry_and_posting_actions_omit_structured_recipient_from_unary_formula():
    examples = [
        (
            "record the deed with the clerk",
            "record",
            "deed",
            "clerk",
            "action_recipient",
            [33, 42],
            "O(∀x (Director(x) → RecordDeed(x)))",
            "RecordDeedClerk",
        ),
        (
            "register the permit with the Bureau",
            "register",
            "permit",
            "Bureau",
            "action_recipient",
            [37, 43],
            "O(∀x (Director(x) → RegisterPermit(x)))",
            "RegisterPermitBureau",
        ),
        (
            "post the notice on the premises",
            "post",
            "notice",
            "premises",
            "action_recipient",
            [31, 39],
            "O(∀x (Director(x) → PostNotice(x)))",
            "PostNoticePremises",
        ),
    ]

    for action, verb, action_object, recipient, span_key, span, expected_formula, rejected_predicate in examples:
        element = dict(extract_normative_elements("The Director shall issue a notice.")[0])
        element["action"] = [action]
        element["action_verb"] = verb
        element["action_object"] = action_object
        element["action_recipient"] = recipient
        element["field_spans"] = {
            **dict(element.get("field_spans") or {}),
            span_key: span,
        }

        norm = LegalNormIR.from_parser_element(element)
        formula = build_deontic_formula_from_ir(norm)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.action == action
        assert norm.action_object == action_object
        assert norm.recipient == recipient
        assert formula == expected_formula
        assert rejected_predicate not in formula
        assert record["formula"] == expected_formula
        assert record["omitted_formula_slots"]["recipients"][0]["value"] == recipient
        assert record["omitted_formula_slots"]["recipients"][0]["span"] == span
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_notice_duties_omit_structured_recipient_from_object_formula():
    examples = [
        (
            "notify the applicant of the decision",
            "notify",
            "decision",
            "applicant",
            "O(∀x (Director(x) → NotifyDecision(x)))",
            "NotifyApplicantDecision",
        ),
        (
            "inform the permittee about the inspection results",
            "inform",
            "inspection results",
            "permittee",
            "O(∀x (Director(x) → InformInspectionResults(x)))",
            "InformPermitteeInspectionResults",
        ),
        (
            "advise the owner regarding the permit denial",
            "advise",
            "permit denial",
            "owner",
            "O(∀x (Director(x) → AdvisePermitDenial(x)))",
            "AdviseOwnerPermitDenial",
        ),
    ]

    for action, verb, action_object, recipient, expected_formula, rejected_predicate in examples:
        element = dict(extract_normative_elements("The Director shall issue a notice.")[0])
        element["action"] = [action]
        element["action_verb"] = verb
        element["action_object"] = action_object
        element["action_recipient"] = recipient
        element["field_spans"] = {
            **dict(element.get("field_spans") or {}),
            "action_recipient": [0, 0],
        }

        norm = LegalNormIR.from_parser_element(element)
        formula = build_deontic_formula_from_ir(norm)
        record = build_deontic_formula_record_from_ir(norm)

        assert formula == expected_formula
        assert rejected_predicate not in formula
        assert record["formula"] == expected_formula
        assert record["omitted_formula_slots"]["recipients"][0]["value"] == recipient
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    recipient_only = dict(extract_normative_elements("The Director shall notify the applicant.")[0])
    recipient_only["action"] = []
    recipient_only["action_verb"] = "notify"
    recipient_only["action_object"] = ""
    recipient_only["action_recipient"] = "applicant"

    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(recipient_only)) == (
        "O(∀x (Director(x) → NotifyApplicant(x)))"
    )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_retention_duration_duty_uses_temporal_slot_not_action_tail():
    element = dict(extract_normative_elements(
        "The custodian shall retain records for three years."
    )[0])
    element["action"] = ["retain records for three years"]
    element["action_verb"] = "retain"
    element["action_object"] = "records"
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "duration",
            "duration": "three years",
            "span": [35, 46],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action"] = [20, 46]
    field_spans["action_verb"] = [20, 26]
    field_spans["action_object"] = [27, 34]
    field_spans["temporal_constraints"] = [35, 46]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert norm.action == "retain records for three years"
    assert norm.temporal_constraints[0]["value"] == "three years"
    assert formula == "O(∀x (Custodian(x) ∧ DurationThreeYears(x) → RetainRecords(x)))"
    assert "RetainRecordsForThreeYears" not in formula
    assert record["formula"] == formula
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_action_verb_and_object_slots():
    element = dict(extract_normative_elements(
        "The inspector shall approve the discharge."
    )[0])
    element["action"] = []
    element["action_verb"] = "approve"
    element["action_object"] = "the discharge"
    element["field_spans"] = {
        **dict(element.get("field_spans") or {}),
        "action_verb": [20, 27],
        "action_object": [28, 41],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.action == ""
    assert norm.action_verb == "approve"
    assert norm.action_object == "the discharge"
    assert formula == "O(∀x (Inspector(x) → ApproveDischarge(x)))"
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_action_component_records():
    element = dict(extract_normative_elements(
        "The inspector shall approve the discharge."
    )[0])
    element["action"] = []
    element["action_verb"] = ""
    element["action_object"] = ""
    element["action_verb_details"] = [
        {
            "type": "action_verb",
            "normalized_text": "approve",
            "span": [20, 27],
        }
    ]
    element["action_object_details"] = [
        {
            "type": "action_object",
            "normalized_text": "the discharge",
            "span": [28, 41],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action_verb"] = [20, 27]
    field_spans["action_object"] = [28, 41]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.action == ""
    assert norm.action_verb == "approve"
    assert norm.action_object == "the discharge"
    assert formula == "O(∀x (Inspector(x) → ApproveDischarge(x)))"
    assert "Action(x)" not in formula
    assert record["formula"] == formula


def test_ir_formula_builder_uses_detail_only_regulated_object_slot():
    element = dict(extract_normative_elements(
        "The inspector shall inspect the premises."
    )[0])
    element["action"] = []
    element["action_verb"] = "inspect"
    element["action_object"] = ""
    element["regulated_object_details"] = [
        {
            "type": "regulated_object",
            "normalized_text": "the premises",
            "span": [28, 40],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action_verb"] = [20, 27]
    field_spans["action_object"] = [28, 40]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.action == ""
    assert norm.action_verb == "inspect"
    assert norm.action_object == "the premises"
    assert norm.to_dict()["action_object"] == "the premises"
    assert formula == "O(∀x (Inspector(x) → InspectPremises(x)))"
    assert "Inspect(x)" not in formula
    assert "Action(x)" not in formula
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_regulated_activity_object_slot():
    element = dict(extract_normative_elements(
        "The inspector shall monitor regulated activity."
    )[0])
    element["action"] = []
    element["action_verb"] = "monitor"
    element["action_object"] = ""
    element["regulated_activity_details"] = [
        {
            "type": "regulated_activity",
            "normalized_text": "regulated activity",
            "span": [28, 46],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action_verb"] = [20, 27]
    field_spans["action_object"] = [28, 46]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.action == ""
    assert norm.action_verb == "monitor"
    assert norm.action_object == "regulated activity"
    assert norm.to_dict()["action_object"] == "regulated activity"
    assert formula == "O(∀x (Inspector(x) → MonitorRegulatedActivity(x)))"
    assert "Monitor(x)" not in formula
    assert "Action(x)" not in formula
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_recipient_slot():
    element = dict(extract_normative_elements(
        "The clerk shall notify the applicant."
    )[0])
    element["action"] = []
    element["action_verb"] = "notify"
    element["action_object"] = ""
    element["action_recipient"] = ""
    element["recipient_details"] = [
        {
            "type": "recipient",
            "normalized_text": "the applicant",
            "span": [23, 36],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action_verb"] = [16, 22]
    field_spans["action_recipient"] = [23, 36]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.action == ""
    assert norm.action_verb == "notify"
    assert norm.action_object == ""
    assert norm.recipient == "the applicant"
    assert norm.to_dict()["recipient"] == "the applicant"
    assert formula == "O(∀x (Clerk(x) → NotifyApplicant(x)))"
    assert "Notify(x)" not in formula
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_actor_slot():
    element = dict(extract_normative_elements(
        "The inspector shall approve the discharge."
    )[0])
    element["subject"] = []
    element["actor_details"] = [
        {
            "type": "actor",
            "normalized_text": "inspector",
            "span": [4, 13],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["subject"] = [4, 13]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.actor == "inspector"
    assert norm.actor_entities == ["inspector"]
    assert norm.to_dict()["actor"] == "inspector"
    assert formula == "O(∀x (Inspector(x) → ApproveDischarge(x)))"
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_definition_term_slot():
    element = dict(extract_normative_elements(
        'In this section, the term "food cart" means a mobile food vending unit.'
    )[0])
    element["subject"] = []
    element["defined_term_details"] = [
        {
            "type": "definition_term",
            "normalized_text": "food cart",
            "span": [27, 36],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["defined_term"] = [27, 36]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.norm_type == "definition"
    assert norm.actor == "food cart"
    assert norm.to_dict()["actor"] == "food cart"
    assert formula == "Definition(FoodCart)"
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_applicability_slots():
    element = dict(extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0])
    element["subject"] = []
    element["action"] = []
    element["applicability_details"] = [
        {
            "type": "applicability",
            "scope": "this section",
            "target": "food carts and mobile vendors",
            "span": [0, 53],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["scope"] = [0, 12]
    field_spans["target"] = [24, 53]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.norm_type == "applicability"
    assert norm.modality == "APP"
    assert norm.actor == "this section"
    assert norm.action == "food carts and mobile vendors"
    assert norm.actor_entities == ["this section"]
    assert norm.to_dict()["actor"] == "this section"
    assert norm.to_dict()["action"] == "food carts and mobile vendors"
    assert formula == "AppliesTo(ThisSection, FoodCartsAndMobileVendors)"
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_exemption_slots():
    element = dict(extract_normative_elements(
        "Emergency repairs are exempt from permit requirements."
    )[0])
    element["subject"] = []
    element["action"] = []
    element["exemption_details"] = [
        {
            "type": "exemption",
            "target": "emergency repairs",
            "requirement": "permit requirements",
            "span": [0, 54],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["exemption_target"] = [0, 17]
    field_spans["exemption_requirement"] = [34, 53]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.norm_type == "exemption"
    assert norm.modality == "EXEMPT"
    assert norm.actor == "emergency repairs"
    assert norm.action == "permit requirements"
    assert norm.actor_entities == ["emergency repairs"]
    assert norm.to_dict()["actor"] == "emergency repairs"
    assert norm.to_dict()["action"] == "permit requirements"
    assert formula == "ExemptFrom(EmergencyRepairs, PermitRequirements)"
    assert record["formula"] == formula
    assert record["proof_ready"] is True

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_instrument_lifecycle_slot():
    element = dict(extract_normative_elements(
        "The license is valid for 30 days."
    )[0])
    element["subject"] = []
    element["action"] = []
    element["instrument_lifecycle_details"] = [
        {
            "type": "validity",
            "instrument_type": "license",
            "duration": "30 days",
            "span": [4, 32],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["instrument"] = [4, 11]
    field_spans["duration"] = [25, 32]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.norm_type == "instrument_lifecycle"
    assert norm.modality == "LIFE"
    assert norm.actor == "license"
    assert norm.action == "valid for 30 days"
    assert norm.actor_entities == ["license"]
    assert norm.to_dict()["action"] == "valid for 30 days"
    assert formula == "ValidFor(License, 30Days)"
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_penalty_sanction_slot():
    element = dict(extract_normative_elements(
        "A violation is punishable by a civil fine of not less than $100 and not more than $500 per violation."
    )[0])
    element["action"] = []
    element["action_verb"] = ""
    element["action_object"] = ""
    element["penalty"] = {
        "sanction_class": "civil fine",
        "min_amount": "$100",
        "max_amount": "$500",
        "recurrence": "per violation",
        "span": [31, 97],
    }
    field_spans = dict(element.get("field_spans") or {})
    field_spans["penalty"] = [31, 97]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.norm_type == "penalty"
    assert norm.actor == "violation"
    assert norm.action == "incur civil fine not less than $100 and not more than $500 per violation"
    assert norm.to_dict()["action"] == norm.action
    assert formula == (
        "O(∀x (Violation(x) → IncurCivilFineNotLessThan100AndNotMoreThan500PerViolation(x)))"
    )
    assert record["formula"] == formula
    assert record["proof_ready"] is True

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_preserves_detail_only_recipient_slot():
    element = dict(extract_normative_elements(
        "The Director shall send the notice to the applicant."
    )[0])
    element["action"] = ["send the notice"]
    element["action_verb"] = "send"
    element["action_object"] = "the notice"
    element["action_recipient"] = ""
    element["action_recipient_details"] = [
        {
            "type": "recipient",
            "normalized_text": "the applicant",
            "span": [38, 51],
        }
    ]
    field_spans = dict(element.get("field_spans") or {})
    field_spans["action_recipient"] = [38, 51]
    element["field_spans"] = field_spans

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.recipient == "the applicant"
    assert norm.to_dict()["recipient"] == "the applicant"
    assert formula == "O(∀x (Director(x) → SendNotice(x)))"
    assert "Applicant" not in formula
    assert record["omitted_formula_slots"]["recipients"] == [
        {
            "value": "the applicant",
            "field": "recipient",
            "reason": "recipient is preserved in IR but omitted from unary deontic formula consequent",
            "span": [38, 51],
        }
    ]

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ir_formula_builder_uses_detail_only_condition_and_exception_alias_slots():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit if fees are paid unless inspection is incomplete."
    )[0])
    element["conditions"] = []
    element["exceptions"] = []
    element["condition_details"] = [
        {
            "type": "if",
            "condition_text": "fees are paid",
            "span": [39, 52],
        }
    ]
    element["exception_details"] = [
        {
            "type": "unless",
            "exception_text": "inspection is incomplete",
            "span": [60, 84],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.conditions[0]["condition_text"] == "fees are paid"
    assert norm.exceptions[0]["exception_text"] == "inspection is incomplete"
    assert formula == (
        "O(∀x (Director(x) ∧ FeesArePaid(x) ∧ ¬InspectionIsIncomplete(x) "
        "→ IssuePermit(x)))"
    )
    assert record["formula"] == formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_formula_record_preserves_capped_condition_slots_as_omitted_provenance():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit if all requirements are met."
    )[0])
    element["condition_details"] = [
        {"type": "if", "value": "all requirements are met", "span": [37, 61]},
        {"type": "if", "value": "fees are paid", "span": [63, 76]},
        {"type": "if", "value": "inspection is complete", "span": [78, 100]},
        {"type": "if", "value": "notice is posted", "span": [102, 118]},
        {"type": "if", "value": "records are retained", "span": [120, 140]},
    ]
    element["conditions"] = [record["value"] for record in element["condition_details"]]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ AllRequirementsAreMet(x) ∧ FeesArePaid(x) "
        "∧ InspectionIsComplete(x) → IssuePermit(x)))"
    )
    assert "NoticeIsPosted" not in formula
    assert "RecordsAreRetained" not in formula
    assert record["omitted_formula_slots"]["conditions"] == [
        {
            "value": "notice is posted",
            "field": "condition",
            "predicate": "NoticeIsPosted",
            "reason": "condition is preserved in IR but omitted from capped deontic formula antecedents",
            "span": [102, 118],
        },
        {
            "value": "records are retained",
            "field": "condition",
            "predicate": "RecordsAreRetained",
            "reason": "condition is preserved in IR but omitted from capped deontic formula antecedents",
            "span": [120, 140],
        },
    ]


def test_formula_record_preserves_capped_exception_slots_as_omitted_provenance():
    element = dict(extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0])
    element["exception_details"] = [
        {"type": "unless", "value": "approval is denied", "span": [45, 63]},
        {"type": "unless", "value": "the application is incomplete", "span": [65, 94]},
        {"type": "unless", "value": "the fee is unpaid", "span": [96, 113]},
        {"type": "unless", "value": "the site is unsafe", "span": [115, 133]},
    ]
    element["exceptions"] = [record["value"] for record in element["exception_details"]]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert "¬ApprovalIsDenied(x)" in formula
    assert "¬ApplicationIsIncomplete(x)" in formula
    assert "¬FeeIsUnpaid(x)" in formula
    assert "SiteIsUnsafe" not in formula
    assert record["omitted_formula_slots"]["exceptions"] == [
        {
            "value": "the site is unsafe",
            "field": "exception",
            "predicate": "SiteIsUnsafe",
            "reason": "exception is preserved in IR but omitted from capped deontic formula antecedents",
            "span": [115, 133],
        }
    ]


def test_ir_formula_record_preserves_blocked_reference_exception_slots():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert "cross_reference_requires_resolution" in record["parser_warnings"]
    assert "exception_requires_scope_review" in record["parser_warnings"]
    assert "cross_reference_requires_resolution" in record["blockers"]
    assert record["omitted_formula_slots"]["exceptions"][0]["value"] == "as provided in section 552"


def test_failure_to_prohibition_becomes_positive_obligation_formula():
    element = dict(extract_normative_elements(
        "No person shall fail to maintain records."
    )[0])
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "F"
    assert norm.action == "fail to maintain records"
    assert formula == "O(∀x (Person(x) → MaintainRecords(x)))"
    assert "FailToMaintainRecords" not in formula
    assert record["formula"] == formula
    assert record["modality"] == "F"
    assert record["proof_ready"] is True

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_refuse_to_prohibition_becomes_positive_obligation_formula():
    element = dict(extract_normative_elements(
        "No person shall refuse to permit inspection."
    )[0])
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "F"
    assert norm.action == "refuse to permit inspection"
    assert formula == "O(∀x (Person(x) → PermitInspection(x)))"
    assert "RefuseToPermitInspection" not in formula
    assert record["formula"] == formula
    assert record["modality"] == "F"
    assert record["proof_ready"] is True

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_neglect_and_omit_to_prohibitions_become_positive_obligation_formulas():
    examples = [
        (
            "No person shall neglect to maintain records.",
            "neglect to maintain records",
            "O(∀x (Person(x) → MaintainRecords(x)))",
            "NeglectToMaintainRecords",
        ),
        (
            "No person shall omit to file the report.",
            "omit to file the report",
            "O(∀x (Person(x) → FileReport(x)))",
            "OmitToFileReport",
        ),
    ]

    for text, expected_action, expected_formula, forbidden_predicate in examples:
        element = dict(extract_normative_elements(text)[0])
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "F"
        assert norm.action == expected_action
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert forbidden_predicate not in record["formula"]
        assert record["formula"] == expected_formula
        assert record["modality"] == "F"
        assert record["proof_ready"] is True

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ordinary_prohibition_remains_forbidden_formula():
    element = extract_normative_elements(
        "No person may discharge pollutants into the sewer."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.modality == "F"
    assert formula == "F(∀x (Person(x) → DischargePollutantsIntoSewer(x)))"
    assert "O(" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_formula_record_preserves_alias_only_reference_exception_omission():
    element = dict(extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0])
    element["exceptions"] = []
    element["exception_details"] = [
        {
            "type": "except",
            "clause_text": "as provided in section 552",
            "span": [46, 72],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    assert record["omitted_formula_slots"]["exceptions"] == [
        {
            "type": "except",
            "clause_text": "as provided in section 552",
            "span": [46, 72],
        }
    ]


def test_simple_substantive_exception_formula_record_is_proof_ready_with_resolution_note():
    element = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "exception_requires_scope_review" in norm.blockers
    assert record["formula"] == "O(∀x (Applicant(x) ∧ ¬ApprovalIsDenied(x) → ObtainPermit(x)))"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["blockers"] == norm.blockers
    assert record["parser_warnings"] == norm.quality.parser_warnings
    assert record["deterministic_resolution"] == {
        "type": "standard_substantive_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "exception": "approval is denied",
        "exception_span": norm.exceptions[0].get("span", []),
        "reason": "single substantive exception is represented as a negated formula antecedent",
    }


def test_reference_exception_formula_record_remains_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    assert "cross_reference_requires_resolution" in record["blockers"]
    assert "exception_requires_scope_review" in record["blockers"]


def test_local_scope_reference_exception_formula_record_is_proof_ready():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in this section."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "exception_requires_scope_review" in norm.blockers
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "AsProvidedThisSection" not in record["formula"]
    assert record["omitted_formula_slots"]["exceptions"][0]["value"] == "as provided in this section"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"] == {
        "type": "local_scope_reference_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "scopes": ["this section"],
        "exception_spans": [norm.exceptions[0].get("span", [])],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }


def test_local_scope_reference_exception_with_otherwise_formula_record_is_proof_ready():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as otherwise provided in this section."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "exception_requires_scope_review" in norm.blockers
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "AsOtherwiseProvidedThisSection" not in record["formula"]
    assert record["omitted_formula_slots"]["exceptions"][0]["value"] == (
        "as otherwise provided in this section"
    )
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"] == {
        "type": "local_scope_reference_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "scopes": ["this section"],
        "exception_spans": [norm.exceptions[0].get("span", [])],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }


def test_local_scope_cross_reference_detail_exception_formula_record_is_proof_ready():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in this section."
    )[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "target": "this",
            "raw_text": "this section",
            "span": [68, 80],
        }
    ]
    element["resolved_cross_references"] = []
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "exception_requires_scope_review" in norm.blockers
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "ThisSection" not in record["formula"]
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"] == {
        "type": "local_scope_reference_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "scopes": ["this section"],
        "exception_spans": [norm.exceptions[0].get("span", [])],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }


def test_local_scope_reference_condition_formula_record_is_proof_ready():
    element = extract_normative_elements(
        "Subject to this section, the Secretary shall publish the notice."
    )[0]
    element = dict(element)
    element["condition_details"] = [
        {"type": "subject_to", "value": "this section", "span": [11, 23]}
    ]
    element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "target": "this",
            "raw_text": "this section",
            "span": [11, 23],
        }
    ]
    element["resolved_cross_references"] = []
    element["parser_warnings"] = ["cross_reference_requires_resolution"]
    element["export_readiness"] = {"blockers": ["cross_reference_requires_resolution"]}
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "ThisSection" not in record["formula"]
    assert record["omitted_formula_slots"]["conditions"][0]["value"] == "this section"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"] == {
        "type": "local_scope_reference_condition",
        "resolved_blockers": ["cross_reference_requires_resolution"],
        "scopes": ["this section"],
        "condition_spans": [norm.conditions[0].get("span", [])],
        "reason": "local self-reference condition is exported as provenance outside the operative formula",
    }


def test_numbered_reference_exception_without_resolution_stays_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["omitted_formula_slots"]["exceptions"][0]["value"] == "as provided in section 552"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_batch_formula_records_resolve_same_document_numbered_reference_exception():
    reference_element = extract_normative_elements("The clerk shall maintain the index.")[0]
    reference_element = dict(reference_element)
    reference_element["canonical_citation"] = "section 552"

    exception_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    reference_norm = LegalNormIR.from_parser_element(reference_element)
    exception_norm = LegalNormIR.from_parser_element(exception_element)
    records = build_deontic_formula_records_from_irs([reference_norm, exception_norm])
    exception_record = records[1]

    assert exception_norm.proof_ready is False
    assert "cross_reference_requires_resolution" in exception_norm.blockers
    assert "exception_requires_scope_review" in exception_norm.blockers
    assert exception_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in exception_record["formula"]
    assert exception_record["omitted_formula_slots"]["exceptions"][0]["value"] == (
        "as provided in section 552"
    )
    assert exception_record["proof_ready"] is True
    assert exception_record["requires_validation"] is False
    assert exception_record["repair_required"] is False
    assert exception_record["deterministic_resolution"] == {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": sorted(set(exception_norm.blockers)),
        "references": ["section 552"],
        "exception_spans": [exception_norm.exceptions[0].get("span", [])],
        "reason": "reference-only exception is backed by explicit same-document cross-reference resolution",
    }


def test_batch_formula_records_do_not_resolve_absent_numbered_reference_exception():
    exception_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    exception_norm = LegalNormIR.from_parser_element(exception_element)

    records = build_deontic_formula_records_from_irs([exception_norm])
    record = records[0]

    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_batch_formula_records_resolve_complete_plural_section_list_exception():
    first_reference = extract_normative_elements("The clerk shall maintain the index.")[0]
    first_reference = dict(first_reference)
    first_reference["canonical_citation"] = "section 552"
    second_reference = extract_normative_elements("The agency shall keep records.")[0]
    second_reference = dict(second_reference)
    second_reference["canonical_citation"] = "section 553"

    exception_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    exception_element = dict(exception_element)
    exception_element["exception_details"] = [
        {
            "type": "cross_reference",
            "value": "as provided in sections 552 and 553",
            "span": [43, 82],
        }
    ]
    exception_element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "raw_text": "sections 552 and 553",
            "span": [58, 82],
        }
    ]
    exception_element["resolved_cross_references"] = []

    records = build_deontic_formula_records_from_irs(
        [
            LegalNormIR.from_parser_element(first_reference),
            LegalNormIR.from_parser_element(second_reference),
            LegalNormIR.from_parser_element(exception_element),
        ]
    )
    exception_record = records[2]

    assert exception_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Sections552And553" not in exception_record["formula"]
    assert exception_record["proof_ready"] is True
    assert exception_record["requires_validation"] is False
    assert exception_record["repair_required"] is False
    assert exception_record["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert exception_record["deterministic_resolution"]["references"] == [
        "section 552",
        "section 553",
    ]


def test_batch_formula_records_keep_partial_plural_section_list_exception_blocked():
    first_reference = extract_normative_elements("The clerk shall maintain the index.")[0]
    first_reference = dict(first_reference)
    first_reference["canonical_citation"] = "section 552"
    exception_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    exception_element = dict(exception_element)
    exception_element["exception_details"] = [
        {"type": "cross_reference", "value": "as provided in sections 552 and 553", "span": [43, 82]}
    ]
    exception_element["cross_reference_details"] = [
        {"reference_type": "section", "raw_text": "sections 552 and 553", "span": [58, 82]}
    ]
    exception_element["resolved_cross_references"] = []

    records = build_deontic_formula_records_from_irs(
        [LegalNormIR.from_parser_element(first_reference), LegalNormIR.from_parser_element(exception_element)]
    )

    assert records[1]["proof_ready"] is False
    assert records[1]["requires_validation"] is True
    assert records[1]["repair_required"] is True
    assert records[1]["deterministic_resolution"] == {}


def test_batch_formula_records_resolve_same_document_numbered_reference_condition():
    reference_element = extract_normative_elements("The clerk shall maintain the index.")[0]
    reference_element = dict(reference_element)
    reference_element["canonical_citation"] = "section 552"

    condition_element = extract_normative_elements(
        "Subject to section 552, the Secretary shall publish the notice."
    )[0]
    condition_element = dict(condition_element)
    condition_element["condition_details"] = [
        {"type": "subject_to", "value": "section 552", "span": [11, 22]}
    ]
    condition_element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [11, 22]}
    ]
    condition_element["resolved_cross_references"] = []

    reference_norm = LegalNormIR.from_parser_element(reference_element)
    condition_norm = LegalNormIR.from_parser_element(condition_element)
    records = build_deontic_formula_records_from_irs([reference_norm, condition_norm])
    condition_record = records[1]

    assert condition_norm.proof_ready is False
    assert "cross_reference_requires_resolution" in condition_norm.blockers
    assert condition_record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in condition_record["formula"]
    assert condition_record["omitted_formula_slots"]["conditions"][0]["value"] == "section 552"
    assert condition_record["proof_ready"] is True
    assert condition_record["requires_validation"] is False
    assert condition_record["repair_required"] is False
    assert condition_record["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_condition"
    )


def test_numbered_cross_reference_detail_does_not_use_local_scope_resolution():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "target": "552",
            "canonical_citation": "section 552",
            "span": [68, 79],
        }
    ]
    element["resolved_cross_references"] = []
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_same_document_reference_exception_uses_canonical_reference_text():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "target": "552",
            "canonical_citation": "section 552",
            "resolution_scope": "same_document",
            "source_id": "deontic:resolved-section-552",
        }
    ]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.resolved_cross_references[0]["value"] == "section 552"
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"] == {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "references": ["section 552"],
        "exception_spans": [norm.exceptions[0].get("span", [])],
        "reason": "reference-only exception is backed by explicit same-document cross-reference resolution",
    }


def test_resolved_same_document_reference_exception_formula_record_is_proof_ready():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "resolution_scope": "same_document",
            "source_id": "deontic:resolved-section-552",
        }
    ]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert "exception_requires_scope_review" in norm.blockers
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["omitted_formula_slots"]["exceptions"][0]["value"] == "as provided in section 552"
    assert record["deterministic_resolution"] == {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "references": ["section 552"],
        "exception_spans": [norm.exceptions[0].get("span", [])],
        "reason": "reference-only exception is backed by explicit same-document cross-reference resolution",
    }


def test_same_document_cross_reference_detail_exception_formula_record_is_proof_ready():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "resolution_scope": "same_document",
            "source_id": "deontic:resolved-section-552",
        }
    ]
    element["resolved_cross_references"] = []
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert norm.cross_references[0]["value"] == "section 552"
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"]["type"] == "resolved_same_document_reference_exception"
    assert record["deterministic_resolution"]["references"] == ["section 552"]


def test_external_resolved_reference_exception_formula_record_remains_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "resolution_scope": "external",
            "source_id": "external:section-552",
        }
    ]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["deterministic_resolution"] == {}
    assert "cross_reference_requires_resolution" in record["blockers"]


def test_mixed_substantive_and_reference_exception_formula_record_remains_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["exception_details"] = list(element["exception_details"]) + [
        {"type": "unless", "value": "publication is impossible", "span": [0, 0]}
    ]
    element["resolved_cross_references"] = [
        {"reference_type": "section", "canonical_citation": "section 552", "target": "552", "same_document": True}
    ]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["deterministic_resolution"] == {}


def test_override_with_exception_formula_record_remains_blocked():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the applicant shall obtain a permit unless approval is denied."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["deterministic_resolution"] == {}
    assert "override_clause_requires_precedence_review" in record["blockers"]


def test_local_applicability_formula_record_is_proof_ready_with_resolution_note():
    element = extract_normative_elements("This section applies to food carts.")[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert record["formula"] == "AppliesTo(ThisSection, FoodCarts)"
    assert record["target_logic"] == "frame_logic"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["blockers"] == norm.blockers
    assert record["parser_warnings"] == norm.quality.parser_warnings
    assert record["deterministic_resolution"] == {
        "type": "local_scope_applicability",
        "resolved_blockers": sorted(set(norm.blockers)),
        "scope": "this section",
        "reason": "local self-scope applicability formula is source-grounded",
    }


def test_external_applicability_formula_record_remains_blocked():
    element = extract_normative_elements("The chapter applies to food carts.")[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "AppliesTo(Chapter, FoodCarts)"
    assert record["target_logic"] == "frame_logic"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["deterministic_resolution"] == {}
    assert "cross_reference_requires_resolution" in record["blockers"]


def test_pure_override_formula_record_is_proof_ready_with_resolution_note():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "P(∀x (Director(x) → IssueVariance(x)))"
    assert "Section501020" not in record["formula"]
    assert norm.proof_ready is False
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["omitted_formula_slots"]["overrides"][0]["value"] == "section 5.01.020"
    assert "override_clause_requires_precedence_review" in record["blockers"]
    assert "cross_reference_requires_resolution" in record["blockers"]
    assert record["deterministic_resolution"] == {
        "type": "pure_precedence_override",
        "resolved_blockers": sorted(set(norm.blockers)),
        "override": "section 5.01.020",
        "override_span": norm.overrides[0].get("span", []),
        "reason": (
            "single source-grounded precedence override is exported as provenance "
            "outside the operative formula"
        ),
    }


def test_conditional_override_formula_record_remains_blocked():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance if hardship is shown."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "P(∀x (Director(x) ∧ HardshipIsShown(x) → IssueVariance(x)))"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["deterministic_resolution"] == {}
    assert "override_clause_requires_precedence_review" in record["blockers"]


def test_ir_preserves_enumerated_child_provenance_in_formula_record():
    elements = extract_normative_elements(
        "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records.",
        expand_enumerations=True,
    )
    element = elements[1]
    norm = LegalNormIR.from_parser_element(element)

    record = build_deontic_formula_record_from_ir(norm)

    assert norm.is_enumerated_child is True
    assert norm.parent_source_id == element["parent_source_id"]
    assert norm.enumeration_label == "2"
    assert norm.enumeration_index == 2
    assert norm.to_dict()["parent_source_id"] == element["parent_source_id"]
    assert norm.to_dict()["enumeration_label"] == "2"
    assert norm.to_dict()["enumeration_index"] == 2
    assert norm.to_dict()["is_enumerated_child"] is True
    assert record["formula"] == "O(∀x (Secretary(x) → SubmitReport(x)))"
    assert record["parent_source_id"] == element["parent_source_id"]
    assert record["enumeration_label"] == "2"
    assert record["enumeration_index"] == 2
    assert record["is_enumerated_child"] is True
    assert record["proof_ready"] is True


def test_ir_derives_enumeration_index_from_alpha_label_when_index_missing():
    element = extract_normative_elements(
        "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records.",
        expand_enumerations=True,
    )[0]
    element = dict(element)
    element["enumeration_label"] = "b"
    element.pop("enumeration_index", None)

    norm = LegalNormIR.from_parser_element(element)

    assert norm.enumeration_label == "b"
    assert norm.enumeration_index == 2
    assert norm.is_enumerated_child is True
    assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_build_deontic_formula_records_from_irs_preserves_order_and_provenance():
    elements = extract_normative_elements(
        "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records.",
        expand_enumerations=True,
    )
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    records = build_deontic_formula_records_from_irs(norms)

    assert [record["formula"] for record in records] == [
        "O(∀x (Secretary(x) → EstablishProcedures(x)))",
        "O(∀x (Secretary(x) → SubmitReport(x)))",
        "O(∀x (Secretary(x) → MaintainRecords(x)))",
    ]
    assert [record["enumeration_index"] for record in records] == [1, 2, 3]
    assert all(record["parent_source_id"] == elements[0]["parent_source_id"] for record in records)
    assert all(record["is_enumerated_child"] is True for record in records)


def test_parser_element_to_formula_record_matches_ir_record():
    element = extract_normative_elements("A permit is not required for emergency work.")[0]
    norm = LegalNormIR.from_parser_element(element)

    assert parser_element_to_formula_record(element) == build_deontic_formula_record_from_ir(norm)
    assert parser_element_to_formula_record(element)["target_logic"] == "frame_logic"


def test_ir_formula_builder_prefers_narrow_value_alias_over_broad_normalized_text():
    element = extract_normative_elements(
        "The Director shall issue a permit if all requirements are met within 10 days after application "
        "unless the application is incomplete."
    )[0]
    element = dict(element)
    element["condition_details"] = [
        {
            "normalized_text": "all requirements are met within 10 days after application unless the application is incomplete",
            "value": "all requirements are met",
            "raw_text": "all requirements are met within 10 days after application unless the application is incomplete",
        }
    ]
    element["temporal_constraint_details"] = [
        {"type": "deadline", "value": "10 days after application"}
    ]
    element["exception_details"] = [{"value": "the application is incomplete"}]

    norm = LegalNormIR.from_parser_element(element)

    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ AllRequirementsAreMet(x) ∧ Deadline10DaysAfterApplication(x) "
        "∧ ¬ApplicationIsIncomplete(x) → IssuePermit(x)))"
    )


def test_ir_formula_builder_uses_structured_temporal_duration_and_anchor():
    element = extract_normative_elements(
        "The Director shall issue a permit within 10 days after application."
    )[0]
    element = dict(element)
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "duration": "10 days",
            "anchor_event": "application",
            "span": [34, 66],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.temporal_constraints[0]["duration"] == "10 days"
    assert norm.temporal_constraints[0]["anchor_event"] == "application"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ Deadline10DaysAfterApplication(x) → IssuePermit(x)))"
    )


def test_ir_temporal_value_alias_is_derived_from_structured_duration_and_anchor():
    element = extract_normative_elements(
        "The Director shall issue a permit within 10 days after application."
    )[0]
    element = dict(element)
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "duration": "10 days",
            "anchor_event": "application",
            "span": [34, 66],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.temporal_constraints == [
        {
            "type": "deadline",
            "duration": "10 days",
            "anchor_event": "application",
            "span": [34, 66],
            "value": "10 days after application",
        }
    ]
    assert norm.to_dict()["temporal_constraints"][0]["value"] == "10 days after application"
    assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_ir_formula_builder_uses_structured_temporal_before_anchor_relation():
    element = extract_normative_elements(
        "The Director shall issue a permit within 10 days after application."
    )[0]
    element = dict(element)
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "duration": "10 days",
            "anchor_event": "hearing",
            "anchor_relation": "before",
            "span": [34, 58],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.temporal_constraints[0]["span"] == [34, 58]
    assert norm.temporal_constraints[0]["value"] == "10 days before hearing"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ Deadline10DaysBeforeHearing(x) → IssuePermit(x)))"
    )


def test_ir_formula_builder_suppresses_base_deadline_when_whichever_modifier_present():
    element = extract_normative_elements(
        "The Director shall complete review within 30 days after application."
    )[0]
    element = dict(element)
    element["action"] = ["complete review"]
    element["action_verb"] = "complete"
    element["action_object"] = "review"
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "value": "30 days after application or 10 days after inspection",
            "span": [43, 96],
        },
        {
            "type": "deadline",
            "value": "30 days after application or 10 days after inspection whichever is earlier",
            "span": [43, 117],
        },
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ "
        "Deadline30DaysAfterApplicationOr10DaysAfterInspectionWhicheverIsEarlier(x) "
        "→ CompleteReview(x)))"
    )
    assert "Deadline30DaysAfterApplicationOr10DaysAfterInspection(x)" not in formula


def test_parser_and_formula_capture_whichever_is_earlier_deadline():
    element = extract_normative_elements(
        "The Director shall issue a permit within 10 days after application or "
        "5 days after hearing, whichever is earlier."
    )[0]
    norm = LegalNormIR.from_parser_element(element)
    temporal_values = [item.get("value") for item in norm.temporal_constraints]

    assert any(
        item.get("temporal_kind") == "whichever_is_earlier"
        for item in element["temporal_constraint_details"]
    )
    assert "10 days after application or 5 days after hearing, whichever is earlier" in temporal_values
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ "
        "Deadline10DaysAfterApplicationOr5DaysAfterHearingWhicheverIsEarlier(x) "
        "→ IssuePermit(x)))"
    )


def test_parser_and_formula_capture_whichever_is_later_deadline():
    element = extract_normative_elements(
        "The Director shall complete review within 30 days after application or "
        "10 days after inspection, whichever is later."
    )[0]
    norm = LegalNormIR.from_parser_element(element)
    temporal_values = [item.get("value") for item in norm.temporal_constraints]

    assert any(
        item.get("temporal_kind") == "whichever_is_later"
        for item in element["temporal_constraint_details"]
    )
    assert "30 days after application or 10 days after inspection, whichever is later" in temporal_values
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ "
        "Deadline30DaysAfterApplicationOr10DaysAfterInspectionWhicheverIsLater(x) "
        "→ CompleteReview(x)))"
    )


def test_parser_and_formula_capture_not_more_than_deadline():
    element = extract_normative_elements(
        "The Director shall issue a permit not more than 10 days after the application is complete."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "issue a permit"
    assert norm.temporal_constraints[0]["type"] == "deadline"
    assert norm.temporal_constraints[0]["temporal_kind"] == "not_more_than"
    assert norm.temporal_constraints[0]["value"] == "10 days after the application is complete"
    assert norm.temporal_constraints[0]["anchor"] == "the application is complete"
    assert norm.temporal_constraints[0]["quantity"] == 10
    assert norm.temporal_constraints[0]["unit"] == "day"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ Deadline10DaysAfterApplicationIsComplete(x) → IssuePermit(x)))"
    )


def test_parser_and_formula_capture_no_later_than_deadline():
    element = extract_normative_elements(
        "The Secretary shall publish notice no later than 30 calendar days after receipt of the application."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "publish notice"
    assert norm.temporal_constraints[0]["temporal_kind"] == "no_later_than"
    assert norm.temporal_constraints[0]["value"] == "30 calendar days after receipt of the application"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Secretary(x) ∧ Deadline30CalendarDaysAfterReceiptApplication(x) "
        "→ PublishNotice(x)))"
    )


def test_parser_and_formula_capture_after_notice_and_hearing_prerequisite():
    element = extract_normative_elements(
        "The Commission shall adopt rules after notice and hearing."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "adopt rules"
    assert norm.temporal_constraints == [
        {
            "type": "procedure",
            "temporal_kind": "after_notice_and_hearing",
            "value": "after notice and hearing",
            "anchor": "",
            "quantity": None,
            "unit": "",
            "calendar": "",
            "anchor_event": "",
            "direction": "",
            "raw_text": "after notice and hearing",
            "normalized_text": "after notice and hearing",
            "span": [33, 57],
        }
    ]
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Commission(x) ∧ ProcedureAfterNoticeAndHearing(x) → AdoptRules(x)))"
    )


def test_parser_and_formula_capture_upon_receipt_prerequisite():
    element = extract_normative_elements(
        "Upon receipt of an application, the Bureau shall inspect the premises before approval."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert element["procedure"]["trigger_event"] == "application"
    assert {
        "event": "inspection",
        "relation": "triggered_by_receipt_of",
        "anchor_event": "application",
        "raw_text": "Upon receipt of an application",
        "span": [0, 30],
    } in element["procedure"]["event_relations"]
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Bureau(x) ∧ ProcedureUponReceiptApplication(x) → InspectPremises(x)))"
    )


def test_non_receipt_procedure_ordering_does_not_add_receipt_prerequisite():
    element = extract_normative_elements(
        "The Bureau shall inspect the premises before approval."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert all(
        relation.get("relation") != "triggered_by_receipt_of"
        for relation in element.get("procedure", {}).get("event_relations", [])
    )
    assert formula == "O(∀x (Bureau(x) → InspectPremises(x)))"
    assert "ProcedureUponReceipt" not in formula


def test_after_notice_without_hearing_does_not_use_notice_and_hearing_prerequisite():
    element = extract_normative_elements(
        "The Commission shall adopt rules after notice is mailed."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "adopt rules"
    assert all(
        constraint.get("temporal_kind") != "after_notice_and_hearing"
        for constraint in norm.temporal_constraints
    )
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Commission(x) → AdoptRules(x)))"
    )


def test_parser_and_formula_capture_after_public_notice_and_hearing_prerequisite():
    text = "The Commission shall adopt rules after public notice and hearing."

    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "adopt rules"
    assert {
        "type": "procedure",
        "temporal_kind": "after_notice_and_hearing",
        "value": "after public notice and hearing",
        "anchor": "",
        "quantity": None,
        "unit": "",
        "calendar": "",
        "anchor_event": "",
        "direction": "",
        "raw_text": "after public notice and hearing",
        "normalized_text": "after public notice and hearing",
        "span": [33, 64],
    } in norm.temporal_constraints
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Commission(x) ∧ ProcedureAfterPublicNoticeAndHearing(x) "
        "→ AdoptRules(x)))"
    )


def test_after_public_notice_without_hearing_does_not_use_notice_and_hearing_prerequisite():
    element = extract_normative_elements(
        "The Commission shall adopt rules after public notice is mailed."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "adopt rules"
    assert all(
        constraint.get("temporal_kind") != "after_notice_and_hearing"
        for constraint in norm.temporal_constraints
    )
    formula = build_deontic_formula_from_ir(norm)
    assert formula == "O(∀x (Commission(x) → AdoptRules(x)))"
    assert "ProcedureAfterPublicNoticeAndHearing" not in formula


def test_public_notice_and_hearing_patch_keeps_numbered_reference_repair_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    record = build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(element))

    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_parser_and_formula_capture_after_consultation_prerequisite():
    text = "The Director shall adopt rules after consultation with the advisory committee."

    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)

    consultation_constraints = [
        constraint
        for constraint in norm.temporal_constraints
        if constraint.get("temporal_kind") == "after_consultation"
    ]
    assert len(consultation_constraints) == 1
    consultation = consultation_constraints[0]
    assert consultation["type"] == "procedure"
    assert consultation["value"] == "after consultation with the advisory committee"
    assert consultation["raw_text"] == "after consultation with the advisory committee"
    assert consultation["normalized_text"] == "after consultation with the advisory committee"
    assert text[consultation["span"][0] : consultation["span"][1]] == (
        "after consultation with the advisory committee"
    )
    assert norm.actor == "Director"
    assert norm.action == "adopt rules"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureAfterConsultationAdvisoryCommittee(x) "
        "→ AdoptRules(x)))"
    )


def test_consultation_phrase_without_after_does_not_add_procedure_prerequisite():
    text = "The Director shall provide consultation with the advisory committee."

    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)

    assert norm.action == "provide consultation with the advisory committee"
    assert all(
        constraint.get("temporal_kind") != "after_consultation"
        for constraint in norm.temporal_constraints
    )
    formula = build_deontic_formula_from_ir(norm)
    assert formula == "O(∀x (Director(x) → ProvideConsultationAdvisoryCommittee(x)))"
    assert "ProcedureAfterConsultation" not in formula


def test_after_consultation_patch_keeps_numbered_reference_repair_blocked():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    record = build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(element))

    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_ir_formula_suppresses_base_deadline_when_whichever_variant_is_later_in_ir_order():
    element = extract_normative_elements(
        "The Director shall complete review within 30 days after application or "
        "10 days after inspection, whichever is later."
    )[0]
    element = dict(element)
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "value": "30 days after application or 10 days after inspection",
            "span": [43, 95],
        },
        {
            "type": "deadline",
            "temporal_kind": "whichever_is_later",
            "value": "30 days after application or 10 days after inspection, whichever is later",
            "span": [43, 116],
        },
    ]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ "
        "Deadline30DaysAfterApplicationOr10DaysAfterInspectionWhicheverIsLater(x) "
        "→ CompleteReview(x)))"
    )
    assert "Deadline30DaysAfterApplicationOr10DaysAfterInspection(x)" not in formula


def test_applicability_formula_targets_regulated_entity_not_apply_artifact():
    element = extract_normative_elements("This section applies to food carts and mobile vendors.")[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.norm_type == "applicability"
    assert norm.modality == "APP"
    assert norm.support_span == norm.source_span
    assert formula == "AppliesTo(ThisSection, FoodCartsAndMobileVendors)"
    assert "ApplyFood" not in formula


def test_apply_action_is_preserved_for_non_applicability_obligations():
    element = extract_normative_elements("The Director shall apply the standards.")[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.norm_type == "obligation"
    assert norm.modality == "O"
    assert norm.action == "apply the standards"
    assert element["parser_warnings"] == []
    assert formula == "O(∀x (Director(x) → ApplyStandards(x)))"


def test_formula_recovers_leading_mens_rea_from_action_slot():
    element = extract_normative_elements(
        "No person may knowingly discharge pollutants into the sewer."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.action == "knowingly discharge pollutants into the sewer"
    assert formula == (
        "F(∀x (Person(x) ∧ Knowingly(x) → DischargePollutantsIntoSewer(x)))"
    )
    assert "KnowinglyDischargePollutantsIntoSewer" not in formula


def test_formula_prefers_structured_mens_rea_slot_over_action_fallback():
    element = extract_normative_elements(
        "No person may knowingly discharge pollutants into the sewer."
    )[0]
    element = dict(element)
    element["mental_state"] = "willfully"
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.mental_state == "willfully"
    assert norm.action == "knowingly discharge pollutants into the sewer"
    assert formula == (
        "F(∀x (Person(x) ∧ Willfully(x) → DischargePollutantsIntoSewer(x)))"
    )
    assert "Knowingly(x)" not in formula


def test_ir_formula_preserves_multiple_structured_actor_subjects():
    element = extract_normative_elements("The Director shall issue a permit.")[0]
    element = dict(element)
    element["subject"] = ["Director", "Commissioner"]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.actor == "Director"
    assert norm.actor_entities == ["Director", "Commissioner"]
    assert norm.to_dict()["actor"] == "Director"
    assert norm.to_dict()["actor_entities"] == ["Director", "Commissioner"]
    assert formula == (
        "O(∀x ((Director(x) ∨ Commissioner(x)) → IssuePermit(x)))"
    )


def test_ir_formula_deduplicates_multiple_actor_aliases():
    element = extract_normative_elements("The Director shall issue a permit.")[0]
    element = dict(element)
    element["subject"] = ["Director", "the Director", "Commissioner"]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.actor == "Director"
    assert norm.actor_entities == ["Director", "the Director", "Commissioner"]
    assert formula == (
        "O(∀x ((Director(x) ∨ Commissioner(x)) → IssuePermit(x)))"
    )
    assert formula.count("Director(x)") == 1
    assert formula.count("Commissioner(x)") == 1


def test_ir_preserves_legacy_slot_lists_when_detail_records_are_absent():
    element = extract_normative_elements(
        "The Director shall issue a permit if all requirements are met within 10 days after application "
        "unless the application is incomplete."
    )[0]
    element = dict(element)
    element["conditions"] = ["all requirements are met"]
    element["condition_details"] = []
    element["temporal_constraints"] = ["10 days after application"]
    element["temporal_constraint_details"] = []
    element["exceptions"] = ["the application is incomplete"]
    element["exception_details"] = []

    norm = LegalNormIR.from_parser_element(element)

    assert norm.conditions == [{"value": "all requirements are met"}]
    assert norm.temporal_constraints == [
        {"value": "10 days after application", "type": "deadline"}
    ]
    assert norm.exceptions == [{"value": "the application is incomplete"}]
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ AllRequirementsAreMet(x) ∧ Deadline10DaysAfterApplication(x) "
        "∧ ¬ApplicationIsIncomplete(x) → IssuePermit(x)))"
    )


def test_ir_prefers_rich_detail_records_over_legacy_slot_lists():
    element = extract_normative_elements(
        "The Director shall issue a permit if all requirements are met within 10 days after application."
    )[0]
    element = dict(element)
    element["conditions"] = ["legacy broad condition"]
    element["condition_details"] = [
        {"normalized_text": "all requirements are met", "raw_text": "all requirements are met", "span": [37, 61]}
    ]
    element["temporal_constraints"] = ["legacy deadline"]
    element["temporal_constraint_details"] = [
        {"type": "deadline", "value": "10 days after application", "span": [69, 94]}
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.conditions[0]["value"] == "all requirements are met"
    assert norm.conditions[0]["normalized_text"] == "all requirements are met"
    assert norm.temporal_constraints[0]["value"] == "10 days after application"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ AllRequirementsAreMet(x) ∧ Deadline10DaysAfterApplication(x) "
        "→ IssuePermit(x)))"
    )


def test_ir_fallback_preserves_legacy_cross_reference_slots():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_references"] = ["section 552"]
    element["cross_reference_details"] = []

    norm = LegalNormIR.from_parser_element(element)

    assert norm.cross_references == [{"value": "section 552"}]
    assert norm.to_dict()["cross_references"] == [{"value": "section 552"}]


def test_ir_cross_reference_value_alias_prefers_canonical_citation():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_references"] = ["section 552"]
    element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "span": [62, 73],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.cross_references == [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "span": [62, 73],
            "value": "section 552",
        }
    ]


def test_ir_cross_reference_value_alias_synthesizes_section_label_from_target():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [62, 73]}
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.cross_references == [
        {"reference_type": "section", "target": "552", "span": [62, 73], "value": "section 552"}
    ]
    assert norm.to_dict()["cross_references"][0]["value"] == "section 552"


def test_ir_resolved_cross_reference_value_alias_prefers_canonical_citation():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    element = dict(element)
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 5.01.020",
            "target_source_id": "deontic:resolved-section-501020",
            "span": [16, 32],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.resolved_cross_references == [
        {
            "reference_type": "section",
            "canonical_citation": "section 5.01.020",
            "target_source_id": "deontic:resolved-section-501020",
            "span": [16, 32],
            "value": "section 5.01.020",
        }
    ]


def test_override_clause_is_provenance_not_formula_antecedent():
    text = "Notwithstanding section 5.01.020, the Director may issue a variance."
    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert formula == "P(∀x (Director(x) → IssueVariance(x)))"
    assert build_deontic_formula(element) == formula
    assert "Section501020" not in formula
    assert norm.overrides == [
        {
            "type": "override",
            "clause_type": "notwithstanding",
            "raw_text": "section 5.01.020",
            "normalized_text": "section 5.01.020",
            "span": [16, 32],
            "clause_span": [0, 33],
            "value": "section 5.01.020",
        }
    ]
    assert "override_clause_requires_precedence_review" in norm.quality.parser_warnings
    assert norm.proof_ready is False


def test_override_exclusion_preserves_true_condition_predicates():
    text = (
        "Subject to approval, notwithstanding section 5.01.020, "
        "the Director may issue a variance."
    )
    element = extract_normative_elements(text)[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.conditions[0]["value"] == "approval"
    assert norm.overrides[0]["value"] == "section 5.01.020"
    assert formula == "P(∀x (Director(x) ∧ Approval(x) → IssueVariance(x)))"
    assert "Section501020" not in formula
    assert "cross_reference_requires_resolution" in norm.quality.parser_warnings
    assert "override_clause_requires_precedence_review" in norm.quality.parser_warnings


def test_cross_reference_exception_is_provenance_not_formula_antecedent():
    text = "The Secretary shall publish the notice except as provided in section 552."
    element = extract_normative_elements(text)[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [62, 73]}
    ]
    element["exception_details"] = [
        {
            "type": "cross_reference",
            "raw_text": "as provided in section 552",
            "normalized_text": "as provided in section 552",
            "span": [43, 73],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.cross_references[0]["value"] == "section 552"
    assert formula == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert build_deontic_formula(element) == formula
    assert "AsProvidedSection552" not in formula
    assert "cross_reference_requires_resolution" in norm.quality.parser_warnings
    assert norm.proof_ready is False


def test_structured_reference_exception_is_excluded_even_without_intro_phrase():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [62, 73]}
    ]
    element["exception_details"] = [
        {"reference_type": "section", "target": "552", "span": [62, 73]}
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.exceptions[0]["value"] == "section 552"
    assert build_deontic_formula_from_ir(norm) == "O(∀x (Secretary(x) → PublishNotice(x)))"


def test_substantive_exception_remains_formula_antecedent():
    element = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Applicant(x) ∧ ¬ApprovalIsDenied(x) → ObtainPermit(x)))"
    )


def test_cross_reference_condition_is_provenance_not_formula_antecedent():
    text = "Subject to section 552, the Secretary shall publish the notice."
    element = extract_normative_elements(text)[0]
    element = dict(element)
    element["condition_details"] = [
        {
            "type": "subject_to",
            "raw_text": "section 552",
            "normalized_text": "section 552",
            "span": [11, 22],
        }
    ]
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [11, 22]}
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.conditions[0]["value"] == "section 552"
    assert norm.cross_references[0]["value"] == "section 552"
    assert formula == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert build_deontic_formula(element) == formula
    assert "Section552" not in formula
    assert "cross_reference_requires_resolution" in norm.quality.parser_warnings
    assert norm.proof_ready is False


def test_resolved_reference_condition_is_still_not_a_factual_antecedent():
    text = "Subject to section 552, the Secretary shall publish the notice."
    element = extract_normative_elements(text)[0]
    element = dict(element)
    element["condition_details"] = [
        {"type": "subject_to", "value": "section 552", "span": [11, 22]}
    ]
    element["resolved_cross_references"] = [
        {"reference_type": "section", "canonical_citation": "section 552", "target": "552"}
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert build_deontic_formula_from_ir(norm) == "O(∀x (Secretary(x) → PublishNotice(x)))"


def test_substantive_subject_to_condition_remains_formula_antecedent():
    element = extract_normative_elements(
        "Subject to approval, the Director shall issue a permit."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    formula = build_deontic_formula_from_ir(norm)

    assert norm.conditions[0]["value"] == "approval"
    assert formula == "O(∀x (Director(x) ∧ Approval(x) → IssuePermit(x)))"


def test_multiple_substantive_conditions_remain_formula_antecedents():
    element = extract_normative_elements(
        "The Director shall issue a permit if all requirements are met."
    )[0]
    element = dict(element)
    element["condition_details"] = [
        {
            "type": "if",
            "value": "all requirements are met",
            "raw_text": "all requirements are met",
            "span": [37, 61],
        },
        {
            "type": "when",
            "value": "fees are paid",
            "raw_text": "fees are paid",
            "span": [0, 0],
        },
        {
            "type": "provided_that",
            "value": "inspection is complete",
            "raw_text": "inspection is complete",
            "span": [0, 0],
        },
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.conditions[0]["span"] == [37, 61]
    assert formula == (
        "O(∀x (Director(x) ∧ AllRequirementsAreMet(x) ∧ FeesArePaid(x) "
        "∧ InspectionIsComplete(x) → IssuePermit(x)))"
    )
    assert build_deontic_formula(element) == formula


def test_duplicate_condition_aliases_are_not_repeated_in_formula():
    element = extract_normative_elements(
        "The Director shall issue a permit if all requirements are met."
    )[0]
    element = dict(element)
    element["condition_details"] = [
        {"type": "if", "value": "all requirements are met", "span": [37, 61]},
        {"type": "if", "normalized_text": "all requirements are met", "span": [37, 61]},
        {"type": "when", "value": "fees are paid", "span": [0, 0]},
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ AllRequirementsAreMet(x) ∧ FeesArePaid(x) "
        "→ IssuePermit(x)))"
    )
    assert formula.count("AllRequirementsAreMet(x)") == 1


def test_reference_condition_filtering_preserves_other_substantive_conditions():
    text = "Subject to section 552, the Secretary shall publish the notice."
    element = extract_normative_elements(text)[0]
    element = dict(element)
    element["condition_details"] = [
        {"type": "subject_to", "value": "section 552", "span": [11, 22]},
        {"type": "if", "value": "notice is complete", "span": [0, 0]},
        {"type": "when", "value": "publication is required", "span": [0, 0]},
    ]
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [11, 22]}
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.cross_references[0]["value"] == "section 552"
    assert formula == (
        "O(∀x (Secretary(x) ∧ NoticeIsComplete(x) ∧ PublicationIsRequired(x) "
        "→ PublishNotice(x)))"
    )
    assert "Section552" not in formula
    assert "cross_reference_requires_resolution" in norm.quality.parser_warnings
    assert norm.proof_ready is False


def test_resolved_reference_condition_formula_record_is_proof_ready_without_reference_predicate():
    text = "Subject to section 552, the Secretary shall publish the notice."
    element = extract_normative_elements(text)[0]
    element = dict(element)
    element["condition_details"] = [
        {"type": "subject_to", "value": "section 552", "span": [11, 22]}
    ]
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [11, 22]}
    ]
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "same_document": True,
            "source_id": "deontic:resolved-section-552",
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.proof_ready is False
    assert "cross_reference_requires_resolution" in norm.blockers
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["omitted_formula_slots"]["conditions"][0]["value"] == "section 552"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"] == {
        "type": "resolved_same_document_reference_condition",
        "resolved_blockers": sorted(set(norm.blockers)),
        "references": ["section 552"],
        "condition_spans": [norm.conditions[0].get("span", [])],
        "reason": "reference-only condition is backed by explicit same-document cross-reference resolution",
    }


def test_unresolved_reference_condition_formula_record_stays_blocked():
    text = "Subject to section 552, the Secretary shall publish the notice."
    element = extract_normative_elements(text)[0]
    element = dict(element)
    element["condition_details"] = [
        {"type": "subject_to", "value": "section 552", "span": [11, 22]}
    ]
    element["cross_reference_details"] = [
        {"reference_type": "section", "target": "552", "span": [11, 22]}
    ]
    element["resolved_cross_references"] = []

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["omitted_formula_slots"]["conditions"][0]["value"] == "section 552"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_batch_formula_records_resolve_reference_exception_from_section_context():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "552"}

    records = build_deontic_formula_records_from_irs(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert records[0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in records[0]["formula"]
    assert records[0]["proof_ready"] is True
    assert records[0]["requires_validation"] is False
    assert records[0]["repair_required"] is False
    assert records[0]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert records[0]["deterministic_resolution"]["references"] == ["section 552"]


def test_batch_formula_records_resolve_section_symbol_reference_exception_from_section_context():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in § 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "552"}

    records = build_deontic_formula_records_from_irs(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert records[0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in records[0]["formula"]
    assert records[0]["proof_ready"] is True
    assert records[0]["requires_validation"] is False
    assert records[0]["repair_required"] is False
    assert records[0]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert records[0]["deterministic_resolution"]["references"] == ["section 552"]


def test_batch_formula_records_keep_section_symbol_reference_exception_blocked_without_context():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in § 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "553"}

    records = build_deontic_formula_records_from_irs(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert records[0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in records[0]["formula"]
    assert records[0]["proof_ready"] is False
    assert records[0]["requires_validation"] is True
    assert records[0]["repair_required"] is True
    assert records[0]["deterministic_resolution"] == {}


def test_batch_formula_records_do_not_resolve_reference_exception_from_mismatched_section_context():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "553"}

    records = build_deontic_formula_records_from_irs(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert records[0]["proof_ready"] is False
    assert records[0]["requires_validation"] is True
    assert records[0]["repair_required"] is True
    assert records[0]["deterministic_resolution"] == {}


def test_ir_defined_term_value_alias_prefers_term_field():
    element = extract_normative_elements(
        'In this section, the term "food cart" means a mobile food vending unit.'
    )[0]
    element = dict(element)
    element["defined_term_refs"] = [
        {
            "term": "food cart",
            "definition": "a mobile food vending unit",
            "scope": "section",
            "span": [27, 36],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.defined_terms == [
        {
            "term": "food cart",
            "definition": "a mobile food vending unit",
            "scope": "section",
            "span": [27, 36],
            "value": "food cart",
        }
    ]
    assert norm.to_dict()["defined_terms"][0]["value"] == "food cart"


def test_ir_ontology_terms_get_stable_value_aliases():
    element = extract_normative_elements(
        "The Bureau may inspect the premises during business hours."
    )[0]
    element = dict(element)
    element["ontology_terms"] = [
        {
            "term": "premises",
            "category": "regulated_property",
            "span": [23, 35],
        },
        {
            "name": "inspection",
            "category": "procedure_event",
            "span": [15, 22],
        },
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.ontology_terms == [
        {
            "term": "premises",
            "category": "regulated_property",
            "span": [23, 35],
            "value": "premises",
        },
        {
            "name": "inspection",
            "category": "procedure_event",
            "span": [15, 22],
            "value": "inspection",
        },
    ]
    assert norm.to_dict()["ontology_terms"][0]["value"] == "premises"


def test_ir_kg_relationship_hints_get_stable_value_aliases():
    element = extract_normative_elements(
        "The Bureau may inspect the premises during business hours."
    )[0]
    element = dict(element)
    element["kg_relationship_hints"] = [
        {
            "subject": "Bureau",
            "predicate": "mayInspect",
            "object": "the premises during business hours",
        }
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.kg_relationship_hints == [
        {
            "subject": "Bureau",
            "predicate": "mayInspect",
            "object": "the premises during business hours",
            "value": "Bureau mayInspect the premises during business hours",
        }
    ]
    assert norm.to_dict()["kg_relationship_hints"][0]["value"] == (
        "Bureau mayInspect the premises during business hours"
    )
    assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_ir_penalty_record_gets_stable_value_alias_from_structured_slots():
    element = extract_normative_elements(
        "A violation is punishable by a civil fine of not less than $100 and not more than $500 per violation."
    )[0]
    element = dict(element)
    element["penalty"] = {
        "sanction_class": "civil_fine",
        "modality": "mandatory",
        "fine_min": "$100",
        "fine_max": "$500",
        "recurrence": "per violation",
    }

    norm = LegalNormIR.from_parser_element(element)

    assert norm.penalty == {
        "sanction_class": "civil_fine",
        "modality": "mandatory",
        "fine_min": "$100",
        "fine_max": "$500",
        "recurrence": "per violation",
        "value": "mandatory civil_fine from $100 to $500 per violation",
    }
    assert norm.to_dict()["penalty"]["value"] == (
        "mandatory civil_fine from $100 to $500 per violation"
    )
    assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_ir_procedure_record_gets_stable_value_alias_from_event_chain():
    element = extract_normative_elements(
        "Upon receipt of an application, the Bureau shall inspect the premises before approval."
    )[0]
    element = dict(element)
    element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "inspection",
        "event_chain": ["application", "inspection", "approval"],
    }

    norm = LegalNormIR.from_parser_element(element)

    assert norm.procedure == {
        "trigger_event": "application",
        "terminal_event": "inspection",
        "event_chain": ["application", "inspection", "approval"],
        "value": "application -> inspection -> approval",
    }
    assert norm.to_dict()["procedure"]["value"] == "application -> inspection -> approval"
    assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_ir_procedure_value_alias_uses_event_relations_without_formula_strengthening():
    element = extract_normative_elements(
        "The Bureau shall inspect the premises before approval."
    )[0]
    element = dict(element)
    element["procedure"] = {
        "event_relations": [
            {
                "event": "inspection",
                "relation": "before",
                "anchor_event": "issuance",
                "raw_text": "before approval",
                "span": [43, 58],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.procedure["value"] == "inspection before issuance"
    assert formula == "O(∀x (Bureau(x) → InspectPremises(x)))"
    assert "ProcedureBeforeIssuance" not in formula


def test_ir_procedure_value_alias_falls_back_to_trigger_and_terminal_events():
    element = extract_normative_elements("The Director shall issue a permit after notice.")[0]
    element = dict(element)
    element["procedure"] = {"trigger_event": "notice", "terminal_event": "issuance"}

    norm = LegalNormIR.from_parser_element(element)

    assert norm.procedure["value"] == "notice -> issuance"


def test_ir_source_span_falls_back_to_support_span_for_legacy_elements():
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]
    element = dict(element)
    element.pop("source_span", None)
    element["support_span"] = [4, 34]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.source_span.to_list() == [4, 34]
    assert norm.support_span.to_list() == [4, 34]
    assert norm.to_dict()["source_span"] == [4, 34]
    assert norm.to_dict()["support_span"] == [4, 34]
    assert build_deontic_formula_from_ir(norm) == build_deontic_formula(element)


def test_ir_explicit_source_span_still_takes_precedence_over_support_span():
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]
    element = dict(element)
    element["source_span"] = [0, 34]
    element["support_span"] = [4, 34]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.source_span.to_list() == [0, 34]
    assert norm.support_span.to_list() == [4, 34]


def test_detail_only_substantive_exception_infers_obligation_operator_for_resolution():
    element = dict(extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0])
    element["deontic_operator"] = None
    element["modality"] = None

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert record["formula"] == "O(∀x (Applicant(x) ∧ ¬ApprovalIsDenied(x) → ObtainPermit(x)))"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"]["type"] == "standard_substantive_exception"


def test_detail_only_applicability_infers_app_operator_for_local_scope_resolution():
    element = dict(extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0])
    element["deontic_operator"] = None
    element["modality"] = None

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "APP"
    assert record["formula"] == "AppliesTo(ThisSection, FoodCartsAndMobileVendors)"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"]["type"] == "local_scope_applicability"


def test_detail_only_override_infers_permission_operator_for_precedence_resolution():
    element = dict(extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0])
    element["deontic_operator"] = None
    element["modality"] = None

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "P"
    assert record["formula"] == "P(∀x (Director(x) → IssueVariance(x)))"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"]["type"] == "pure_precedence_override"


def test_detail_only_numbered_reference_exception_infers_operator_but_stays_blocked():
    element = dict(extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0])
    element["deontic_operator"] = None
    element["modality"] = None

    norm = LegalNormIR.from_parser_element(element)
    record = build_deontic_formula_record_from_ir(norm)

    assert norm.modality == "O"
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}


def test_batch_formula_records_resolve_numbered_exception_with_exact_same_document_section():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = dict(extract_normative_elements("The Bureau shall maintain the public register.")[0])
    cited_element["canonical_citation"] = "section 552"
    cited_element["section_context"] = {"section": "552"}

    records = build_deontic_formula_records_from_irs(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert records[0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in records[0]["formula"]
    assert records[0]["proof_ready"] is True
    assert records[0]["requires_validation"] is False
    assert records[0]["repair_required"] is False
    assert records[0]["deterministic_resolution"] == {
        "type": "resolved_same_document_reference_exception",
        "resolved_blockers": [
            "cross_reference_requires_resolution",
            "exception_requires_scope_review",
        ],
        "references": ["section 552"],
        "exception_spans": [reference_element["exception_details"][0].get("span", [])],
        "reason": "numbered exception reference is resolved to an exact same-document section and retained as provenance",
    }


def test_batch_formula_records_keep_numbered_exception_blocked_without_same_document_section():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    records = build_deontic_formula_records_from_irs([
        LegalNormIR.from_parser_element(reference_element),
    ])

    assert records[0]["proof_ready"] is False
    assert records[0]["requires_validation"] is True
    assert records[0]["repair_required"] is True
    assert records[0]["deterministic_resolution"] == {}


def test_ir_temporal_value_alias_handles_whichever_earlier_structured_alternatives():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit within 10 days after application."
    )[0])
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "alternatives": [
                {
                    "duration": "10 days",
                    "anchor_event": "application",
                    "anchor_relation": "after",
                },
                {
                    "duration": "30 days",
                    "anchor_event": "notice",
                    "anchor_relation": "after",
                },
            ],
            "selector": "earlier",
            "span": [34, 96],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.temporal_constraints[0]["value"] == (
        "10 days after application or 30 days after notice whichever is earlier"
    )
    assert formula == (
        "O(∀x (Director(x) ∧ Deadline10DaysAfterApplicationOr30DaysAfterNoticeWhicheverIsEarlier(x) "
        "→ IssuePermit(x)))"
    )


def test_ir_temporal_value_alias_handles_quantity_unit_calendar_deadline():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit within 10 business days after application."
    )[0])
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "quantity": 10,
            "unit": "days",
            "calendar": "business",
            "anchor_event": "application",
            "anchor_relation": "after",
            "span": [34, 80],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.temporal_constraints[0]["value"] == "10 business days after application"
    assert formula == (
        "O(∀x (Director(x) ∧ Deadline10BusinessDaysAfterApplication(x) "
        "→ IssuePermit(x)))"
    )


def test_action_recipient_is_not_formula_antecedent_regression():
    element = dict(extract_normative_elements(
        "The Director shall provide consultation with the advisory committee."
    )[0])
    element["action_recipient"] = "advisory committee"

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.recipient == "advisory committee"
    assert formula == "O(∀x (Director(x) → ProvideConsultationAdvisoryCommittee(x)))"
    assert "RecipientAdvisoryCommittee" not in formula


def test_structured_procedure_filing_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after filing of an application."
    )[0])
    element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_filing_of",
                "anchor_event": "application",
                "raw_text": "after filing of an application",
                "span": [36, 66],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureUponFilingApplication(x) → IssuePermit(x)))"
    )
    assert "Recipient" not in formula


def test_structured_procedure_submission_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after submission of a complete application."
    )[0])
    element["procedure"] = {
        "trigger_event": "complete application",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_submission_of",
                "anchor_event": "complete application",
                "raw_text": "after submission of a complete application",
                "span": [36, 78],
            },
            {
                "event": "issuance",
                "relation": "before",
                "anchor_event": "inspection",
                "raw_text": "before inspection",
                "span": [0, 0],
            },
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureUponSubmissionCompleteApplication(x) → IssuePermit(x)))"
    )
    assert "ProcedureBeforeInspection" not in formula


def test_structured_procedure_notice_and_hearing_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after notice and hearing."
    )[0])
    element["procedure"] = {
        "trigger_event": "notice and hearing",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_notice_and_hearing",
                "anchor_event": "notice and hearing",
                "raw_text": "after notice and hearing",
                "span": [36, 60],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterNoticeAndHearing(x) → IssuePermit(x)))"
    )
    assert formula.count("ProcedureAfterNoticeAndHearing(x)") == 1


def test_structured_procedure_notice_and_hearing_deduplicates_condition_alias():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after notice and hearing."
    )[0])
    element["condition_details"] = [
        {
            "type": "procedure",
            "value": "procedure after notice and hearing",
            "raw_text": "after notice and hearing",
            "span": [36, 60],
        }
    ]
    element["procedure"] = {
        "trigger_event": "notice and hearing",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_notice_and_hearing",
                "anchor_event": "notice and hearing",
                "raw_text": "after notice and hearing",
                "span": [36, 60],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterNoticeAndHearing(x) → IssuePermit(x)))"
    )
    assert formula.count("ProcedureAfterNoticeAndHearing(x)") == 1


def test_structured_procedure_approval_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit upon approval of an application."
    )[0])
    element["action"] = ["issue a permit upon approval application"]
    element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_approval_of",
                "anchor_event": "application",
                "raw_text": "upon approval of an application",
                "span": [36, 67],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureUponApprovalApplication(x) → IssuePermit(x)))"
    )
    assert "IssuePermitUponApprovalApplication" not in formula


def test_structured_procedure_approval_trigger_deduplicates_condition_alias():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit upon approval of an application."
    )[0])
    element["action"] = ["issue a permit upon approval application"]
    element["condition_details"] = [
        {
            "type": "procedure",
            "value": "procedure upon approval application",
            "raw_text": "upon approval of an application",
            "span": [36, 67],
        }
    ]
    element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_approval_of",
                "anchor_event": "application",
                "raw_text": "upon approval of an application",
                "span": [36, 67],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureUponApprovalApplication(x) → IssuePermit(x)))"
    )
    assert formula.count("ProcedureUponApprovalApplication(x)") == 1
    assert "IssuePermitUponApprovalApplication" not in formula


def test_structured_procedure_completion_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after completion of an inspection."
    )[0])
    element["action"] = ["issue a permit after completion inspection"]
    element["procedure"] = {
        "trigger_event": "inspection",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_completion_of",
                "anchor_event": "inspection",
                "raw_text": "after completion of an inspection",
                "span": [36, 70],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterCompletionInspection(x) → IssuePermit(x)))"
    )
    assert "IssuePermitAfterCompletionInspection" not in formula


def test_structured_procedure_effective_date_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit upon the effective date of the ordinance."
    )[0])
    element["action"] = ["issue a permit upon effective date ordinance"]
    element["procedure"] = {
        "trigger_event": "ordinance",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_effective_date_of",
                "anchor_event": "ordinance",
                "raw_text": "upon the effective date of the ordinance",
                "span": [36, 78],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureUponEffectiveDateOrdinance(x) → IssuePermit(x)))"
    )
    assert "IssuePermitUponEffectiveDateOrdinance" not in formula


def test_structured_procedure_certification_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit upon certification of an inspection."
    )[0])
    element["action"] = ["issue a permit upon certification inspection"]
    element["procedure"] = {
        "trigger_event": "inspection",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_certification_of",
                "anchor_event": "inspection",
                "raw_text": "upon certification of an inspection",
                "span": [36, 73],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureUponCertificationInspection(x) → IssuePermit(x)))"
    )
    assert "IssuePermitUponCertificationInspection" not in formula


def test_structured_procedure_issuance_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall renew a permit after issuance of the license."
    )[0])
    element["action"] = ["renew a permit after issuance license"]
    element["procedure"] = {
        "trigger_event": "license",
        "terminal_event": "renewal",
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_issuance_of",
                "anchor_event": "license",
                "raw_text": "after issuance of the license",
                "span": [36, 65],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterIssuanceLicense(x) → RenewPermit(x)))"
    )
    assert "RenewPermitAfterIssuanceLicense" not in formula


def test_structured_procedure_publication_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall renew a permit after publication of the notice."
    )[0])
    element["action"] = ["renew a permit after publication notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "renewal",
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_publication_of",
                "anchor_event": "notice",
                "raw_text": "after publication of the notice",
                "span": [36, 68],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterPublicationNotice(x) → RenewPermit(x)))"
    )
    assert "RenewPermitAfterPublicationNotice" not in formula


def test_structured_procedure_inspection_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall renew a permit after inspection of the premises."
    )[0])
    element["action"] = ["renew a permit after inspection premises"]
    element["procedure"] = {
        "trigger_event": "premises",
        "terminal_event": "renewal",
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_inspection_of",
                "anchor_event": "premises",
                "raw_text": "after inspection of the premises",
                "span": [36, 69],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterInspectionPremises(x) → RenewPermit(x)))"
    )
    assert "Procedureafterinspectionpremises" not in formula
    assert "RenewPermitAfterInspectionPremises" not in formula


def test_structured_procedure_service_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall renew a permit after service of notice."
    )[0])
    element["action"] = ["renew a permit after service notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "renewal",
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_service_of",
                "anchor_event": "notice",
                "raw_text": "after service of notice",
                "span": [36, 59],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterServiceNotice(x) → RenewPermit(x)))"
    )
    assert "Procedureafterservicenotice" not in formula
    assert "RenewPermitAfterServiceNotice" not in formula


def test_structured_procedure_mailing_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue an order after mailing of the notice."
    )[0])
    element["action"] = ["issue an order after mailing notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_mailing_of",
                "anchor_event": "notice",
                "raw_text": "after mailing of the notice",
                "span": [36, 64],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterMailingNotice(x) → IssueOrder(x)))"
    assert "IssueOrderAfterMailingNotice" not in formula


def test_structured_procedure_certified_mailing_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue an order after certified mailing of the notice."
    )[0])
    element["action"] = ["issue an order after certified mailing notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_certified_mailing_of",
                "anchor_event": "notice",
                "raw_text": "after certified mailing of the notice",
                "span": [36, 74],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterCertifiedMailingNotice(x) → IssueOrder(x)))"
    assert "IssueOrderAfterCertifiedMailingNotice" not in formula


def test_structured_procedure_delivery_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue an order after delivery of the notice."
    )[0])
    element["action"] = ["issue an order after delivery notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_delivery_of",
                "anchor_event": "notice",
                "raw_text": "after delivery of the notice",
                "span": [36, 65],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterDeliveryNotice(x) → IssueOrder(x)))"
    assert "IssueOrderAfterDeliveryNotice" not in formula


def test_structured_procedure_postmark_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall accept an appeal after postmark of the notice."
    )[0])
    element["action"] = ["accept an appeal after postmark notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "acceptance",
        "event_relations": [
            {
                "event": "acceptance",
                "relation": "triggered_by_postmark_of",
                "anchor_event": "notice",
                "raw_text": "after postmark of the notice",
                "span": [37, 66],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterPostmarkNotice(x) → AcceptAppeal(x)))"
    assert "AcceptAppealAfterPostmarkNotice" not in formula


def test_structured_procedure_docketing_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Board shall accept an appeal after docketing of the appeal."
    )[0])
    element["action"] = ["accept an appeal after docketing appeal"]
    element["procedure"] = {
        "trigger_event": "appeal",
        "terminal_event": "acceptance",
        "event_relations": [
            {
                "event": "acceptance",
                "relation": "triggered_by_docketing_of",
                "anchor_event": "appeal",
                "raw_text": "after docketing of the appeal",
                "span": [33, 63],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Board(x) ∧ ProcedureAfterDocketingAppeal(x) → AcceptAppeal(x)))"
    assert "AcceptAppealAfterDocketingAppeal" not in formula


def test_structured_procedure_entry_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Board shall serve notice after entry of the final order."
    )[0])
    element["action"] = ["serve notice after entry final order"]
    element["procedure"] = {
        "trigger_event": "final order",
        "terminal_event": "service",
        "event_relations": [
            {
                "event": "service",
                "relation": "triggered_by_entry_of",
                "anchor_event": "final order",
                "raw_text": "after entry of the final order",
                "span": [29, 61],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Board(x) ∧ ProcedureAfterEntryFinalOrder(x) → ServeNotice(x)))"
    assert "ServeNoticeAfterEntryFinalOrder" not in formula


def test_structured_procedure_signature_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Board shall serve notice after signature of the final order."
    )[0])
    element["action"] = ["serve notice after signature final order"]
    element["procedure"] = {
        "trigger_event": "final order",
        "terminal_event": "service",
        "event_relations": [
            {
                "event": "service",
                "relation": "triggered_by_signature_of",
                "anchor_event": "final order",
                "raw_text": "after signature of the final order",
                "span": [29, 65],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Board(x) ∧ ProcedureAfterSignatureFinalOrder(x) → ServeNotice(x)))"
    assert "ServeNoticeAfterSignatureFinalOrder" not in formula


def test_structured_procedure_opening_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Board shall award the contract after opening of the bids."
    )[0])
    element["action"] = ["award the contract after opening bids"]
    element["procedure"] = {
        "trigger_event": "bids",
        "terminal_event": "award",
        "event_relations": [
            {
                "event": "award",
                "relation": "triggered_by_opening_of",
                "anchor_event": "bids",
                "raw_text": "after opening of the bids",
                "span": [31, 58],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Board(x) ∧ ProcedureAfterOpeningBids(x) → AwardContract(x)))"
    assert "AwardContractAfterOpeningBids" not in formula


def test_structured_procedure_return_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Board shall dismiss the appeal after return of the notice."
    )[0])
    element["action"] = ["dismiss the appeal after return notice"]
    element["procedure"] = {
        "trigger_event": "notice",
        "terminal_event": "dismissal",
        "event_relations": [
            {
                "event": "dismissal",
                "relation": "triggered_by_return_of",
                "anchor_event": "notice",
                "raw_text": "after return of the notice",
                "span": [35, 62],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Board(x) ∧ ProcedureAfterReturnNotice(x) → DismissAppeal(x)))"
    assert "DismissAppealAfterReturnNotice" not in formula


def test_structured_procedure_adoption_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall publish guidelines after adoption of rules."
    )[0])
    element["action"] = ["publish guidelines after adoption rules"]
    element["procedure"] = {
        "trigger_event": "rules",
        "terminal_event": "publication",
        "event_relations": [
            {
                "event": "publication",
                "relation": "triggered_by_adoption_of",
                "anchor_event": "rules",
                "raw_text": "after adoption of rules",
                "span": [39, 62],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterAdoptionRules(x) → PublishGuidelines(x)))"
    )
    assert "Procedureafteradoptionrules" not in formula
    assert "PublishGuidelinesAfterAdoptionRules" not in formula


def test_structured_procedure_commencement_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after commencement of operations."
    )[0])
    element["action"] = ["inspect the premises after commencement operations"]
    element["procedure"] = {
        "trigger_event": "operations",
        "terminal_event": "inspection",
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_commencement_of",
                "anchor_event": "operations",
                "raw_text": "after commencement of operations",
                "span": [40, 72],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterCommencementOperations(x) → InspectPremises(x)))"
    )
    assert "Procedureaftercommencementoperations" not in formula
    assert "InspectPremisesAfterCommencementOperations" not in formula


def test_structured_procedure_execution_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a certificate after execution of the agreement."
    )[0])
    element["action"] = ["issue a certificate after execution agreement"]
    element["procedure"] = {
        "trigger_event": "agreement",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_execution_of",
                "anchor_event": "agreement",
                "raw_text": "after execution of the agreement",
                "span": [39, 72],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterExecutionAgreement(x) → IssueCertificate(x)))"
    )
    assert "Procedureafterexecutionagreement" not in formula
    assert "IssueCertificateAfterExecutionAgreement" not in formula


def test_structured_procedure_recording_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall renew a license after recording of the deed."
    )[0])
    element["action"] = ["renew a license after recording deed"]
    element["procedure"] = {
        "trigger_event": "deed",
        "terminal_event": "renewal",
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_recording_of",
                "anchor_event": "deed",
                "raw_text": "after recording of the deed",
                "span": [35, 63],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterRecordingDeed(x) → RenewLicense(x)))"
    )
    assert "Procedureafterrecordingdeed" not in formula
    assert "RenewLicenseAfterRecordingDeed" not in formula


def test_structured_procedure_renewal_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after renewal of the license."
    )[0])
    element["action"] = ["inspect the premises after renewal license"]
    element["procedure"] = {
        "trigger_event": "license",
        "terminal_event": "inspection",
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_renewal_of",
                "anchor_event": "license",
                "raw_text": "after renewal of the license",
                "span": [40, 69],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterRenewalLicense(x) → InspectPremises(x)))"
    )
    assert "Procedureafterrenewallicense" not in formula
    assert "InspectPremisesAfterRenewalLicense" not in formula


def test_structured_procedure_expiration_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after expiration of the license."
    )[0])
    element["action"] = ["inspect the premises after expiration license"]
    element["procedure"] = {
        "trigger_event": "license",
        "terminal_event": "inspection",
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_expiration_of",
                "anchor_event": "license",
                "raw_text": "after expiration of the license",
                "span": [40, 72],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterExpirationLicense(x) → InspectPremises(x)))"
    )
    assert "Procedureafterexpirationlicense" not in formula
    assert "InspectPremisesAfterExpirationLicense" not in formula


def test_structured_procedure_termination_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after termination of the license."
    )[0])
    element["action"] = ["inspect the premises after termination license"]
    element["procedure"] = {
        "trigger_event": "license",
        "terminal_event": "inspection",
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_termination_of",
                "anchor_event": "license",
                "raw_text": "after termination of the license",
                "span": [40, 73],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterTerminationLicense(x) → InspectPremises(x)))"
    )
    assert "Procedureafterterminationlicense" not in formula
    assert "InspectPremisesAfterTerminationLicense" not in formula


def test_structured_procedure_revocation_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after revocation of the license."
    )[0])
    element["action"] = ["inspect the premises after revocation license"]
    element["procedure"] = {
        "trigger_event": "license",
        "terminal_event": "inspection",
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_revocation_of",
                "anchor_event": "license",
                "raw_text": "after revocation of the license",
                "span": [40, 72],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Director(x) ∧ ProcedureAfterRevocationLicense(x) → InspectPremises(x)))"
    )
    assert "Procedureafterrevocationlicense" not in formula
    assert "InspectPremisesAfterRevocationLicense" not in formula


def test_structured_procedure_denial_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a notice after denial of the application."
    )[0])
    element["action"] = ["issue a notice after denial application"]
    element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_denial_of",
                "anchor_event": "application",
                "raw_text": "after denial of the application",
                "span": [36, 68],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterDenialApplication(x) → IssueNotice(x)))"
    assert "Procedureafterdenialapplication" not in formula
    assert "IssueNoticeAfterDenialApplication" not in formula


def test_structured_procedure_payment_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after payment of the fee."
    )[0])
    element["action"] = ["issue a permit after payment fee"]
    element["procedure"] = {
        "trigger_event": "fee",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_payment_of",
                "anchor_event": "fee",
                "raw_text": "after payment of the fee",
                "span": [36, 60],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterPaymentFee(x) → IssuePermit(x)))"
    assert "Procedureafterpaymentfee" not in formula
    assert "IssuePermitAfterPaymentFee" not in formula


def test_structured_procedure_assessment_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a notice after assessment of the fee."
    )[0])
    element["action"] = ["issue a notice after assessment fee"]
    element["procedure"] = {
        "trigger_event": "fee",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_assessment_of",
                "anchor_event": "fee",
                "raw_text": "after assessment of the fee",
                "span": [36, 64],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterAssessmentFee(x) → IssueNotice(x)))"
    assert "Procedureafterassessmentfee" not in formula
    assert "IssueNoticeAfterAssessmentFee" not in formula


def test_structured_procedure_determination_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after determination of eligibility."
    )[0])
    element["action"] = ["issue a permit after determination eligibility"]
    element["procedure"] = {
        "trigger_event": "eligibility",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_determination_of",
                "anchor_event": "eligibility",
                "raw_text": "after determination of eligibility",
                "span": [36, 70],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterDeterminationEligibility(x) → IssuePermit(x)))"
    assert "IssuePermitAfterDeterminationEligibility" not in formula


def test_structured_procedure_verification_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit after verification of residency."
    )[0])
    element["action"] = ["issue a permit after verification residency"]
    element["procedure"] = {
        "trigger_event": "residency",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_verification_of",
                "anchor_event": "residency",
                "raw_text": "after verification of residency",
                "span": [36, 67],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Director(x) ∧ ProcedureAfterVerificationResidency(x) → IssuePermit(x)))"
    assert "IssuePermitAfterVerificationResidency" not in formula


def test_structured_procedure_validation_trigger_becomes_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Bureau shall approve the license after validation of the application."
    )[0])
    element["action"] = ["approve the license after validation application"]
    element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "approval",
        "event_relations": [
            {
                "event": "approval",
                "relation": "triggered_by_validation_of",
                "anchor_event": "application",
                "raw_text": "after validation of the application",
                "span": [39, 75],
            }
        ],
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == "O(∀x (Bureau(x) ∧ ProcedureAfterValidationApplication(x) → ApproveLicense(x)))"
    assert "ApproveLicenseAfterValidationApplication" not in formula


def test_structured_procedure_review_and_reconsideration_triggers_become_formula_prerequisites():
    review_element = dict(extract_normative_elements(
        "The Director shall issue a permit after review of the application."
    )[0])
    review_element["action"] = ["issue a permit after review application"]
    review_element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_review_of",
                "anchor_event": "application",
                "raw_text": "after review of the application",
                "span": [36, 67],
            }
        ],
    }
    reconsideration_element = dict(extract_normative_elements(
        "The Board shall issue a final order after reconsideration of the appeal."
    )[0])
    reconsideration_element["action"] = ["issue a final order after reconsideration appeal"]
    reconsideration_element["procedure"] = {
        "trigger_event": "appeal",
        "terminal_event": "issuance",
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_reconsideration_of",
                "anchor_event": "appeal",
                "raw_text": "after reconsideration of the appeal",
                "span": [36, 73],
            }
        ],
    }

    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(review_element)) == (
        "O(∀x (Director(x) ∧ ProcedureAfterReviewApplication(x) → IssuePermit(x)))"
    )
    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(reconsideration_element)) == (
        "O(∀x (Board(x) ∧ ProcedureAfterReconsiderationAppeal(x) → IssueFinalOrder(x)))"
    )


def test_structured_procedure_hearing_and_final_decision_triggers_become_formula_prerequisites():
    hearing_element = dict(extract_normative_elements(
        "The Board shall issue a final order after hearing on the appeal."
    )[0])
    hearing_element["action"] = ["issue a final order after hearing appeal"]
    hearing_element["procedure"] = {
        "trigger_event": "appeal",
        "terminal_event": "issuance",
        "event_relations": [
            {"event": "issuance", "relation": "triggered_by_hearing_of", "anchor_event": "appeal"}
        ],
    }
    decision_element = dict(extract_normative_elements(
        "The Director shall issue a permit after final decision on the application."
    )[0])
    decision_element["action"] = ["issue a permit after final decision application"]
    decision_element["procedure"] = {
        "trigger_event": "application",
        "terminal_event": "issuance",
        "event_relations": [
            {"event": "issuance", "relation": "triggered_by_final_decision_of", "anchor_event": "application"}
        ],
    }

    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(hearing_element)) == (
        "O(∀x (Board(x) ∧ ProcedureAfterHearingAppeal(x) → IssueFinalOrder(x)))"
    )
    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(decision_element)) == (
        "O(∀x (Director(x) ∧ ProcedureAfterFinalDecisionApplication(x) → IssuePermit(x)))"
    )


def test_structured_public_comment_and_consultation_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Director shall adopt the rule after public comment on the proposal and after consultation with the Board."
    )[0])
    element["action"] = [
        "adopt the rule after public comment proposal and after consultation Board"
    ]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "adoption",
                "relation": "triggered_by_public_comment_on",
                "anchor_event": "proposal",
                "raw_text": "after public comment on the proposal",
                "span": [32, 68],
            },
            {
                "event": "adoption",
                "relation": "triggered_by_consultation_with",
                "anchor_event": "Board",
                "raw_text": "after consultation with the Board",
                "span": [73, 106],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Director(x) ∧ ")
    assert formula.endswith(" → AdoptRule(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → AdoptRule(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Director(x)",
        "ProcedureAfterPublicCommentProposal(x)",
        "ProcedureAfterConsultationBoard(x)",
    }
    assert "AdoptRuleAfterPublicCommentProposal" not in formula
    assert "AdoptRuleAfterConsultationBoard" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_temporal_duration_without_unit_remains_conservative():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit within 10 days after application."
    )[0])
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {"type": "deadline", "quantity": 10, "anchor_event": "application"}
    ]

    norm = LegalNormIR.from_parser_element(element)

    assert norm.temporal_constraints[0]["value"] == "10 after application"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ Deadline10AfterApplication(x) → IssuePermit(x)))"
    )


def test_structured_alternative_deadline_options_become_formula_prerequisite():
    element = dict(extract_normative_elements(
        "The Director shall issue a permit within 10 days after application."
    )[0])
    element["temporal_constraints"] = []
    element["temporal_constraint_details"] = [
        {
            "type": "deadline",
            "deadline_options": [
                {"quantity": 10, "unit": "days", "anchor_event": "application"},
                {"quantity": 5, "unit": "days", "anchor_event": "inspection"},
            ],
            "selector": "whichever_is_earlier",
            "span": [36, 64],
        }
    ]

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert norm.temporal_constraints[0]["value"] == (
        "10 days after application or 5 days after inspection whichever is earlier"
    )
    assert formula == (
        "O(∀x (Director(x) ∧ "
        "Deadline10DaysAfterApplicationOr5DaysAfterInspectionWhicheverIsEarlier(x) "
        "→ IssuePermit(x)))"
    )

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_registration_and_enrollment_triggers_become_formula_prerequisites():
    registration_element = dict(extract_normative_elements(
        "The Clerk shall activate the permit after registration of the applicant."
    )[0])
    registration_element["action"] = ["activate the permit after registration applicant"]
    registration_element["procedure"] = {
        "event_relations": [
            {
                "event": "activation",
                "relation": "triggered_by_registration_of",
                "anchor_event": "applicant",
                "raw_text": "after registration of the applicant",
                "span": [32, 67],
            }
        ],
    }
    enrollment_element = dict(extract_normative_elements(
        "The Clerk shall activate the permit after enrollment of the license."
    )[0])
    enrollment_element["action"] = ["activate the permit after enrollment license"]
    enrollment_element["procedure"] = {
        "event_relations": [
            {
                "event": "activation",
                "relation": "triggered_by_enrollment_of",
                "anchor_event": "license",
                "raw_text": "after enrollment of the license",
                "span": [32, 63],
            }
        ],
    }

    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(registration_element)) == (
        "O(∀x (Clerk(x) ∧ ProcedureAfterRegistrationApplicant(x) → ActivatePermit(x)))"
    )
    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(enrollment_element)) == (
        "O(∀x (Clerk(x) ∧ ProcedureAfterEnrollmentLicense(x) → ActivatePermit(x)))"
    )


def test_structured_acceptance_and_acknowledgment_triggers_become_formula_prerequisites():
    acceptance_element = dict(extract_normative_elements(
        "The Board shall schedule the hearing after acceptance of the appeal."
    )[0])
    acceptance_element["action"] = ["schedule the hearing after acceptance appeal"]
    acceptance_element["procedure"] = {
        "event_relations": [
            {
                "event": "scheduling",
                "relation": "triggered_by_acceptance_of",
                "anchor_event": "appeal",
                "raw_text": "after acceptance of the appeal",
                "span": [33, 63],
            }
        ],
    }
    acknowledgment_element = dict(extract_normative_elements(
        "The Clerk shall docket the filing after acknowledgment of the filing."
    )[0])
    acknowledgment_element["action"] = ["docket the filing after acknowledgment filing"]
    acknowledgment_element["procedure"] = {
        "event_relations": [
            {
                "event": "docketing",
                "relation": "triggered_by_acknowledgment_of",
                "anchor_event": "filing",
                "raw_text": "after acknowledgment of the filing",
                "span": [31, 66],
            }
        ],
    }

    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(acceptance_element)) == (
        "O(∀x (Board(x) ∧ ProcedureAfterAcceptanceAppeal(x) → ScheduleHearing(x)))"
    )
    assert build_deontic_formula_from_ir(LegalNormIR.from_parser_element(acknowledgment_element)) == (
        "O(∀x (Clerk(x) ∧ ProcedureAfterAcknowledgmentFiling(x) → DocketFiling(x)))"
    )


def test_structured_electronic_filing_and_service_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Clerk shall docket the appeal after electronic filing of the appeal and after electronic service on the respondent."
    )[0])
    element["action"] = [
        "docket the appeal after electronic filing appeal and after electronic service respondent"
    ]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "docketing",
                "relation": "triggered_by_electronic_filing_of",
                "anchor_event": "appeal",
                "raw_text": "after electronic filing of the appeal",
                "span": [31, 68],
            },
            {
                "event": "docketing",
                "relation": "triggered_by_electronic_service_on",
                "anchor_event": "respondent",
                "raw_text": "after electronic service on the respondent",
                "span": [73, 114],
            },
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    formula = build_deontic_formula_from_ir(norm)

    assert formula == (
        "O(∀x (Clerk(x) ∧ ProcedureAfterElectronicFilingAppeal(x) "
        "∧ ProcedureAfterElectronicServiceRespondent(x) → DocketAppeal(x)))"
    )
    assert "DocketAppealAfterElectronicFilingAppeal" not in formula
    assert "DocketAppealAfterElectronicServiceRespondent" not in formula


def test_structured_notice_delivery_and_docketing_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Clerk shall serve the order after certified mailing of the notice and after docketing of the appeal."
    )[0])
    element["action"] = ["serve the order"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "service",
                "relation": "triggered_by_certified_mailing_of",
                "anchor_event": "notice",
                "raw_text": "after certified mailing of the notice",
                "span": [29, 66],
            },
            {
                "event": "service",
                "relation": "triggered_by_docketing_of",
                "anchor_event": "appeal",
                "raw_text": "after docketing of the appeal",
                "span": [71, 101],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Clerk(x) ∧ ")
    assert formula.endswith(" → ServeOrder(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → ServeOrder(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Clerk(x)",
        "ProcedureAfterCertifiedMailingNotice(x)",
        "ProcedureAfterDocketingAppeal(x)",
    }
    assert "ServeOrderAfterCertifiedMailingNotice" not in formula
    assert "ServeOrderAfterDocketingAppeal" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_signature_and_countersignature_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Clerk shall record the deed after signature of the final order and after countersignature of the certificate."
    )[0])
    element["action"] = ["record the deed"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "recording",
                "relation": "triggered_by_signature_of",
                "anchor_event": "final order",
                "raw_text": "after signature of the final order",
                "span": [29, 65],
            },
            {
                "event": "recording",
                "relation": "triggered_by_countersignature_of",
                "anchor_event": "certificate",
                "raw_text": "after countersignature of the certificate",
                "span": [70, 111],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Clerk(x) ∧ ")
    assert formula.endswith(" → RecordDeed(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → RecordDeed(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Clerk(x)",
        "ProcedureAfterSignatureFinalOrder(x)",
        "ProcedureAfterCountersignatureCertificate(x)",
    }
    assert "RecordDeedAfterSignatureFinalOrder" not in formula
    assert "RecordDeedAfterCountersignatureCertificate" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_determination_and_verification_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Director shall issue the certificate after determination of eligibility and after verification of the address."
    )[0])
    element["action"] = ["issue the certificate"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_determination_of",
                "anchor_event": "eligibility",
                "raw_text": "after determination of eligibility",
                "span": [37, 71],
            },
            {
                "event": "issuance",
                "relation": "triggered_by_verification_of",
                "anchor_event": "address",
                "raw_text": "after verification of the address",
                "span": [76, 109],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Director(x) ∧ ")
    assert formula.endswith(" → IssueCertificate(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → IssueCertificate(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Director(x)",
        "ProcedureAfterDeterminationEligibility(x)",
        "ProcedureAfterVerificationAddress(x)",
    }
    assert "IssueCertificateAfterDeterminationEligibility" not in formula
    assert "IssueCertificateAfterVerificationAddress" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_financial_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Treasurer shall release the permit after payment of the fee and after assessment of charges."
    )[0])
    element["action"] = ["release the permit"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "release",
                "relation": "triggered_by_payment_of",
                "anchor_event": "fee",
                "raw_text": "after payment of the fee",
                "span": [43, 67],
            },
            {
                "event": "release",
                "relation": "triggered_by_assessment_of",
                "anchor_event": "charges",
                "raw_text": "after assessment of charges",
                "span": [72, 99],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Treasurer(x) ∧ ")
    assert formula.endswith(" → ReleasePermit(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → ReleasePermit(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Treasurer(x)",
        "ProcedureAfterPaymentFee(x)",
        "ProcedureAfterAssessmentCharges(x)",
    }
    assert "ReleasePermitAfterPaymentFee" not in formula
    assert "ReleasePermitAfterAssessmentCharges" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_accounting_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Auditor shall certify the refund after calculation of the fee and after audit of the account."
    )[0])
    element["action"] = ["certify the refund"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "certification",
                "relation": "triggered_by_calculation_of",
                "anchor_event": "fee",
                "raw_text": "after calculation of the fee",
                "span": [37, 65],
            },
            {
                "event": "certification",
                "relation": "triggered_by_audit_of",
                "anchor_event": "account",
                "raw_text": "after audit of the account",
                "span": [70, 96],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Auditor(x) ∧ ")
    assert formula.endswith(" → CertifyRefund(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → CertifyRefund(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Auditor(x)",
        "ProcedureAfterCalculationFee(x)",
        "ProcedureAfterAuditAccount(x)",
    }
    assert "CertifyRefundAfterCalculationFee" not in formula
    assert "CertifyRefundAfterAuditAccount" not in formula


def test_structured_compliance_inspection_triggers_become_formula_prerequisites():
    element = dict(extract_normative_elements(
        "The Inspector shall approve the discharge after sampling of the effluent and after testing of the meter."
    )[0])
    element["action"] = ["approve the discharge"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "approval",
                "relation": "triggered_by_sampling_of",
                "anchor_event": "effluent",
                "raw_text": "after sampling of the effluent",
                "span": [40, 70],
            },
            {
                "event": "approval",
                "relation": "triggered_by_testing_of",
                "anchor_event": "meter",
                "raw_text": "after testing of the meter",
                "span": [75, 101],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Inspector(x) ∧ ")
    assert formula.endswith(" → ApproveDischarge(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → ApproveDischarge(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Inspector(x)",
        "ProcedureAfterSamplingEffluent(x)",
        "ProcedureAfterTestingMeter(x)",
    }
    assert "ApproveDischargeAfterSamplingEffluent" not in formula
    assert "ApproveDischargeAfterTestingMeter" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_structured_recordkeeping_triggers_become_formula_prerequisites_without_action_tail():
    element = dict(extract_normative_elements(
        "The Clerk shall destroy the record after archiving of the file and after retention of the index."
    )[0])
    element["action"] = [
        "destroy the record after archiving file and after retention index"
    ]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "destruction",
                "relation": "triggered_by_archiving_of",
                "anchor_event": "file",
                "raw_text": "after archiving of the file",
                "span": [32, 59],
            },
            {
                "event": "destruction",
                "relation": "triggered_by_retention_of",
                "anchor_event": "index",
                "raw_text": "after retention of the index",
                "span": [64, 92],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Clerk(x) ∧ ")
    assert formula.endswith(" → DestroyRecord(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → DestroyRecord(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Clerk(x)",
        "ProcedureAfterArchivingFile(x)",
        "ProcedureAfterRetentionIndex(x)",
    }
    assert "DestroyRecordAfterArchivingFile" not in formula
    assert "DestroyRecordAfterRetentionIndex" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_supplemental_procedure_triggers_become_prerequisites_without_action_tail():
    element = dict(extract_normative_elements(
        "The Clerk shall file the certificate after transmission of the order and after receipt confirmation of the notice."
    )[0])
    element["action"] = [
        "file the certificate after transmission order and after receipt confirmation notice"
    ]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "filing",
                "relation": "triggered_by_transmission_of",
                "anchor_event": "order",
                "raw_text": "after transmission of the order",
                "span": [35, 66],
            },
            {
                "event": "filing",
                "relation": "triggered_by_receipt_confirmation_of",
                "anchor_event": "notice",
                "raw_text": "after receipt confirmation of the notice",
                "span": [71, 111],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Clerk(x) ∧ ")
    assert formula.endswith(" → FileCertificate(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → FileCertificate(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Clerk(x)",
        "ProcedureAfterTransmissionOrder(x)",
        "ProcedureAfterReceiptConfirmationNotice(x)",
    }
    assert "FileCertificateAfterTransmissionOrder" not in formula
    assert "FileCertificateAfterReceiptConfirmationNotice" not in formula


def test_supplemental_status_triggers_become_prerequisites_without_action_tail():
    element = dict(extract_normative_elements(
        "The Board shall restore the license after posting of the bond and after reinstatement of the permit."
    )[0])
    element["action"] = [
        "restore the license after posting bond and after reinstatement permit"
    ]
    element["procedure"] = {
        "event_relations": [
            {"event": "restoration", "relation": "triggered_by_posting_of", "anchor_event": "bond"},
            {"event": "restoration", "relation": "triggered_by_reinstatement_of", "anchor_event": "permit"},
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Board(x) ∧ ")
    assert formula.endswith(" → RestoreLicense(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → RestoreLicense(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Board(x)",
        "ProcedureAfterPostingBond(x)",
        "ProcedureAfterReinstatementPermit(x)",
    }
    assert "RestoreLicenseAfterPostingBond" not in formula
    assert "RestoreLicenseAfterReinstatementPermit" not in formula


def test_commencement_and_execution_triggers_become_prerequisites_without_action_tail():
    element = dict(extract_normative_elements(
        "The Clerk shall docket the order after commencement of the case and after execution of the agreement."
    )[0])
    element["action"] = [
        "docket the order after commencement case and after execution agreement"
    ]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "docketing",
                "relation": "triggered_by_commencement_of",
                "anchor_event": "case",
                "raw_text": "after commencement of the case",
                "span": [30, 60],
            },
            {
                "event": "docketing",
                "relation": "triggered_by_execution_of",
                "anchor_event": "agreement",
                "raw_text": "after execution of the agreement",
                "span": [65, 97],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Clerk(x) ∧ ")
    assert formula.endswith(" → DocketOrder(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → DocketOrder(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Clerk(x)",
        "ProcedureAfterCommencementCase(x)",
        "ProcedureAfterExecutionAgreement(x)",
    }
    assert "DocketOrderAfterCommencementCase" not in formula
    assert "DocketOrderAfterExecutionAgreement" not in formula

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_public_participation_triggers_become_formula_prerequisites_without_action_tail():
    element = dict(extract_normative_elements(
        "The Director shall adopt the rule after public comment on the proposal and after consultation with the Board."
    )[0])
    element["action"] = [
        "adopt the rule after public comment proposal and after consultation Board"
    ]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "adoption",
                "relation": "triggered_by_public_comment_on",
                "anchor_event": "proposal",
                "raw_text": "after public comment on the proposal",
                "span": [32, 68],
            },
            {
                "event": "adoption",
                "relation": "triggered_by_consultation_with",
                "anchor_event": "Board",
                "raw_text": "after consultation with the Board",
                "span": [73, 106],
            },
        ]
    }

    formula = build_deontic_formula_from_ir(LegalNormIR.from_parser_element(element))

    assert formula.startswith("O(∀x (Director(x) ∧ ")
    assert formula.endswith(" → AdoptRule(x)))")
    antecedent = formula.removeprefix("O(∀x (").removesuffix(" → AdoptRule(x)))")
    assert set(antecedent.split(" ∧ ")) == {
        "Director(x)",
        "ProcedureAfterPublicCommentProposal(x)",
        "ProcedureAfterConsultationBoard(x)",
    }
    assert "AdoptRuleAfterPublicCommentProposal" not in formula
    assert "AdoptRuleAfterConsultationBoard" not in formula


def test_assessment_imposition_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make an assessment of the fee.",
            "make an assessment of the fee",
            [19, 48],
            "O(∀x (Director(x) → AssessFee(x)))",
            "MakeAssessmentFee",
        ),
        (
            "The Board shall make an imposition of the civil penalty.",
            "make an imposition of the civil penalty",
            [16, 55],
            "O(∀x (Board(x) → ImposeCivilPenalty(x)))",
            "MakeImpositionCivilPenalty",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_deletion_erasure_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Agency shall perform deletion of the file.",
            "perform deletion of the file",
            [17, 45],
            "O(∀x (Agency(x) → DeleteFile(x)))",
            "PerformDeletionFile",
        ),
        (
            "The Clerk shall complete erasure of the record.",
            "complete erasure of the record",
            [16, 46],
            "O(∀x (Clerk(x) → EraseRecord(x)))",
            "CompleteErasureRecord",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_preservation_restoration_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Agency shall perform preservation of the file.",
            "perform preservation of the file",
            [17, 49],
            "O(∀x (Agency(x) → PreserveFile(x)))",
            "PerformPreservationFile",
        ),
        (
            "The Board shall complete restoration of the permit.",
            "complete restoration of the permit",
            [16, 50],
            "O(∀x (Board(x) → RestorePermit(x)))",
            "CompleteRestorationPermit",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_archival_retention_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall perform archiving of the permit.",
            "perform archiving of the permit",
            [16, 47],
            "O(∀x (Clerk(x) → ArchivePermit(x)))",
            "PerformArchivingPermit",
        ),
        (
            "The Agency shall complete retention of the file.",
            "complete retention of the file",
            [17, 47],
            "O(∀x (Agency(x) → RetainFile(x)))",
            "CompleteRetentionFile",
        ),
    ]

    for text, action, action_span, expected_formula, rejected_predicate in examples:
        element = extract_normative_elements(text)[0]
        norm = LegalNormIR.from_parser_element(element)
        record = build_deontic_formula_record_from_ir(norm)

        assert norm.modality == "O"
        assert norm.action == action
        assert norm.support_span == norm.source_span
        assert element["field_spans"]["action"] == action_span
        assert build_deontic_formula_from_ir(norm) == expected_formula
        assert record["formula"] == expected_formula
        assert rejected_predicate not in expected_formula
        assert record["proof_ready"] is True
        assert record["requires_validation"] is False
        assert record["repair_required"] is False

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_redaction_anonymization_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Agency shall perform redaction of the file.",
            "perform redaction of the file",
            "O(∀x (Agency(x) → RedactFile(x)))",
            "PerformRedactionFile",
        ),
        (
            "The Clerk shall complete anonymization of the index.",
            "complete anonymization of the index",
            "O(∀x (Clerk(x) → AnonymizeIndex(x)))",
            "CompleteAnonymizationIndex",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_masking_pseudonymization_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Agency shall perform masking of the identifiers.",
            "perform masking of the identifiers",
            "O(∀x (Agency(x) → MaskIdentifiers(x)))",
            "PerformMaskingIdentifiers",
        ),
        (
            "The Clerk shall complete pseudonymization of the dataset.",
            "complete pseudonymization of the dataset",
            "O(∀x (Clerk(x) → PseudonymizeDataset(x)))",
            "CompletePseudonymizationDataset",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_encryption_tokenization_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Agency shall perform encryption of the file.",
            "perform encryption of the file",
            "O(∀x (Agency(x) → EncryptFile(x)))",
            "PerformEncryptionFile",
        ),
        (
            "The Clerk shall complete decryption of the record.",
            "complete decryption of the record",
            "O(∀x (Clerk(x) → DecryptRecord(x)))",
            "CompleteDecryptionRecord",
        ),
        (
            "The processor shall complete tokenization of the account number.",
            "complete tokenization of the account number",
            "O(∀x (Processor(x) → TokenizeAccountNumber(x)))",
            "CompleteTokenizationAccountNumber",
        ),
        (
            "The custodian shall perform detokenization of the dataset.",
            "perform detokenization of the dataset",
            "O(∀x (Custodian(x) → DetokenizeDataset(x)))",
            "PerformDetokenizationDataset",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_sealing_unsealing_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall perform sealing of the record.",
            "perform sealing of the record",
            "O(∀x (Clerk(x) → SealRecord(x)))",
            "PerformSealingRecord",
        ),
        (
            "The custodian shall complete unsealing of the file.",
            "complete unsealing of the file",
            "O(∀x (Custodian(x) → UnsealFile(x)))",
            "CompleteUnsealingFile",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_expungement_destruction_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall perform expungement of the record.",
            "perform expungement of the record",
            "O(∀x (Clerk(x) → ExpungeRecord(x)))",
            "PerformExpungementRecord",
        ),
        (
            "The custodian shall complete destruction of the file.",
            "complete destruction of the file",
            "O(∀x (Custodian(x) → DestroyFile(x)))",
            "CompleteDestructionFile",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_enforcement_remedy_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Agency shall file a lien against the property.",
            "file a lien against the property",
            "O(∀x (Agency(x) → LienProperty(x)))",
            "FileLienProperty",
        ),
        (
            "The Treasurer shall impose a levy on the account.",
            "impose a levy on the account",
            "O(∀x (Treasurer(x) → LevyAccount(x)))",
            "ImposeLevyAccount",
        ),
        (
            "The Court shall order forfeiture of the bond.",
            "order forfeiture of the bond",
            "O(∀x (Court(x) → ForfeitBond(x)))",
            "OrderForfeitureBond",
        ),
        (
            "The officer shall conduct seizure of the vehicle.",
            "conduct seizure of the vehicle",
            "O(∀x (Officer(x) → SeizeVehicle(x)))",
            "ConductSeizureVehicle",
        ),
        (
            "The Bureau shall order impoundment of the vehicle.",
            "order impoundment of the vehicle",
            "O(∀x (Bureau(x) → ImpoundVehicle(x)))",
            "OrderImpoundmentVehicle",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_recordation_memorialization_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make a recordation of the lien.",
            "make a recordation of the lien",
            "O(∀x (Clerk(x) → RecordLien(x)))",
            "MakeRecordationLien",
        ),
        (
            "The Board shall enter memorialization of the order.",
            "enter memorialization of the order",
            "O(∀x (Board(x) → MemorializeOrder(x)))",
            "EnterMemorializationOrder",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ratification_confirmation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Council shall make a ratification of the agreement.",
            "make a ratification of the agreement",
            "O(∀x (Council(x) → RatifyAgreement(x)))",
            "MakeRatificationAgreement",
        ),
        (
            "The Clerk shall issue confirmation of the order.",
            "issue confirmation of the order",
            "O(∀x (Clerk(x) → ConfirmOrder(x)))",
            "IssueConfirmationOrder",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_attestation_notarization_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make an attestation of the signature.",
            "make an attestation of the signature",
            "O(∀x (Clerk(x) → AttestSignature(x)))",
            "MakeAttestationSignature",
        ),
        (
            "The notary shall perform notarization of the affidavit.",
            "perform notarization of the affidavit",
            "O(∀x (Notary(x) → NotarizeAffidavit(x)))",
            "PerformNotarizationAffidavit",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_acknowledgment_authentication_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make an acknowledgment of the receipt.",
            "make an acknowledgment of the receipt",
            "O(∀x (Clerk(x) → AcknowledgeReceipt(x)))",
            "MakeAcknowledgmentReceipt",
        ),
        (
            "The officer shall perform authentication of the identity.",
            "perform authentication of the identity",
            "O(∀x (Officer(x) → AuthenticateIdentity(x)))",
            "PerformAuthenticationIdentity",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_summarization_indexing_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare a summary of the minutes.",
            "prepare a summary of the minutes",
            "O(∀x (Clerk(x) → SummarizeMinutes(x)))",
            "PrepareSummaryMinutes",
        ),
        (
            "The agency shall create indexing of the records.",
            "create indexing of the records",
            "O(∀x (Agency(x) → IndexRecords(x)))",
            "CreateIndexingRecords",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_transcription_translation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare a transcription of the recording.",
            "prepare a transcription of the recording",
            "O(∀x (Clerk(x) → TranscribeRecording(x)))",
            "PrepareTranscriptionRecording",
        ),
        (
            "The interpreter shall provide translation of the notice.",
            "provide translation of the notice",
            "O(∀x (Interpreter(x) → TranslateNotice(x)))",
            "ProvideTranslationNotice",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_codification_recodification_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make a codification of the ordinance.",
            "make a codification of the ordinance",
            "O(∀x (Clerk(x) → CodifyOrdinance(x)))",
            "MakeCodificationOrdinance",
        ),
        (
            "The Council shall complete recodification of the chapter.",
            "complete recodification of the chapter",
            "O(∀x (Council(x) → RecodifyChapter(x)))",
            "CompleteRecodificationChapter",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_consolidation_reconciliation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare a consolidation of the docket.",
            "prepare a consolidation of the docket",
            "O(∀x (Clerk(x) → ConsolidateDocket(x)))",
            "PrepareConsolidationDocket",
        ),
        (
            "The Treasurer shall perform reconciliation of the account.",
            "perform reconciliation of the account",
            "O(∀x (Treasurer(x) → ReconcileAccount(x)))",
            "PerformReconciliationAccount",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_aggregation_tabulation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare an aggregation of the returns.",
            "prepare an aggregation of the returns",
            "O(∀x (Clerk(x) → AggregateReturns(x)))",
            "PrepareAggregationReturns",
        ),
        (
            "The Auditor shall perform tabulation of the ballots.",
            "perform tabulation of the ballots",
            "O(∀x (Auditor(x) → TabulateBallots(x)))",
            "PerformTabulationBallots",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_segregation_sequestration_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The custodian shall perform segregation of the funds.",
            "perform segregation of the funds",
            "O(∀x (Custodian(x) → SegregateFunds(x)))",
            "PerformSegregationFunds",
        ),
        (
            "The receiver shall complete sequestration of the property.",
            "complete sequestration of the property",
            "O(∀x (Receiver(x) → SequesterProperty(x)))",
            "CompleteSequestrationProperty",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_assignment_allocation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make an assignment of the claim.",
            "make an assignment of the claim",
            "O(∀x (Clerk(x) → AssignClaim(x)))",
            "MakeAssignmentClaim",
        ),
        (
            "The Treasurer shall perform allocation of the funds.",
            "perform allocation of the funds",
            "O(∀x (Treasurer(x) → AllocateFunds(x)))",
            "PerformAllocationFunds",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_prioritization_scheduling_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall prepare a prioritization of the applications.",
            "prepare a prioritization of the applications",
            "O(∀x (Clerk(x) → PrioritizeApplications(x)))",
            "PreparePrioritizationApplications",
        ),
        (
            "The Board shall make a scheduling of the hearing.",
            "make a scheduling of the hearing",
            "O(∀x (Board(x) → ScheduleHearing(x)))",
            "MakeSchedulingHearing",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_delegation_reservation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make a delegation of the authority.",
            "make a delegation of the authority",
            "O(∀x (Director(x) → DelegateAuthority(x)))",
            "MakeDelegationAuthority",
        ),
        (
            "The Board shall make a reservation of the jurisdiction.",
            "make a reservation of the jurisdiction",
            "O(∀x (Board(x) → ReserveJurisdiction(x)))",
            "MakeReservationJurisdiction",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_ratification_confirmation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Board shall make a ratification of the decision.",
            "make a ratification of the decision",
            "O(∀x (Board(x) → RatifyDecision(x)))",
            "MakeRatificationDecision",
        ),
        (
            "The Clerk shall issue confirmation of the order.",
            "issue confirmation of the order",
            "O(∀x (Clerk(x) → ConfirmOrder(x)))",
            "IssueConfirmationOrder",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_codification_consolidation_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Commission shall make a codification of the rules.",
            "make a codification of the rules",
            "O(∀x (Commission(x) → CodifyRules(x)))",
            "MakeCodificationRules",
        ),
        (
            "The Court shall effect consolidation of the proceedings.",
            "effect consolidation of the proceedings",
            "O(∀x (Court(x) → ConsolidateProceedings(x)))",
            "EffectConsolidationProceedings",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_revocation_suspension_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Director shall make a revocation of the permit.",
            "make a revocation of the permit",
            "O(∀x (Director(x) → RevokePermit(x)))",
            "MakeRevocationPermit",
        ),
        (
            "The Board shall order suspension of the license.",
            "order suspension of the license",
            "O(∀x (Board(x) → SuspendLicense(x)))",
            "OrderSuspensionLicense",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]


def test_expungement_sealing_light_verb_duties_export_operative_predicates():
    examples = [
        (
            "The Clerk shall make an expungement of the record.",
            "make an expungement of the record",
            "O(∀x (Clerk(x) → ExpungeRecord(x)))",
            "MakeExpungementRecord",
        ),
        (
            "The Court shall order sealing of the file.",
            "order sealing of the file",
            "O(∀x (Court(x) → SealFile(x)))",
            "OrderSealingFile",
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

    blocked = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert blocked["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in blocked["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in blocked["llm_repair"]["reasons"]
