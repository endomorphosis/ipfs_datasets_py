"""Fictional source tests for the explicit semicolon duty-scope profile.

Bare conjunctions, disjunctions, and shared actors are outside this profile.
Assertions concern source ownership and readiness, not legal validity.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def checked_rows(source, expected_actors):
    rows = extract_normative_elements(source)
    norms = [LegalNormIR.from_parser_element(row) for row in rows]
    assert [norm.actor for norm in norms] == expected_actors
    assert all(row["text"] == rows[0]["text"] for row in rows)
    for row, norm in zip(rows, norms):
        support_start, support_end = row["support_span"]
        assert row["support_text"] == row["text"][support_start:support_end]
        start, end = row["field_spans"]["action"]
        assert support_start <= start < end <= support_end
        assert row["text"][start:end] == norm.action
        for item in norm.conditions + norm.exceptions + norm.temporal_constraints + norm.cross_references:
            start, end = item["span"]
            assert type(start) is type(end) is int
            assert support_start <= start < end <= support_end
            assert norm.source_text[start:end] == item["raw_text"]
    return rows, norms


def slot_texts(norm, slot):
    return [item["raw_text"] for item in getattr(norm, slot)]


@pytest.mark.parametrize("separator", ["; ", "; and "])
@pytest.mark.parametrize("first_modal,second_modal,operators", [
    ("shall", "shall", ["O", "O"]),
    ("shall not", "may", ["F", "P"]),
    ("is required to", "must", ["O", "O"]),
])
def test_explicit_semicolon_duties_keep_actor_modal_and_action_ownership(separator, first_modal, second_modal, operators):
    source = f"The Secretary {first_modal} publish the notice{separator}the Clerk {second_modal} file the report."
    rows, norms = checked_rows(source, ["Secretary", "Clerk"])
    assert [norm.action for norm in norms] == ["publish the notice", "file the report"]
    assert [norm.modality for norm in norms] == operators
    assert rows[0]["support_span"][1] <= rows[1]["support_span"][0]
    for norm in norms:
        result = build_deontic_formula_record_from_ir(norm)
        assert "formula_duty_scope_unresolved" not in result["blockers"]


@pytest.mark.parametrize("first_tail,second_tail,expected", [
    (" if approval is granted", "", [["approval is granted"], []]),
    ("", " if funding is available", [[], ["funding is available"]]),
    (" if approval is granted", " if funding is available", [["approval is granted"], ["funding is available"]]),
])
def test_postfix_conditions_belong_only_to_their_own_clause(first_tail, second_tail, expected):
    _, norms = checked_rows(
        f"The Secretary shall publish the notice{first_tail}; the Clerk shall file the report{second_tail}.",
        ["Secretary", "Clerk"],
    )
    assert [slot_texts(norm, "conditions") for norm in norms] == expected
    assert all(not norm.exceptions for norm in norms)


@pytest.mark.parametrize("first_tail,second_tail,expected", [
    (" unless approval is denied", "", [["approval is denied"], []]),
    ("", " unless funding is denied", [[], ["funding is denied"]]),
    (" unless approval is denied", " unless funding is denied", [["approval is denied"], ["funding is denied"]]),
])
def test_postfix_exceptions_belong_only_to_their_own_clause(first_tail, second_tail, expected):
    _, norms = checked_rows(
        f"The Secretary shall publish the notice{first_tail}; the Clerk shall file the report{second_tail}.",
        ["Secretary", "Clerk"],
    )
    assert [slot_texts(norm, "exceptions") for norm in norms] == expected
    assert all(not norm.conditions for norm in norms)


@pytest.mark.parametrize("owner", [0, 1])
def test_reference_list_and_unresolved_readiness_do_not_leak_to_the_neighbor(owner):
    actions = ["The Secretary shall publish the notice", "the Clerk shall file the report"]
    actions[owner] += " except as provided in sections 552, 553, and 554"
    _, norms = checked_rows("; ".join(actions) + ".", ["Secretary", "Clerk"])
    assert slot_texts(norms[owner], "exceptions") == ["as provided in sections 552, 553, and 554"]
    assert {item["value"] for item in norms[owner].cross_references} == {"552", "553", "554"}
    other = norms[1 - owner]
    assert other.exceptions == []
    assert other.cross_references == []
    blocked = build_deontic_formula_record_from_ir(norms[owner])
    assert blocked["proof_ready"] is False
    assert "formula_reference_exception_unresolved" in blocked["blockers"]
    assert "formula_reference_exception_unresolved" not in build_deontic_formula_record_from_ir(other)["blockers"]


def test_deadlines_and_procedure_mentions_stay_inside_their_own_support_span():
    rows, norms = checked_rows(
        "The Secretary shall publish the notice within 10 days after application; "
        "the Clerk shall file the report within 20 days after review.",
        ["Secretary", "Clerk"],
    )
    assert [slot_texts(norm, "temporal_constraints") for norm in norms] == [
        ["within 10 days after application"], ["within 20 days after review"],
    ]
    for row, expected_anchor in zip(rows, ["application", "review"]):
        support_start, support_end = row["support_span"]
        procedure = row["procedure"]
        # "File the report" has no recognized procedure operative event in
        # the standalone profile. Scope must not invent a resolved owner.
        assert procedure["trigger_event"] == ("application" if expected_anchor == "application" else "")
        assert any(item.get("event") == expected_anchor for item in procedure["event_mentions"])
        for key in ("event_mentions", "event_relations", "unresolved_event_relations"):
            for item in procedure.get(key, []):
                start, end = item["span"]
                assert support_start <= start < end <= support_end
                assert row["text"][start:end] == item["raw_text"]


@pytest.mark.parametrize("body", ["approval is granted", "the Director may grant a waiver"])
def test_inline_exception_and_its_inner_modal_stay_with_the_first_actor(body):
    _, norms = checked_rows(
        f"The Secretary shall (unless {body}) publish the notice; the Clerk shall file the report.",
        ["Secretary", "Clerk"],
    )
    assert [norm.action for norm in norms] == ["publish the notice", "file the report"]
    assert slot_texts(norms[0], "exceptions") == [body]
    assert norms[1].exceptions == []


@pytest.mark.parametrize("body", [
    "except as provided in section 552 unless approval is granted",
    "unless approval is granted, except during an emergency",
])
def test_nested_inline_exception_remains_blocked_without_leaking_to_the_second_duty(body):
    _, norms = checked_rows(
        f"The Secretary shall ({body}) publish the notice; the Clerk shall file the report.",
        ["Secretary", "Clerk"],
    )
    result = build_deontic_formula_record_from_ir(norms[0])
    assert result["proof_ready"] is False
    assert "formula_inline_exception_action_unresolved" in result["blockers"]
    assert norms[1].action == "file the report"
    assert norms[1].exceptions == []
    assert norms[1].cross_references == []


@pytest.mark.parametrize("first_action,second_action", [
    ('display "The Clerk shall file the report"', "record the notice"),
    ('display "notice; the Clerk shall file the report"', "record the notice"),
    ("publish the notice", 'display "The Officer must destroy the file"'),
])
def test_quoted_modals_and_semicolons_do_not_create_additional_duties(first_action, second_action):
    _, norms = checked_rows(
        f"The Secretary shall {first_action}; the Registrar shall {second_action}.",
        ["Secretary", "Registrar"],
    )
    assert [norm.action for norm in norms] == [first_action, second_action]


def test_three_explicit_duties_keep_three_distinct_source_scopes():
    rows, norms = checked_rows(
        "The Secretary shall publish the notice; the Clerk shall file the report; "
        "the Registrar shall record the decision.",
        ["Secretary", "Clerk", "Registrar"],
    )
    assert [norm.action for norm in norms] == ["publish the notice", "file the report", "record the decision"]
    assert all(left["support_span"][1] <= right["support_span"][0] for left, right in zip(rows, rows[1:]))


def test_repeated_action_text_binds_each_actor_to_its_own_occurrence():
    rows, norms = checked_rows(
        "The Secretary shall publish the notice; the Clerk shall publish the notice.",
        ["Secretary", "Clerk"],
    )
    assert [norm.action for norm in norms] == ["publish the notice", "publish the notice"]
    assert rows[0]["field_spans"]["action"][1] < rows[1]["field_spans"]["action"][0]


@pytest.mark.parametrize("source", [
    "Subject to approval, the Secretary shall publish the notice; the Clerk shall file the report.",
    "The Secretary shall publish the notice; or the Clerk shall file the report.",
    "The Secretary shall publish the notice; and shall file the report.",
    "The Secretary shall (unless approval is granted publish the notice; the Clerk shall file the report.",
])
def test_deferred_semicolon_grammar_is_not_claimed_by_the_scoped_profile(source):
    rows = extract_normative_elements(source)
    assert rows
    for row in rows:
        assert not row.get("duty_scope_span")
        assert row["text"] == source.rstrip(".")
        result = build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(row))
        assert "formula_duty_scope_unresolved" not in result["blockers"]
    # Existing readiness for these unsupported forms is not endorsed here.


@pytest.mark.parametrize("mutation", ["merged_action", "foreign_condition", "foreign_exception"])
@pytest.mark.parametrize("cached", [False, True])
def test_supported_scopes_reject_stale_merge_or_foreign_qualifier_even_with_cached_clearance(mutation, cached):
    tail = {"merged_action": "", "foreign_condition": " if approval is granted",
            "foreign_exception": " unless approval is denied"}[mutation]
    rows, _ = checked_rows(
        f"The Secretary shall publish the notice{tail}; the Clerk shall file the report.",
        ["Secretary", "Clerk"],
    )
    if mutation == "merged_action":
        row = deepcopy(rows[0])
        start = row["field_spans"]["action"][0]
        row["action"] = row["text"][start:]
        row["field_spans"]["action"] = [start, len(row["text"])]
    else:
        row = deepcopy(rows[1])
        field = "condition_details" if mutation == "foreign_condition" else "exception_details"
        row[field] = deepcopy(rows[0][field])
    norm = LegalNormIR.from_parser_element(row)
    if mutation == "foreign_condition":
        assert slot_texts(norm, "conditions") == ["approval is granted"]
    elif mutation == "foreign_exception":
        assert slot_texts(norm, "exceptions") == ["approval is denied"]
    else:
        assert "the Clerk shall file the report" in norm.action
    if cached:
        norm = replace(norm, quality=replace(
            norm.quality, parser_warnings=[], promotable_to_theorem=True,
            export_readiness={"blockers": [], "formula_proof_ready": True,
                              "formula_requires_validation": False,
                              "deterministic_resolution": {"type": "source_grounded_reconstruction_warning_bundle"}},
        ))
    before = deepcopy(norm)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is False
    assert result["requires_validation"] is result["repair_required"] is True
    assert result["deterministic_resolution"] == {}
    assert "formula_duty_scope_unresolved" in result["blockers"]
    assert norm == before


@pytest.mark.parametrize("connector", [" and ", " or ", ", or "])
def test_deferred_bare_conjunction_or_disjunction_is_not_newly_split_into_two_duties(connector):
    rows = extract_normative_elements(
        "The Secretary shall publish the notice" + connector + "the Clerk shall file the report."
    )
    # This preserves the declared profile boundary. It does not endorse legacy
    # formula readiness or claim that the unsplit text models disjunction.
    assert len(rows) == 1
    norm = LegalNormIR.from_parser_element(rows[0])
    assert "the Clerk shall file the report" in norm.action
