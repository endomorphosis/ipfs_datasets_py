"""Tests for IR-derived deterministic export records."""

from ipfs_datasets_py.logic.deontic.exports import (
    active_repair_details_from_parser_elements,
    build_document_export_tables_from_ir,
    build_formal_logic_record_from_ir,
    build_proof_obligation_record_from_ir,
    build_procedure_event_records_from_ir,
    normalize_repair_required_evaluation,
    normalize_repair_required_details_from_parser_elements,
    parser_element_has_active_repair,
    parser_elements_to_export_tables,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
    parser_elements_to_ir_aligned_export_tables,
    summarize_active_repair_from_parser_elements,
    validate_export_tables,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_ir_formal_logic_record_preserves_provenance_for_proof_ready_clause():
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_formal_logic_record_from_ir(norm)

    assert record["formula"] == "O(∀x (Tenant(x) ∧ PeriodMonthly(x) → PayRentMonthly(x)))"
    assert record["formula_id"].startswith("formula:")
    assert record["source_id"] == element["source_id"]
    assert record["support_span"] == element["support_span"]
    assert record["field_spans"] == element["field_spans"]
    assert record["target_logic"] == "deontic"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["blockers"] == []


def test_ir_formal_logic_record_preserves_deterministic_resolution_metadata():
    element = extract_normative_elements("This section applies to food carts.")[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_formal_logic_record_from_ir(norm)

    assert norm.proof_ready is False
    assert record["formula"] == "AppliesTo(ThisSection, FoodCarts)"
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"]["type"] == "local_scope_applicability"
    assert "cross_reference_requires_resolution" in record["blockers"]


def test_ir_proof_record_uses_formula_level_resolution_for_local_applicability():
    element = extract_normative_elements("This section applies to food carts.")[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_proof_obligation_record_from_ir(norm)

    assert norm.proof_ready is False
    assert record["formula"] == "AppliesTo(ThisSection, FoodCarts)"
    assert record["theorem_candidate"] is True
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["repair_required"] is False
    assert record["deterministic_resolution"]["type"] == "local_scope_applicability"
    assert "cross_reference_requires_resolution" in record["blockers"]


def test_canonical_rows_expose_export_repair_status_without_relaxing_parser_gate():
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    tables = build_document_export_tables_from_ir(norms)
    canonical = tables["canonical"]

    assert [norm.proof_ready for norm in norms] == [False, False, False, False]
    assert [row["parser_proof_ready"] for row in canonical] == [False, False, False, False]
    assert [row["proof_ready"] for row in canonical] == [True, True, True, False]
    assert [row["export_proof_ready"] for row in canonical] == [True, True, True, False]
    assert [row["requires_validation"] for row in canonical] == [False, False, False, True]
    assert [row["export_repair_required"] for row in canonical] == [False, False, False, True]
    assert [row["repair_required"] for row in canonical] == [False, False, False, True]
    assert [row["deterministic_resolution"].get("type") for row in canonical] == [
        "local_scope_applicability",
        "standard_substantive_exception",
        "pure_precedence_override",
        None,
    ]
    assert len(tables["repair_queue"]) == 1


def test_ir_proof_record_uses_formula_level_resolution_for_substantive_exception():
    element = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_proof_obligation_record_from_ir(norm)

    assert norm.proof_ready is False
    assert record["formula"] == "O(∀x (Applicant(x) ∧ ¬ApprovalIsDenied(x) → ObtainPermit(x)))"
    assert record["theorem_candidate"] is True
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["deterministic_resolution"]["type"] == "standard_substantive_exception"
    assert "exception_requires_scope_review" in record["blockers"]


def test_ir_proof_record_uses_formula_level_resolution_for_pure_override():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_proof_obligation_record_from_ir(norm)

    assert norm.proof_ready is False
    assert record["formula"] == "P(∀x (Director(x) → IssueVariance(x)))"
    assert record["theorem_candidate"] is True
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert record["deterministic_resolution"]["type"] == "pure_precedence_override"
    assert "override_clause_requires_precedence_review" in record["blockers"]


def test_ir_proof_record_does_not_promote_blocked_cross_reference_exception():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    record = build_proof_obligation_record_from_ir(norm)

    assert record["proof_obligation_id"].startswith("proof:")
    assert record["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in record["formula"]
    assert record["theorem_candidate"] is False
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert "cross_reference_requires_resolution" in record["blockers"]
    assert "exception_requires_scope_review" in record["parser_warnings"]
    assert record["deterministic_resolution"] == {}


def test_ir_procedure_event_relation_records_preserve_ordering_provenance_without_formula_strengthening():
    element = extract_normative_elements(
        "Upon receipt of an application, the Bureau shall inspect the premises before approval."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    receipt_record = next(
        record for record in records if record["relation"] == "triggered_by_receipt_of"
    )
    before_record = next(record for record in records if record["relation"] == "before")

    assert receipt_record["event_id"].startswith("event:")
    assert receipt_record["source_id"] == element["source_id"]
    assert receipt_record["event"] == "inspection"
    assert receipt_record["event_symbol"] == "Inspection"
    assert receipt_record["anchor_event"] == "application"
    assert receipt_record["anchor_symbol"] == "Application"
    assert receipt_record["span"] == [0, 30]
    assert receipt_record["support_span"] == element["support_span"]
    assert receipt_record["is_formula_antecedent"] is True
    assert receipt_record["proof_role"] == "prerequisite"

    assert before_record["source_id"] == element["source_id"]
    assert before_record["event"] == "inspection"
    assert before_record["anchor_event"] == "issuance"
    assert before_record["raw_text"].startswith("before approval")
    assert before_record["is_formula_antecedent"] is False
    assert before_record["proof_role"] == "ordering_provenance"
    assert before_record["relation_record"]["relation"] == "before"

    formula = build_deontic_formula_from_ir(norm)
    assert formula == "O(∀x (Bureau(x) ∧ ProcedureUponReceiptApplication(x) → InspectPremises(x)))"
    assert "ProcedureBeforeIssuance" not in formula


def test_ir_procedure_event_records_mark_filing_and_submission_triggers_as_prerequisites():
    element = extract_normative_elements(
        "The Director shall issue a permit after filing of an application."
    )[0]
    element = dict(element)
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_filing_of",
                "anchor_event": "application",
                "raw_text": "after filing of an application",
                "span": [36, 66],
            },
            {
                "event": "issuance",
                "relation": "triggered_by_submission_of",
                "anchor_event": "complete application",
                "raw_text": "after submission of a complete application",
                "span": [0, 0],
            },
            {
                "event": "issuance",
                "relation": "after",
                "anchor_event": "notice",
                "raw_text": "after notice",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    filing_record = next(
        record for record in records if record["relation"] == "triggered_by_filing_of"
    )
    submission_record = next(
        record for record in records if record["relation"] == "triggered_by_submission_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert filing_record["is_formula_antecedent"] is True
    assert filing_record["proof_role"] == "prerequisite"
    assert filing_record["anchor_event"] == "application"
    assert filing_record["span"] == [36, 66]
    assert submission_record["is_formula_antecedent"] is True
    assert submission_record["proof_role"] == "prerequisite"
    assert submission_record["anchor_event"] == "complete application"
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"


def test_ir_procedure_event_records_mark_notice_and_hearing_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall issue a permit after notice and hearing."
    )[0]
    element = dict(element)
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_notice_and_hearing",
                "anchor_event": "notice and hearing",
                "raw_text": "after notice and hearing",
                "span": [36, 60],
            },
            {
                "event": "issuance",
                "relation": "after",
                "anchor_event": "publication",
                "raw_text": "after publication",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    notice_record = next(
        record for record in records if record["relation"] == "triggered_by_notice_and_hearing"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert notice_record["is_formula_antecedent"] is True
    assert notice_record["proof_role"] == "prerequisite"
    assert notice_record["anchor_event"] == "notice and hearing"
    assert notice_record["anchor_symbol"] == "NoticeAndHearing"
    assert notice_record["span"] == [36, 60]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"


def test_ir_procedure_event_records_mark_approval_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall issue a permit upon approval of an application."
    )[0]
    element = dict(element)
    element["action"] = ["issue a permit upon approval application"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_approval_of",
                "anchor_event": "application",
                "raw_text": "upon approval of an application",
                "span": [36, 67],
            },
            {
                "event": "issuance",
                "relation": "after",
                "anchor_event": "publication",
                "raw_text": "after publication",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    approval_record = next(
        record for record in records if record["relation"] == "triggered_by_approval_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert approval_record["is_formula_antecedent"] is True
    assert approval_record["proof_role"] == "prerequisite"
    assert approval_record["anchor_event"] == "application"
    assert approval_record["anchor_symbol"] == "Application"
    assert approval_record["span"] == [36, 67]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureUponApprovalApplication(x) → IssuePermit(x)))"
    )


def test_ir_procedure_event_records_mark_completion_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall issue a permit after completion of an inspection."
    )[0]
    element = dict(element)
    element["action"] = ["issue a permit after completion inspection"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_completion_of",
                "anchor_event": "inspection",
                "raw_text": "after completion of an inspection",
                "span": [36, 70],
            },
            {
                "event": "issuance",
                "relation": "after",
                "anchor_event": "publication",
                "raw_text": "after publication",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    completion_record = next(
        record for record in records if record["relation"] == "triggered_by_completion_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert completion_record["is_formula_antecedent"] is True
    assert completion_record["proof_role"] == "prerequisite"
    assert completion_record["anchor_event"] == "inspection"
    assert completion_record["anchor_symbol"] == "Inspection"
    assert completion_record["span"] == [36, 70]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureAfterCompletionInspection(x) → IssuePermit(x)))"
    )


def test_ir_procedure_event_records_mark_effective_date_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall issue a permit upon the effective date of the ordinance."
    )[0]
    element = dict(element)
    element["action"] = ["issue a permit upon effective date ordinance"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_effective_date_of",
                "anchor_event": "ordinance",
                "raw_text": "upon the effective date of the ordinance",
                "span": [36, 78],
            },
            {
                "event": "issuance",
                "relation": "after",
                "anchor_event": "publication",
                "raw_text": "after publication",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    effective_date_record = next(
        record for record in records if record["relation"] == "triggered_by_effective_date_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert effective_date_record["is_formula_antecedent"] is True
    assert effective_date_record["proof_role"] == "prerequisite"
    assert effective_date_record["anchor_event"] == "ordinance"
    assert effective_date_record["anchor_symbol"] == "Ordinance"
    assert effective_date_record["span"] == [36, 78]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureUponEffectiveDateOrdinance(x) → IssuePermit(x)))"
    )


def test_ir_procedure_event_records_mark_certification_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall issue a permit upon certification of an inspection."
    )[0]
    element = dict(element)
    element["action"] = ["issue a permit upon certification inspection"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_certification_of",
                "anchor_event": "inspection",
                "raw_text": "upon certification of an inspection",
                "span": [36, 73],
            },
            {
                "event": "issuance",
                "relation": "after",
                "anchor_event": "publication",
                "raw_text": "after publication",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    certification_record = next(
        record for record in records if record["relation"] == "triggered_by_certification_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert certification_record["is_formula_antecedent"] is True
    assert certification_record["proof_role"] == "prerequisite"
    assert certification_record["anchor_event"] == "inspection"
    assert certification_record["anchor_symbol"] == "Inspection"
    assert certification_record["span"] == [36, 73]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureUponCertificationInspection(x) → IssuePermit(x)))"
    )


def test_ir_procedure_event_records_mark_issuance_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall renew a permit after issuance of the license."
    )[0]
    element = dict(element)
    element["action"] = ["renew a permit after issuance license"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_issuance_of",
                "anchor_event": "license",
                "raw_text": "after issuance of the license",
                "span": [36, 65],
            },
            {
                "event": "renewal",
                "relation": "after",
                "anchor_event": "inspection",
                "raw_text": "after inspection",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    issuance_record = next(
        record for record in records if record["relation"] == "triggered_by_issuance_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert issuance_record["is_formula_antecedent"] is True
    assert issuance_record["proof_role"] == "prerequisite"
    assert issuance_record["anchor_event"] == "license"
    assert issuance_record["anchor_symbol"] == "License"
    assert issuance_record["span"] == [36, 65]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureAfterIssuanceLicense(x) → RenewPermit(x)))"
    )


def test_ir_procedure_event_records_mark_publication_trigger_as_prerequisite():
    element = extract_normative_elements(
        "The Director shall renew a permit after publication of the notice."
    )[0]
    element = dict(element)
    element["action"] = ["renew a permit after publication notice"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_publication_of",
                "anchor_event": "notice",
                "raw_text": "after publication of the notice",
                "span": [36, 68],
            },
            {
                "event": "renewal",
                "relation": "after",
                "anchor_event": "inspection",
                "raw_text": "after inspection",
                "span": [0, 0],
            },
        ]
    }
    norm = LegalNormIR.from_parser_element(element)

    records = build_procedure_event_records_from_ir(norm)
    publication_record = next(
        record for record in records if record["relation"] == "triggered_by_publication_of"
    )
    after_record = next(record for record in records if record["relation"] == "after")

    assert publication_record["is_formula_antecedent"] is True
    assert publication_record["proof_role"] == "prerequisite"
    assert publication_record["anchor_event"] == "notice"
    assert publication_record["anchor_symbol"] == "Notice"
    assert publication_record["span"] == [36, 68]
    assert after_record["is_formula_antecedent"] is False
    assert after_record["proof_role"] == "ordering_provenance"
    assert build_deontic_formula_from_ir(norm) == (
        "O(∀x (Director(x) ∧ ProcedureAfterPublicationNotice(x) → RenewPermit(x)))"
    )


def test_document_export_tables_from_ir_include_repair_rows_only_for_blocked_norms():
    elements = [
        extract_normative_elements("The tenant must pay rent monthly.")[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    tables = build_document_export_tables_from_ir(norms)

    assert set(tables) == {"canonical", "formal_logic", "proof_obligations", "repair_queue"}
    assert len(tables["canonical"]) == 2
    assert len(tables["formal_logic"]) == 2
    assert len(tables["proof_obligations"]) == 2
    assert len(tables["repair_queue"]) == 1

    proof_ready_rows = [row for row in tables["proof_obligations"] if row["proof_ready"]]
    blocked_rows = [row for row in tables["proof_obligations"] if not row["proof_ready"]]
    assert len(proof_ready_rows) == 1
    assert len(blocked_rows) == 1
    assert tables["repair_queue"][0]["source_id"] == blocked_rows[0]["source_id"]
    assert tables["repair_queue"][0]["allow_llm_repair"] is False
    assert tables["repair_queue"][0]["formula_proof_ready"] is False
    assert tables["repair_queue"][0]["formula_repair_required"] is True
    assert "cross_reference_requires_resolution" in tables["repair_queue"][0]["reasons"]

    validation = validate_export_tables(tables)
    assert validation == {"valid": True, "errors": []}


def test_document_export_tables_skip_repair_rows_for_formula_resolved_norms():
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    tables = build_document_export_tables_from_ir(norms)

    assert len(tables["canonical"]) == 4
    assert len(tables["formal_logic"]) == 4
    assert len(tables["proof_obligations"]) == 4
    assert len(tables["repair_queue"]) == 1
    assert [row["proof_ready"] for row in tables["proof_obligations"]] == [
        True,
        True,
        True,
        False,
    ]
    assert tables["proof_obligations"][0]["deterministic_resolution"]["type"] == "local_scope_applicability"
    assert tables["proof_obligations"][1]["deterministic_resolution"]["type"] == "standard_substantive_exception"
    assert tables["proof_obligations"][2]["deterministic_resolution"]["type"] == "pure_precedence_override"
    assert tables["repair_queue"][0]["source_id"] == norms[3].source_id
    assert validate_export_tables(tables)["valid"] is True


def test_parser_elements_with_ir_export_readiness_clears_formula_resolved_repair_noise():
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    aligned = parser_elements_with_ir_export_readiness(elements)

    assert [element["promotable_to_theorem"] for element in aligned] == [
        False,
        False,
        False,
        False,
    ]
    assert [element["export_readiness"]["proof_ready"] for element in aligned] == [
        True,
        True,
        True,
        False,
    ]
    assert [element["export_readiness"]["repair_required"] for element in aligned] == [
        False,
        False,
        False,
        True,
    ]
    assert [element["export_readiness"]["deterministic_resolution"].get("type") for element in aligned] == [
        "local_scope_applicability",
        "standard_substantive_exception",
        "pure_precedence_override",
        None,
    ]
    assert [element["llm_repair"].get("required") for element in aligned] == [
        False,
        False,
        False,
        True,
    ]
    assert aligned[3]["llm_repair"].get("deterministically_resolved") is not True
    assert "cross_reference_requires_resolution" in aligned[3]["llm_repair"]["reasons"]


def test_parser_element_readiness_clears_substantive_exception_repair_reason():
    element = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]

    aligned = parser_elements_with_ir_export_readiness([element])

    assert element["promotable_to_theorem"] is False
    assert "exception_requires_scope_review" in element["parser_warnings"]
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["deterministically_resolved"] is True
    assert element["llm_repair"]["deterministic_resolution"]["type"] == "standard_substantive_exception"
    assert aligned[0]["promotable_to_theorem"] is False
    assert aligned[0]["export_readiness"]["parser_proof_ready"] is False
    assert aligned[0]["export_readiness"]["formula_proof_ready"] is True
    assert aligned[0]["export_readiness"]["proof_ready"] is True
    assert aligned[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "standard_substantive_exception"
    )
    assert aligned[0]["llm_repair"]["required"] is False
    assert aligned[0]["llm_repair"]["allow_llm_repair"] is False
    assert aligned[0]["llm_repair"]["reasons"] == []
    assert aligned[0]["llm_repair"]["deterministically_resolved"] is True
    assert aligned[0]["export_readiness"]["metric_requires_validation"] is False
    assert aligned[0]["export_readiness"]["metric_repair_required"] is False
    assert aligned[0]["active_repair_warnings"] == []
    assert aligned[0]["repair_required_warnings"] == []


def test_formula_resolved_substantive_exception_is_not_active_repair_detail():
    elements = [
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    details = active_repair_details_from_parser_elements(elements)

    assert len(details) == 1
    assert details[0]["source_id"] == elements[1]["source_id"]
    assert details[0]["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]


def test_document_export_tables_skip_repair_row_for_resolved_reference_exception():
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

    tables = build_document_export_tables_from_ir([norm])

    assert norm.proof_ready is False
    assert len(tables["canonical"]) == 1
    assert len(tables["formal_logic"]) == 1
    assert len(tables["proof_obligations"]) == 1
    assert tables["repair_queue"] == []
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["repair_required"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert tables["formal_logic"][0]["deterministic_resolution"]["references"] == ["section 552"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert tables["proof_obligations"][0]["requires_validation"] is False
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_skip_repair_row_for_local_scope_reference_exception():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in this section."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    assert norm.proof_ready is False
    assert tables["repair_queue"] == []
    assert tables["canonical"][0]["parser_proof_ready"] is False
    assert tables["canonical"][0]["proof_ready"] is True
    assert tables["canonical"][0]["repair_required"] is False
    assert tables["formal_logic"][0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "AsProvidedThisSection" not in tables["formal_logic"][0]["formula"]
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["repair_required"] is False
    assert tables["formal_logic"][0]["omitted_formula_slots"]["exceptions"][0]["value"] == (
        "as provided in this section"
    )
    assert tables["formal_logic"][0]["deterministic_resolution"] == {
        "type": "local_scope_reference_exception",
        "resolved_blockers": sorted(set(norm.blockers)),
        "scopes": ["this section"],
        "exception_spans": [norm.exceptions[0].get("span", [])],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert tables["proof_obligations"][0]["requires_validation"] is False
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_keep_repair_row_for_numbered_reference_exception_without_resolution():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    assert len(tables["repair_queue"]) == 1
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"] == {}
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_use_canonical_text_for_same_document_reference_exception():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "target": "552",
            "canonical_citation": "section 552",
            "same_document": True,
            "source_id": "deontic:resolved-section-552",
        }
    ]
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    assert tables["repair_queue"] == []
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"]["references"] == [
        "section 552"
    ]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert tables["proof_obligations"][0]["deterministic_resolution"]["references"] == [
        "section 552"
    ]
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_skip_repair_row_for_same_document_cross_reference_detail():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "target": "552",
            "canonical_citation": "section 552",
            "same_document": True,
            "source_id": "deontic:resolved-section-552",
        }
    ]
    element["resolved_cross_references"] = []
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    assert norm.proof_ready is False
    assert tables["repair_queue"] == []
    assert tables["canonical"][0]["parser_proof_ready"] is False
    assert tables["canonical"][0]["proof_ready"] is True
    assert tables["canonical"][0]["repair_required"] is False
    assert tables["formal_logic"][0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in tables["formal_logic"][0]["formula"]
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert tables["formal_logic"][0]["deterministic_resolution"]["references"] == ["section 552"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_resolve_numbered_reference_exception_from_same_batch_section():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    target_element = extract_normative_elements("The Bureau shall maintain the public register.")[0]
    target_element = dict(target_element)
    target_element["canonical_citation"] = "section 552"

    norms = [
        LegalNormIR.from_parser_element(reference_element),
        LegalNormIR.from_parser_element(target_element),
    ]

    tables = build_document_export_tables_from_ir(norms)

    assert tables["repair_queue"] == []
    reference_formula = tables["formal_logic"][0]
    assert reference_formula["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in reference_formula["formula"]
    assert reference_formula["proof_ready"] is True
    assert reference_formula["requires_validation"] is False
    assert reference_formula["repair_required"] is False
    assert reference_formula["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert reference_formula["deterministic_resolution"]["references"] == ["section 552"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert tables["canonical"][0]["parser_proof_ready"] is False
    assert tables["canonical"][0]["export_proof_ready"] is True
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_keep_numbered_reference_exception_blocked_when_section_absent():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    unrelated_element = extract_normative_elements("The Bureau shall maintain the public register.")[0]
    unrelated_element = dict(unrelated_element)
    unrelated_element["canonical_citation"] = "section 553"

    norms = [
        LegalNormIR.from_parser_element(reference_element),
        LegalNormIR.from_parser_element(unrelated_element),
    ]

    tables = build_document_export_tables_from_ir(norms)

    assert len(tables["repair_queue"]) == 1
    assert tables["repair_queue"][0]["source_id"] == reference_element["source_id"]
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["requires_validation"] is True
    assert tables["formal_logic"][0]["deterministic_resolution"] == {}
    assert tables["proof_obligations"][0]["theorem_candidate"] is False
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_resolve_reference_condition_from_same_batch_section():
    reference_element = extract_normative_elements(
        "Subject to section 552, the Secretary shall publish the notice."
    )[0]
    target_element = extract_normative_elements("The Bureau shall maintain the public register.")[0]
    target_element = dict(target_element)
    target_element["canonical_citation"] = "section 552"

    norms = [
        LegalNormIR.from_parser_element(reference_element),
        LegalNormIR.from_parser_element(target_element),
    ]

    tables = build_document_export_tables_from_ir(norms)

    assert tables["repair_queue"] == []
    reference_formula = tables["formal_logic"][0]
    assert reference_formula["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in reference_formula["formula"]
    assert reference_formula["proof_ready"] is True
    assert reference_formula["requires_validation"] is False
    assert reference_formula["repair_required"] is False
    assert reference_formula["omitted_formula_slots"]["conditions"][0]["value"] == "section 552"
    assert reference_formula["deterministic_resolution"] == {
        "type": "resolved_same_document_reference_condition",
        "resolved_blockers": sorted(set(norms[0].blockers)),
        "references": ["section 552"],
        "condition_spans": [norms[0].conditions[0].get("span", [])],
        "reason": "reference-only condition is backed by explicit same-document cross-reference resolution",
    }
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert tables["canonical"][0]["parser_proof_ready"] is False
    assert tables["canonical"][0]["export_proof_ready"] is True
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_keep_reference_condition_blocked_when_section_absent():
    reference_element = extract_normative_elements(
        "Subject to section 552, the Secretary shall publish the notice."
    )[0]
    unrelated_element = extract_normative_elements("The Bureau shall maintain the public register.")[0]
    unrelated_element = dict(unrelated_element)
    unrelated_element["canonical_citation"] = "section 553"

    norms = [
        LegalNormIR.from_parser_element(reference_element),
        LegalNormIR.from_parser_element(unrelated_element),
    ]

    tables = build_document_export_tables_from_ir(norms)

    assert len(tables["repair_queue"]) == 1
    assert tables["repair_queue"][0]["source_id"] == reference_element["source_id"]
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["requires_validation"] is True
    assert tables["formal_logic"][0]["deterministic_resolution"] == {}
    assert tables["proof_obligations"][0]["theorem_candidate"] is False
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_keep_reference_condition_blocked_for_external_resolution():
    element = extract_normative_elements(
        "Subject to section 552, the Secretary shall publish the notice."
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

    tables = build_document_export_tables_from_ir([norm])

    assert len(tables["repair_queue"]) == 1
    assert tables["formal_logic"][0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in tables["formal_logic"][0]["formula"]
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["requires_validation"] is True
    assert tables["formal_logic"][0]["deterministic_resolution"] == {}
    assert tables["proof_obligations"][0]["theorem_candidate"] is False
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_skip_repair_row_for_local_scope_cross_reference_detail():
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

    tables = build_document_export_tables_from_ir([norm])

    assert norm.proof_ready is False
    assert tables["repair_queue"] == []
    assert tables["canonical"][0]["parser_proof_ready"] is False
    assert tables["canonical"][0]["proof_ready"] is True
    assert tables["canonical"][0]["repair_required"] is False
    assert tables["formal_logic"][0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"]["type"] == (
        "local_scope_reference_exception"
    )
    assert tables["formal_logic"][0]["deterministic_resolution"]["scopes"] == ["this section"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_skip_repair_row_for_otherwise_local_scope_exception():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as otherwise provided in this section."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    assert norm.proof_ready is False
    assert "exception_requires_scope_review" in norm.blockers
    assert tables["repair_queue"] == []
    assert tables["canonical"][0]["parser_proof_ready"] is False
    assert tables["canonical"][0]["proof_ready"] is True
    assert tables["canonical"][0]["repair_required"] is False
    assert tables["formal_logic"][0]["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "AsOtherwiseProvidedThisSection" not in tables["formal_logic"][0]["formula"]
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"]["type"] == "local_scope_reference_exception"
    assert tables["formal_logic"][0]["deterministic_resolution"]["scopes"] == ["this section"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_keep_repair_row_for_external_reference_exception():
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

    tables = build_document_export_tables_from_ir([norm])

    assert len(tables["repair_queue"]) == 1
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["requires_validation"] is True
    assert tables["formal_logic"][0]["repair_required"] is True
    assert tables["proof_obligations"][0]["repair_required"] is True
    assert tables["formal_logic"][0]["deterministic_resolution"] == {}
    assert tables["proof_obligations"][0]["theorem_candidate"] is False
    assert tables["repair_queue"][0]["source_id"] == norm.source_id
    assert "cross_reference_requires_resolution" in tables["repair_queue"][0]["reasons"]
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_repair_queue_uses_formula_requires_validation_not_parser_theorem_gate():
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
    ]
    norms = [LegalNormIR.from_parser_element(element) for element in elements]

    tables = build_document_export_tables_from_ir(norms)

    assert [norm.proof_ready for norm in norms] == [False, False, False]
    assert tables["repair_queue"] == []
    assert [row["requires_validation"] for row in tables["formal_logic"]] == [
        False,
        False,
        False,
    ]
    assert [row["repair_required"] for row in tables["formal_logic"]] == [
        False,
        False,
        False,
    ]
    assert [row["proof_ready"] for row in tables["proof_obligations"]] == [
        True,
        True,
        True,
    ]
    assert [row["deterministic_resolution"]["type"] for row in tables["formal_logic"]] == [
        "local_scope_applicability",
        "standard_substantive_exception",
        "pure_precedence_override",
    ]


def test_parser_elements_to_export_tables_matches_ir_table_shape():
    elements = extract_normative_elements(
        "The Secretary shall (1) establish procedures; (2) submit a report; and (3) maintain records.",
        expand_enumerations=True,
    )

    tables = parser_elements_to_export_tables(elements)

    assert len(tables["canonical"]) == 3
    assert len(tables["formal_logic"]) == 3
    assert [row["formula"] for row in tables["formal_logic"]] == [
        "O(∀x (Secretary(x) → EstablishProcedures(x)))",
        "O(∀x (Secretary(x) → SubmitReport(x)))",
        "O(∀x (Secretary(x) → MaintainRecords(x)))",
    ]
    assert all(row["proof_ready"] for row in tables["proof_obligations"])
    assert tables["repair_queue"] == []
    assert validate_export_tables(tables)["valid"] is True


def test_ir_aligned_export_tables_clear_formula_resolved_repairs_and_keep_auxiliary_tables():
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    legacy_tables = {
        "canonical": [{"source_id": "legacy:stale", "repair_required": True}],
        "formal_logic": [{"formula_id": "legacy:stale", "source_id": "legacy:stale"}],
        "proof_obligations": [{"proof_obligation_id": "legacy:stale", "source_id": "legacy:stale"}],
        "repair_queue": [{"repair_id": "legacy:stale", "source_id": "legacy:stale"}],
        "knowledge_graph_triples": [
            {"triple_id": "triple:1", "source_id": elements[0]["source_id"], "predicate": "appliesTo"}
        ],
        "procedure_event_records": [
            {"event_id": "event:1", "source_id": elements[1]["source_id"], "event": "review"}
        ],
    }

    tables = parser_elements_to_ir_aligned_export_tables(elements, legacy_tables)

    assert len(tables["canonical"]) == 4
    assert len(tables["formal_logic"]) == 4
    assert len(tables["proof_obligations"]) == 4
    assert [row["proof_ready"] for row in tables["proof_obligations"]] == [
        True,
        True,
        True,
        False,
    ]
    assert [row["deterministic_resolution"].get("type") for row in tables["formal_logic"]] == [
        "local_scope_applicability",
        "standard_substantive_exception",
        "pure_precedence_override",
        None,
    ]
    assert len(tables["repair_queue"]) == 1
    assert tables["repair_queue"][0]["source_id"] == elements[3]["source_id"]
    assert tables["knowledge_graph_triples"] == legacy_tables["knowledge_graph_triples"]
    assert tables["procedure_event_records"] == legacy_tables["procedure_event_records"]
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_ir_aligned_export_tables_preserve_legacy_core_fields_while_clearing_resolved_repairs():
    elements = [
        extract_normative_elements("This section applies to food carts.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    legacy_tables = {
        "canonical": [
            {
                "source_id": element["source_id"],
                "logic_frame": element["logic_frame"],
                "legal_frame": element["legal_frame"],
                "repair_required": True,
            }
            for element in elements
        ],
        "formal_logic": [
            {
                "formula_id": "legacy:" + element["source_id"],
                "source_id": element["source_id"],
                "legacy_formula_shape": True,
            }
            for element in elements
        ],
        "proof_obligations": [
            {
                "proof_obligation_id": "legacy:" + element["source_id"],
                "source_id": element["source_id"],
                "legacy_review_state": "parser_gate",
            }
            for element in elements
        ],
        "repair_queue": [
            {
                "repair_id": "legacy:" + element["source_id"],
                "source_id": element["source_id"],
                "legacy_prompt": "review parser warning",
            }
            for element in elements
        ],
    }

    tables = parser_elements_to_ir_aligned_export_tables(elements, legacy_tables)

    assert [row["logic_frame"] for row in tables["canonical"]] == [
        element["logic_frame"] for element in elements
    ]
    assert [row["legal_frame"] for row in tables["canonical"]] == [
        element["legal_frame"] for element in elements
    ]
    assert [row["repair_required"] for row in tables["canonical"]] == [False, False, True]
    assert [row["proof_ready"] for row in tables["proof_obligations"]] == [True, True, False]
    assert [row["legacy_formula_shape"] for row in tables["formal_logic"]] == [True, True, True]
    assert len(tables["repair_queue"]) == 1
    assert tables["repair_queue"][0]["source_id"] == elements[2]["source_id"]
    assert tables["repair_queue"][0]["legacy_prompt"] == "review parser warning"
    assert "cross_reference_requires_resolution" in tables["repair_queue"][0]["reasons"]
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_same_document_reference_exception_exports_resolution_provenance():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    element = dict(element)
    element["resolved_cross_references"] = [
        {
            "reference_type": "section",
            "canonical_citation": "section 552",
            "target": "552",
            "same_document": True,
            "source_id": "deontic:section-552",
            "span": [63, 74],
        }
    ]
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    for table_name in ("canonical", "formal_logic", "proof_obligations"):
        row = tables[table_name][0]
        assert row["cross_reference_count"] == 1
        assert row["cross_reference_resolution_status"] == "resolved"
        assert row["unresolved_cross_references"] == []
        assert row["resolved_cross_references"] == [
            {
                "reference_type": "section",
                "target": "552",
                "canonical_citation": "section 552",
                "value": "section 552",
                "span": [63, 74],
                "source_id": "deontic:section-552",
                "same_document": True,
                "resolved": True,
            }
        ]
    assert tables["repair_queue"] == []


def test_local_scope_reference_exception_exports_resolved_local_reference_provenance():
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

    tables = build_document_export_tables_from_ir([norm])

    assert tables["repair_queue"] == []
    for table_name in ("canonical", "formal_logic", "proof_obligations"):
        row = tables[table_name][0]
        assert row["proof_ready"] is True
        assert row["requires_validation"] is False
        assert row["cross_reference_count"] == 1
        assert row["cross_reference_resolution_status"] == "resolved"
        assert row["unresolved_cross_references"] == []
        assert row["resolved_cross_references"] == [
            {
                "reference_type": "section",
                "target": "this",
                "value": "this section",
                "raw_text": "this section",
                "span": [68, 80],
                "resolution_scope": "local_self",
                "resolved": True,
                "same_document": True,
            }
        ]
        assert row["deterministic_resolution"]["type"] == "local_scope_reference_exception"
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_local_scope_reference_condition_exports_resolved_local_reference_provenance():
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

    tables = build_document_export_tables_from_ir([norm])

    assert tables["repair_queue"] == []
    for table_name in ("canonical", "formal_logic", "proof_obligations"):
        row = tables[table_name][0]
        assert row["proof_ready"] is True
        assert row["requires_validation"] is False
        assert row["cross_reference_count"] == 1
        assert row["cross_reference_resolution_status"] == "resolved"
        assert row["unresolved_cross_references"] == []
        assert row["resolved_cross_references"] == [
            {
                "reference_type": "section",
                "target": "this",
                "value": "this section",
                "raw_text": "this section",
                "span": [11, 23],
                "resolution_scope": "local_self",
                "resolved": True,
                "same_document": True,
            }
        ]
        assert row["deterministic_resolution"] == {
            "type": "local_scope_reference_condition",
            "resolved_blockers": ["cross_reference_requires_resolution"],
            "scopes": ["this section"],
            "condition_spans": [norm.conditions[0].get("span", [])],
            "reason": "local self-reference condition is exported as provenance outside the operative formula",
        }
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_unresolved_reference_exception_exports_repair_provenance():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    norm = LegalNormIR.from_parser_element(element)

    tables = build_document_export_tables_from_ir([norm])

    assert len(tables["repair_queue"]) == 1
    for table_name in ("canonical", "formal_logic", "proof_obligations", "repair_queue"):
        row = tables[table_name][0]
        assert row["cross_reference_count"] == 1
        assert row["cross_reference_resolution_status"] == "unresolved"
        assert row["resolved_cross_references"] == []
        assert row["unresolved_cross_references"][0]["canonical_citation"] == "section 552"
        assert row["unresolved_cross_references"][0]["value"] == "section 552"
        assert row["unresolved_cross_references"][0]["resolved"] is False
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["repair_queue"][0]["formula_repair_required"] is True


def test_export_tables_resolve_reference_exception_from_section_context():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"current_section_number": "552"}

    tables = build_document_export_tables_from_ir(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert tables["repair_queue"] == []
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["formal_logic"][0]["requires_validation"] is False
    assert tables["formal_logic"][0]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    for table_name in ("canonical", "formal_logic", "proof_obligations"):
        row = tables[table_name][0]
        assert row["cross_reference_resolution_status"] == "resolved"
        assert row["unresolved_cross_references"] == []
        assert row["resolved_cross_references"][0]["canonical_citation"] == "section 552"
        assert row["resolved_cross_references"][0]["same_document"] is True
        assert row["resolved_cross_references"][0]["resolved"] is True
        assert row["resolved_cross_references"][0]["source_id"] == cited_element["source_id"]
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_export_tables_keep_absent_section_context_reference_in_repair_queue():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"current_section_number": "553"}

    tables = build_document_export_tables_from_ir(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(cited_element),
        ]
    )

    assert len(tables["repair_queue"]) == 1
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["requires_validation"] is True
    assert tables["formal_logic"][0]["cross_reference_resolution_status"] == "unresolved"
    assert tables["repair_queue"][0]["source_id"] == reference_element["source_id"]
    assert "cross_reference_requires_resolution" in tables["repair_queue"][0]["reasons"]


def test_parser_element_readiness_resolves_same_document_reference_exception_from_section_context():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "552"}

    aligned = parser_elements_with_ir_export_readiness(
        [reference_element, cited_element]
    )

    assert reference_element["promotable_to_theorem"] is False
    assert aligned[0]["promotable_to_theorem"] is False
    assert aligned[0]["export_readiness"]["parser_proof_ready"] is False
    assert aligned[0]["export_readiness"]["formula_proof_ready"] is True
    assert aligned[0]["export_readiness"]["proof_ready"] is True
    assert aligned[0]["export_readiness"]["formula_requires_validation"] is False
    assert aligned[0]["export_readiness"]["formula_repair_required"] is False
    assert aligned[0]["export_readiness"]["export_requires_validation"] is False
    assert aligned[0]["export_readiness"]["export_repair_required"] is False
    assert isinstance(aligned[0]["export_readiness"]["requires_validation"], list)
    assert "llm_router_repair" in aligned[0]["export_readiness"]["requires_validation"]
    assert aligned[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert aligned[0]["export_readiness"]["deterministic_resolution"]["references"] == [
        "section 552"
    ]
    assert aligned[0]["llm_repair"]["required"] is False
    assert aligned[0]["llm_repair"]["allow_llm_repair"] is False
    assert aligned[0]["llm_repair"]["deterministically_resolved"] is True
    assert aligned[0]["resolved_cross_references"] == [
        {
            "reference_type": "section",
            "target": "552",
            "canonical_citation": "section 552",
            "value": "section 552",
            "span": [61, 72],
            "source_id": cited_element["source_id"],
            "resolved_source_id": cited_element["source_id"],
            "resolution_scope": "same_document",
            "resolved": True,
            "resolution_status": "resolved",
            "same_document": True,
            "target_exists": True,
        }
    ]


def test_parser_element_readiness_projects_local_applicability_resolution():
    element = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]

    aligned = parser_elements_with_ir_export_readiness([element])

    assert element["promotable_to_theorem"] is False
    assert aligned[0]["promotable_to_theorem"] is False
    assert aligned[0]["export_readiness"]["parser_proof_ready"] is False
    assert aligned[0]["export_readiness"]["formula_proof_ready"] is True
    assert aligned[0]["export_readiness"]["proof_ready"] is True
    assert aligned[0]["export_readiness"]["formula_requires_validation"] is False
    assert aligned[0]["export_readiness"]["formula_repair_required"] is False
    assert aligned[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "local_scope_applicability"
    )
    assert aligned[0]["llm_repair"]["required"] is False
    assert aligned[0]["llm_repair"]["allow_llm_repair"] is False
    assert aligned[0]["llm_repair"]["deterministically_resolved"] is True
    assert aligned[0]["resolved_cross_references"] == [
        {
            "reference_type": "section",
            "target": "this",
            "value": "this section",
            "raw_text": "This section",
            "span": [0, 12],
            "resolution_scope": "local_self",
            "resolved": True,
            "resolution_status": "resolved",
            "same_document": True,
            "target_exists": True,
        }
    ]


def test_raw_parser_marks_local_applicability_repair_inactive_without_hiding_warning():
    element = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert element["parser_warnings"] == ["cross_reference_requires_resolution"]
    assert element["active_repair_warnings"] == []
    assert element["repair_required_warnings"] == []
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["prompt_context"] == {}
    assert element["llm_repair"]["deterministically_resolved"] is True
    assert element["llm_repair"]["deterministic_resolution"]["type"] == (
        "local_scope_applicability"
    )
    assert element["export_readiness"]["metric_repair_required"] is False
    assert element["resolved_cross_references"] == [
        {
            "reference_type": "section",
            "target": "this",
            "value": "this section",
            "raw_text": "This section",
            "span": [0, 12],
            "resolution_scope": "local_self",
            "resolved": True,
            "resolution_status": "resolved",
            "same_document": True,
            "target_exists": True,
        }
    ]


def test_raw_parser_marks_formula_resolved_exception_repair_inactive_without_hiding_warning():
    element = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert element["parser_warnings"] == ["exception_requires_scope_review"]
    assert element["active_repair_warnings"] == []
    assert element["repair_required_warnings"] == []
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["prompt_context"] == {}
    assert element["llm_repair"]["prompt_hash"] == ""
    assert element["llm_repair"]["suggested_router"] == ""
    assert element["llm_repair"]["deterministically_resolved"] is True
    assert element["llm_repair"]["deterministic_resolution"] == {
        "type": "standard_substantive_exception",
        "resolved_blockers": ["exception_requires_scope_review"],
        "exception": "approval is denied",
        "exception_span": [43, 61],
        "reason": "single substantive exception is represented as a negated formula antecedent",
    }
    assert element["export_readiness"]["metric_repair_required"] is False


def test_raw_parser_marks_formula_resolved_override_repair_inactive_without_hiding_warning():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert element["parser_warnings"] == [
        "cross_reference_requires_resolution",
        "override_clause_requires_precedence_review",
    ]
    assert element["active_repair_warnings"] == []
    assert element["repair_required_warnings"] == []
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["prompt_context"] == {}
    assert element["llm_repair"]["deterministically_resolved"] is True
    assert element["llm_repair"]["deterministic_resolution"]["type"] == "pure_precedence_override"
    assert element["export_readiness"]["metric_repair_required"] is False
    assert element["resolved_cross_references"] == [
        {
            "type": "section",
            "value": "5.01.020",
            "raw_text": "section 5.01.020",
            "normalized_text": "section 5.01.020",
            "span": [16, 32],
            "resolution_scope": "precedence_provenance",
            "resolved": True,
            "resolution_status": "resolved",
            "precedence_only": True,
            "same_document": False,
            "target_exists": False,
        }
    ]


def test_pure_precedence_override_clearance_helper_does_not_need_formula_projection():
    """Parser-native override slots are enough to clear stale active repair."""

    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    element = dict(element)
    element["llm_repair"] = {
        "required": True,
        "allow_llm_repair": True,
        "reasons": list(element["parser_warnings"]),
        "prompt_context": {"source_text": element["text"]},
        "prompt_hash": "stale",
        "suggested_router": "llm_router",
    }
    element["export_readiness"] = {
        "metric_requires_validation": True,
        "metric_repair_required": True,
    }

    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
        _apply_active_repair_status,
        _clear_pure_precedence_override_active_repair,
    )

    _clear_pure_precedence_override_active_repair(element)
    _apply_active_repair_status([element])

    assert element["parser_warnings"] == [
        "cross_reference_requires_resolution",
        "override_clause_requires_precedence_review",
    ]
    assert element["promotable_to_theorem"] is False
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["prompt_context"] == {}
    assert element["llm_repair"]["deterministic_resolution"]["type"] == "pure_precedence_override"
    assert element["export_readiness"]["metric_repair_required"] is False
    assert element["active_repair_required"] is False
    assert element["resolved_cross_references"][0]["resolution_scope"] == "precedence_provenance"


def test_raw_parser_keeps_numbered_reference_exception_active_for_repair():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert "cross_reference_requires_resolution" in element["parser_warnings"]
    assert element.get("active_repair_warnings", element["parser_warnings"]) == element["parser_warnings"]
    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]


def test_parser_element_readiness_projects_precedence_override_reference_provenance():
    element = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]

    aligned = parser_elements_with_ir_export_readiness([element])

    assert element["promotable_to_theorem"] is False
    assert aligned[0]["promotable_to_theorem"] is False
    assert aligned[0]["export_readiness"]["parser_proof_ready"] is False
    assert aligned[0]["export_readiness"]["formula_proof_ready"] is True
    assert aligned[0]["export_readiness"]["proof_ready"] is True
    assert aligned[0]["export_readiness"]["formula_requires_validation"] is False
    assert aligned[0]["export_readiness"]["formula_repair_required"] is False
    assert aligned[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "pure_precedence_override"
    )
    assert aligned[0]["llm_repair"]["required"] is False
    assert aligned[0]["llm_repair"]["allow_llm_repair"] is False
    assert aligned[0]["llm_repair"]["deterministically_resolved"] is True
    assert aligned[0]["resolved_cross_references"] == [
        {
            "reference_type": "section",
            "canonical_citation": "section 5.01.020",
            "value": "section 5.01.020",
            "raw_text": "section 5.01.020",
            "span": [16, 32],
            "resolution_scope": "precedence_provenance",
            "resolved": True,
            "resolution_status": "resolved",
            "precedence_only": True,
            "same_document": False,
        }
    ]


def test_parser_element_readiness_keeps_mismatched_section_context_reference_blocked():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited_element = extract_normative_elements("The agency shall keep records.")[0]
    cited_element = dict(cited_element)
    cited_element["canonical_citation"] = ""
    cited_element["section_context"] = {"section": "553"}

    aligned = parser_elements_with_ir_export_readiness(
        [reference_element, cited_element]
    )

    assert aligned[0]["promotable_to_theorem"] is False
    assert aligned[0]["export_readiness"]["formula_proof_ready"] is False
    assert aligned[0]["export_readiness"]["proof_ready"] is False
    assert aligned[0]["export_readiness"]["formula_requires_validation"] is True
    assert aligned[0]["export_readiness"]["formula_repair_required"] is True
    assert aligned[0]["export_readiness"]["export_requires_validation"] is True
    assert aligned[0]["export_readiness"]["export_repair_required"] is True
    assert isinstance(aligned[0]["export_readiness"]["requires_validation"], list)
    assert "llm_router_repair" in aligned[0]["export_readiness"]["requires_validation"]
    assert aligned[0]["export_readiness"]["deterministic_resolution"] == {}
    assert aligned[0]["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in aligned[0]["llm_repair"]["reasons"]
    assert aligned[0]["resolved_cross_references"] == reference_element["resolved_cross_references"]


def test_document_export_tables_resolve_complete_plural_section_list_exception():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    reference_element = dict(reference_element)
    reference_element["exception_details"] = [
        {
            "type": "exception",
            "clause_type": "except",
            "raw_text": "as provided in sections 552 and 553",
            "normalized_text": "as provided in sections 552 and 553",
            "span": [46, 82],
            "clause_span": [39, 82],
        }
    ]
    reference_element["cross_reference_details"] = [
        {
            "reference_type": "section",
            "raw_text": "sections 552 and 553",
            "normalized_text": "sections 552 and 553",
            "span": [61, 82],
        }
    ]
    reference_element["resolved_cross_references"] = []

    section_552 = extract_normative_elements("The Bureau shall maintain the public register.")[0]
    section_552 = dict(section_552)
    section_552["canonical_citation"] = "section 552"
    section_553 = extract_normative_elements("The Bureau shall publish the annual index.")[0]
    section_553 = dict(section_553)
    section_553["canonical_citation"] = "section 553"

    tables = build_document_export_tables_from_ir(
        [
            LegalNormIR.from_parser_element(reference_element),
            LegalNormIR.from_parser_element(section_552),
            LegalNormIR.from_parser_element(section_553),
        ]
    )

    assert tables["repair_queue"] == []
    reference_formula = tables["formal_logic"][0]
    assert reference_formula["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert "Section552" not in reference_formula["formula"]
    assert "Section553" not in reference_formula["formula"]
    assert reference_formula["proof_ready"] is True
    assert reference_formula["requires_validation"] is False
    assert reference_formula["repair_required"] is False
    assert reference_formula["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert reference_formula["deterministic_resolution"]["references"] == [
        "section 552",
        "section 553",
    ]
    assert reference_formula["cross_reference_resolution_status"] == "resolved"
    assert reference_formula["unresolved_cross_references"] == []
    assert [record["canonical_citation"] for record in reference_formula["resolved_cross_references"]] == [
        "section 552",
        "section 553",
    ]
    assert tables["proof_obligations"][0]["theorem_candidate"] is True
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_document_export_tables_keep_partial_plural_section_list_exception_blocked():
    reference_element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    reference_element = dict(reference_element)
    reference_element["exception_details"] = [
        {"type": "exception", "clause_type": "except", "raw_text": "as provided in sections 552 and 553", "normalized_text": "as provided in sections 552 and 553", "span": [46, 82]}
    ]
    reference_element["cross_reference_details"] = [
        {"reference_type": "section", "raw_text": "sections 552 and 553", "normalized_text": "sections 552 and 553", "span": [61, 82]}
    ]
    reference_element["resolved_cross_references"] = []
    section_552 = extract_normative_elements("The Bureau shall maintain the public register.")[0]
    section_552 = dict(section_552)
    section_552["canonical_citation"] = "section 552"

    tables = build_document_export_tables_from_ir(
        [LegalNormIR.from_parser_element(reference_element), LegalNormIR.from_parser_element(section_552)]
    )

    assert len(tables["repair_queue"]) == 1
    assert tables["repair_queue"][0]["source_id"] == reference_element["source_id"]
    assert tables["formal_logic"][0]["proof_ready"] is False
    assert tables["formal_logic"][0]["requires_validation"] is True
    assert tables["formal_logic"][0]["deterministic_resolution"] == {}
    assert validate_export_tables(tables) == {"valid": True, "errors": []}


def test_validate_export_tables_reports_missing_and_duplicate_keys():
    element = extract_normative_elements("The tenant must pay rent monthly.")[0]
    norm = LegalNormIR.from_parser_element(element)
    tables = build_document_export_tables_from_ir([norm])

    duplicate = dict(tables["formal_logic"][0])
    missing_source = dict(tables["proof_obligations"][0])
    missing_source["source_id"] = ""
    tables["formal_logic"].append(duplicate)
    tables["proof_obligations"][0] = missing_source

    validation = validate_export_tables(tables)

    assert validation["valid"] is False
    assert {
        "table": "formal_logic",
        "row_index": 1,
        "field": "formula_id",
        "message": "duplicate primary key",
    } in validation["errors"]
    assert {
        "table": "proof_obligations",
        "row_index": 0,
        "field": "source_id",
        "message": "missing source_id",
    } in validation["errors"]


def test_parser_elements_for_metrics_clears_only_formula_resolved_repair_markers():
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    rows = parser_elements_for_metrics(elements)

    assert [row["promotable_to_theorem"] for row in rows] == [False, False, False, False]
    assert [
        row["export_readiness"].get("deterministic_resolution", {}).get("type")
        for row in rows
    ] == [
        "local_scope_applicability",
        "standard_substantive_exception",
        "pure_precedence_override",
        None,
    ]
    assert [row["export_readiness"]["formula_repair_required"] for row in rows] == [
        False,
        False,
        False,
        True,
    ]
    assert [row["export_readiness"]["metric_repair_required"] for row in rows] == [
        False,
        False,
        False,
        True,
    ]
    assert [row["export_readiness"].get("repair_required") for row in rows] == [
        False,
        False,
        False,
        True,
    ]
    assert [row["export_readiness"].get("requires_validation") for row in rows[:3]] == [[], [], []]
    assert "llm_router_repair" in rows[3]["export_readiness"].get("requires_validation", [])
    assert [row["llm_repair"]["required"] for row in rows] == [False, False, False, True]
    assert [row["llm_repair"].get("reasons") for row in rows[:3]] == [[], [], []]
    assert [row["llm_repair"].get("prompt_context") for row in rows[:3]] == [{}, {}, {}]
    assert [row["llm_repair"].get("prompt_hash") for row in rows[:3]] == ["", "", ""]
    assert [row["llm_repair"].get("suggested_router") for row in rows[:3]] == ["", "", ""]
    assert [
        row["llm_repair"].get("deterministic_resolution", {}).get("type")
        for row in rows[:3]
    ] == [
        "local_scope_applicability",
        "standard_substantive_exception",
        "pure_precedence_override",
    ]
    assert [row["parser_warnings"] for row in rows[:3]] == [
        ["cross_reference_requires_resolution"],
        ["exception_requires_scope_review"],
        ["cross_reference_requires_resolution", "override_clause_requires_precedence_review"],
    ]
    assert [row["repair_required_warnings"] for row in rows[:3]] == [[], [], []]
    assert [row["active_repair_warnings"] for row in rows[:3]] == [[], [], []]
    assert rows[3]["repair_required_warnings"] == rows[3]["parser_warnings"]
    assert rows[3]["active_repair_warnings"] == rows[3]["parser_warnings"]
    assert rows[3]["llm_repair"]["reasons"]
    assert rows[3]["llm_repair"].get("prompt_context")


def test_parser_element_has_active_repair_uses_formula_readiness_projection():
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    assert [parser_element_has_active_repair(element) for element in elements] == [
        False,
        False,
        False,
        True,
    ]

    details = active_repair_details_from_parser_elements(elements)
    assert len(details) == 1
    assert details[0]["source_id"] == elements[3]["source_id"]
    assert details[0]["deterministic_resolution"] == {}


def test_active_repair_details_ignore_formula_resolved_rows():
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    details = active_repair_details_from_parser_elements(elements)

    assert len(details) == 1
    detail = details[0]
    assert detail["source_id"] == elements[3]["source_id"]
    assert detail["text"] == elements[3]["text"]
    assert detail["norm_type"] == "obligation"
    assert detail["modality"] == "O"
    assert detail["subject"] == ["Secretary"]
    assert detail["action"] == ["publish the notice"]
    assert detail["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert detail["parser_warnings"] == detail["active_repair_warnings"]
    assert detail["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in detail["llm_repair"]["reasons"]
    assert detail["llm_repair"].get("prompt_context")
    assert detail["deterministic_resolution"] == {}

    resolved_rows = parser_elements_for_metrics(elements[:3])
    assert [row["parser_warnings"] for row in resolved_rows] == [
        ["cross_reference_requires_resolution"],
        ["exception_requires_scope_review"],
        ["cross_reference_requires_resolution", "override_clause_requires_precedence_review"],
    ]
    assert active_repair_details_from_parser_elements(elements[:3]) == []


def test_active_repair_summary_counts_only_unresolved_repair_probes():
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]

    summary = summarize_active_repair_from_parser_elements(elements)

    assert summary["element_count"] == 4
    assert summary["repair_required_count"] == 1
    assert summary["repair_required_rate"] == 0.25
    assert summary["repair_required"] == [elements[3]["source_id"]]
    assert summary["active_repair_required_by_source_id"] == {
        elements[0]["source_id"]: False,
        elements[1]["source_id"]: False,
        elements[2]["source_id"]: False,
        elements[3]["source_id"]: True,
    }
    assert summary["repair_required_details"][0]["source_id"] == elements[3]["source_id"]
    assert summary["repair_required_details"][0]["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert summary["repair_required_details"][0]["deterministic_resolution"] == {}


def test_normalize_repair_required_details_filters_formula_resolved_raw_details():
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    raw_details = [
        {
            "source_id": element["source_id"],
            "text": element["text"],
            "norm_type": element["norm_type"],
            "parser_warnings": list(element["parser_warnings"]),
            "llm_repair": dict(element["llm_repair"]),
        }
        for element in elements
    ]

    details = normalize_repair_required_details_from_parser_elements(elements, raw_details)

    assert len(details) == 1
    assert details[0]["source_id"] == elements[3]["source_id"]
    assert details[0]["text"] == elements[3]["text"]
    assert details[0]["norm_type"] == "obligation"
    assert details[0]["parser_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert details[0]["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert details[0]["deterministic_resolution"] == {}
    assert details[0]["llm_repair"]["required"] is True


def test_normalize_repair_required_details_adds_missing_active_projected_detail():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    details = normalize_repair_required_details_from_parser_elements([element], [])

    assert len(details) == 1
    assert details[0]["source_id"] == element["source_id"]
    assert details[0]["active_repair_warnings"] == element["parser_warnings"]
    assert details[0]["deterministic_resolution"] == {}


def test_normalize_repair_required_evaluation_filters_formula_resolved_details():
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    raw_evaluation = {
        "element_count": 4,
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required": [element["source_id"] for element in elements],
        "repair_required_details": [
            {
                "source_id": element["source_id"],
                "text": element["text"],
                "norm_type": element["norm_type"],
                "parser_warnings": list(element["parser_warnings"]),
                "llm_repair": dict(element["llm_repair"]),
            }
            for element in elements
        ],
        "parity_score": 0.9763,
    }

    normalized = normalize_repair_required_evaluation(elements, raw_evaluation)

    assert normalized["parity_score"] == 0.9763
    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 0.25
    assert normalized["repair_required"] == [elements[3]["source_id"]]
    assert normalized["active_repair_required_by_source_id"] == {
        elements[0]["source_id"]: False,
        elements[1]["source_id"]: False,
        elements[2]["source_id"]: False,
        elements[3]["source_id"]: True,
    }
    assert len(normalized["repair_required_details"]) == 1
    detail = normalized["repair_required_details"][0]
    assert detail["source_id"] == elements[3]["source_id"]
    assert detail["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert detail["deterministic_resolution"] == {}


def test_raw_parser_clears_llm_prompt_for_formula_resolved_repair_probes():
    examples = [
        (
            "This section applies to food carts and mobile vendors.",
            "local_scope_applicability",
            ["cross_reference_requires_resolution"],
        ),
        (
            "The applicant shall obtain a permit unless approval is denied.",
            "standard_substantive_exception",
            ["exception_requires_scope_review"],
        ),
        (
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            "pure_precedence_override",
            ["cross_reference_requires_resolution", "override_clause_requires_precedence_review"],
        ),
    ]

    for text, resolution_type, parser_warnings in examples:
        element = extract_normative_elements(text)[0]

        assert element["promotable_to_theorem"] is False
        assert element["parser_warnings"] == parser_warnings
        assert element["llm_repair"]["required"] is False
        assert element["llm_repair"]["allow_llm_repair"] is False
        assert element["llm_repair"]["reasons"] == []
        assert element["llm_repair"]["suggested_router"] == ""
        assert element["llm_repair"]["prompt_hash"] == ""
        assert element["llm_repair"]["prompt_context"] == {}
        assert element["llm_repair"]["deterministically_resolved"] is True
        assert element["llm_repair"]["deterministic_resolution"]["type"] == resolution_type
        assert element["export_readiness"]["proof_ready"] is False
        assert "human_or_llm_semantic_review" in element["export_readiness"]["requires_validation"]


def test_raw_parser_exposes_active_repair_status_for_stalled_probe_metrics():
    """Active repair fields should separate resolved audit warnings from blockers."""
    resolved_examples = [
        (
            "This section applies to food carts and mobile vendors.",
            ["cross_reference_requires_resolution"],
        ),
        (
            "The applicant shall obtain a permit unless approval is denied.",
            ["exception_requires_scope_review"],
        ),
        (
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            ["cross_reference_requires_resolution", "override_clause_requires_precedence_review"],
        ),
    ]

    for text, parser_warnings in resolved_examples:
        element = extract_normative_elements(text)[0]

        assert element["parser_warnings"] == parser_warnings
        assert element["promotable_to_theorem"] is False
        assert element["llm_repair"]["required"] is False
        assert element["active_repair_required"] is False
        assert element["repair_required"] is False
        assert element["active_repair_warnings"] == []
        assert element["repair_required_warnings"] == []

    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert unresolved["active_repair_required"] is True
    assert unresolved["repair_required"] is True
    assert unresolved["active_repair_warnings"] == unresolved["llm_repair"]["reasons"]


def test_raw_parser_projects_top_level_modality_for_repair_probe_details():
    """Repair detail metrics should not see null modality for parsed clauses."""
    examples = [
        ("This section applies to food carts and mobile vendors.", "APP"),
        (
            "The applicant shall obtain a permit unless approval is denied.",
            "O",
        ),
        (
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            "P",
        ),
        (
            "The Secretary shall publish the notice except as provided in section 552.",
            "O",
        ),
    ]

    for text, expected_modality in examples:
        element = extract_normative_elements(text)[0]

        assert element["deontic_operator"] == expected_modality
        assert element["modality"] == expected_modality

    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    assert unresolved["llm_repair"]["required"] is True


def test_raw_parser_keeps_llm_prompt_for_unresolved_numbered_reference_exception():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert element["llm_repair"]["required"] is True
    assert element["llm_repair"]["allow_llm_repair"] is True
    assert element["llm_repair"]["suggested_router"] == "llm_router"
    assert element["llm_repair"]["prompt_hash"]
    assert element["llm_repair"]["prompt_context"]
    assert element["llm_repair"]["deterministically_resolved"] is False
    assert element["llm_repair"]["deterministic_resolution"] == {}
    assert "cross_reference_requires_resolution" in element["llm_repair"]["reasons"]
    assert "exception_requires_scope_review" in element["llm_repair"]["reasons"]
    assert "llm_router_repair" in element["export_readiness"]["requires_validation"]


def test_raw_parser_clears_active_repair_for_local_scope_reference_exception():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in this section."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert element["parser_warnings"] == ["exception_requires_scope_review"]
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["suggested_router"] == ""
    assert element["llm_repair"]["prompt_hash"] == ""
    assert element["llm_repair"]["prompt_context"] == {}
    assert element["llm_repair"]["deterministically_resolved"] is True
    assert element["llm_repair"]["deterministic_resolution"] == {
        "type": "local_scope_reference_exception",
        "scopes": ["this section"],
        "reason": "local self-reference exception is exported as provenance outside the operative formula",
    }
    assert element["active_repair_required"] is False
    assert element["repair_required"] is False
    assert element["active_repair_warnings"] == []
    assert element["repair_required_warnings"] == []
    assert element["export_readiness"]["metric_repair_required"] is False


def test_raw_parser_clears_active_repair_for_local_scope_reference_condition():
    element = extract_normative_elements(
        "Subject to this section, the Secretary shall publish the notice."
    )[0]

    assert element["promotable_to_theorem"] is False
    assert element["parser_warnings"] == ["cross_reference_requires_resolution"]
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["suggested_router"] == ""
    assert element["llm_repair"]["prompt_hash"] == ""
    assert element["llm_repair"]["prompt_context"] == {}
    assert element["llm_repair"]["deterministically_resolved"] is True
    assert element["llm_repair"]["deterministic_resolution"] == {
        "type": "local_scope_reference_condition",
        "scopes": ["this section"],
        "reason": "local self-reference condition is exported as provenance outside the operative formula",
    }
    assert element["active_repair_required"] is False
    assert element["repair_required"] is False
    assert element["active_repair_warnings"] == []
    assert element["repair_required_warnings"] == []
    assert element["export_readiness"]["metric_repair_required"] is False


def test_raw_parser_keeps_active_repair_for_numbered_reference_condition_without_resolution():
    element = extract_normative_elements(
        "Subject to section 552, the Secretary shall publish the notice."
    )[0]

    assert element["active_repair_required"] is True
    assert element["repair_required"] is True
    assert element["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in element["active_repair_warnings"]
    assert element["llm_repair"]["prompt_context"]


def test_raw_parser_keeps_active_repair_for_numbered_reference_exception_after_local_clearance():
    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert element["active_repair_required"] is True
    assert element["llm_repair"]["required"] is True
    assert element["llm_repair"]["prompt_context"]


def test_metrics_projection_resolves_numbered_reference_exception_with_same_document_section():
    """Metrics can clear active repair when the cited section is in the same batch."""
    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited = extract_normative_elements("The agency shall keep records.")[0]
    cited = dict(cited)
    cited["canonical_citation"] = "section 552"

    projected = parser_elements_for_metrics([reference, cited])
    projected_reference = projected[0]

    assert reference["active_repair_required"] is True
    assert parser_element_has_active_repair(reference) is True
    assert projected_reference["parser_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert projected_reference["active_repair_required"] is False
    assert projected_reference["repair_required"] is False
    assert projected_reference["active_repair_warnings"] == []
    assert projected_reference["repair_required_warnings"] == []
    assert projected_reference["llm_repair"]["required"] is False
    assert projected_reference["llm_repair"]["allow_llm_repair"] is False
    assert projected_reference["export_readiness"]["metric_repair_required"] is False
    assert projected_reference["export_readiness"]["formula_proof_ready"] is True
    assert projected_reference["export_readiness"]["formula_requires_validation"] is False
    assert projected_reference["export_readiness"]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert projected_reference["export_readiness"]["deterministic_resolution"]["references"] == [
        "section 552"
    ]
    assert projected_reference["resolved_cross_references"] == [
        {
            "type": "section",
            "value": "552",
            "raw_text": "section 552",
            "normalized_text": "section 552",
            "span": [61, 72],
            "resolution_status": "resolved",
            "target_exists": True,
            "resolution_scope": "same_document",
            "same_document": True,
            "resolved": True,
            "source_id": cited["source_id"],
            "resolved_source_id": cited["source_id"],
        }
    ]


def test_raw_parser_clears_active_repair_for_same_document_numbered_reference_exception():
    text = """Section 552. Publication rules
The agency shall keep records.
Section 553. Notice rule
The Secretary shall publish the notice except as provided in section 552."""

    elements = extract_normative_elements(text)
    reference = next(
        element for element in elements if element["action"] == ["publish the notice"]
    )

    assert reference["promotable_to_theorem"] is False
    assert "exception_requires_scope_review" in reference["parser_warnings"]
    assert reference["resolved_cross_references"] == [
        {
            "type": "section",
            "value": "552",
            "raw_text": "section 552",
            "normalized_text": "section 552",
            "span": [61, 72],
            "resolution_status": "resolved",
            "target_exists": True,
            "target_section": "552",
            "target_heading": "Publication rules",
            "target_hierarchy_path": ["section:552", "heading:Publication rules"],
            "resolved": True,
            "same_document": True,
            "resolution_scope": "same_document",
        }
    ]
    assert reference["llm_repair"]["required"] is False
    assert reference["llm_repair"]["allow_llm_repair"] is False
    assert reference["llm_repair"]["reasons"] == []
    assert reference["llm_repair"]["prompt_context"] == {}
    assert reference["llm_repair"]["deterministically_resolved"] is True
    assert reference["llm_repair"]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert reference["active_repair_required"] is False
    assert reference["repair_required"] is False
    assert reference["active_repair_warnings"] == []
    assert reference["repair_required_warnings"] == []


def test_raw_parser_keeps_active_repair_for_standalone_numbered_reference_exception():
    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert reference["active_repair_required"] is True
    assert reference["repair_required"] is True
    assert reference["llm_repair"]["required"] is True
    assert "cross_reference_requires_resolution" in reference["active_repair_warnings"]
    assert "exception_requires_scope_review" in reference["active_repair_warnings"]


def test_raw_parser_same_document_reference_metadata_survives_ir_metrics_projection():
    text = """Section 552. Publication rules
The agency shall keep records.
Section 553. Notice rule
The Secretary shall publish the notice except as provided in section 552."""

    elements = extract_normative_elements(text)
    reference = next(
        element for element in elements if element["action"] == ["publish the notice"]
    )

    projected = parser_elements_for_metrics([reference])[0]

    assert reference["active_repair_required"] is False
    assert projected["active_repair_required"] is False
    assert projected["repair_required"] is False
    assert projected["llm_repair"]["required"] is False
    assert projected["resolved_cross_references"][0]["resolution_status"] == "resolved"
    assert projected["resolved_cross_references"][0]["target_exists"] is True
    assert projected["resolved_cross_references"][0]["resolved"] is True
    assert projected["resolved_cross_references"][0]["same_document"] is True
    assert projected["resolved_cross_references"][0]["resolution_scope"] == "same_document"
    assert projected["export_readiness"]["metric_repair_required"] is False


def test_metrics_projection_is_idempotent_for_resolved_numbered_reference_exception():
    """A resolved reference row should not become active when reprocessed alone."""
    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited = extract_normative_elements("The agency shall keep records.")[0]
    cited = dict(cited)
    cited["canonical_citation"] = "section 552"

    projected_reference = parser_elements_for_metrics([reference, cited])[0]
    reprojected_reference = parser_elements_for_metrics([projected_reference])[0]

    assert projected_reference["active_repair_required"] is False
    assert projected_reference["repair_required"] is False
    assert projected_reference["llm_repair"]["required"] is False
    assert projected_reference["export_readiness"]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert reprojected_reference["parser_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert reprojected_reference["active_repair_required"] is False
    assert reprojected_reference["repair_required"] is False
    assert reprojected_reference["active_repair_warnings"] == []
    assert reprojected_reference["repair_required_warnings"] == []
    assert reprojected_reference["llm_repair"]["required"] is False
    assert reprojected_reference["llm_repair"]["allow_llm_repair"] is False
    assert reprojected_reference["export_readiness"]["metric_repair_required"] is False
    assert reprojected_reference["export_readiness"]["deterministic_resolution"]["type"] == (
        "resolved_same_document_reference_exception"
    )
    assert reprojected_reference["resolved_cross_references"] == projected_reference["resolved_cross_references"]
    assert parser_element_has_active_repair(projected_reference) is False
    assert active_repair_details_from_parser_elements([projected_reference]) == []

    raw_evaluation = {
        "element_count": 1,
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required": [projected_reference["source_id"]],
        "repair_required_details": [{"source_id": projected_reference["source_id"]}],
        "metrics": {
            "repair_required_count": 4,
            "repair_required_rate": 0.25,
            "coverage_gaps": ["repair_required_count: 4", "cross_reference_resolution_rate: 0.0"],
        },
    }

    normalized = normalize_repair_required_evaluation([projected_reference], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["repair_required_rate"] == 0.0
    assert normalized["metrics"]["coverage_gaps"] == [
        "cross_reference_resolution_rate: 0.0"
    ]


def test_normalize_repair_required_evaluation_recovers_parser_rows_from_samples():
    """Stalled metric payloads may carry parser-shaped rows only in samples."""
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    raw_evaluation = {
        "samples": [{"parser_elements": [element]} for element in elements],
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required": [element["source_id"] for element in elements],
        "repair_required_details": [
            {
                "source_id": element["source_id"],
                "text": element["text"],
                "norm_type": element["norm_type"],
                "parser_warnings": list(element["parser_warnings"]),
                "llm_repair": dict(element["llm_repair"]),
            }
            for element in elements
        ],
        "metrics": {
            "repair_required_count": 4,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 4"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 0.25
    assert normalized["repair_required"] == [elements[3]["source_id"]]
    assert normalized["active_repair_required_by_source_id"] == {
        elements[0]["source_id"]: False,
        elements[1]["source_id"]: False,
        elements[2]["source_id"]: False,
        elements[3]["source_id"]: True,
    }
    assert len(normalized["repair_required_details"]) == 1
    assert normalized["repair_required_details"][0]["source_id"] == elements[3]["source_id"]
    assert normalized["repair_required_details"][0]["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required_rate"] == 0.25
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_parser_rows_from_repair_prompt_contexts():
    """Repair-detail-only metric payloads should still use IR readiness."""
    elements = [
        extract_normative_elements("This section applies to food carts and mobile vendors.")[0],
        extract_normative_elements(
            "The applicant shall obtain a permit unless approval is denied."
        )[0],
        extract_normative_elements(
            "Notwithstanding section 5.01.020, the Director may issue a variance."
        )[0],
        extract_normative_elements(
            "The Secretary shall publish the notice except as provided in section 552."
        )[0],
    ]
    raw_evaluation = {
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required": [element["source_id"] for element in elements],
        "repair_required_details": [
            {
                "source_id": element["source_id"],
                "text": element["text"],
                "norm_type": element["norm_type"],
                "parser_warnings": list(element["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(element["parser_warnings"]),
                    "prompt_context": dict(element["llm_repair"].get("prompt_context") or element),
                },
            }
            for element in elements
        ],
        "metrics": {
            "repair_required_count": 4,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 4"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 0.25
    assert normalized["repair_required"] == [elements[3]["source_id"]]
    assert normalized["active_repair_required_by_source_id"] == {
        elements[0]["source_id"]: False,
        elements[1]["source_id"]: False,
        elements[2]["source_id"]: False,
        elements[3]["source_id"]: True,
    }
    assert len(normalized["repair_required_details"]) == 1
    detail = normalized["repair_required_details"][0]
    assert detail["source_id"] == elements[3]["source_id"]
    assert detail["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert detail["deterministic_resolution"] == {}
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required_rate"] == 0.25
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_preserves_rich_prompt_context_slots():
    """Prompt contexts may carry dict slots under legacy parser field names."""
    exception = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    override = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    applicability = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    prompt_contexts = []
    for element in [exception, override, applicability, unresolved]:
        context = {
            "schema_version": element["schema_version"],
            "source_id": element["source_id"],
            "canonical_citation": element["canonical_citation"],
            "source_text": element["text"],
            "support_text": element["support_text"],
            "support_span": element["support_span"],
            "source_span": element.get("source_span", element["support_span"]),
            "norm_type": element["norm_type"],
            "deontic_operator": element["deontic_operator"],
            "subject": list(element["subject"]),
            "action": list(element["action"]),
            "conditions": list(element.get("condition_details") or element.get("conditions") or []),
            "exceptions": list(element.get("exception_details") or element.get("exceptions") or []),
            "override_clauses": list(element.get("override_clause_details") or element.get("override_clauses") or []),
            "cross_references": list(element.get("cross_reference_details") or element.get("cross_references") or []),
            "resolved_cross_references": list(element.get("resolved_cross_references") or []),
            "parser_warnings": list(element["parser_warnings"]),
            "export_readiness": dict(element.get("export_readiness") or {}),
            "promotable_to_theorem": bool(element.get("promotable_to_theorem")),
        }
        prompt_contexts.append(context)

    raw_evaluation = {
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required": [context["source_id"] for context in prompt_contexts],
        "repair_required_details": [
            {
                "source_id": context["source_id"],
                "text": context["source_text"],
                "norm_type": context["norm_type"],
                "parser_warnings": list(context["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(context["parser_warnings"]),
                    "prompt_context": context,
                },
            }
            for context in prompt_contexts
        ],
        "metrics": {
            "repair_required_count": 4,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 4"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 0.25
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert len(normalized["repair_required_details"]) == 1
    detail = normalized["repair_required_details"][0]
    assert detail["source_id"] == unresolved["source_id"]
    assert detail["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert detail["deterministic_resolution"] == {}
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required_rate"] == 0.25
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_stalled_detail_payload_shape():
    """The evaluator may provide only raw repair details with prompt contexts."""
    exception = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    override = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    applicability = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    def detail_for(sample_id, element):
        context = {
            "source_text": element["text"],
            "source_id": element["source_id"],
            "canonical_citation": element["canonical_citation"],
            "support_text": element["support_text"],
            "support_span": element["support_span"],
            "source_span": element.get("source_span", element["support_span"]),
            "deontic_operator": element["deontic_operator"],
            "norm_type": element["norm_type"],
            "subject": list(element["subject"]),
            "action": list(element["action"]),
            "conditions": list(element.get("condition_details") or element.get("conditions") or []),
            "exceptions": list(element.get("exception_details") or element.get("exceptions") or []),
            "override_clauses": list(element.get("override_clause_details") or element.get("override_clauses") or []),
            "cross_references": list(element.get("cross_reference_details") or element.get("cross_references") or []),
            "resolved_cross_references": list(element.get("resolved_cross_references") or []),
            "parser_warnings": list(element["parser_warnings"]),
        }
        return {
            "sample_id": sample_id,
            "text": element["text"],
            "source_id": element["source_id"],
            "norm_type": element["norm_type"],
            "modality": None,
            "subject": list(element["subject"]),
            "action": list(element["action"]),
            "parser_warnings": list(element["parser_warnings"]),
            "llm_repair": {"required": True, "reasons": list(element["parser_warnings"]), "prompt_context": context},
        }

    raw_evaluation = {
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            detail_for("exception", exception),
            detail_for("override", override),
            detail_for("applicability", applicability),
            detail_for("cross_reference", unresolved),
        ],
        "metrics": {"repair_required_count": 4, "repair_required_rate": 1.0, "coverage_gaps": ["repair_required_count: 4"]},
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 0.25
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == ["cross_reference"]
    assert normalized["repair_required_details"][0]["active_repair_warnings"] == unresolved["parser_warnings"]
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_detail_only_rows_without_prompt_context():
    """Raw repair details alone should still use deterministic IR readiness."""
    exception = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    override = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    applicability = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    def detail_for(sample_id, element):
        return {
            "sample_id": sample_id,
            "text": element["text"],
            "source_id": element["source_id"],
            "canonical_citation": element["canonical_citation"],
            "support_text": element["support_text"],
            "support_span": element["support_span"],
            "source_span": element.get("source_span", element["support_span"]),
            "norm_type": element["norm_type"],
            "modality": None,
            "subject": list(element["subject"]),
            "action": list(element["action"]),
            "conditions": list(element.get("condition_details") or element.get("conditions") or []),
            "exceptions": list(element.get("exception_details") or element.get("exceptions") or []),
            "override_clauses": list(element.get("override_clause_details") or element.get("override_clauses") or []),
            "cross_references": list(element.get("cross_reference_details") or element.get("cross_references") or []),
            "resolved_cross_references": list(element.get("resolved_cross_references") or []),
            "parser_warnings": list(element["parser_warnings"]),
            "llm_repair": {"required": True, "reasons": list(element["parser_warnings"])},
        }

    raw_evaluation = {
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            detail_for("exception", exception),
            detail_for("override", override),
            detail_for("applicability", applicability),
            detail_for("cross_reference", unresolved),
        ],
        "metrics": {
            "repair_required_count": 4,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 4"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 0.25
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == ["cross_reference"]
    assert normalized["repair_required_details"][0]["active_repair_warnings"] == unresolved["parser_warnings"]
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_detail_only_override_from_text():
    """A detail-only pure precedence override should not stay active repair."""
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    override_text = "Notwithstanding section 5.01.020, the Director may issue a variance."
    override = extract_normative_elements(override_text)[0]

    raw_evaluation = {
        "repair_required_count": 2,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "override",
                "text": override_text,
                "source_id": override["source_id"],
                "canonical_citation": override["canonical_citation"],
                "support_text": override["support_text"],
                "support_span": override["support_span"],
                "source_span": override.get("source_span", override["support_span"]),
                "norm_type": "permission",
                "modality": None,
                "subject": ["Director"],
                "action": ["issue a variance"],
                "parser_warnings": [
                    "cross_reference_requires_resolution",
                    "override_clause_requires_precedence_review",
                ],
                "llm_repair": {
                    "required": True,
                    "reasons": [
                        "cross_reference_requires_resolution",
                        "override_clause_requires_precedence_review",
                    ],
                },
            },
            {
                "sample_id": "cross_reference",
                "text": unresolved["text"],
                "source_id": unresolved["source_id"],
                "canonical_citation": unresolved["canonical_citation"],
                "support_text": unresolved["support_text"],
                "support_span": unresolved["support_span"],
                "source_span": unresolved.get("source_span", unresolved["support_span"]),
                "norm_type": unresolved["norm_type"],
                "modality": None,
                "subject": list(unresolved["subject"]),
                "action": list(unresolved["action"]),
                "exceptions": list(unresolved.get("exception_details") or []),
                "cross_references": list(unresolved.get("cross_reference_details") or []),
                "parser_warnings": list(unresolved["parser_warnings"]),
                "llm_repair": {"required": True, "reasons": list(unresolved["parser_warnings"])},
            },
        ],
        "metrics": {"repair_required_count": 2, "repair_required_rate": 1.0, "coverage_gaps": ["repair_required_count: 2"]},
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == ["cross_reference"]
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_operator_bearing_detail_only_override():
    """Explicit-operator precedence rows should still recover override slots."""
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    override_text = "Notwithstanding section 5.01.020, the Director may issue a variance."
    override = extract_normative_elements(override_text)[0]

    raw_evaluation = {
        "repair_required_count": 2,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "override",
                "text": override_text,
                "source_id": override["source_id"],
                "canonical_citation": override["canonical_citation"],
                "support_text": override["support_text"],
                "support_span": override["support_span"],
                "source_span": override.get("source_span", override["support_span"]),
                "norm_type": "permission",
                "deontic_operator": "P",
                "subject": ["Director"],
                "action": ["issue a variance"],
                "parser_warnings": [
                    "cross_reference_requires_resolution",
                    "override_clause_requires_precedence_review",
                ],
                "llm_repair": {
                    "required": True,
                    "reasons": [
                        "cross_reference_requires_resolution",
                        "override_clause_requires_precedence_review",
                    ],
                },
            },
            {
                "sample_id": "cross_reference",
                "text": unresolved["text"],
                "source_id": unresolved["source_id"],
                "canonical_citation": unresolved["canonical_citation"],
                "support_text": unresolved["support_text"],
                "support_span": unresolved["support_span"],
                "source_span": unresolved.get("source_span", unresolved["support_span"]),
                "norm_type": unresolved["norm_type"],
                "modality": None,
                "subject": list(unresolved["subject"]),
                "action": list(unresolved["action"]),
                "exceptions": list(unresolved.get("exception_details") or []),
                "cross_references": list(unresolved.get("cross_reference_details") or []),
                "parser_warnings": list(unresolved["parser_warnings"]),
                "llm_repair": {"required": True, "reasons": list(unresolved["parser_warnings"])},
            },
        ],
        "metrics": {
            "repair_required_count": 2,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 2"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == [
        "cross_reference"
    ]
    assert normalized["active_repair_required_by_source_id"][override["source_id"]] is False
    assert normalized["active_repair_required_by_source_id"][unresolved["source_id"]] is True
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_prompt_context_override_without_override_slot():
    """Prompt-context precedence rows should recover override slots before metrics."""

    override = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    raw_evaluation = {
        "repair_required_count": 2,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "override",
                "text": override["text"],
                "source_id": override["source_id"],
                "norm_type": override["norm_type"],
                "modality": None,
                "subject": list(override["subject"]),
                "action": list(override["action"]),
                "parser_warnings": list(override["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(override["parser_warnings"]),
                    "prompt_context": {
                        "source_text": override["text"],
                        "source_id": override["source_id"],
                        "support_text": override["support_text"],
                        "support_span": override["support_span"],
                        "source_span": override.get("source_span", override["support_span"]),
                        "deontic_operator": override["deontic_operator"],
                        "norm_type": override["norm_type"],
                        "subject": list(override["subject"]),
                        "action": list(override["action"]),
                        "cross_references": list(override.get("cross_reference_details") or []),
                        "parser_warnings": list(override["parser_warnings"]),
                    },
                },
            },
            {
                "sample_id": "cross_reference",
                "text": unresolved["text"],
                "source_id": unresolved["source_id"],
                "canonical_citation": unresolved["canonical_citation"],
                "support_text": unresolved["support_text"],
                "support_span": unresolved["support_span"],
                "source_span": unresolved.get("source_span", unresolved["support_span"]),
                "norm_type": unresolved["norm_type"],
                "modality": None,
                "subject": list(unresolved["subject"]),
                "action": list(unresolved["action"]),
                "exceptions": list(unresolved.get("exception_details") or []),
                "cross_references": list(unresolved.get("cross_reference_details") or []),
                "parser_warnings": list(unresolved["parser_warnings"]),
                "llm_repair": {"required": True, "reasons": list(unresolved["parser_warnings"])},
            },
        ],
        "metrics": {"repair_required_count": 2, "repair_required_rate": 1.0, "coverage_gaps": ["repair_required_count: 2"]},
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == ["cross_reference"]
    assert normalized["active_repair_required_by_source_id"][override["source_id"]] is False
    assert normalized["active_repair_required_by_source_id"][unresolved["source_id"]] is True
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_detail_only_applicability_without_operator():
    """A detail-only local applicability row should not stay active repair."""
    applicability = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]
    unresolved = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    raw_evaluation = {
        "repair_required_count": 2,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "applicability",
                "text": applicability["text"],
                "source_id": applicability["source_id"],
                "canonical_citation": applicability["canonical_citation"],
                "support_text": applicability["support_text"],
                "support_span": applicability["support_span"],
                "source_span": applicability.get("source_span", applicability["support_span"]),
                "norm_type": "applicability",
                "modality": None,
                "subject": ["this section"],
                "action": ["apply to food carts and mobile vendors"],
                "cross_references": list(applicability.get("cross_reference_details") or []),
                "parser_warnings": ["cross_reference_requires_resolution"],
                "llm_repair": {
                    "required": True,
                    "reasons": ["cross_reference_requires_resolution"],
                },
            },
            {
                "sample_id": "cross_reference",
                "text": unresolved["text"],
                "source_id": unresolved["source_id"],
                "canonical_citation": unresolved["canonical_citation"],
                "support_text": unresolved["support_text"],
                "support_span": unresolved["support_span"],
                "source_span": unresolved.get("source_span", unresolved["support_span"]),
                "norm_type": unresolved["norm_type"],
                "modality": None,
                "subject": list(unresolved["subject"]),
                "action": list(unresolved["action"]),
                "exceptions": list(unresolved.get("exception_details") or []),
                "cross_references": list(unresolved.get("cross_reference_details") or []),
                "parser_warnings": list(unresolved["parser_warnings"]),
                "llm_repair": {"required": True, "reasons": list(unresolved["parser_warnings"])},
            },
        ],
        "metrics": {"repair_required_count": 2, "repair_required_rate": 1.0, "coverage_gaps": ["repair_required_count: 2"]},
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required"] == [unresolved["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == ["cross_reference"]
    assert normalized["active_repair_required_by_source_id"][applicability["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_resolves_detail_only_cross_reference_from_sample_context():
    """Detail-only numbered exceptions can clear only with same-document evidence."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    cited = extract_normative_elements("The agency shall keep records.")[0]
    cited = dict(cited)
    cited["canonical_citation"] = ""
    cited["section_context"] = {"section": "552"}

    raw_evaluation = {
        "samples": [
            {
                "sample_id": "section_552_context",
                "elements": [cited],
            }
        ],
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "cross_reference",
                "text": reference["text"],
                "source_id": reference["source_id"],
                "canonical_citation": reference["canonical_citation"],
                "support_text": reference["support_text"],
                "support_span": reference["support_span"],
                "source_span": reference.get("source_span", reference["support_span"]),
                "norm_type": reference["norm_type"],
                "modality": None,
                "subject": list(reference["subject"]),
                "action": list(reference["action"]),
                "exceptions": list(reference.get("exception_details") or []),
                "cross_references": list(reference.get("cross_reference_details") or []),
                "parser_warnings": list(reference["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(reference["parser_warnings"]),
                },
            }
        ],
        "metrics": {
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_resolves_text_only_section_context():
    """Text-only same-document section samples can resolve detail-only references."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    raw_evaluation = {
        "samples": [
            {
                "sample_id": "section_552_context",
                "text": "Section 552. The agency shall keep records.",
            }
        ],
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "cross_reference",
                "text": reference["text"],
                "source_id": reference["source_id"],
                "canonical_citation": reference["canonical_citation"],
                "support_text": reference["support_text"],
                "support_span": reference["support_span"],
                "source_span": reference.get("source_span", reference["support_span"]),
                "norm_type": reference["norm_type"],
                "modality": None,
                "subject": list(reference["subject"]),
                "action": list(reference["action"]),
                "exceptions": list(reference.get("exception_details") or []),
                "cross_references": list(reference.get("cross_reference_details") or []),
                "parser_warnings": list(reference["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(reference["parser_warnings"]),
                },
            }
        ],
        "metrics": {
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_resolves_document_text_section_context():
    """Document-level section headings can resolve detail-only references."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    raw_evaluation = {
        "document_text": "Section 552. The agency shall keep records.",
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "cross_reference",
                "text": reference["text"],
                "source_id": reference["source_id"],
                "canonical_citation": reference["canonical_citation"],
                "support_text": reference["support_text"],
                "support_span": reference["support_span"],
                "source_span": reference.get("source_span", reference["support_span"]),
                "norm_type": reference["norm_type"],
                "modality": None,
                "subject": list(reference["subject"]),
                "action": list(reference["action"]),
                "exceptions": list(reference.get("exception_details") or []),
                "cross_references": list(reference.get("cross_reference_details") or []),
                "parser_warnings": list(reference["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(reference["parser_warnings"]),
                },
            }
        ],
        "metrics": {
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_resolves_nested_metrics_document_text_section_context():
    """Nested metric payload document text can resolve detail-only references."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    raw_evaluation = {
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "cross_reference",
                "text": reference["text"],
                "source_id": reference["source_id"],
                "canonical_citation": reference["canonical_citation"],
                "support_text": reference["support_text"],
                "support_span": reference["support_span"],
                "source_span": reference.get("source_span", reference["support_span"]),
                "norm_type": reference["norm_type"],
                "modality": None,
                "subject": list(reference["subject"]),
                "action": list(reference["action"]),
                "exceptions": list(reference.get("exception_details") or []),
                "cross_references": list(reference.get("cross_reference_details") or []),
                "parser_warnings": list(reference["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(reference["parser_warnings"]),
                },
            }
        ],
        "metrics": {
            "document_text": "Section 552. The agency shall keep records.",
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "repair_required_details": [],
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["repair_required_rate"] == 0.0
    assert normalized["metrics"]["repair_required"] == []
    assert normalized["metrics"]["repair_required_details"] == []
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_recovers_nested_metric_details_when_top_level_details_empty():
    """Nested metric details still count as source rows when top-level details are empty."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail = {
        "sample_id": "cross_reference",
        "text": reference["text"],
        "source_id": reference["source_id"],
        "canonical_citation": reference["canonical_citation"],
        "support_text": reference["support_text"],
        "support_span": reference["support_span"],
        "source_span": reference.get("source_span", reference["support_span"]),
        "norm_type": reference["norm_type"],
        "modality": None,
        "subject": list(reference["subject"]),
        "action": list(reference["action"]),
        "exceptions": list(reference.get("exception_details") or []),
        "cross_references": list(reference.get("cross_reference_details") or []),
        "parser_warnings": list(reference["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(reference["parser_warnings"]),
        },
    }
    raw_evaluation = {
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [],
        "metrics": {
            "document_text": "Section 552. The agency shall keep records.",
            "repair_required": [reference["source_id"]],
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "repair_required_details": [detail],
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["repair_required_rate"] == 0.0
    assert normalized["metrics"]["repair_required"] == []
    assert normalized["metrics"]["repair_required_details"] == []
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_keeps_nested_metric_mismatch_blocked_when_top_level_details_empty():
    """Nested metric recovery must still require the exact cited section."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail = {
        "sample_id": "cross_reference",
        "text": reference["text"],
        "source_id": reference["source_id"],
        "canonical_citation": reference["canonical_citation"],
        "support_text": reference["support_text"],
        "support_span": reference["support_span"],
        "source_span": reference.get("source_span", reference["support_span"]),
        "norm_type": reference["norm_type"],
        "modality": None,
        "subject": list(reference["subject"]),
        "action": list(reference["action"]),
        "exceptions": list(reference.get("exception_details") or []),
        "cross_references": list(reference.get("cross_reference_details") or []),
        "parser_warnings": list(reference["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(reference["parser_warnings"]),
        },
    }
    raw_evaluation = {
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [],
        "metrics": {
            "document_text": "Section 553. The agency shall keep records.",
            "repair_required": [reference["source_id"]],
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "repair_required_details": [detail],
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 1.0
    assert normalized["repair_required"] == [reference["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == [
        "cross_reference"
    ]
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is True
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required"] == [reference["source_id"]]
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_keeps_mismatched_text_only_section_blocked():
    """Text-only context must cite the same numbered section to clear repair."""

    reference = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    raw_evaluation = {
        "samples": [
            {
                "sample_id": "section_553_context",
                "text": "Section 553. The agency shall keep records.",
            }
        ],
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [
            {
                "sample_id": "cross_reference",
                "text": reference["text"],
                "source_id": reference["source_id"],
                "canonical_citation": reference["canonical_citation"],
                "support_text": reference["support_text"],
                "support_span": reference["support_span"],
                "source_span": reference.get("source_span", reference["support_span"]),
                "norm_type": reference["norm_type"],
                "modality": None,
                "subject": list(reference["subject"]),
                "action": list(reference["action"]),
                "exceptions": list(reference.get("exception_details") or []),
                "cross_references": list(reference.get("cross_reference_details") or []),
                "parser_warnings": list(reference["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(reference["parser_warnings"]),
                },
            }
        ],
        "metrics": {
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required_rate"] == 1.0
    assert normalized["repair_required"] == [reference["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == ["cross_reference"]
    assert normalized["active_repair_required_by_source_id"][reference["source_id"]] is True
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["coverage_gaps"] == []


def test_normalize_repair_required_evaluation_keeps_unrecoverable_payload_conservative():
    """Without parser rows, normalization must not invent cleared repairs."""
    raw_evaluation = {
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required": ["deontic:missing"],
        "repair_required_details": [{"source_id": "deontic:missing"}],
        "metrics": {"repair_required_count": 1, "coverage_gaps": ["repair_required_count: 1"]},
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["coverage_gaps"] == []


def test_metrics_hydrate_detail_only_prompt_context_exception_slots():
    """Prompt-context parser slots should survive metrics projection."""

    parsed = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    detail_only = {
        "sample_id": "exception",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "modality": None,
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "support_text": parsed["support_text"],
                "support_span": parsed["support_span"],
                "source_span": parsed.get("source_span", parsed["support_span"]),
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed["exception_details"]),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }

    projected = parser_elements_for_metrics([detail_only])

    assert projected[0]["exception_details"][0]["raw_text"] == "approval is denied"
    assert projected[0]["active_repair_required"] is False
    assert projected[0]["repair_required"] is False
    assert projected[0]["export_readiness"]["formula_repair_required"] is False
    assert projected[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "standard_substantive_exception"
    )
    assert parser_element_has_active_repair(projected[0]) is False


def test_metrics_hydrate_prompt_context_override_precedence_slots():
    """Detail-only precedence rows should regain override provenance."""

    parsed = extract_normative_elements(
        "Notwithstanding section 5.01.020, the Director may issue a variance."
    )[0]
    detail_only = {
        "sample_id": "override",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "modality": None,
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "support_text": parsed["support_text"],
                "support_span": parsed["support_span"],
                "source_span": parsed.get("source_span", parsed["support_span"]),
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "cross_references": list(parsed["cross_reference_details"]),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }

    projected = parser_elements_for_metrics([detail_only])

    assert projected[0]["override_clause_details"][0]["raw_text"] == "section 5.01.020"
    assert projected[0]["override_clause_details"][0]["clause_type"] == "notwithstanding"
    assert projected[0]["active_repair_required"] is False
    assert projected[0]["repair_required"] is False
    assert projected[0]["export_readiness"]["formula_repair_required"] is False
    assert projected[0]["export_readiness"]["deterministic_resolution"]["type"] == (
        "pure_precedence_override"
    )
    assert parser_element_has_active_repair(projected[0]) is False


def test_metrics_hydrate_prompt_context_but_keep_numbered_reference_blocked():
    """Hydration must not clear unresolved numbered exception references."""

    parsed = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail_only = {
        "sample_id": "cross_reference",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed["exception_details"]),
                "cross_references": list(parsed["cross_reference_details"]),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }

    projected = parser_elements_for_metrics([detail_only])

    assert projected[0]["exception_details"][0]["raw_text"] == "as provided in section 552"
    assert projected[0]["cross_reference_details"][0]["raw_text"] == "section 552"
    assert projected[0]["active_repair_required"] is True
    assert projected[0]["export_readiness"]["formula_repair_required"] is True
    assert parser_element_has_active_repair(projected[0]) is True


def test_metrics_clear_numbered_reference_with_prompt_context_same_document_section():
    """Detail-only numbered exceptions may clear with explicit same-document evidence."""

    parsed = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail_only = {
        "sample_id": "cross_reference",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed["exception_details"]),
                "cross_references": list(parsed["cross_reference_details"]),
                "parser_warnings": list(parsed["parser_warnings"]),
                "document_text": (
                    "Section 552. Notice publication.\n"
                    "The Secretary shall keep a public notice register."
                ),
            },
        },
    }

    projected = parser_elements_for_metrics([detail_only])

    assert projected[0]["exception_details"][0]["raw_text"] == "as provided in section 552"
    assert projected[0]["cross_reference_details"][0]["raw_text"] == "section 552"
    assert projected[0]["resolved_cross_references"] == [
        {
            "type": "section",
            "value": "552",
            "raw_text": "section 552",
            "normalized_text": "section 552",
            "span": [61, 72],
            "resolution_status": "resolved",
            "target_exists": True,
            "resolution_scope": "same_document",
            "same_document": True,
            "resolved": True,
            "source_id": parsed["source_id"],
            "resolved_source_id": parsed["source_id"],
        }
    ]
    assert projected[0]["active_repair_required"] is False
    assert projected[0]["export_readiness"]["formula_repair_required"] is False
    assert parser_element_has_active_repair(projected[0]) is False


def test_metrics_projection_recovers_same_document_section_from_context_only_document_text():
    """Context-only document text should resolve references without becoming a metric row."""

    parsed = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail_only = {
        "sample_id": "cross_reference",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "exceptions": list(parsed.get("exception_details") or []),
        "cross_references": list(parsed.get("cross_reference_details") or []),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed.get("exception_details") or []),
                "cross_references": list(parsed.get("cross_reference_details") or []),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }
    context_only = {
        "_context_only": True,
        "document_text": "Section 552. Notice publication.\nThe agency shall keep records.",
        "active_repair_required": True,
        "active_repair_warnings": [],
    }

    projected = parser_elements_for_metrics([detail_only, context_only])

    assert len(projected) == 1
    assert projected[0]["source_id"] == parsed["source_id"]
    assert projected[0]["resolved_cross_references"] == [
        {
            "type": "section",
            "value": "552",
            "raw_text": "section 552",
            "normalized_text": "section 552",
            "span": [61, 72],
            "resolution_status": "resolved",
            "target_exists": True,
            "resolution_scope": "same_document",
            "same_document": True,
            "resolved": True,
            "source_id": parsed["source_id"],
            "resolved_source_id": parsed["source_id"],
        }
    ]
    assert projected[0]["active_repair_required"] is False
    assert projected[0]["active_repair_warnings"] == []
    assert projected[0]["export_readiness"]["formula_repair_required"] is False
    assert parser_element_has_active_repair(projected[0]) is False


def test_metrics_projection_keeps_context_only_document_text_mismatch_blocked():
    """Context-only document text must cite the exact referenced section."""

    parsed = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail_only = {
        "sample_id": "cross_reference",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "exceptions": list(parsed.get("exception_details") or []),
        "cross_references": list(parsed.get("cross_reference_details") or []),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed.get("exception_details") or []),
                "cross_references": list(parsed.get("cross_reference_details") or []),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }
    context_only = {
        "_context_only": True,
        "document_text": "Section 553. Notice publication.\nThe agency shall keep records.",
        "active_repair_required": True,
        "active_repair_warnings": [],
    }

    projected = parser_elements_for_metrics([detail_only, context_only])

    assert len(projected) == 1
    assert projected[0]["source_id"] == parsed["source_id"]
    assert projected[0].get("resolved_cross_references", []) == []
    assert projected[0]["active_repair_required"] is True
    assert projected[0]["active_repair_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert projected[0]["export_readiness"]["formula_repair_required"] is True
    assert parser_element_has_active_repair(projected[0]) is True


def test_normalize_repair_required_evaluation_recovers_context_from_nested_metric_samples():
    """Nested metric samples may carry the only same-document section evidence."""

    parsed = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    detail = {
        "sample_id": "cross_reference",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "canonical_citation": parsed["canonical_citation"],
        "support_text": parsed["support_text"],
        "support_span": parsed["support_span"],
        "source_span": parsed.get("source_span", parsed["support_span"]),
        "norm_type": parsed["norm_type"],
        "modality": None,
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "exceptions": list(parsed.get("exception_details") or []),
        "cross_references": list(parsed.get("cross_reference_details") or []),
        "parser_warnings": list(parsed["parser_warnings"]),
        "llm_repair": {
            "required": True,
            "reasons": list(parsed["parser_warnings"]),
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed.get("exception_details") or []),
                "cross_references": list(parsed.get("cross_reference_details") or []),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }
    raw_evaluation = {
        "repair_required": [parsed["source_id"]],
        "repair_required_count": 1,
        "repair_required_rate": 1.0,
        "repair_required_details": [detail],
        "metrics": {
            "samples": [
                {
                    "sample_id": "section_552_context",
                    "text": "Section 552. Notice publication.\nThe agency shall keep records.",
                }
            ],
            "repair_required": [parsed["source_id"]],
            "repair_required_count": 1,
            "repair_required_rate": 1.0,
            "repair_required_details": [detail],
            "coverage_gaps": ["repair_required_count: 1"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 0
    assert normalized["repair_required_rate"] == 0.0
    assert normalized["repair_required"] == []
    assert normalized["repair_required_details"] == []
    assert normalized["active_repair_required_by_source_id"][parsed["source_id"]] is False
    assert normalized["metrics"]["repair_required_count"] == 0
    assert normalized["metrics"]["repair_required"] == []
    assert normalized["metrics"]["repair_required_details"] == []
    assert normalized["metrics"]["coverage_gaps"] == []


def test_metrics_hydrates_prompt_context_operator_for_detail_only_stale_repair_rows():
    """Detail-only rows with null modality should still clear deterministic repairs."""

    examples = [
        ("exception", "The applicant shall obtain a permit unless approval is denied."),
        ("override", "Notwithstanding section 5.01.020, the Director may issue a variance."),
        ("applicability", "This section applies to food carts and mobile vendors."),
    ]
    detail_rows = []
    for sample_id, text in examples:
        parsed = extract_normative_elements(text)[0]
        detail_rows.append(
            {
                "sample_id": sample_id,
                "text": parsed["text"],
                "source_id": parsed["source_id"],
                "norm_type": parsed["norm_type"],
                "modality": None,
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "parser_warnings": list(parsed["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(parsed["parser_warnings"]),
                    "prompt_context": {
                        "source_text": parsed["text"],
                        "source_id": parsed["source_id"],
                        "deontic_operator": parsed["deontic_operator"],
                        "norm_type": parsed["norm_type"],
                        "subject": list(parsed["subject"]),
                        "action": list(parsed["action"]),
                        "conditions": list(parsed.get("condition_details") or []),
                        "exceptions": list(parsed.get("exception_details") or []),
                        "override_clauses": list(parsed.get("override_clause_details") or []),
                        "cross_references": list(parsed.get("cross_reference_details") or []),
                        "resolved_cross_references": list(parsed.get("resolved_cross_references") or []),
                        "parser_warnings": list(parsed["parser_warnings"]),
                    },
                },
            }
        )

    projected = parser_elements_for_metrics(detail_rows)

    assert [row["deontic_operator"] for row in projected] == ["O", "P", "APP"]
    assert [row["active_repair_required"] for row in projected] == [False, False, False]
    assert [parser_element_has_active_repair(row) for row in projected] == [False, False, False]
    assert [row["llm_repair"]["required"] for row in projected] == [False, False, False]


def test_metrics_projects_formula_resolution_onto_detail_only_active_repair_flags():
    """Stale detail rows should not remain active after deterministic projection."""

    examples = [
        (
            "exception",
            "The applicant shall obtain a permit unless approval is denied.",
            "standard_substantive_exception",
        ),
        (
            "override",
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            "pure_precedence_override",
        ),
        (
            "applicability",
            "This section applies to food carts and mobile vendors.",
            "local_scope_applicability",
        ),
    ]
    detail_rows = []
    for sample_id, text, _resolution_type in examples:
        parsed = extract_normative_elements(text)[0]
        detail_rows.append(
            {
                "sample_id": sample_id,
                "text": parsed["text"],
                "source_id": parsed["source_id"],
                "norm_type": parsed["norm_type"],
                "modality": None,
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "parser_warnings": list(parsed["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "allow_llm_repair": True,
                    "reasons": list(parsed["parser_warnings"]),
                    "prompt_context": {
                        "source_text": parsed["text"],
                        "source_id": parsed["source_id"],
                        "deontic_operator": parsed["deontic_operator"],
                        "norm_type": parsed["norm_type"],
                        "subject": list(parsed["subject"]),
                        "action": list(parsed["action"]),
                        "conditions": list(parsed.get("condition_details") or []),
                        "exceptions": list(parsed.get("exception_details") or []),
                        "override_clauses": list(parsed.get("override_clause_details") or []),
                        "cross_references": list(parsed.get("cross_reference_details") or []),
                        "resolved_cross_references": list(parsed.get("resolved_cross_references") or []),
                        "parser_warnings": list(parsed["parser_warnings"]),
                    },
                },
            }
        )

    projected = parser_elements_for_metrics(detail_rows)

    assert [row["active_repair_required"] for row in projected] == [False, False, False]
    assert [row["active_repair_warnings"] for row in projected] == [[], [], []]
    assert [row["llm_repair"]["required"] for row in projected] == [False, False, False]
    assert [row["llm_repair"]["allow_llm_repair"] for row in projected] == [False, False, False]
    assert [row["llm_repair"]["deterministically_resolved"] for row in projected] == [
        True,
        True,
        True,
    ]
    assert [
        row["export_readiness"]["deterministic_resolution"]["type"] for row in projected
    ] == [resolution_type for _sample_id, _text, resolution_type in examples]
    assert [parser_element_has_active_repair(row) for row in projected] == [False, False, False]


def test_normalize_repair_required_evaluation_clears_prompt_context_stalled_probes():
    """Only the unresolved numbered reference should remain active repair."""

    examples = [
        ("exception", "The applicant shall obtain a permit unless approval is denied."),
        ("override", "Notwithstanding section 5.01.020, the Director may issue a variance."),
        ("applicability", "This section applies to food carts and mobile vendors."),
        ("cross_reference", "The Secretary shall publish the notice except as provided in section 552."),
    ]
    details = []
    for sample_id, text in examples:
        parsed = extract_normative_elements(text)[0]
        prompt_context = {
            "source_text": parsed["text"],
            "source_id": parsed["source_id"],
            "support_text": parsed["support_text"],
            "support_span": parsed["support_span"],
            "source_span": parsed.get("source_span", parsed["support_span"]),
            "deontic_operator": parsed["deontic_operator"],
            "norm_type": parsed["norm_type"],
            "subject": list(parsed["subject"]),
            "action": list(parsed["action"]),
            "conditions": list(parsed.get("condition_details") or []),
            "exceptions": list(parsed.get("exception_details") or []),
            "override_clauses": list(parsed.get("override_clause_details") or []),
            "cross_references": list(parsed.get("cross_reference_details") or []),
            "resolved_cross_references": list(parsed.get("resolved_cross_references") or []),
            "parser_warnings": list(parsed["parser_warnings"]),
        }
        details.append(
            {
                "sample_id": sample_id,
                "text": parsed["text"],
                "source_id": parsed["source_id"],
                "norm_type": parsed["norm_type"],
                "modality": None,
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "parser_warnings": list(parsed["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(parsed["parser_warnings"]),
                    "prompt_context": prompt_context,
                },
            }
        )

    raw_evaluation = {
        "repair_required": [detail["source_id"] for detail in details],
        "repair_required_count": 4,
        "repair_required_rate": 1.0,
        "repair_required_details": details,
        "metrics": {
            "repair_required_count": 4,
            "repair_required_rate": 1.0,
            "coverage_gaps": ["repair_required_count: 4"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required"] == [details[3]["source_id"]]
    assert [
        detail["sample_id"]
        for detail in normalized["metrics"]["repair_required_details"]
    ] == ["cross_reference"]
    assert normalized["metrics"]["active_repair_required_by_source_id"] == {
        details[0]["source_id"]: False,
        details[1]["source_id"]: False,
        details[2]["source_id"]: False,
        details[3]["source_id"]: True,
    }
    assert normalized["metrics"]["coverage_gaps"] == []
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == [
        "cross_reference"
    ]
    active_by_id = normalized["active_repair_required_by_source_id"]
    assert active_by_id[details[0]["source_id"]] is False
    assert active_by_id[details[1]["source_id"]] is False
    assert active_by_id[details[2]["source_id"]] is False
    assert active_by_id[details[3]["source_id"]] is True


def test_normalize_repair_required_evaluation_recovers_nested_metric_details():
    """Daemon metric payloads may carry repair details only under metrics."""

    examples = [
        ("exception", "The applicant shall obtain a permit unless approval is denied."),
        ("override", "Notwithstanding section 5.01.020, the Director may issue a variance."),
        ("applicability", "This section applies to food carts and mobile vendors."),
        ("cross_reference", "The Secretary shall publish the notice except as provided in section 552."),
    ]
    details = []
    for sample_id, text in examples:
        parsed = extract_normative_elements(text)[0]
        details.append(
            {
                "sample_id": sample_id,
                "text": parsed["text"],
                "source_id": parsed["source_id"],
                "norm_type": parsed["norm_type"],
                "modality": None,
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "parser_warnings": list(parsed["parser_warnings"]),
                "llm_repair": {
                    "required": True,
                    "reasons": list(parsed["parser_warnings"]),
                    "prompt_context": {
                        "source_text": parsed["text"],
                        "source_id": parsed["source_id"],
                        "support_text": parsed["support_text"],
                        "support_span": parsed["support_span"],
                        "source_span": parsed.get("source_span", parsed["support_span"]),
                        "deontic_operator": parsed["deontic_operator"],
                        "norm_type": parsed["norm_type"],
                        "subject": list(parsed["subject"]),
                        "action": list(parsed["action"]),
                        "conditions": list(parsed.get("condition_details") or []),
                        "exceptions": list(parsed.get("exception_details") or []),
                        "override_clauses": list(parsed.get("override_clause_details") or []),
                        "cross_references": list(parsed.get("cross_reference_details") or []),
                        "resolved_cross_references": list(parsed.get("resolved_cross_references") or []),
                        "parser_warnings": list(parsed["parser_warnings"]),
                    },
                },
            }
        )

    raw_evaluation = {
        "metrics": {
            "repair_required": [detail["source_id"] for detail in details],
            "repair_required_count": 4,
            "repair_required_rate": 1.0,
            "repair_required_details": details,
            "coverage_gaps": ["repair_required_count: 4"],
        },
    }

    normalized = normalize_repair_required_evaluation([], raw_evaluation)

    assert normalized["repair_required_count"] == 1
    assert normalized["repair_required"] == [details[3]["source_id"]]
    assert [detail["sample_id"] for detail in normalized["repair_required_details"]] == [
        "cross_reference"
    ]
    assert normalized["metrics"]["repair_required_count"] == 1
    assert normalized["metrics"]["repair_required"] == [details[3]["source_id"]]
    assert [
        detail["sample_id"]
        for detail in normalized["metrics"]["repair_required_details"]
    ] == ["cross_reference"]
    assert normalized["metrics"]["active_repair_required_by_source_id"] == {
        details[0]["source_id"]: False,
        details[1]["source_id"]: False,
        details[2]["source_id"]: False,
        details[3]["source_id"]: True,
    }
    assert normalized["metrics"]["coverage_gaps"] == []


def test_metric_projection_clears_stale_llm_flag_when_formula_readiness_resolved():
    """Formula-resolved detail rows should not survive as active repair."""

    parsed = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]
    detail_row = {
        "sample_id": "exception",
        "text": parsed["text"],
        "source_id": parsed["source_id"],
        "norm_type": parsed["norm_type"],
        "modality": None,
        "subject": list(parsed["subject"]),
        "action": list(parsed["action"]),
        "parser_warnings": list(parsed["parser_warnings"]),
        "export_readiness": {
            "formula_proof_ready": True,
            "formula_requires_validation": False,
            "formula_repair_required": False,
            "deterministic_resolution": {
                "type": "standard_substantive_exception",
                "resolved_blockers": ["exception_requires_scope_review"],
            },
        },
        "llm_repair": {
            "required": True,
            "allow_llm_repair": True,
            "reasons": ["exception_requires_scope_review"],
            "prompt_context": {
                "source_text": parsed["text"],
                "source_id": parsed["source_id"],
                "deontic_operator": parsed["deontic_operator"],
                "norm_type": parsed["norm_type"],
                "subject": list(parsed["subject"]),
                "action": list(parsed["action"]),
                "exceptions": list(parsed.get("exception_details") or []),
                "parser_warnings": list(parsed["parser_warnings"]),
            },
        },
    }

    projected = parser_elements_for_metrics([detail_row])[0]

    assert projected["active_repair_required"] is False
    assert projected["active_repair_warnings"] == []
    assert projected["llm_repair"]["required"] is False
    assert projected["llm_repair"]["allow_llm_repair"] is False
    assert projected["llm_repair"]["deterministically_resolved"] is True
    assert parser_element_has_active_repair(projected) is False


def test_raw_parser_clears_repair_for_standard_substantive_exception():
    """A single plain unless-clause is deterministic formula structure, not LLM repair."""

    element = extract_normative_elements(
        "The applicant shall obtain a permit unless approval is denied."
    )[0]

    assert element["parser_warnings"] == ["exception_requires_scope_review"]
    assert element["promotable_to_theorem"] is False
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["deterministic_resolution"] == {
        "type": "standard_substantive_exception",
        "resolved_blockers": ["exception_requires_scope_review"],
        "exception": "approval is denied",
        "exception_span": element["exception_details"][0].get("span", []),
        "reason": "single substantive exception is represented as a negated formula antecedent",
    }
    assert element["export_readiness"]["formula_proof_ready"] is True
    assert element["export_readiness"]["formula_requires_validation"] is False
    assert element["export_readiness"]["formula_repair_required"] is False
    assert element["active_repair_required"] is False
    assert element["active_repair_warnings"] == []
    assert parser_element_has_active_repair(element) is False


def test_raw_parser_clears_repair_for_local_applicability_without_hiding_warning():
    """Local applicability self-references are provenance, not active repair."""

    element = extract_normative_elements(
        "This section applies to food carts and mobile vendors."
    )[0]

    assert element["norm_type"] == "applicability"
    assert element["deontic_operator"] == "APP"
    assert element["parser_warnings"] == ["cross_reference_requires_resolution"]
    assert element["promotable_to_theorem"] is False
    assert element["resolved_cross_references"] == [
        {
            "reference_type": "section",
            "target": "this",
            "value": "this section",
            "raw_text": "This section",
            "span": [0, 12],
            "resolution_scope": "local_self",
            "resolved": True,
            "resolution_status": "resolved",
            "same_document": True,
            "target_exists": True,
        }
    ]
    assert element["llm_repair"]["required"] is False
    assert element["llm_repair"]["allow_llm_repair"] is False
    assert element["llm_repair"]["reasons"] == []
    assert element["llm_repair"]["deterministic_resolution"]["type"] == "local_scope_applicability"
    assert element["active_repair_required"] is False
    assert element["active_repair_warnings"] == []
    assert parser_element_has_active_repair(element) is False


def test_raw_parser_keeps_numbered_reference_exception_repair_active():
    """External or unresolved numbered exception references still require repair."""

    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]

    assert element["parser_warnings"] == [
        "cross_reference_requires_resolution",
        "exception_requires_scope_review",
    ]
    assert element["llm_repair"]["required"] is True
    assert parser_element_has_active_repair(element) is True


def test_raw_parser_same_document_reference_resolution_uses_canonical_reference_text():
    """Bare resolved section targets still display canonical section provenance."""

    element = extract_normative_elements(
        "The Secretary shall publish the notice except as provided in section 552."
    )[0]
    context = extract_normative_elements("The agency shall keep records.")[0]
    context = dict(context)
    context["canonical_citation"] = "section 552"
    context["section_context"] = {
        "section": "552",
        "canonical_citation": "section 552",
    }

    aligned = parser_elements_for_metrics([element, context])[0]

    assert aligned["llm_repair"]["deterministic_resolution"]["references"] == [
        "section 552"
    ]
    assert aligned["resolved_cross_references"][0]["value"] == "552"
    assert aligned["resolved_cross_references"][0]["normalized_text"] == "section 552"


def test_ir_procedure_event_records_mark_service_trigger_as_prerequisite():
    """Service of notice is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall renew a permit after service of notice."
    )[0])
    element["procedure"] = {
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_service_of",
                "anchor_event": "notice",
                "raw_text": "after service of notice",
                "span": [36, 59],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "renewal"
    assert records[0]["event_symbol"] == "Renewal"
    assert records[0]["relation"] == "triggered_by_service_of"
    assert records[0]["anchor_event"] == "notice"
    assert records[0]["anchor_symbol"] == "Notice"
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"
    assert records[0]["relation_record"]["raw_text"] == "after service of notice"


def test_ir_procedure_event_records_mark_adoption_trigger_as_prerequisite():
    """Adoption of rules is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall publish guidelines after adoption of rules."
    )[0])
    element["procedure"] = {
        "event_relations": [
            {
                "event": "publication",
                "relation": "triggered_by_adoption_of",
                "anchor_event": "rules",
                "raw_text": "after adoption of rules",
                "span": [39, 62],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "publication"
    assert records[0]["event_symbol"] == "Publication"
    assert records[0]["relation"] == "triggered_by_adoption_of"
    assert records[0]["anchor_event"] == "rules"
    assert records[0]["anchor_symbol"] == "Rules"
    assert records[0]["raw_text"] == "after adoption of rules"
    assert records[0]["span"] == [39, 62]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"
    assert records[0]["relation_record"]["relation"] == "triggered_by_adoption_of"


def test_ir_procedure_event_records_mark_commencement_trigger_as_prerequisite():
    """Commencement of operations is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after commencement of operations."
    )[0])
    element["procedure"] = {
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_commencement_of",
                "anchor_event": "operations",
                "raw_text": "after commencement of operations",
                "span": [40, 72],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "inspection"
    assert records[0]["event_symbol"] == "Inspection"
    assert records[0]["relation"] == "triggered_by_commencement_of"
    assert records[0]["anchor_event"] == "operations"
    assert records[0]["anchor_symbol"] == "Operations"
    assert records[0]["raw_text"] == "after commencement of operations"
    assert records[0]["span"] == [40, 72]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"
    assert records[0]["relation_record"]["relation"] == "triggered_by_commencement_of"


def test_ir_procedure_event_records_mark_execution_trigger_as_prerequisite():
    """Execution of an agreement is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a certificate after execution of the agreement."
    )[0])
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_execution_of",
                "anchor_event": "agreement",
                "raw_text": "after execution of the agreement",
                "span": [39, 72],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_execution_of"
    assert records[0]["anchor_event"] == "agreement"
    assert records[0]["anchor_symbol"] == "Agreement"
    assert records[0]["raw_text"] == "after execution of the agreement"
    assert records[0]["span"] == [39, 72]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"
    assert records[0]["relation_record"]["relation"] == "triggered_by_execution_of"


def test_ir_procedure_event_records_mark_recording_trigger_as_prerequisite():
    """Recording of an instrument is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall renew a license after recording of the deed."
    )[0])
    element["procedure"] = {
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_recording_of",
                "anchor_event": "deed",
                "raw_text": "after recording of the deed",
                "span": [35, 63],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "renewal"
    assert records[0]["event_symbol"] == "Renewal"
    assert records[0]["relation"] == "triggered_by_recording_of"
    assert records[0]["anchor_event"] == "deed"
    assert records[0]["anchor_symbol"] == "Deed"
    assert records[0]["raw_text"] == "after recording of the deed"
    assert records[0]["span"] == [35, 63]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"
    assert records[0]["relation_record"]["relation"] == "triggered_by_recording_of"


def test_ir_procedure_event_records_mark_inspection_trigger_as_prerequisite():
    """Inspection of premises is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall renew a permit after inspection of the premises."
    )[0])
    element["action"] = ["renew a permit after inspection premises"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "renewal",
                "relation": "triggered_by_inspection_of",
                "anchor_event": "premises",
                "raw_text": "after inspection of the premises",
                "span": [36, 69],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "renewal"
    assert records[0]["event_symbol"] == "Renewal"
    assert records[0]["relation"] == "triggered_by_inspection_of"
    assert records[0]["anchor_event"] == "premises"
    assert records[0]["anchor_symbol"] == "Premises"
    assert records[0]["raw_text"] == "after inspection of the premises"
    assert records[0]["span"] == [36, 69]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_renewal_trigger_as_prerequisite():
    """Renewal of a license is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after renewal of the license."
    )[0])
    element["action"] = ["inspect the premises after renewal license"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_renewal_of",
                "anchor_event": "license",
                "raw_text": "after renewal of the license",
                "span": [40, 69],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "inspection"
    assert records[0]["event_symbol"] == "Inspection"
    assert records[0]["relation"] == "triggered_by_renewal_of"
    assert records[0]["anchor_event"] == "license"
    assert records[0]["anchor_symbol"] == "License"
    assert records[0]["raw_text"] == "after renewal of the license"
    assert records[0]["span"] == [40, 69]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_expiration_trigger_as_prerequisite():
    """Expiration of a license is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after expiration of the license."
    )[0])
    element["action"] = ["inspect the premises after expiration license"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_expiration_of",
                "anchor_event": "license",
                "raw_text": "after expiration of the license",
                "span": [40, 72],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "inspection"
    assert records[0]["event_symbol"] == "Inspection"
    assert records[0]["relation"] == "triggered_by_expiration_of"
    assert records[0]["anchor_event"] == "license"
    assert records[0]["anchor_symbol"] == "License"
    assert records[0]["raw_text"] == "after expiration of the license"
    assert records[0]["span"] == [40, 72]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_termination_trigger_as_prerequisite():
    """Termination of a license is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after termination of the license."
    )[0])
    element["action"] = ["inspect the premises after termination license"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_termination_of",
                "anchor_event": "license",
                "raw_text": "after termination of the license",
                "span": [40, 73],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "inspection"
    assert records[0]["event_symbol"] == "Inspection"
    assert records[0]["relation"] == "triggered_by_termination_of"
    assert records[0]["anchor_event"] == "license"
    assert records[0]["anchor_symbol"] == "License"
    assert records[0]["raw_text"] == "after termination of the license"
    assert records[0]["span"] == [40, 73]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_revocation_trigger_as_prerequisite():
    """Revocation of a license is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall inspect the premises after revocation of the license."
    )[0])
    element["action"] = ["inspect the premises after revocation license"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "inspection",
                "relation": "triggered_by_revocation_of",
                "anchor_event": "license",
                "raw_text": "after revocation of the license",
                "span": [40, 72],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "inspection"
    assert records[0]["event_symbol"] == "Inspection"
    assert records[0]["relation"] == "triggered_by_revocation_of"
    assert records[0]["anchor_event"] == "license"
    assert records[0]["anchor_symbol"] == "License"
    assert records[0]["raw_text"] == "after revocation of the license"
    assert records[0]["span"] == [40, 72]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_denial_trigger_as_prerequisite():
    """Denial of an application is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a notice after denial of the application."
    )[0])
    element["action"] = ["issue a notice after denial application"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_denial_of",
                "anchor_event": "application",
                "raw_text": "after denial of the application",
                "span": [36, 68],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_denial_of"
    assert records[0]["anchor_event"] == "application"
    assert records[0]["anchor_symbol"] == "Application"
    assert records[0]["raw_text"] == "after denial of the application"
    assert records[0]["span"] == [36, 68]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_payment_trigger_as_prerequisite():
    """Payment of a fee is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a permit after payment of the fee."
    )[0])
    element["action"] = ["issue a permit after payment fee"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_payment_of",
                "anchor_event": "fee",
                "raw_text": "after payment of the fee",
                "span": [36, 60],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_payment_of"
    assert records[0]["anchor_event"] == "fee"
    assert records[0]["anchor_symbol"] == "Fee"
    assert records[0]["raw_text"] == "after payment of the fee"
    assert records[0]["span"] == [36, 60]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_assessment_trigger_as_prerequisite():
    """Assessment of a fee is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a notice after assessment of the fee."
    )[0])
    element["action"] = ["issue a notice after assessment fee"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_assessment_of",
                "anchor_event": "fee",
                "raw_text": "after assessment of the fee",
                "span": [36, 64],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_assessment_of"
    assert records[0]["anchor_event"] == "fee"
    assert records[0]["anchor_symbol"] == "Fee"
    assert records[0]["raw_text"] == "after assessment of the fee"
    assert records[0]["span"] == [36, 64]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_determination_trigger_as_prerequisite():
    """Determination of eligibility is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a permit after determination of eligibility."
    )[0])
    element["action"] = ["issue a permit after determination eligibility"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_determination_of",
                "anchor_event": "eligibility",
                "raw_text": "after determination of eligibility",
                "span": [36, 70],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_determination_of"
    assert records[0]["anchor_event"] == "eligibility"
    assert records[0]["anchor_symbol"] == "Eligibility"
    assert records[0]["raw_text"] == "after determination of eligibility"
    assert records[0]["span"] == [36, 70]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_verification_trigger_as_prerequisite():
    """Verification of residency is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a permit after verification of residency."
    )[0])
    element["action"] = ["issue a permit after verification residency"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_verification_of",
                "anchor_event": "residency",
                "raw_text": "after verification of residency",
                "span": [36, 67],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_verification_of"
    assert records[0]["anchor_event"] == "residency"
    assert records[0]["anchor_symbol"] == "Residency"
    assert records[0]["raw_text"] == "after verification of residency"
    assert records[0]["span"] == [36, 67]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_validation_trigger_as_prerequisite():
    """Validation of an application is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Bureau shall approve the license after validation of the application."
    )[0])
    element["action"] = ["approve the license after validation application"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "approval",
                "relation": "triggered_by_validation_of",
                "anchor_event": "application",
                "raw_text": "after validation of the application",
                "span": [39, 75],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "approval"
    assert records[0]["event_symbol"] == "Approval"
    assert records[0]["relation"] == "triggered_by_validation_of"
    assert records[0]["anchor_event"] == "application"
    assert records[0]["anchor_symbol"] == "Application"
    assert records[0]["raw_text"] == "after validation of the application"
    assert records[0]["span"] == [39, 75]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_review_trigger_as_prerequisite():
    """Review of an application is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Director shall issue a permit after review of the application."
    )[0])
    element["action"] = ["issue a permit after review application"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_review_of",
                "anchor_event": "application",
                "raw_text": "after review of the application",
                "span": [36, 67],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_review_of"
    assert records[0]["anchor_event"] == "application"
    assert records[0]["anchor_symbol"] == "Application"
    assert records[0]["raw_text"] == "after review of the application"
    assert records[0]["span"] == [36, 67]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"


def test_ir_procedure_event_records_mark_reconsideration_trigger_as_prerequisite():
    """Reconsideration of an appeal is a procedural prerequisite, not ordering-only provenance."""

    element = dict(extract_normative_elements(
        "The Board shall issue a final order after reconsideration of the appeal."
    )[0])
    element["action"] = ["issue a final order after reconsideration appeal"]
    element["procedure"] = {
        "event_relations": [
            {
                "event": "issuance",
                "relation": "triggered_by_reconsideration_of",
                "anchor_event": "appeal",
                "raw_text": "after reconsideration of the appeal",
                "span": [36, 73],
            }
        ]
    }

    norm = LegalNormIR.from_parser_element(element)
    records = build_procedure_event_records_from_ir(norm)

    assert len(records) == 1
    assert records[0]["event"] == "issuance"
    assert records[0]["event_symbol"] == "Issuance"
    assert records[0]["relation"] == "triggered_by_reconsideration_of"
    assert records[0]["anchor_event"] == "appeal"
    assert records[0]["anchor_symbol"] == "Appeal"
    assert records[0]["raw_text"] == "after reconsideration of the appeal"
    assert records[0]["span"] == [36, 73]
    assert records[0]["is_formula_antecedent"] is True
    assert records[0]["proof_role"] == "prerequisite"
