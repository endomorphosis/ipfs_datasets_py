"""Source-backed inline exceptions survive action recovery and readiness exports."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


ACTION = "publish the notice"
REFERENCE_BLOCKER = "formula_reference_exception_unresolved"
REFERENCE_LIST = "sections 552, 553, and 554"


def source_clause(exception, modal="shall"):
    return f"The Secretary {modal} ({exception}) {ACTION}."


def source_document(*, complete):
    targets = ("552", "553", "554") if complete else ("552", "553")
    sections = [f"Section {number}. Rule {number}\nThe agency shall retain record {number}." for number in targets]
    return "\n".join([*sections, "Section 555. Notice rule\n" + source_clause("except as provided in " + REFERENCE_LIST)])


def selected_element(elements):
    return next(row for row in elements if row["action"] == [ACTION])


def assert_exact_source_slots(element, norm, body, *, modal="shall"):
    assert element["action"] == [ACTION]
    assert norm.action == ACTION
    assert norm.actor == "Secretary"
    assert element["text"][slice(*element["field_spans"]["action"])] == ACTION
    assert element["text"][slice(*element["field_spans"]["modal"])] == modal
    assert norm.modality == ("F" if modal == "shall not" else "O")
    exception, = norm.exceptions
    assert exception["value"] == exception["raw_text"] == body
    for record in [exception, *norm.cross_references]:
        start, end = record["span"]
        assert type(start) is int and type(end) is int
        assert 0 <= start < end <= len(element["text"])
        assert element["text"][start:end] == record["raw_text"]
    assert exception["span"][1] < element["field_spans"]["action"][0]


def assert_blocked_projection(element):
    ready = element["export_readiness"]
    assert ready["formula_proof_ready"] is False
    assert ready["formula_requires_validation"] is True
    assert ready["formula_repair_required"] is True
    assert ready["export_requires_validation"] is True
    assert ready["export_repair_required"] is True
    assert REFERENCE_BLOCKER in ready["formula_blockers"]
    assert ready["deterministic_resolution"] == {}
    assert element["active_repair_required"] is True
    assert REFERENCE_BLOCKER in element["active_repair_warnings"]
    assert element["llm_repair"]["allow_llm_repair"] is False


@pytest.mark.parametrize("reference_text, targets", [
    ("section 552", {"552"}),
    (REFERENCE_LIST, {"552", "553", "554"}),
    ("sections 552(a), 553(b), and 554(c)", {"552(a)", "553(b)", "554(c)"}),
    ("sections 5.01.020, 5.01.030, and 5.01.040", {"5.01.020", "5.01.030", "5.01.040"}),
])
def test_unresolved_inline_references_retain_real_action_and_block_all_readiness(reference_text, targets):
    body = "as provided in " + reference_text
    element, = extract_normative_elements(source_clause("except " + body))
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    assert_exact_source_slots(element, norm, body)
    assert {reference["value"] for reference in norm.cross_references} == targets
    formula = build_deontic_formula_record_from_ir(norm)
    assert formula["formula"] == "O(∀x (Secretary(x) → PublishNotice(x)))"
    assert formula["proof_ready"] is False
    assert formula["requires_validation"] is formula["repair_required"] is True
    assert REFERENCE_BLOCKER in formula["blockers"]
    tables = build_document_export_tables_from_ir([norm])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        row, = tables[name]
        assert row["proof_ready"] is False
        assert row["requires_validation"] is True
        assert REFERENCE_BLOCKER in row["blockers"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is False
    repair, = tables["repair_queue"]
    assert REFERENCE_BLOCKER in repair["reasons"]
    assert repair["allow_llm_repair"] is False
    decoder, = tables["decoder_reconstructions"]
    assert decoder["decoded_text"] == decode_legal_norm_ir(norm).text == f"Secretary shall {ACTION} except {body}."
    assert decoder["proof_ready"] is False
    assert decoder["requires_validation"] is True
    syntax, = tables["prover_syntax_summaries"]
    assert syntax["proof_ready"] is False
    assert syntax["requires_validation"] is True
    projected, = parser_elements_for_metrics([element])
    assert_blocked_projection(projected)
    metrics = summarize_parser_elements([projected])
    assert metrics["repair_required_count"] == 1
    assert metrics["proof_ready_count"] == 0
    assert element == original


@pytest.mark.parametrize("complete", [False, True])
def test_actual_document_targets_control_inline_reference_readiness(complete):
    elements = extract_normative_elements(source_document(complete=complete))
    original = deepcopy(elements)
    element = selected_element(elements)
    norm = LegalNormIR.from_parser_element(element)
    assert_exact_source_slots(element, norm, "as provided in " + REFERENCE_LIST)
    assert {reference["value"] for reference in norm.cross_references} == {"552", "553", "554"}
    resolved = {row["value"] for row in norm.resolved_cross_references if row.get("target_exists") is True}
    assert resolved == ({"552", "553", "554"} if complete else {"552", "553"})
    tables = build_document_export_tables_from_ir([LegalNormIR.from_parser_element(row) for row in elements])
    formal = next(row for row in tables["formal_logic"] if row["source_id"] == norm.source_id)
    proof = next(row for row in tables["proof_obligations"] if row["source_id"] == norm.source_id)
    assert formal["proof_ready"] is complete
    assert proof["theorem_candidate"] is complete
    repairs = [row for row in tables["repair_queue"] if row["source_id"] == norm.source_id]
    assert bool(repairs) is (not complete)
    decoder = next(row for row in tables["decoder_reconstructions"] if row["source_id"] == norm.source_id)
    assert decoder["decoded_text"] == f"Secretary shall {ACTION} except as provided in {REFERENCE_LIST}."
    if not complete:
        assert REFERENCE_BLOCKER in formal["blockers"]
        assert decoder["requires_validation"] is True
    projected = selected_element(parser_elements_for_metrics(elements))
    assert projected["export_readiness"]["formula_proof_ready"] is complete
    assert projected["active_repair_required"] is (not complete)
    assert elements == original


@pytest.mark.parametrize("document_context", [False, True])
def test_cached_inline_reference_clearance_cannot_supply_missing_targets(document_context):
    elements = extract_normative_elements(source_document(complete=False) if document_context else source_clause("except as provided in " + REFERENCE_LIST))
    element = selected_element(elements)
    stale_resolution = {
        "type": "resolved_same_document_reference_exception",
        "references": ["section 552", "section 553"],
    }
    element["active_repair_required"] = False
    element["repair_required"] = False
    element["export_readiness"] = {
        **element.get("export_readiness", {}),
        "formula_proof_ready": True, "formula_requires_validation": False,
        "formula_repair_required": False, "export_requires_validation": False,
        "export_repair_required": False, "deterministic_resolution": stale_resolution,
    }
    element["llm_repair"] = {
        **element.get("llm_repair", {}), "required": False,
        "deterministically_resolved": True, "deterministic_resolution": stale_resolution,
    }
    original = deepcopy(elements)
    projected = parser_elements_with_ir_export_readiness(elements)
    assert_blocked_projection(selected_element(projected))
    for _ in range(3):
        projected = parser_elements_for_metrics(projected)
        selected = selected_element(projected)
        assert_blocked_projection(selected)
        norm = LegalNormIR.from_parser_element(selected)
        assert_exact_source_slots(selected, norm, "as provided in " + REFERENCE_LIST)
        assert summarize_parser_elements([selected])["proof_ready_count"] == 0
    assert elements == original


@pytest.mark.parametrize("modal, operator", [("shall", "O"), ("shall not", "F")])
def test_substantive_inline_unless_retains_negated_exception_scaffold(modal, operator):
    element, = extract_normative_elements(source_clause("unless approval is granted", modal))
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    assert_exact_source_slots(element, norm, "approval is granted", modal=modal)
    assert norm.cross_references == []
    formula = build_deontic_formula_record_from_ir(norm)
    assert formula["formula"] == f"{operator}(∀x (Secretary(x) ∧ ¬ApprovalIsGranted(x) → PublishNotice(x)))"
    tables = build_document_export_tables_from_ir([norm])
    assert tables["decoder_reconstructions"][0]["decoded_text"] == f"Secretary {modal} {ACTION} unless approval is granted."
    assert "exception_requires_scope_review" in element["parser_warnings"]
    # This is the existing conditional scaffold, not independently supplied legal semantics.
    assert element["promotable_to_theorem"] is False
    projected, = parser_elements_for_metrics([element])
    assert projected["action"] == [ACTION]
    assert projected["promotable_to_theorem"] is False
    assert element == original


@pytest.mark.parametrize("exception, body", [
    (" unless approval is granted", "approval is granted"),
    (" except as provided in this section", "as provided in this section"),
])
def test_space_inside_parenthesis_does_not_append_action_to_exception(exception, body):
    element, = extract_normative_elements(source_clause(exception))
    norm = LegalNormIR.from_parser_element(element)
    assert_exact_source_slots(element, norm, body)
    formula = build_deontic_formula_record_from_ir(norm)["formula"]
    assert "PublishNotice" in formula
    assert "GrantedPublishNotice" not in formula
    assert "SectionPublishNotice" not in formula
    assert decode_legal_norm_ir(norm).text == f"Secretary shall {ACTION} {exception.strip()}."


@pytest.mark.parametrize("modal", ["shall", "shall not"])
def test_pure_local_inline_reference_keeps_existing_readiness_control(modal):
    element, = extract_normative_elements(source_clause("except as provided in this section", modal))
    norm = LegalNormIR.from_parser_element(element)
    assert_exact_source_slots(element, norm, "as provided in this section", modal=modal)
    tables = build_document_export_tables_from_ir([norm])
    assert tables["formal_logic"][0]["proof_ready"] is True
    assert tables["repair_queue"] == []
    assert tables["decoder_reconstructions"][0]["decoded_text"] == f"Secretary {modal} {ACTION} except as provided in this section."
    projected, = parser_elements_for_metrics([element])
    assert projected["export_readiness"]["formula_proof_ready"] is True
    assert projected["active_repair_required"] is False
