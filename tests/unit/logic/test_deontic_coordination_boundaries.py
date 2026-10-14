"""Fictional adversarial boundaries for repeated-modal alternative readiness.

These assertions reject independent-duty proof clearance for an unresolved
source alternative. They neither assign alternative semantics nor endorse
legacy outputs for excluded grammar.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR, SourceSpan
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    _unresolved_duty_disjunction_groups,
    extract_normative_elements,
)

MARKER = "formula_coordination_scope_unresolved"


def formula_for(source):
    return [build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(row))
            for row in extract_normative_elements(source)]


def cleared(norm):
    return replace(norm, quality=replace(norm.quality, parser_warnings=[],
        promotable_to_theorem=True, export_readiness={
            "proof_ready": True, "formula_proof_ready": True,
            "formula_requires_validation": False, "formula_repair_required": False,
            "blockers": [], "formula_blockers": [],
            "deterministic_resolution": {"type": "core_slots_complete"},
        }))


def assert_blocked(norm):
    before = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert MARKER in record["blockers"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    assert norm == before


@pytest.mark.parametrize("source", [
    "The Secretary shall publish the notice or shall file the report.",
    "The Secretary shall publish the notice or the Clerk shall file the report.",
    "The Secretary shall publish the notice, or the Clerk shall file the report.",
    "The Secretary shall publish the notice; or the Clerk shall file the report.",
    "The Secretary shall not disclose the record or the Clerk may publish the notice.",
    "The Secretary is required to publish the notice or the Clerk is authorized to file the report.",
    "The Secretary shall publish the notice or the Clerk shall file the report or the Registrar shall record the decision.",
    'The Secretary shall display "The Officer shall file the report" or shall retain the notice.',
    "If approval is granted, the Secretary shall publish the notice or shall file the report.",
    "The Secretary shall publish the notice or shall file the report if approval is granted.",
])
def test_covered_source_alternatives_cannot_be_cleared_as_independent_duties(source):
    rows = extract_normative_elements(source)
    assert rows
    for row in rows:
        assert_blocked(LegalNormIR.from_parser_element(row))
        assert_blocked(cleared(LegalNormIR.from_parser_element(row)))


@pytest.mark.parametrize("source", [
    '"The Secretary shall publish the notice or shall file the report."',
    'The Secretary shall display "publish the notice or shall file the report".',
    'The Secretary shall display “The Clerk shall file or the Officer shall record” and retain the notice.',
    "The Secretary shall display 'The Clerk shall file or the Officer shall record' and retain the notice.",
    "The Secretary shall (unless the Director may grant or may deny approval) publish the notice.",
    "The Secretary shall display [The Clerk shall file or the Officer shall record] and retain the notice.",
    "The Secretary shall display {The Clerk shall file or the Officer shall record} and retain the notice.",
    "The Secretary shall publish the notice if the Clerk shall file or the Officer shall record.",
    "The Secretary shall publish the notice or file the report if the Clerk shall approve the notice.",
    "The Secretary shall publish the notice unless the Clerk may file or the Officer may record.",
    "The Secretary shall publish the notice or the report.",
    "The Secretary shall publish the notice except as provided in sections 552 or 553.",
    "The Secretary shall publish the notice or the report; the Clerk shall file the record.",
    'The Secretary shall display "or the Clerk shall file the report"; the Registrar shall retain the notice.',
    "The Secretary shall publish the notice; the Clerk shall file the report.",
    "The Secretary shall publish the notice and shall file the report.",
    "The Secretary shall publish the notice or file the report.",
])
def test_object_citation_quoted_nested_and_subordinate_alternatives_are_not_claimed(source):
    assert _unresolved_duty_disjunction_groups(source) == []
    records = formula_for(source)
    assert records
    assert all(MARKER not in record["blockers"] for record in records)


@pytest.mark.parametrize("prefix", [True, False])
def test_legacy_action_containing_alternative_is_blocked_even_when_modal_is_an_independent_neighbor(prefix):
    neighbor = "The Registrar shall record the decision"
    alternative = "The Secretary shall publish the notice or the Clerk shall file the report"
    source = "; ".join([neighbor, alternative] if prefix else [alternative, neighbor]) + "."
    rows = extract_normative_elements(source)
    assert len(rows) == 1
    assert "or the Clerk shall" in LegalNormIR.from_parser_element(rows[0]).action
    assert_blocked(cleared(LegalNormIR.from_parser_element(rows[0])))


@pytest.mark.parametrize("mutation", [
    "missing_fields", "missing_modal", "forged_modal", "missing_support", "wrong_actor",
    "cleaned_action", "empty_action", "wrong_operator", "unbound_fields",
])
def test_source_alternative_cannot_be_hidden_by_cached_or_missing_core_evidence(mutation):
    row = extract_normative_elements("The Secretary shall publish the notice or shall file the report.")[0]
    norm = cleared(LegalNormIR.from_parser_element(row))
    fields = deepcopy(norm.field_spans)
    updates = {}
    if mutation == "missing_fields":
        fields = {}
    elif mutation == "missing_modal":
        fields.pop("modal", None)
    elif mutation == "forged_modal":
        fields["modal"] = list(fields["action"])
    elif mutation == "missing_support":
        updates.update(support_span=SourceSpan(0, 0), support_text="")
    elif mutation == "wrong_actor":
        updates["actor"] = "Clerk"
    elif mutation == "cleaned_action":
        updates["action"] = "publish the notice"
    elif mutation == "empty_action":
        updates["action"] = ""
    elif mutation == "wrong_operator":
        updates["modality"] = "P"
    elif mutation == "unbound_fields":
        fields = {key: [1000, 1001] for key in fields}
    updates["field_spans"] = fields
    assert_blocked(replace(norm, **updates))


def test_distinct_sentence_neighbor_does_not_inherit_alternative_blocker():
    rows = extract_normative_elements(
        "The Secretary shall publish the notice or shall file the report. "
        "The Registrar shall record the decision."
    )
    norms = [LegalNormIR.from_parser_element(row) for row in rows]
    assert [norm.actor for norm in norms] == ["Secretary", "Secretary", "Registrar"]
    assert_blocked(norms[0])
    assert_blocked(norms[1])
    assert MARKER not in build_deontic_formula_record_from_ir(norms[2])["blockers"]


@pytest.mark.parametrize("position", ["before", "after", "both"])
def test_top_level_semicolon_bounds_source_group_before_independent_duties(position):
    alternative = "The Secretary shall publish the notice or the Clerk shall file the report"
    before = "The Registrar shall record the decision; " if position in {"before", "both"} else ""
    after = "; the Officer shall retain the record" if position in {"after", "both"} else ""
    source = before + alternative + after + "."
    groups = _unresolved_duty_disjunction_groups(source)
    assert len(groups) == 1
    group = groups[0]
    assert group["raw_text"] == source[slice(*group["span"])]
    assert "Registrar" not in group["raw_text"]
    assert "Officer" not in group["raw_text"]
    assert len(group["members"]) == 2
    for member in group["members"]:
        assert member["raw_text"] == source[slice(*member["span"])]
        assert member["modal_raw_text"] == source[slice(*member["modal_span"])]
        assert group["span"][0] <= member["span"][0] < member["span"][1] <= group["span"][1]
    assert [source[slice(*item["span"])] for item in group["connectors"]] == ["or"]


@pytest.mark.parametrize("source", [
    "The Secretary shall publish notice or report and the Clerk shall file the record.",
    "The Secretary shall publish notice or a report, and the Clerk shall file the record.",
    "The Secretary shall publish notice or the report and shall file the record.",
    "The Secretary shall publish notice or the report but the Clerk shall file the record.",
    "The Secretary shall publish notice or the Clerk and the Officer shall file the record.",
])
def test_object_alternative_before_a_later_duty_and_coordinated_actor_are_outside_profile(source):
    assert _unresolved_duty_disjunction_groups(source) == []
    assert all(MARKER not in result["blockers"] for result in formula_for(source))


def bind_individual_source_row(full_source, clause):
    """Construct a cached local row with exact evidence in a larger source.

    This is a guard mutation test, separate from actual parser-source replay.
    """
    norm = LegalNormIR.from_parser_element(extract_normative_elements(clause + ".")[0])
    source = full_source.rstrip(".")
    start = source.index(clause)
    fields = {key: [start + value[0], start + value[1]] if len(value) == 2 else deepcopy(value)
              for key, value in norm.field_spans.items()}
    return cleared(replace(norm, source_text=source, source_span=SourceSpan(0, len(source)),
        support_span=SourceSpan(start, start + len(clause)), support_text=clause,
        field_spans=fields))


@pytest.mark.parametrize("source,clause", [
    ("The Secretary shall publish notice or the Clerk shall file the report and the Officer shall retain the record.",
     "the Officer shall retain the record"),
    ("The Secretary shall publish notice and the Clerk shall file the report or the Officer shall retain the record.",
     "The Secretary shall publish notice"),
])
def test_mixed_and_or_duty_cannot_be_cleared_without_a_precedence_model(source, clause):
    norm = bind_individual_source_row(source, clause)
    assert norm.source_text[slice(*norm.field_spans["action"])] == norm.action
    assert norm.source_text[norm.support_span.start:norm.support_span.end] == clause
    assert_blocked(norm)


@pytest.mark.parametrize("source,clause", [
    ("The Secretary shall publish notice or the Clerk shall file the report; the Officer shall retain the record.",
     "the Officer shall retain the record"),
    ("The Secretary shall publish notice; the Clerk shall file the report or the Officer shall retain the record.",
     "The Secretary shall publish notice"),
])
def test_independent_semicolon_neighbor_with_exact_core_evidence_remains_outside_alternative(source, clause):
    norm = bind_individual_source_row(source, clause)
    assert norm.source_text[slice(*norm.field_spans["action"])] == norm.action
    assert MARKER not in build_deontic_formula_record_from_ir(norm)["blockers"]
