"""Actual-source cap omissions stay blocked across downstream projections."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
)
from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


VALUES = {
    "conditions": ("approval is granted", "the fee is paid", "the form is signed", "the site is safe"),
    "exceptions": ("approval is denied", "the fee is unpaid", "the form is unsigned", "the site is unsafe"),
}
MARKERS = {
    "conditions": "formula_condition_cap_exceeded",
    "exceptions": "formula_exception_cap_exceeded",
}


def source_element(slot, *, values=None):
    values = VALUES[slot] if values is None else values
    connector = "if " if slot == "conditions" else "unless "
    source = "The Director shall issue a permit " + ", ".join(connector + value for value in values) + "."
    elements = extract_normative_elements(source)
    assert len(elements) == 1
    return elements[0]


def assert_source_records(element, records):
    for record in records:
        start, end = record["span"]
        assert type(start) is int and type(end) is int
        assert 0 <= start < end <= len(element["text"])
        assert element["text"][start:end] == record["raw_text"]


def assert_active_projection(element, marker, *, metric=False):
    ready = element["export_readiness"]
    assert ready["formula_proof_ready"] is False
    assert ready["formula_requires_validation"] is True
    assert ready["formula_repair_required"] is True
    assert ready["export_requires_validation"] is True
    assert ready["export_repair_required"] is True
    assert marker in ready["formula_blockers"]
    assert ready["deterministic_resolution"] == {}
    assert element["active_repair_required"] is True
    assert element["repair_required"] is True
    assert marker in element["active_repair_warnings"]
    assert element["llm_repair"]["allow_llm_repair"] is False
    if metric:
        assert ready["metric_requires_validation"] is True
        assert ready["metric_repair_required"] is True


@pytest.mark.parametrize("slot", ["conditions", "exceptions"])
def test_actual_source_omission_blocks_tables_but_preserves_complete_ir_and_decoder(slot):
    element = source_element(slot)
    original = deepcopy(element)
    norm = LegalNormIR.from_parser_element(element)
    records = getattr(norm, slot)
    assert len(records) == 4
    assert_source_records(element, records)
    original_records = deepcopy(records)
    formula = build_deontic_formula_from_ir(norm)
    tables = build_document_export_tables_from_ir([norm])
    marker = MARKERS[slot]

    for table in ("canonical", "formal_logic", "proof_obligations"):
        row, = tables[table]
        assert row["proof_ready"] is False
        assert row["requires_validation"] is True
        assert marker in row["blockers"]
    proof, = tables["proof_obligations"]
    assert proof["theorem_candidate"] is False
    formal, = tables["formal_logic"]
    assert formal["formula"] == formula
    assert formal["repair_required"] is True
    assert formal["deterministic_resolution"] == {}
    omitted, = formal["omitted_formula_slots"][slot]
    assert omitted["value"] == VALUES[slot][-1]
    assert omitted["span"] == records[-1]["span"]
    assert omitted["predicate"] + "(x)" not in formula

    repair, = tables["repair_queue"]
    assert marker in repair["reasons"]
    assert repair["formula_proof_ready"] is False
    assert repair["formula_repair_required"] is True
    assert repair["allow_llm_repair"] is False
    assert repair["omitted_formula_slots"][slot] == [omitted]

    decoder, = tables["decoder_reconstructions"]
    connector = "if" if slot == "conditions" else "unless"
    expected = "Director shall issue a permit " + f" and {connector} ".join(
        [f"{connector} " + VALUES[slot][0], *VALUES[slot][1:]]
    ) + "."
    assert decoder["decoded_text"] == decode_legal_norm_ir(norm).text == expected
    assert decoder["proof_ready"] is False
    assert decoder["requires_validation"] is True
    assert any(records[-1]["span"] in phrase["spans"] for phrase in decoder["phrase_provenance"])
    syntax, = tables["prover_syntax_summaries"]
    assert syntax["proof_ready"] is False
    assert syntax["requires_validation"] is True
    assert getattr(norm, slot) == original_records
    assert element == original


@pytest.mark.parametrize("slot", ["conditions", "exceptions"])
def test_actual_source_omission_remains_active_on_repeated_metrics_projection(slot):
    element = source_element(slot)
    before = deepcopy(element)
    historical_parser_ready = element.get("promotable_to_theorem")
    projected, = parser_elements_with_ir_export_readiness([element])
    assert_active_projection(projected, MARKERS[slot])
    assert projected.get("promotable_to_theorem") == historical_parser_ready
    for _ in range(3):
        projected, = parser_elements_for_metrics([projected])
        assert_active_projection(projected, MARKERS[slot], metric=True)
        metrics = summarize_parser_elements([projected])
        assert metrics["repair_required_count"] == 1
        assert metrics["proof_ready_count"] == 0
        assert metrics["phase8_parser_capability_formula_ready_rate"] == 0.0
    assert element == before


@pytest.mark.parametrize("slot", ["conditions", "exceptions"])
def test_cached_inactive_resolution_cannot_clear_actual_source_cap_omission(slot):
    element = source_element(slot)
    resolution = {
        "type": "source_grounded_reconstruction_warning_bundle",
        "resolved_blockers": ["exception_requires_scope_review"],
        "core_slots": ["actor", "modality", "action"],
    }
    element["active_repair_required"] = False
    element["repair_required"] = False
    element["export_readiness"] = {
        **element.get("export_readiness", {}),
        "formula_proof_ready": True, "formula_requires_validation": False,
        "formula_repair_required": False, "export_requires_validation": False,
        "export_repair_required": False, "deterministic_resolution": resolution,
    }
    element["llm_repair"] = {
        **element.get("llm_repair", {}),
        "required": False, "deterministically_resolved": True,
        "deterministic_resolution": resolution,
    }
    original = deepcopy(element)
    for _ in range(3):
        projected, = parser_elements_for_metrics([element])
        assert_active_projection(projected, MARKERS[slot], metric=True)
        projected, = parser_elements_for_metrics([projected])
        assert_active_projection(projected, MARKERS[slot], metric=True)
    assert element == original


@pytest.mark.parametrize("slot", ["conditions", "exceptions"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_three_distinct_source_predicates_do_not_acquire_cap_blockers(slot, duplicate):
    values = VALUES[slot][:3]
    if duplicate:
        values += (VALUES[slot][0],)
    element = source_element(slot, values=values)
    norm = LegalNormIR.from_parser_element(element)
    assert_source_records(element, getattr(norm, slot))
    record = build_deontic_formula_record_from_ir(norm)
    assert not set(MARKERS.values()).intersection(record["blockers"])
    assert not record["omitted_formula_slots"].get(slot)
    assert record["proof_ready"] is True
    tables = build_document_export_tables_from_ir([norm])
    assert tables["repair_queue"] == []


@pytest.mark.parametrize("slot", ["conditions", "exceptions"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("identity", ["duplicate-probe", None])
def test_colliding_or_missing_source_ids_cannot_borrow_another_rows_readiness(slot, reverse, identity):
    capped = source_element(slot)
    control = extract_normative_elements("The Director shall issue a permit.")[0]

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

    rows = [replace_identity(capped), replace_identity(control)]
    if reverse:
        rows.reverse()
    before = deepcopy(rows)
    projected = rows
    for _ in range(3):
        projected = parser_elements_for_metrics(projected)
        assert len(projected) == 2
        for row in projected:
            if row["text"] == capped["text"]:
                assert_active_projection(row, MARKERS[slot], metric=True)
            else:
                assert row["text"] == control["text"]
                ready = row["export_readiness"]
                assert ready["formula_proof_ready"] is True
                assert ready["formula_repair_required"] is False
                assert not set(MARKERS.values()).intersection(ready["formula_blockers"])
                assert row["active_repair_required"] is False
    assert rows == before
