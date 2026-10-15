"""Unresolved alternative duties cannot acquire readiness through downstream exports."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir
from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
    parser_elements_with_ir_export_readiness,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR, SourceSpan
from ipfs_datasets_py.logic.deontic.metrics import summarize_parser_elements
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


MARKER = "formula_coordination_scope_unresolved"
WARNING = "disjunctive_duty_scope_unresolved"
ALTERNATIVES = [
    "The Secretary shall publish the notice or shall retain the record.",
    "The Secretary shall publish the notice or the Clerk shall retain the record.",
    "The Secretary shall publish the notice; or the Clerk shall retain the record.",
    "The Secretary shall not publish the notice or shall retain the record.",
    "The Secretary may publish the notice or shall retain the record.",
]


def clear_quality(norm):
    return replace(norm.quality, promotable_to_theorem=True, export_readiness={
        **norm.quality.export_readiness,
        "proof_ready": True, "formula_proof_ready": True,
        "formula_requires_validation": False, "formula_repair_required": False,
        "export_requires_validation": False, "export_repair_required": False,
        "deterministic_resolution": {"type": "core_slots_complete"},
    })


def assert_export_blocked(norm):
    original = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert MARKER in record["blockers"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    groups = record["coordination_scope_evidence"]
    assert groups
    for group in groups:
        assert norm.source_text[slice(*group["span"])] == group["raw_text"]
        assert group["connectors"] and len(group["members"]) >= 2
        for connector in group["connectors"]:
            assert norm.source_text[slice(*connector["span"])] == connector["raw_text"]
        for member in group["members"]:
            assert norm.source_text[slice(*member["span"])] == member["raw_text"]
            assert norm.source_text[slice(*member["modal_span"])] == member["modal_raw_text"]
    tables = build_document_export_tables_from_ir([norm])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        row, = tables[name]
        assert MARKER in row["blockers"]
        assert row["proof_ready"] is False
        assert row["requires_validation"] is True
    for name in ("decoder_reconstructions", "prover_syntax_summaries"):
        row, = tables[name]
        assert row["proof_ready"] is False
        assert row["requires_validation"] is True
    assert MARKER in tables["repair_queue"][0]["reasons"]
    # A deterministic reconstruction can retain branch text without qualifying
    # its interpretation. The export is the readiness-bearing decoder API.
    decoded = decode_legal_norm_ir(norm)
    assert tables["decoder_reconstructions"][0]["decoded_text"] == decoded.text
    assert tables["decoder_reconstructions"][0]["coordination_scope_evidence"] == groups
    assert decoded.source_id == norm.source_id
    assert decoded.support_span == norm.support_span.to_list()
    assert norm == original
    return tables


def assert_projection_blocked(row):
    readiness = row["export_readiness"]
    assert readiness["formula_proof_ready"] is False
    assert readiness["formula_requires_validation"] is True
    assert readiness["formula_repair_required"] is True
    assert readiness["export_requires_validation"] is True
    assert readiness["export_repair_required"] is True
    assert readiness["deterministic_resolution"] == {}
    assert MARKER in readiness["formula_blockers"]
    assert row["active_repair_required"] is True
    assert MARKER in row["active_repair_warnings"]
    assert row["llm_repair"]["allow_llm_repair"] is False


@pytest.mark.parametrize("source", ALTERNATIVES)
def test_alternative_duties_remain_unqualified_across_all_exports(source):
    elements = extract_normative_elements(source)
    assert elements
    original = deepcopy(elements)
    for element in elements:
        norm = LegalNormIR.from_parser_element(element)
        assert norm.source_text == element["text"] == source.rstrip(".")
        assert_export_blocked(norm)
        assert WARNING in norm.quality.parser_warnings
        assert WARNING in decode_legal_norm_ir(norm).parser_warnings
        for slot in ("subject", "modal", "action"):
            start, end = element["field_spans"][slot]
            assert type(start) is type(end) is int
            assert 0 <= start < end <= len(norm.source_text)
        assert norm.source_text[slice(*element["field_spans"]["action"])] == norm.action
    projected = parser_elements_for_metrics(elements)
    for row in projected:
        assert_projection_blocked(row)
        assert row["text"] == source.rstrip(".")
    assert summarize_parser_elements(projected)["repair_required_count"] == len(elements)
    assert elements == original


def test_typed_ir_without_parser_warning_still_has_source_recomputed_export_blocker():
    norm = LegalNormIR.from_parser_element(extract_normative_elements(ALTERNATIVES[0])[0])
    altered = replace(norm, quality=replace(clear_quality(norm), parser_warnings=[]))
    assert decode_legal_norm_ir(altered).parser_warnings == []
    assert_export_blocked(altered)


@pytest.mark.parametrize("source", ALTERNATIVES[:3])
def test_stale_clearances_cannot_survive_repeated_readiness_projection(source):
    elements = extract_normative_elements(source)
    for row in elements:
        row["active_repair_required"] = row["repair_required"] = False
        row["export_readiness"] = {
            **row.get("export_readiness", {}),
            "formula_proof_ready": True, "formula_requires_validation": False,
            "formula_repair_required": False, "export_requires_validation": False,
            "export_repair_required": False,
            "deterministic_resolution": {"type": "core_slots_complete"},
        }
        row["llm_repair"] = {
            **row.get("llm_repair", {}), "required": False,
            "deterministically_resolved": True,
            "deterministic_resolution": {"type": "core_slots_complete"},
        }
    original = deepcopy(elements)
    projected = parser_elements_with_ir_export_readiness(elements)
    for _ in range(3):
        projected = parser_elements_for_metrics(projected)
        for row in projected:
            assert_projection_blocked(row)
            assert row["text"] == source.rstrip(".")
    assert elements == original


@pytest.mark.parametrize("mutation", [
    "missing_modal_spans", "nonmodal_span", "empty_support", "foreign_support",
    "whole_source_support", "operator_permission", "operator_non_deontic",
])
def test_typed_ir_source_group_cannot_be_cleared_by_rewriting_span_or_modality_metadata(mutation):
    source = ALTERNATIVES[0]
    elements = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(elements[0])
    fields = deepcopy(norm.field_spans)
    updates = {"quality": clear_quality(norm)}
    if mutation == "missing_modal_spans":
        for key in ("modal", "modality", "deontic_operator"):
            fields.pop(key, None)
    elif mutation == "nonmodal_span":
        for key in ("modal", "modality", "deontic_operator"):
            fields[key] = fields["action"][:]
    elif mutation == "empty_support":
        updates.update(support_span=SourceSpan(0, 0), support_text="")
    elif mutation == "foreign_support":
        updates.update(support_span=SourceSpan(len(source) - 1, len(source)), support_text=".")
    elif mutation == "whole_source_support":
        updates.update(support_span=SourceSpan(0, len(source)), support_text=source)
    elif mutation == "operator_permission":
        updates.update(modality="P", norm_type="permission")
    elif mutation == "operator_non_deontic":
        updates.update(modality="DEF", norm_type="definition")
    assert_export_blocked(replace(norm, field_spans=fields, **updates))


@pytest.mark.parametrize("source", [
    "The Secretary shall publish the notice and shall retain the record.",
    "The Secretary shall publish the notice; the Clerk shall retain the record.",
    "The Secretary shall publish the notice if approval is granted or consent is granted.",
    "The Secretary shall publish the notice unless approval is denied or consent is revoked.",
    "The Secretary shall publish the notice or the record.",
])
def test_non_duty_disjunction_and_conjunctive_duties_do_not_acquire_group_blocker(source):
    elements = extract_normative_elements(source)
    assert elements
    for row in elements:
        norm = LegalNormIR.from_parser_element(row)
        assert MARKER not in build_deontic_formula_record_from_ir(norm)["blockers"]
        tables = build_document_export_tables_from_ir([norm])
        for name in ("canonical", "formal_logic", "proof_obligations"):
            assert MARKER not in tables[name][0]["blockers"]


def test_independent_third_duty_can_keep_source_bound_readiness():
    prefix = "The Secretary shall publish the notice; or the Clerk shall retain the record; "
    clause = "the Archivist shall preserve the file."
    source = prefix + clause
    element, = extract_normative_elements(clause)
    local = LegalNormIR.from_parser_element(element)
    offset = len(prefix)
    fields = {key: ([span[0] + offset, span[1] + offset] if len(span) == 2 else span)
              for key, span in local.field_spans.items()}
    norm = replace(local, source_text=source, field_spans=fields,
                   support_span=SourceSpan(local.support_span.start + offset,
                                           local.support_span.end + offset))
    original = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert MARKER not in record["blockers"]
    assert record["proof_ready"] is True
    tables = build_document_export_tables_from_ir([norm])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        assert tables[name][0]["proof_ready"] is True
        assert MARKER not in tables[name][0]["blockers"]
    assert tables["decoder_reconstructions"][0]["decoded_text"] == "Archivist shall preserve the file."
    assert tables["repair_queue"] == []
    assert norm == original


@pytest.mark.parametrize("procedure_shape", [
    "complete", "chain_only", "relations_only", "spanless_relation", "value_only",
    "wrong_raw_text", "wrong_local_span",
])
def test_alternative_procedure_cannot_leak_into_an_independent_duty_reconstruction(procedure_shape):
    first_clause = "The Secretary shall publish the notice after a hearing"
    prefix = first_clause + "; or the Clerk shall retain the record; "
    clause = "the Archivist shall preserve the file"
    source = prefix + clause
    local = LegalNormIR.from_parser_element(extract_normative_elements(clause + ".")[0])
    offset = len(prefix)
    fields = {key: ([span[0] + offset, span[1] + offset] if len(span) == 2 else span)
              for key, span in local.field_spans.items()}
    independent = replace(local, source_text=source, field_spans=fields,
                          support_span=SourceSpan(offset, len(source)),
                          source_span=SourceSpan(0, len(source)),
                          quality=clear_quality(local))
    baseline = build_deontic_formula_record_from_ir(independent)
    assert baseline["proof_ready"] is True
    assert MARKER not in baseline["blockers"]
    alternative = LegalNormIR.from_parser_element(extract_normative_elements(first_clause + ".")[0])
    procedure = deepcopy(alternative.procedure)
    assert procedure["event_relations"] and procedure["event_mentions"]
    if procedure_shape == "chain_only":
        procedure = {"event_chain": procedure["event_chain"]}
    elif procedure_shape == "relations_only":
        procedure = {"event_relations": procedure["event_relations"]}
    elif procedure_shape == "spanless_relation":
        relation = procedure["event_relations"][0]
        relation.pop("span")
        procedure = {"event_relations": [relation]}
    elif procedure_shape == "value_only":
        procedure = {"value": procedure["value"], "trigger_event": "hearing"}
    elif procedure_shape in {"wrong_raw_text", "wrong_local_span"}:
        relation = procedure["event_relations"][0]
        relation["span"] = fields["action"][:]
        if procedure_shape == "wrong_local_span":
            relation["raw_text"] = source[slice(*relation["span"])]
        procedure = {"event_relations": [relation]}
    altered = replace(independent, procedure=procedure)
    assert_export_blocked(altered)


@pytest.mark.parametrize("partial", [False, True])
def test_independent_duty_retains_its_own_procedure_occurrences(partial):
    from ipfs_datasets_py.logic.deontic.utils.deontic_parser import _offset_source_spans
    prefix = "The Secretary shall publish notice; or the Clerk shall retain the record; "
    clause = "the Archivist shall publish the notice after a hearing"
    source = prefix + clause
    element, = extract_normative_elements(clause + ".")
    local = LegalNormIR.from_parser_element(element)
    assert local.procedure["event_relations"]
    offset = len(prefix)
    fields = _offset_source_spans({"field_spans": local.field_spans}, offset)["field_spans"]
    procedure = _offset_source_spans(local.procedure, offset)
    if partial:
        procedure = {"event_relations": procedure["event_relations"]}
    norm = replace(local, source_text=source, field_spans=fields, procedure=procedure,
                   support_span=SourceSpan(offset, len(source)), source_span=SourceSpan(0, len(source)))
    record = build_deontic_formula_record_from_ir(norm)
    assert MARKER not in record["blockers"]
    assert record["proof_ready"] == build_deontic_formula_record_from_ir(local)["proof_ready"]
    assert "coordination_scope_evidence" not in record
