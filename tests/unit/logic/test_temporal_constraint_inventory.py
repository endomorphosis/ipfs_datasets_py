"""Lossless temporal parser inventory, without models or native builds."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def parser():
    path = (
        Path(__file__).resolve().parents[3]
        / "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py"
    )
    spec = importlib.util.spec_from_file_location("temporal_inventory_parser", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("sentence", ["", "The clerk shall file a report."])
def test_empty_inventory_keeps_the_legacy_empty_result(parser, sentence):
    assert parser.extract_temporal_constraint_inventory(sentence) == {
        "schema_version": "legal-temporal-constraint-inventory/v1",
        "retained": [],
        "excluded": [],
        "containers": [],
    }
    assert parser.extract_temporal_constraint_details(sentence) == []


def test_retained_details_keep_complete_legacy_values_and_pattern_order(parser):
    sentence = (
        "The clerk shall file within 3 days after receipt, "
        "and report by June 1 annually."
    )
    expected = [
        {
            "type": "deadline",
            "temporal_kind": "by_date",
            "value": "june 1",
            "anchor": "",
            "quantity": None,
            "unit": "",
            "calendar": "",
            "anchor_event": "",
            "direction": "",
            "raw_text": "by June 1",
            "normalized_text": "june 1",
            "span": [61, 70],
        },
        {
            "type": "deadline",
            "temporal_kind": "within_duration",
            "value": "within 3 days after receipt",
            "anchor": "receipt",
            "quantity": 3,
            "unit": "day",
            "calendar": "calendar",
            "anchor_event": "receipt",
            "direction": "after",
            "raw_text": "within 3 days after receipt",
            "normalized_text": "within 3 days after receipt",
            "span": [21, 48],
        },
        {
            "type": "period",
            "temporal_kind": "annually",
            "value": "annually",
            "anchor": "",
            "quantity": None,
            "unit": "",
            "calendar": "",
            "anchor_event": "",
            "direction": "",
            "raw_text": "annually",
            "normalized_text": "annually",
            "span": [71, 79],
        },
    ]
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    assert inventory["retained"] == expected
    assert inventory["excluded"] == []
    assert inventory["containers"] == []
    assert parser.extract_temporal_constraint_details(sentence) == expected
    assert parser.extract_temporal_constraints(sentence) == [
        {"type": "deadline", "value": "june 1"},
        {"type": "deadline", "value": "within 3 days after receipt"},
        {"type": "period", "value": "annually"},
    ]


@pytest.mark.parametrize(
    "sentence,kind,clause_type,body,body_span,clause_span,temporal_span,anchor",
    [
        (
            "If the clerk files within 3 days after receipt, "
            "the agency shall act within 7 days after notice.",
            "condition",
            "if",
            "the clerk files within 3 days after receipt",
            [3, 46],
            [0, 47],
            [19, 46],
            "receipt",
        ),
        (
            "The clerk shall file within 7 days unless notice arrives within 3 days.",
            "exception",
            "unless",
            "notice arrives within 3 days",
            [42, 70],
            [35, 71],
            [57, 70],
            "",
        ),
    ],
)
def test_excluded_details_preserve_full_observation_and_container(
    parser, sentence, kind, clause_type, body, body_span, clause_span, temporal_span, anchor
):
    value = "within 3 days after receipt" if anchor else "within 3 days"
    container = {
        "kind": kind,
        "span": clause_span,
        "detail": {
            "type": kind,
            "clause_type": clause_type,
            "raw_text": body,
            "normalized_text": body,
            "span": body_span,
            "clause_span": clause_span,
        },
    }
    expected = {
        "detail": {
            "type": "deadline",
            "temporal_kind": "within_duration",
            "value": value,
            "anchor": anchor,
            "quantity": 3,
            "unit": "day",
            "calendar": "calendar",
            "anchor_event": anchor,
            "direction": "after" if anchor else "",
            "raw_text": value,
            "normalized_text": value,
            "span": temporal_span,
        },
        "containers": [container],
        "reason_codes": ["contained_in_condition_or_exception"],
    }
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    assert inventory["excluded"] == [expected]
    assert inventory["containers"] == [container]
    assert [item["quantity"] for item in inventory["retained"]] == [7]
    assert parser.extract_temporal_constraint_details(sentence) == inventory["retained"]


def test_containers_are_reported_even_without_temporal_observations(parser):
    sentence = "The clerk shall file if a permit exists unless an exemption applies."
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    assert inventory["retained"] == inventory["excluded"] == []
    assert inventory["containers"] == [
        {"kind": kind, "span": detail["clause_span"], "detail": detail}
        for kind, details in (
            ("condition", parser.extract_condition_details(sentence)),
            ("exception", parser.extract_exception_details(sentence)),
        )
        for detail in details
    ]
    assert [item["kind"] for item in inventory["containers"]] == ["condition", "exception"]


def test_nested_observation_reports_every_containing_clause(parser):
    sentence = (
        "If notice arrives within 3 days unless a review ends within 2 days, "
        "the agency shall act."
    )
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    assert inventory["retained"] == []
    first, nested = inventory["excluded"]
    assert first["detail"]["raw_text"] == "within 3 days"
    assert nested["detail"]["raw_text"] == "within 2 days"
    assert first["containers"] == inventory["containers"][:1]
    assert nested["containers"] == inventory["containers"]
    assert [item["kind"] for item in nested["containers"]] == ["condition", "exception"]
    assert nested["reason_codes"] == ["contained_in_condition_or_exception"]


def test_repeated_equal_text_keeps_both_source_positions(parser):
    sentence = "The clerk shall file within 3 days; the board shall respond within 3 days."
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    first, second = inventory["retained"]
    assert first["span"] == [21, 34]
    assert second["span"] == [60, 73]
    assert {key: value for key, value in first.items() if key != "span"} == {
        key: value for key, value in second.items() if key != "span"
    }
    assert inventory["excluded"] == []


def test_repeated_equal_text_can_be_retained_and_excluded(parser):
    sentence = "The clerk shall file within 3 days unless notice arrives within 3 days."
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    assert len(inventory["retained"]) == len(inventory["excluded"]) == 1
    retained, excluded = inventory["retained"][0], inventory["excluded"][0]["detail"]
    assert retained["raw_text"] == excluded["raw_text"] == "within 3 days"
    assert retained["span"] == [21, 34]
    assert excluded["span"] == [57, 70]


def test_distinct_observations_at_the_same_span_are_preserved(parser):
    sentence = (
        "The board shall act within 3 days after receipt or 7 days after notice "
        "whichever is earlier."
    )
    details = parser.extract_temporal_constraint_inventory(sentence)["retained"]
    assert [item["temporal_kind"] for item in details] == [
        "whichever_is_earlier", "within_duration"
    ]
    assert details[0]["span"] == details[1]["span"] == [20, 91]
    assert details[0]["raw_text"] == details[1]["raw_text"]
    assert details[0]["value"] != details[1]["value"]


@pytest.mark.parametrize("excluded", [False, True])
def test_unicode_offsets_preserve_exact_source_slice_and_stripped_raw_text(parser, excluded):
    prefix = "Préambule 👩🏽‍⚖️: "
    body = "if notice arrives " if excluded else "the clerk shall file "
    phrase = "within 3 days after réception  "
    sentence = prefix + body + phrase + "."
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    detail = inventory["excluded"][0]["detail"] if excluded else inventory["retained"][0]
    start, end = detail["span"]
    assert start == len(prefix + body)
    assert start != len((prefix + body).encode("utf-8"))
    assert end == start + len(phrase)
    assert sentence[start:end] == phrase
    assert detail["raw_text"] == phrase.strip()
    assert detail["raw_text"] != sentence[start:end]
    assert detail["anchor_event"] == "réception"
    assert parser.extract_temporal_constraint_details(sentence) == inventory["retained"]


def test_partial_overlap_keeps_the_legacy_full_containment_policy(parser):
    sentence = "If notice arrives by June 1, 2027, the agency shall act."
    inventory = parser.extract_temporal_constraint_inventory(sentence)
    assert inventory["excluded"] == []
    assert len(inventory["retained"]) == len(inventory["containers"]) == 1
    assert inventory["retained"][0]["span"] == [18, 33]
    assert inventory["containers"][0]["span"] == [0, 28]
    assert inventory["retained"][0]["raw_text"] == "by June 1, 2027"
