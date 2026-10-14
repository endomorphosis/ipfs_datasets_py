"""Cached clearances cannot merge or exchange independently scoped duties."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.exports import (
    build_document_export_tables_from_ir,
    parser_elements_for_metrics,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR, SourceSpan
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


SOURCE = (
    "The Secretary shall publish notice; the Clerk shall file the report "
    "unless approval is denied."
)
MARKER = "formula_duty_scope_unresolved"


def cached_quality(norm):
    return replace(norm.quality, promotable_to_theorem=True, export_readiness={
        **norm.quality.export_readiness,
        "proof_ready": True, "formula_proof_ready": True,
        "formula_requires_validation": False, "formula_repair_required": False,
        "deterministic_resolution": {"type": "core_slots_complete"},
    })


def assert_blocked(norm):
    original = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert MARKER in record["blockers"]
    assert record["proof_ready"] is False
    assert record["requires_validation"] is record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    tables = build_document_export_tables_from_ir([norm])
    for name in ("canonical", "formal_logic", "proof_obligations"):
        assert MARKER in tables[name][0]["blockers"]
        assert tables[name][0]["proof_ready"] is False
    for name in ("decoder_reconstructions", "prover_syntax_summaries"):
        assert tables[name][0]["proof_ready"] is False
        assert tables[name][0]["requires_validation"] is True
    assert MARKER in tables["repair_queue"][0]["reasons"]
    assert norm == original


@pytest.mark.parametrize("mutation", [
    "merged_action", "merged_support", "wrong_support_text", "missing_modal", "nonmodal_span",
    "foreign_modal_alias", "missing_action_span", "noninteger_action_span",
    "wrong_action", "wrong_actor", "foreign_subject_span", "foreign_exception",
    "spanless_exception", "missing_own_exception", "wrong_own_exception",
    "forged_own_exception_span", "duplicate_wrong_exception",
])
def test_current_duty_scope_overrides_cached_clearance(mutation):
    first, second = [LegalNormIR.from_parser_element(row) for row in extract_normative_elements(SOURCE)]
    assert [norm.actor for norm in (first, second)] == ["Secretary", "Clerk"]
    assert all(build_deontic_formula_record_from_ir(norm)["proof_ready"] for norm in (first, second))
    norm = second if mutation in {
        "missing_own_exception", "wrong_own_exception", "forged_own_exception_span",
        "duplicate_wrong_exception",
    } else first
    updates = {"quality": cached_quality(norm)}
    fields = deepcopy(norm.field_spans)
    if mutation == "merged_action":
        fields["action"][1] = second.field_spans["action"][1]
        updates["action"] = norm.source_text[slice(*fields["action"])]
    elif mutation == "merged_support":
        updates["support_span"] = SourceSpan(0, len(norm.source_text))
        updates["support_text"] = norm.source_text
    elif mutation == "wrong_support_text":
        updates["support_text"] = second.support_text
    elif mutation == "missing_modal":
        fields.pop("modal")
    elif mutation == "nonmodal_span":
        fields["modal"] = fields["action_verb"]
    elif mutation == "foreign_modal_alias":
        fields["modality"] = second.field_spans["modal"]
    elif mutation == "missing_action_span":
        fields.pop("action")
    elif mutation == "noninteger_action_span":
        fields["action"] = [float(value) for value in fields["action"]]
    elif mutation == "wrong_action":
        updates["action"] = "withhold notice"
    elif mutation == "wrong_actor":
        updates["actor"] = "Clerk"
    elif mutation == "foreign_subject_span":
        fields["subject"] = second.field_spans["subject"]
    elif mutation in {"foreign_exception", "spanless_exception"}:
        updates["exceptions"] = deepcopy(second.exceptions)
        if mutation == "spanless_exception":
            updates["exceptions"][0].pop("span")
    elif mutation == "missing_own_exception":
        updates["exceptions"] = []
    else:
        exceptions = deepcopy(second.exceptions)
        if mutation == "wrong_own_exception":
            exceptions[0]["value"] = "approval is granted"
        elif mutation == "forged_own_exception_span":
            exceptions[0]["span"] = list(first.field_spans["action"])
            exceptions[0]["raw_text"] = first.action
        else:
            wrong = deepcopy(exceptions[0])
            wrong["value"] = "approval is granted"
            exceptions.append(wrong)
        updates["exceptions"] = exceptions
    updates["field_spans"] = fields
    assert_blocked(replace(norm, **updates))


@pytest.mark.parametrize("suffix,slot", [
    (" if funding is available", "conditions"),
    (" unless approval is denied", "exceptions"),
    (" within 30 days after receipt of notice", "temporal_constraints"),
    (" except as provided in section 552", "cross_references"),
])
def test_dropped_local_qualifiers_cannot_be_cleared_by_cached_readiness(suffix, slot):
    source = "The Secretary shall publish notice; the Clerk shall file the report" + suffix + "."
    _, element = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(element)
    assert getattr(norm, slot)
    assert_blocked(replace(norm, **{slot: [], "quality": cached_quality(norm)}))


def test_metrics_cannot_restore_merged_action_clearance():
    first, second = extract_normative_elements(SOURCE)
    first["action"] = [first["text"][first["field_spans"]["action"][0]:second["field_spans"]["action"][1]]]
    first["field_spans"]["action"][1] = second["field_spans"]["action"][1]
    first["export_readiness"].update({
        "formula_proof_ready": True, "formula_requires_validation": False,
        "formula_repair_required": False,
        "deterministic_resolution": {"type": "core_slots_complete"},
    })
    original = deepcopy(first)
    rows = [first]
    for _ in range(3):
        rows = parser_elements_for_metrics(rows)
        ready = rows[0]["export_readiness"]
        assert MARKER in ready["formula_blockers"]
        assert ready["formula_proof_ready"] is False
        assert ready["metric_repair_required"] is True
        assert ready["deterministic_resolution"] == {}
        assert rows[0]["active_repair_required"] is True
    assert first == original
