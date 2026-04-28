"""Tests for IR-derived deterministic export records."""

from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    build_formal_logic_record_from_ir,
    build_proof_obligation_record_from_ir,
    parser_elements_to_export_tables,
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
    assert record["blockers"] == []


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
    assert "cross_reference_requires_resolution" in tables["repair_queue"][0]["reasons"]

    validation = validate_export_tables(tables)
    assert validation == {"valid": True, "errors": []}


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
