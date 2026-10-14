"""Fictional actual-source boundaries for immediate inline exceptions.

No completed parser slots are injected. These checks concern exact extraction
and conservative formula readiness, not authoritative legal interpretations.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def parsed(source):
    row, = extract_normative_elements(source)
    return row, LegalNormIR.from_parser_element(row)


def assert_source_span(text, span, expected):
    assert isinstance(span, (list, tuple)) and len(span) == 2
    start, end = span
    assert type(start) is type(end) is int
    assert 0 <= start < end <= len(text)
    assert text[start:end] == expected


def assert_operative_action(row, norm, action):
    assert norm.action == action
    assert row["action"] == [action]
    assert_source_span(row["text"], row["field_spans"]["action"], action)
    assert norm.actor == "Secretary"
    for record in norm.conditions + norm.exceptions + norm.cross_references:
        assert_source_span(norm.source_text, record["span"], record["raw_text"])


def assert_exception(norm, raw_text, action):
    assert norm.exceptions
    match, = [record for record in norm.exceptions if record["raw_text"] == raw_text]
    assert_source_span(norm.source_text, match["span"], raw_text)
    start, end = match["clause_span"]
    assert 0 <= start < end <= len(norm.source_text)
    assert raw_text in norm.source_text[start:end]
    assert end <= norm.field_spans["action"][0]


@pytest.mark.parametrize("modal,operator", [
    ("shall", "O"), ("must", "O"), ("may", "P"), ("is required to", "O"),
])
@pytest.mark.parametrize("clause,body", [
    ("unless approval is granted", "approval is granted"),
    ("except during an emergency", "during an emergency"),
])
def test_balanced_immediate_exception_preserves_action_and_modal(modal, operator, clause, body):
    action = "publish the notice"
    row, norm = parsed(f"The Secretary {modal} ({clause}) {action}.")
    assert_operative_action(row, norm, action)
    assert_exception(norm, body, action)
    assert norm.modality == operator
    assert_source_span(row["text"], row["field_spans"]["modal"], modal)
    before = deepcopy(norm)
    formula = build_deontic_formula_record_from_ir(norm)
    assert "PublishNotice(x)" in formula["formula"]
    assert "Unless" not in formula["formula"]
    assert "Except" not in formula["formula"]
    assert "formula_inline_exception_action_unresolved" not in formula["blockers"]
    assert norm == before


@pytest.mark.parametrize("body", [
    "as provided in section 552(a)",
    "as provided in section 552(a)(1)",
    "as provided in sections 552(a), 553(b), and 554(c)",
])
def test_nested_reference_parentheses_do_not_end_the_exception_early(body):
    action = "publish the notice"
    row, norm = parsed(f"The Secretary shall (except {body}) {action}.")
    assert_operative_action(row, norm, action)
    assert_exception(norm, body, action)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is False
    assert "formula_reference_exception_unresolved" in result["blockers"]
    assert result["deterministic_resolution"] == {}
    assert "PublishNotice(x)" in result["formula"]


def test_nested_nonreference_parenthesis_is_kept_inside_exception_text():
    body = "the Director approves (in writing)"
    row, norm = parsed(f"The Secretary shall (unless {body}) publish the notice.")
    assert_operative_action(row, norm, "publish the notice")
    assert_exception(norm, body, "publish the notice")


@pytest.mark.parametrize("modal", ["shall not", "must not", "may not", "cannot"])
def test_negative_modal_keeps_prohibition_and_positive_operative_action(modal):
    action = "disclose the record"
    row, norm = parsed(f"The Secretary {modal} (unless approval is granted) {action}.")
    assert_operative_action(row, norm, action)
    assert norm.modality == "F"
    assert_source_span(row["text"], row["field_spans"]["modal"], modal)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["formula"].startswith("F(")
    assert "DiscloseRecord(x)" in result["formula"]
    assert "formula_inline_exception_action_unresolved" not in result["blockers"]


def test_negation_after_the_parenthesis_remains_in_the_exact_action():
    action = "not disclose the record"
    row, norm = parsed(f"The Secretary shall (unless approval is granted) {action}.")
    assert_operative_action(row, norm, action)
    assert norm.modality == "O"
    assert_source_span(row["text"], row["field_spans"]["modal"], "shall")
    result = build_deontic_formula_record_from_ir(norm)
    assert "NotDiscloseRecord(x)" in result["formula"] or "¬DiscloseRecord(x)" in result["formula"]


@pytest.mark.parametrize("clause,body", [
    ("unless approval is granted", "approval is granted"),
    ("except as provided in section 552", "as provided in section 552"),
])
def test_postfix_condition_remains_separate_from_action_and_inline_exception(clause, body):
    row, norm = parsed(
        f"The Secretary shall ({clause}) publish the notice if funding is available."
    )
    assert_operative_action(row, norm, "publish the notice")
    assert_exception(norm, body, "publish the notice")
    condition, = norm.conditions
    assert condition["raw_text"] == "funding is available"
    assert_source_span(norm.source_text, condition["span"], "funding is available")
    if "section" in body:
        result = build_deontic_formula_record_from_ir(norm)
        assert result["proof_ready"] is False
        assert "formula_reference_exception_unresolved" in result["blockers"]


def test_inline_reference_list_and_postfix_substantive_exception_both_survive():
    body = "as provided in sections 552, 553, and 554"
    row, norm = parsed(
        f"The Secretary shall (except {body}) publish the notice unless funding is unavailable."
    )
    assert_operative_action(row, norm, "publish the notice")
    assert_exception(norm, body, "publish the notice")
    assert {item["raw_text"] for item in norm.exceptions} == {body, "funding is unavailable"}
    assert {"552", "553", "554"}.issubset({item.get("value") for item in norm.cross_references})
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is False
    assert "formula_reference_exception_unresolved" in result["blockers"]


def test_inner_modal_in_exception_does_not_create_an_independent_norm():
    body = "the Director may grant a waiver"
    row, norm = parsed(f"The Secretary shall (unless {body}) publish the notice.")
    assert_operative_action(row, norm, "publish the notice")
    assert_exception(norm, body, "publish the notice")
    assert norm.modality == "O"
    assert_source_span(row["text"], row["field_spans"]["modal"], "shall")


def test_repeated_action_words_inside_exception_do_not_steal_the_operative_span():
    action = "publish the notice"
    body = "the Director orders the Secretary to publish the notice"
    row, norm = parsed(f"The Secretary shall (unless {body}) {action}.")
    assert_operative_action(row, norm, action)
    assert_exception(norm, body, action)
    first_occurrence = row["text"].index(action)
    last_occurrence = row["text"].rindex(action)
    assert first_occurrence < last_occurrence
    assert row["field_spans"]["action"] == [last_occurrence, last_occurrence + len(action)]


@pytest.mark.parametrize("tail", [
    "(subject to approval) publish the notice",
    "(for administrative purposes) publish the notice",
    "(without written approval) publish the notice",
    "() publish the notice",
    "(unless approval is granted publish the notice",
    "(unless approval is granted)) publish the notice",
    '"(unless approval is granted)" publish the notice',
    "(unless approval is granted) (except during an emergency) publish the notice",
    "(unless approval is granted) (for administrative purposes) publish the notice",
])
def test_unsupported_or_malformed_parentheticals_are_not_silently_removed(tail):
    row, norm = parsed(f"The Secretary shall {tail}.")
    assert norm.action == tail
    assert_source_span(row["text"], row["field_spans"]["action"], tail)


def test_later_position_parenthetical_is_not_treated_as_immediate_interrupter():
    action = "publish (unless approval is granted) the notice"
    row, norm = parsed(f"The Secretary shall {action}.")
    assert norm.action == action
    assert_source_span(row["text"], row["field_spans"]["action"], action)


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("tail", [
    "(unless approval is granted publish the notice",
    "(unless approval is granted)) publish the notice",
    "(unless approval is granted) (except during an emergency) publish the notice",
    "(except as provided in section 552)",
    "(unless approval is granted)",
])
def test_recognized_unsupported_interrupter_cannot_borrow_saved_clearance(tail, cached):
    _, norm = parsed(f"The Secretary shall {tail}.")
    if cached:
        norm = replace(norm, quality=replace(
            norm.quality,
            parser_warnings=[],
            promotable_to_theorem=True,
            export_readiness={
                "blockers": [], "formula_proof_ready": True,
                "formula_requires_validation": False, "formula_repair_required": False,
                "deterministic_resolution": {
                    "type": "source_grounded_reconstruction_warning_bundle", "resolved_blockers": [],
                },
            },
        ))
        assert norm.proof_ready is True
    before = deepcopy(norm)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is False
    assert result["requires_validation"] is result["repair_required"] is True
    assert result["deterministic_resolution"] == {}
    assert "formula_inline_exception_action_unresolved" in result["blockers"]
    assert norm == before


@pytest.mark.parametrize("alias", ["value", "normalized_text", "text"])
def test_exception_semantic_alias_must_agree_with_its_exact_source_body(alias):
    row, = extract_normative_elements(
        "The Secretary shall (unless approval is granted) publish the notice."
    )
    exception, = row["exception_details"]
    exception[alias] = "a different event occurs"
    norm = LegalNormIR.from_parser_element(row)
    assert_operative_action(row, norm, "publish the notice")
    assert_exception(norm, "approval is granted", "publish the notice")
    before = deepcopy(norm)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is False
    assert result["requires_validation"] is result["repair_required"] is True
    assert result["deterministic_resolution"] == {}
    assert "formula_inline_exception_action_unresolved" in result["blockers"]
    assert norm == before


@pytest.mark.parametrize("bad_first", [False, True])
def test_valid_duplicate_cannot_hide_conflicting_alias_for_the_same_exception_span(bad_first):
    row, = extract_normative_elements(
        "The Secretary shall (unless approval is granted) publish the notice."
    )
    good, = row["exception_details"]
    bad = deepcopy(good)
    bad["value"] = "a different event occurs"
    row["exception_details"] = [bad, good] if bad_first else [good, bad]
    norm = LegalNormIR.from_parser_element(row)
    assert len(norm.exceptions) == 2
    assert_operative_action(row, norm, "publish the notice")
    before = deepcopy(norm)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is False
    assert result["requires_validation"] is result["repair_required"] is True
    assert result["deterministic_resolution"] == {}
    assert "formula_inline_exception_action_unresolved" in result["blockers"]
    assert norm == before


@pytest.mark.parametrize("separator", [". ", "\n", ".\n"])
def test_recovered_action_does_not_absorb_a_separate_norm(separator):
    rows = extract_normative_elements(
        "The Secretary shall (unless approval is granted) publish the notice"
        + separator + "The Clerk shall file the report."
    )
    assert len(rows) == 2
    first, second = [LegalNormIR.from_parser_element(row) for row in rows]
    assert_operative_action(rows[0], first, "publish the notice")
    assert_exception(first, "approval is granted", "publish the notice")
    assert second.actor == "Clerk"
    assert second.action == "file the report"
    assert second.exceptions == []


def test_semicolon_boundary_does_not_produce_a_clean_merged_action():
    rows = extract_normative_elements(
        "The Secretary shall (unless approval is granted) publish the notice; "
        "the Clerk shall file the report."
    )
    assert rows
    secretary = [row for row in rows if LegalNormIR.from_parser_element(row).actor == "Secretary"]
    assert secretary
    for row in secretary:
        norm = LegalNormIR.from_parser_element(row)
        if norm.action.startswith("publish"):
            assert norm.action == "publish the notice"
            assert_source_span(row["text"], row["field_spans"]["action"], "publish the notice")
        else:
            # Legacy semicolon splitting is a separate limitation. Abstention
            # must retain the unrecognized interrupter, not clean a merged duty.
            assert "(unless approval is granted)" in norm.action
