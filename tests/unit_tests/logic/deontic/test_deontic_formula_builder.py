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
