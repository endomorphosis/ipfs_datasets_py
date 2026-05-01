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
