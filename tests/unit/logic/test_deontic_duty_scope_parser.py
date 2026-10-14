"""Source-coordinate and enrichment ownership for explicit semicolon duties."""

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    _explicit_duty_scope_ranges,
    _finalize_element,
    analyze_normative_sentence,
    extract_normative_elements,
)


def assert_local_records(row, value):
    if isinstance(value, dict):
        if value.get("raw_text") is not None and isinstance(value.get("span"), list):
            start, end = value["span"]
            scope_start, scope_end = row["support_span"]
            assert scope_start <= start < end <= scope_end
            assert row["text"][start:end] == value["raw_text"]
        for item in value.values():
            assert_local_records(row, item)
    elif isinstance(value, list):
        for item in value:
            assert_local_records(row, item)


@pytest.mark.parametrize("separator", ["; ", "; and ", ";\tAND\t"])
def test_scope_helper_selects_exact_original_clause_slices(separator):
    left = "The Secretary shall publish notice"
    right = "the Clerk must retain records"
    source = left + separator + right
    scopes = _explicit_duty_scope_ranges(source)
    assert [source[start:end] for start, end in scopes] == [left, right]
    rows = analyze_normative_sentence(source, "statute")
    assert len(rows) == 2
    assert [row["text"] for row in rows] == [source, source]
    assert [row["support_span"] for row in rows] == [list(scope) for scope in scopes]
    assert [row["support_text"] for row in rows] == [left, right]
    assert all(row["slot_details_scoped"] for row in rows)


@pytest.mark.parametrize("source", [
    "If approved, the Secretary shall publish notice; the Clerk shall retain records.",
    "Except during emergencies, the Secretary shall publish notice; the Clerk shall retain records.",
    "The Secretary shall publish notice; or the Clerk shall retain records.",
    "The Secretary shall publish notice; and shall retain records.",
    "The Secretary shall publish notice; records remain available.",
    "The Secretary shall (unless approval is granted publish notice; the Clerk shall retain records.",
    'The Secretary shall display "notice; the Clerk shall retain records".',
    "The Secretary shall (unless the Clerk objects; the Director concurs) publish notice.",
    "The Secretary shall publish notice and the Clerk shall retain records.",
])
def test_ambiguous_or_unsupported_scope_abstains_without_inventing_ranges(source):
    assert _explicit_duty_scope_ranges(source) == []


@pytest.mark.parametrize("prefix,slot,body", [
    ("if funding is available, ", "conditions", "funding is available"),
    ("subject to approval, ", "conditions", "approval"),
    ("except as provided in section 552, ", "exceptions", "as provided in section 552"),
])
def test_right_hand_leading_qualifier_has_local_source_ownership(prefix, slot, body):
    source = f"The Secretary shall publish notice; {prefix}the Clerk shall retain records."
    rows = extract_normative_elements(source)
    assert len(rows) == 2
    norms = [LegalNormIR.from_parser_element(row) for row in rows]
    assert getattr(norms[0], slot) == []
    assert [item["raw_text"] for item in getattr(norms[1], slot)] == [body]
    for row in rows:
        assert_local_records(row, [row["condition_details"], row["exception_details"], row["cross_reference_details"]])


def test_repeated_operative_text_uses_each_dutys_actual_occurrence():
    rows = extract_normative_elements("The Secretary shall publish notice; the Clerk shall publish notice.")
    assert len(rows) == 2
    assert len({row["source_id"] for row in rows}) == 2
    for row in rows:
        assert row["text"][slice(*row["field_spans"]["action"])] == "publish notice"
    assert rows[0]["field_spans"]["action"][1] < rows[1]["field_spans"]["action"][0]


def test_repeated_finalization_does_not_restore_a_neighbors_money_or_penalty():
    rows = extract_normative_elements("The Secretary shall publish notice; the Clerk must pay a fine of $100.")
    assert len(rows) == 2
    for _ in range(3):
        rows = [_finalize_element(deepcopy(row)) for row in rows]
        assert rows[0]["monetary_amounts"] == []
        assert rows[0]["penalty"] == {}
        assert rows[0]["legal_frame"]["category"] != "penalty"
        assert len(rows[1]["monetary_amount_details"]) == 1
        assert len(rows[1]["penalty"]["monetary_amount_details"]) == 1
        assert_local_records(rows[1], [rows[1]["monetary_amount_details"], rows[1]["penalty"]])


@pytest.mark.parametrize("owner", [0, 1])
def test_procedure_and_temporal_source_spans_remain_local_after_finalization(owner):
    clauses = ["The Bureau shall inspect the premises", "the Clerk shall retain records"]
    clauses[owner] += " within 10 days after receipt of an application"
    rows = extract_normative_elements("; ".join(clauses) + ".")
    assert len(rows) == 2
    for _ in range(2):
        rows = [_finalize_element(deepcopy(row)) for row in rows]
        other = rows[1 - owner]
        assert other["temporal_constraint_details"] == []
        assert other["procedure"] == {}
        assert rows[owner]["temporal_constraint_details"]
        assert_local_records(rows[owner], [rows[owner]["temporal_constraint_details"], rows[owner]["procedure"]])


@pytest.mark.parametrize("body", [
    "unless approval is granted",
    "except as provided in sections 552(a), 553(b), and 554(c)",
])
def test_inline_exception_and_nested_citations_are_owned_by_one_duty(body):
    source = f"The Secretary shall ({body}) publish notice; the Clerk shall retain records."
    rows = extract_normative_elements(source)
    assert len(rows) == 2
    norms = [LegalNormIR.from_parser_element(row) for row in rows]
    assert [norm.action for norm in norms] == ["publish notice", "retain records"]
    assert norms[0].exceptions
    assert norms[1].exceptions == []
    assert norms[1].cross_references == []
    assert_local_records(rows[0], [rows[0]["exception_details"], rows[0]["cross_reference_details"]])


def test_parenthesized_semicolon_inside_exception_does_not_create_an_extra_duty():
    source = "The Secretary shall (unless the Clerk objects; the Director concurs) publish notice; the Registrar shall retain records."
    scopes = _explicit_duty_scope_ranges(source)
    assert len(scopes) == 2
    rows = extract_normative_elements(source)
    assert [row["subject"] for row in rows] == [["Secretary"], ["Registrar"]]
    assert rows[0]["exception_details"][0]["raw_text"] == "the Clerk objects; the Director concurs"
    assert rows[1]["exception_details"] == []
