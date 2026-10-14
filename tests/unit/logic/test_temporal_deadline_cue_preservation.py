"""Deadline polarity survives parser values, vocabulary and source-withheld output."""
from __future__ import annotations

import pytest

from ipfs_datasets_py.logic import autoformal
from ipfs_datasets_py.logic.deontic.utils import deontic_parser as parser


@pytest.mark.parametrize("cue,kind", [("Not later than", "not_later_than"),
                                     ("No later than", "no_later_than")])
@pytest.mark.parametrize("payload,quantity,unit", [
    ("10 days after receipt of notice", 10, "day"),
    ("2 weeks after delivery", 2, "week"),
    ("3 business days after receipt", 3, "day"),
])
def test_complete_relation_survives_all_parser_views(cue, kind, payload, quantity, unit):
    text = f"The agency shall file {cue} {payload}."
    detail, = parser.extract_temporal_constraint_details(text)
    expected = f"{cue.lower()} {payload}"
    assert detail["temporal_kind"] == kind
    assert detail["value"] == detail["normalized_text"] == expected
    assert detail["quantity"] == quantity and detail["unit"] == unit
    assert detail["anchor"] == detail["anchor_event"] == payload.split(" after ")[1]
    assert detail["direction"] == "after"
    assert text[slice(*detail["span"])] == detail["raw_text"] == f"{cue} {payload}"
    assert parser.extract_temporal_constraints(text) == [{"type": "deadline", "value": expected}]
    assert autoformal._temporal_records(text) == [{"temporal_kind": kind, "value": expected,
                                                  "quantity": quantity}]


@pytest.mark.parametrize("cue", ["NOT\tlater  than", "No\nlater\tthan"])
def test_whitespace_normalization_keeps_raw_offsets_and_explicit_anchor(cue):
    raw = cue + " 10\tdays\nafter\treceipt  of notice"
    text = "Préface: the agency shall file " + raw + "."
    detail, = parser.extract_temporal_constraint_details(text)
    assert detail["value"] == " ".join(raw.lower().split())
    assert detail["raw_text"] == raw
    assert text[slice(*detail["span"])] == raw
    assert detail["quantity"] == 10
    assert detail["anchor"] == detail["anchor_event"] == "receipt of notice"
    assert detail["direction"] == "after"


@pytest.mark.parametrize("cue", ["not later than", "no later than"])
def test_canonical_vocabulary_and_decompiler_keep_cue(cue):
    text = f"The agency shall file a report {cue} 10 days."
    value = f"{cue} 10 days"
    vocabulary = autoformal.vocabulary_from_clause(text)
    assert vocabulary["qualifiers"] == [value]
    session = autoformal.AutoformalSession()
    result = autoformal.compile_span(session, text, "deadline-cue")
    assert result["compiler_status"] == "compiled"
    assert result["rule"]["temporal"] == [value]
    assert value in result["decompiled"]
    assert result["admitted"] is False
    # Reparse the source-withheld output: the lexical relation cannot disappear.
    detail, = parser.extract_temporal_constraint_details(result["decompiled"])
    assert detail["value"] == value


@pytest.mark.parametrize("connector", ["if", "unless"])
def test_deadline_inside_condition_or_exception_stays_excluded(connector):
    text = f"The agency shall file {connector} notice arrives not later than 3 days after receipt."
    inventory = parser.extract_temporal_constraint_inventory(text)
    assert inventory["retained"] == []
    excluded, = inventory["excluded"]
    detail = excluded["detail"]
    assert detail["value"] == "not later than 3 days after receipt"
    assert detail["quantity"] == 3
    assert text[slice(*detail["span"])] == detail["raw_text"]
    assert excluded["reason_codes"] == ["contained_in_condition_or_exception"]


def test_repeated_deadlines_keep_separate_source_occurrences():
    phrase = "not later than 3 days after receipt"
    text = f"The agency shall file {phrase}; the board shall report {phrase}."
    details = parser.extract_temporal_constraint_details(text)
    assert len(details) == 2
    assert details[0]["value"] == details[1]["value"] == phrase
    assert details[0]["span"] != details[1]["span"]
    assert all(text[slice(*item["span"])] == phrase for item in details)


def test_similar_duration_kinds_are_not_relabelled_as_deadlines():
    details = parser.extract_temporal_constraint_details("The agency shall retain records for at least 10 days.")
    details += parser.extract_temporal_constraint_details("The agency shall file within 3 days.")
    assert {item["temporal_kind"]: item["value"] for item in details} == {
        "within_duration": "within 3 days", "minimum_duration": "10 days"}
