"""Tests for IR-derived deterministic export records."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    build_formal_logic_record_from_ir,
    build_proof_obligation_record_from_ir,
    parser_elements_to_export_tables,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
    parser_elements_to_ir_aligned_export_tables,
    validate_export_tables,
)
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
