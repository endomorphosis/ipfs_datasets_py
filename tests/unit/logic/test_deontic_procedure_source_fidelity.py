"""Lexical procedure evidence must stay tied to the supplied source text."""

import pytest

from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_normative_elements,
    extract_procedure_details,
    extract_procedure_event_relations,
)


def _assert_source_spans(procedure, source):
    for record in procedure["event_mentions"] + procedure["event_relations"] + procedure["unresolved_event_relations"]:
        start, end = record["span"]
        assert 0 <= start < end <= len(source)
        assert source[start:end] == record["raw_text"]
    assert procedure["raw_text"] == source


def test_inspection_owns_receipt_trigger_and_before_approval_relation():
    source = (
        "Upon receipt of an application, the Bureau shall inspect the premises before approval."
    )
    element = extract_normative_elements(source)[0]
    procedure = element["procedure"]
    assert element["action"] == ["inspect the premises before approval"]
    assert procedure["events"] == ["application", "receipt", "inspection", "issuance"]
    assert [(item["event"], item["relation"], item["anchor_event"]) for item in procedure["event_relations"]] == [
        ("inspection", "triggered_by_receipt_of", "application"),
        ("receipt", "receives", "application"),
        ("inspection", "before", "issuance"),
    ]
    assert len(procedure["event_mentions"]) == 4
    assert procedure["trigger_event"] == "application"
    assert procedure["terminal_event"] == "inspection"
    _assert_source_spans(procedure, element["text"])


def test_whitespace_and_unicode_source_offsets_are_not_normalized_or_duplicated():
    source = "  À titre provisoire, the Bureau shall inspect the café before approval   .  "
    procedure = extract_procedure_details(source, "inspect the café before approval")
    assert len(procedure["event_mentions"]) == 2
    assert procedure["event_relations"][0]["raw_text"] == "before approval"
    _assert_source_spans(procedure, source)


@pytest.mark.parametrize(
    ("action", "owner"),
    [
        ("submit an application", "application"),
        ("receive documents", "receipt"),
        ("inspect the premises", "inspection"),
        ("conduct an inspection", "inspection"),
        ("review the report", "review"),
        ("investigate the complaint", "review"),
        ("provide written notice", "notice"),
        ("hold a hearing", "hearing"),
        ("make a determination", "decision"),
        ("issue a permit", "issuance"),
        ("renew the permit", "renewal"),
        ("suspend the permit", "suspension"),
        ("revoke the permit", "revocation"),
        ("appeal the order", ""),  # Two supported event types; ownership is ambiguous.
    ],
)
def test_only_supported_operative_event_constructions_receive_ordering(action, owner):
    source = f"The Bureau shall {action} before inspection."
    relations = extract_procedure_event_relations(source, action)
    expected = [] if not owner or owner == "inspection" else [(owner, "before", "inspection")]
    assert [(item["event"], item["relation"], item["anchor_event"]) for item in relations] == expected


@pytest.mark.parametrize(
    "action",
    [
        "record approval",
        "archive the inspection",
        "discuss the hearing",
        "adopt rules",
        "inspect the premises and approve the application",
        "revoke or suspend the permit",
    ],
)
def test_incidental_or_ambiguous_event_nouns_do_not_choose_an_owner(action):
    source = f"The Bureau shall {action} after notice."
    assert extract_procedure_event_relations(source, action) == []


@pytest.mark.parametrize("action", ["", "inspect the premises", "APPROVE the permit"])
def test_absent_action_evidence_does_not_fall_back_to_event_taxonomy(action):
    source = "The Bureau shall approve the permit after notice."
    assert extract_procedure_event_relations(source, action) == []


def test_action_cannot_add_events_or_spans_to_an_empty_source():
    assert extract_procedure_details("", "inspect the premises before approval") == {}
    assert extract_procedure_event_relations("", "inspect", ["inspection", "issuance"]) == []


def test_repeated_action_occurrences_are_not_arbitrarily_selected():
    source = "The Bureau shall inspect the premises before approval and inspect the premises after notice."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


@pytest.mark.parametrize("boundary", [". ", "; ", "\n", "? ", "! "])
def test_other_clause_connectors_do_not_attach_to_selected_action(boundary):
    source = (
        "The Bureau shall inspect the premises"
        + boundary
        + "The Clerk shall approve the permit after notice."
    )
    assert extract_procedure_event_relations(source, "inspect the premises") == []


@pytest.mark.parametrize("boundary", ["?", "!"])
@pytest.mark.parametrize("fronted", ["After notice", "Before approval"])
def test_fronted_previous_sentence_connector_does_not_attach_to_later_action(boundary, fronted):
    source = f"{fronted}{boundary} The Bureau shall inspect the premises."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


@pytest.mark.parametrize("boundary", ["?", "!"])
def test_previous_sentence_receipt_retains_only_its_independent_source_relation(boundary):
    source = f"Upon receipt of an application{boundary} The Bureau shall inspect the premises."
    relations = extract_procedure_event_relations(source, "inspect the premises")
    assert [(item["event"], item["relation"], item["anchor_event"]) for item in relations] == [
        ("receipt", "receives", "application")
    ]
    assert relations[0]["raw_text"] == "Upon receipt of an application"
    assert relations[0]["span"] == [0, 30]


@pytest.mark.parametrize("boundary", ["?", "!"])
def test_detached_following_sentence_connector_without_modal_does_not_attach(boundary):
    source = f"The Bureau shall inspect the premises{boundary} Before approval the Clerk reviews the report."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


def test_second_modal_in_same_clause_leaves_owner_unresolved():
    source = "The Bureau shall inspect the premises and the Clerk may approve the permit after notice."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


@pytest.mark.parametrize("joiner", [", while ", " and ", ", although "])
@pytest.mark.parametrize("include_following_clause_in_action", [False, True])
def test_nonmodal_intervening_actor_clause_does_not_own_selected_actions_ordering(
    joiner, include_following_clause_in_action
):
    action = "inspect the premises"
    following_clause = joiner + "the Clerk reviews the report before approval"
    source = "The Bureau shall " + action + following_clause + "."
    if include_following_clause_in_action:
        action += following_clause
    assert extract_procedure_event_relations(source, action) == []


def test_anchor_finite_clause_cannot_use_its_object_as_the_event():
    source = "The Bureau shall inspect the premises after the clerk approves the application."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


def test_direct_duration_gap_does_not_change_exact_connector_span():
    source = "The Bureau shall inspect the premises within 10 business days after notice."
    relations = extract_procedure_event_relations(source, "inspect the premises")
    assert [(item["event"], item["relation"], item["anchor_event"]) for item in relations] == [
        ("inspection", "after", "notice")
    ]
    assert relations[0]["raw_text"] == "after notice"
    start, end = relations[0]["span"]
    assert source[start:end] == "after notice"


@pytest.mark.parametrize("opening, closing", [('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"), ("(", ")"), ("[", "]")])
def test_quoted_or_parenthetical_connectors_do_not_claim_ordering(opening, closing):
    source = f"The Bureau shall inspect the premises marked {opening}before approval{closing}."
    assert extract_procedure_event_relations(source, "inspect the premises") == []
    procedure = extract_procedure_details(source, f"inspect the premises marked {opening}before approval{closing}")
    assert procedure["event_relations"] == []
    _assert_source_spans(procedure, source)


def test_quoted_action_is_not_the_operative_action():
    source = 'The label says "inspect the premises" before approval.'
    assert extract_procedure_event_relations(source, "inspect the premises") == []


def test_unrecognized_receipt_object_does_not_invent_receipt_self_relation():
    source = "Upon receipt of the documents, the Bureau shall inspect the premises."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


def test_independent_receipt_relation_can_remain_when_action_owner_is_unresolved():
    source = "Upon receipt of an application, the Bureau shall adopt rules."
    relations = extract_procedure_event_relations(source, "adopt rules")
    assert [(item["event"], item["relation"], item["anchor_event"]) for item in relations] == [
        ("receipt", "receives", "application")
    ]


def test_ambiguous_anchor_phrase_does_not_choose_alias_priority():
    source = "The Bureau shall inspect the premises after application approval."
    assert extract_procedure_event_relations(source, "inspect the premises") == []


def test_explicit_notice_and_hearing_anchors_remain_distinct():
    source = "The Bureau shall inspect the premises after notice and hearing."
    relations = extract_procedure_event_relations(source, "inspect the premises")
    assert [(item["event"], item["relation"], item["anchor_event"]) for item in relations] == [
        ("inspection", "after", "notice"), ("inspection", "after", "hearing")
    ]


@pytest.mark.parametrize("anchor", ["10 days", "one day", "30 business days", "2027-01-01", "May 1", "Monday", "5pm", "12:30", "noon", "tomorrow", "all"])
def test_scalar_and_date_anchors_do_not_create_procedure_objects(anchor):
    source = f"The Bureau shall issue a permit after {anchor}."
    assert extract_procedure_details(source, "issue a permit") == {}


@pytest.mark.parametrize("anchor", ["one inspection", "3 hearings", "all approvals", "Monday's inspection", "May 1 inspection"])
def test_quantified_or_dated_event_anchors_retain_unresolved_source_cues(anchor):
    source = f"The Bureau shall issue a permit after {anchor}."
    procedure = extract_procedure_details(source, "issue a permit")
    assert procedure["event_relations"] == []
    assert len(procedure["unresolved_event_relations"]) == 1
    assert procedure["unresolved_event_relations"][0]["raw_text"] == f"after {anchor}"
    _assert_source_spans(procedure, source)


def test_disjunctive_anchors_are_not_emitted_as_conjoined_ordering_relations():
    source = "The Bureau shall inspect the premises after notice or hearing."
    procedure = extract_procedure_details(source, "inspect the premises")
    assert procedure["event_relations"] == []
    assert procedure["unresolved_event_relations"][0]["reason"] == "disjunctive_anchor_requires_interpretation"


def test_single_event_unresolved_procedure_does_not_invent_trigger_or_terminal_roles():
    source = "The Bureau shall record approval after verification."
    procedure = extract_procedure_details(source, "record approval")
    assert procedure["events"] == ["issuance"]
    assert procedure["event_relations"] == []
    assert procedure["trigger_event"] == procedure["terminal_event"] == ""
    for item in procedure["unresolved_event_relations"]:
        assert set(item) == {"connector", "raw_text", "span", "reason", "interpretation_required"}
        assert item["interpretation_required"] is True
    _assert_source_spans(procedure, source)


_RETAINED_WAIVER_PARAGRAPH = (
    "(2) Not later than 10 days after the Secretary provides a waiver under paragraph (1), "
    "the Secretary shall submit to the Committee on Armed Services of the Senate and the "
    "Committee on Armed Services of the House of Representatives a written notice setting "
    "forth the reasoning for the waiver, together with a copy of the waiver itself."
)
_RETAINED_WAIVER_DECOMPILE = (
    "Secretary must submit to the Committee on Armed Services of the Senate and the Committee "
    "on Armed Services of the House of Representatives a written notice setting forth the "
    "reasoning for the waiver together with a copy of the waiver itself not later than 10 days "
    "after the secretary provides a waiver under paragraph (1)."
)
_RETAINED_HISTORICAL_NOTICE_COMMENT = (
    "Subsec. (d). Pub. L. 117–81, §851(a)(3), amended subsec. (d) generally. Prior to amendment, "
    'text read as follows: "Not later than May 1, 2022, the Secretary shall promulgate regulations, '
    'after an opportunity for notice and comment, implementing this section."'
)


@pytest.mark.parametrize("source", [_RETAINED_WAIVER_PARAGRAPH, _RETAINED_WAIVER_DECOMPILE, _RETAINED_HISTORICAL_NOTICE_COMMENT])
def test_retained_source_unresolved_procedure_keeps_canonical_compiler_abstention(source):
    # These retained 2024 source/decoder strings are regression evidence, not legal gold.
    from ipfs_datasets_py.logic import autoformal

    elements = extract_normative_elements(source)
    procedures = [element["procedure"] for element in elements if element["procedure"]]
    assert procedures
    assert any(procedure["unresolved_event_relations"] for procedure in procedures)
    for element in elements:
        if element["procedure"]:
            _assert_source_spans(element["procedure"], element["text"])
            assert element["procedure"]["event_relations"] == []
    compiled = autoformal.compile_span(autoformal.AutoformalSession(), source, "retained-unresolved-procedure")
    assert compiled["compiler_status"] == "abstain"
    assert compiled["reason"] == "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:procedure"
    assert compiled["admitted"] is False
