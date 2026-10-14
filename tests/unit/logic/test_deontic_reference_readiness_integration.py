"""Unresolved references cannot acquire readiness through downstream caches."""
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


CASES = {
    "applicability": (
        "The chapter applies to food carts.",
        "formula_external_applicability_unresolved",
        "AppliesTo(Chapter, FoodCarts)",
        "The chapter applies to food carts.",
    ),
    "condition": (
        "Subject to approval, subject to section 552, the Director shall issue a permit.",
        "formula_reference_condition_unresolved",
        "O(∀x (Director(x) ∧ Approval(x) → IssuePermit(x)))",
        "Director shall issue a permit if approval and if section 552.",
    ),
    "exception": (
        "The Director shall issue a permit unless approval is denied, except as provided in section 552.",
        "formula_reference_exception_unresolved",
        "O(∀x (Director(x) ∧ ¬ApprovalIsDenied(x) → IssuePermit(x)))",
        "Director shall issue a permit unless approval is denied and except as provided in section 552.",
    ),
}
MARKERS = {case[1] for case in CASES.values()}


def source_element(kind):
    element, = extract_normative_elements(CASES[kind][0])
    return element


def assert_blocked_projection(element, marker):
    ready = element["export_readiness"]
    assert ready["formula_proof_ready"] is False
    assert ready["formula_requires_validation"] is True
    assert ready["formula_repair_required"] is True
    assert ready["export_requires_validation"] is True
    assert ready["export_repair_required"] is True
    assert marker in ready["formula_blockers"]
    assert ready["deterministic_resolution"] == {}
    assert element["active_repair_required"] is True
    assert marker in element["active_repair_warnings"]
    assert element["llm_repair"]["allow_llm_repair"] is False


@pytest.mark.parametrize("kind", CASES)
def test_source_reference_blocker_survives_all_tables_and_reconstruction(kind):
    element = source_element(kind)
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    source_records = deepcopy((norm.conditions, norm.exceptions, norm.cross_references))
    for record in norm.conditions + norm.exceptions:
        start, end = record["span"]
        assert 0 <= start < end <= len(element["text"])
        assert element["text"][start:end] == record["raw_text"]

    _, marker, formula, decoded = CASES[kind]
    record = build_deontic_formula_record_from_ir(norm)
    assert record["formula"] == formula
    assert marker in record["blockers"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    tables = build_document_export_tables_from_ir([norm])
    for table in ("canonical", "formal_logic", "proof_obligations"):
        row, = tables[table]
        assert row["proof_ready"] is False
        assert row["requires_validation"] is True
        assert marker in row["blockers"]
    assert tables["proof_obligations"][0]["theorem_candidate"] is False
    repair, = tables["repair_queue"]
    assert marker in repair["reasons"]
    assert repair["formula_repair_required"] is True
    assert repair["allow_llm_repair"] is False
    decoder, = tables["decoder_reconstructions"]
    assert decoder["decoded_text"] == decode_legal_norm_ir(norm).text == decoded
    assert decoder["proof_ready"] is False
    assert decoder["requires_validation"] is True
    syntax, = tables["prover_syntax_summaries"]
    assert syntax["proof_ready"] is False
    assert syntax["requires_validation"] is True
    assert (norm.conditions, norm.exceptions, norm.cross_references) == source_records
    assert element == original


@pytest.mark.parametrize("kind", CASES)
def test_cached_reference_clearance_is_recomputed_on_repeated_projection(kind):
    element = source_element(kind)
    marker = CASES[kind][1]
    stale_resolution = {
        "type": "source_grounded_reconstruction_warning_bundle",
        "resolved_blockers": ["cross_reference_requires_resolution"],
        "core_slots": ["actor", "modality", "action"],
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
    original = deepcopy(element)
    projected, = parser_elements_with_ir_export_readiness([element])
    assert_blocked_projection(projected, marker)
    for _ in range(3):
        projected, = parser_elements_for_metrics([projected])
        assert_blocked_projection(projected, marker)
        assert projected["export_readiness"]["metric_repair_required"] is True
        metrics = summarize_parser_elements([projected])
        assert metrics["repair_required_count"] == 1
        assert metrics["proof_ready_count"] == 0
        assert metrics["phase8_parser_capability_formula_ready_rate"] == 0.0
    assert element == original


@pytest.mark.parametrize("kind", CASES)
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("identity", ["duplicate-probe", None])
def test_reference_row_cannot_borrow_control_readiness_when_ids_collide_or_are_missing(kind, reverse, identity):
    blocked = source_element(kind)
    control, = extract_normative_elements("The clerk shall retain the record.")

    def replace_identity(value):
        if isinstance(value, dict):
            return {
                key: identity if key == "source_id" else replace_identity(item)
                for key, item in value.items()
                if key != "source_id" or identity is not None
            }
        if isinstance(value, list):
            return [replace_identity(item) for item in value]
        return value

    rows = [replace_identity(blocked), replace_identity(control)]
    if reverse:
        rows.reverse()
    original = deepcopy(rows)
    projected = rows
    for _ in range(2):
        projected = parser_elements_for_metrics(projected)
        assert len(projected) == 2
        for row in projected:
            if row["text"] == blocked["text"]:
                assert_blocked_projection(row, CASES[kind][1])
            else:
                assert row["text"] == control["text"]
                assert row["export_readiness"]["formula_proof_ready"] is True
                assert row["active_repair_required"] is False
                assert not MARKERS.intersection(row["export_readiness"]["formula_blockers"])
    assert rows == original


@pytest.mark.parametrize("source", [
    "This section applies to food carts.",
    "Subject to this section, the Director shall issue a permit.",
    "The Director shall issue a permit except as provided in this section.",
])
def test_pure_local_reference_controls_remain_ready(source):
    element, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(element)
    tables = build_document_export_tables_from_ir([norm])
    assert tables["repair_queue"] == []
    assert tables["formal_logic"][0]["proof_ready"] is True
    projected, = parser_elements_for_metrics([element])
    assert projected["export_readiness"]["formula_proof_ready"] is True
    assert projected["active_repair_required"] is False


@pytest.mark.parametrize("slot", ["condition", "exception"])
@pytest.mark.parametrize("mixed", [False, True])
def test_actual_same_document_heading_resolves_only_pure_reference_qualifiers(slot, mixed):
    if slot == "condition":
        clause = ("Subject to approval, " if mixed else "") + "Subject to section 552, the Secretary shall publish the notice."
    else:
        clause = "The Secretary shall publish the notice " + ("unless approval is denied, " if mixed else "") + "except as provided in section 552."
    source = "Section 552. Publication rules\nThe agency shall keep records.\nSection 553. Notice rule\n" + clause
    elements = extract_normative_elements(source)
    original = deepcopy(elements)
    norms = [LegalNormIR.from_parser_element(element) for element in elements]
    selected = next(norm for norm in norms if norm.action == "publish the notice")
    assert selected.resolved_cross_references[0]["target_exists"] is True
    tables = build_document_export_tables_from_ir(norms)
    row = next(row for row in tables["formal_logic"] if row["source_id"] == selected.source_id)
    assert row["proof_ready"] is (not mixed)
    if mixed:
        assert CASES[slot][1] in row["blockers"]
        assert row["deterministic_resolution"] == {}
    else:
        assert not MARKERS.intersection(row["blockers"])
    projected = parser_elements_for_metrics(elements)
    selected_projection = next(row for row in projected if row["action"] == ["publish the notice"])
    assert selected_projection["export_readiness"]["formula_proof_ready"] is (not mixed)
    assert selected_projection["active_repair_required"] is mixed
    assert elements == original
