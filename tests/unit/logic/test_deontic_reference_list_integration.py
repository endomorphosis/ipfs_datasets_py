"""Source reference-list members survive parsing, resolution and reporting."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


TARGETS = {"552", "553", "554"}
LIST_TEXT = "sections 552, 553, and 554"
MARKERS = {
    "condition": "formula_reference_condition_unresolved",
    "exception": "formula_reference_exception_unresolved",
}


def clause(slot, list_text=LIST_TEXT):
    if slot == "condition":
        return f"Subject to {list_text}, the Secretary shall publish the notice."
    return f"The Secretary shall publish the notice except as provided in {list_text}."


def document(slot, *, complete):
    targets = ("552", "553", "554") if complete else ("552", "553")
    sections = [f"Section {number}. Rule {number}\nThe agency shall retain record {number}." for number in targets]
    return "\n".join([*sections, "Section 555. Notice rule\n" + clause(slot)])


def selected_element(elements):
    return next(row for row in elements if row["action"] == ["publish the notice"])


def assert_source_members(element, norm, slot, list_text=LIST_TEXT):
    records = norm.conditions if slot == "condition" else norm.exceptions
    record, = records
    expected = list_text if slot == "condition" else "as provided in " + list_text
    assert record["raw_text"] == record["value"] == expected
    assert element["text"][slice(*record["span"])] == expected
    assert {row["value"] for row in norm.cross_references} == TARGETS
    assert len(norm.cross_references) == 3
    for reference in norm.cross_references:
        assert reference["type"] == "section"
        assert reference["normalized_text"] == "section " + reference["value"]
        start, end = reference["span"]
        assert type(start) is int and type(end) is int
        assert 0 <= start < end <= len(element["text"])
        assert element["text"][start:end] == reference["raw_text"]


def assert_blocked_projection(row, slot):
    ready = row["export_readiness"]
    assert ready["formula_proof_ready"] is False
    assert ready["formula_requires_validation"] is True
    assert ready["formula_repair_required"] is True
    assert MARKERS[slot] in ready["formula_blockers"]
    assert ready["deterministic_resolution"] == {}
    assert row["active_repair_required"] is True
    assert MARKERS[slot] in row["active_repair_warnings"]


@pytest.mark.parametrize("slot", ["condition", "exception"])
@pytest.mark.parametrize("list_text", [
    LIST_TEXT,
    "sections 552, 553 and 554",
    "section 552, section 553, or section 554",
])
def test_actual_standalone_reference_list_retains_every_member_and_remains_blocked(slot, list_text):
    element, = extract_normative_elements(clause(slot, list_text))
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    assert_source_members(element, norm, slot, list_text)
    record = build_deontic_formula_record_from_ir(norm)
    assert record["proof_ready"] is False
    assert MARKERS[slot] in record["blockers"]
    tables = build_document_export_tables_from_ir([norm])
    for table in ("canonical", "formal_logic", "proof_obligations"):
        assert tables[table][0]["proof_ready"] is False
        assert MARKERS[slot] in tables[table][0]["blockers"]
    repair, = tables["repair_queue"]
    assert MARKERS[slot] in repair["reasons"]
    assert repair["allow_llm_repair"] is False
    decoder, = tables["decoder_reconstructions"]
    assert list_text in decoder["decoded_text"]
    assert decoder["requires_validation"] is True
    projected, = parser_elements_for_metrics([element])
    assert_blocked_projection(projected, slot)
    assert summarize_parser_elements([projected])["repair_required_count"] == 1
    assert element == original


@pytest.mark.parametrize("slot", ["condition", "exception"])
@pytest.mark.parametrize("complete", [False, True])
def test_actual_document_headings_must_cover_all_list_members(slot, complete):
    elements = extract_normative_elements(document(slot, complete=complete))
    original = deepcopy(elements)
    element = selected_element(elements)
    norm = LegalNormIR.from_parser_element(element)
    assert_source_members(element, norm, slot)
    resolved = {row["value"] for row in norm.resolved_cross_references if row.get("target_exists") is True}
    assert resolved == (TARGETS if complete else {"552", "553"})
    tables = build_document_export_tables_from_ir([LegalNormIR.from_parser_element(row) for row in elements])
    formal = next(row for row in tables["formal_logic"] if row["source_id"] == norm.source_id)
    proof = next(row for row in tables["proof_obligations"] if row["source_id"] == norm.source_id)
    decoder = next(row for row in tables["decoder_reconstructions"] if row["source_id"] == norm.source_id)
    repairs = [row for row in tables["repair_queue"] if row["source_id"] == norm.source_id]
    assert formal["proof_ready"] is complete
    assert proof["theorem_candidate"] is complete
    assert bool(repairs) is (not complete)
    assert LIST_TEXT in decoder["decoded_text"]
    if not complete:
        assert MARKERS[slot] in formal["blockers"]
        assert decoder["requires_validation"] is True
    projected = parser_elements_for_metrics(elements)
    selected = selected_element(projected)
    assert selected["export_readiness"]["formula_proof_ready"] is complete
    assert selected["active_repair_required"] is (not complete)
    assert elements == original


@pytest.mark.parametrize("slot", ["condition", "exception"])
def test_cached_clearance_for_partial_document_cannot_erase_missing_list_member(slot):
    elements = extract_normative_elements(document(slot, complete=False))
    partial = selected_element(elements)
    stale_resolution = {
        "type": "resolved_same_document_reference_" + slot,
        "references": ["section 552", "section 553"],
    }
    partial["active_repair_required"] = False
    partial["repair_required"] = False
    partial["export_readiness"] = {
        **partial.get("export_readiness", {}),
        "formula_proof_ready": True, "formula_requires_validation": False,
        "formula_repair_required": False, "deterministic_resolution": stale_resolution,
    }
    partial["llm_repair"] = {
        **partial.get("llm_repair", {}),
        "required": False, "deterministically_resolved": True,
        "deterministic_resolution": stale_resolution,
    }
    original = deepcopy(elements)
    projected = elements
    for _ in range(3):
        projected = parser_elements_for_metrics(projected)
        selected = selected_element(projected)
        assert_blocked_projection(selected, slot)
        norm = LegalNormIR.from_parser_element(selected)
        assert_source_members(selected, norm, slot)
    assert elements == original
