"""Immediate parenthetical exceptions preserve operative source coordinates."""

import pytest

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_exception_details,
    extract_normative_elements,
)


def norm_for(source):
    element, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(element)
    for record in norm.exceptions + norm.cross_references + norm.conditions:
        start, end = record["span"]
        assert 0 <= start < end <= len(norm.source_text)
        assert norm.source_text[start:end] == record["raw_text"]
    return element, norm


@pytest.mark.parametrize("modal,operator", [
    ("shall", "O"), ("must", "O"), ("may", "P"),
    ("shall not", "F"), ("must not", "F"), ("may not", "F"),
    ("is required to", "O"), ("is permitted to", "P"),
])
def test_immediate_unless_keeps_negation_and_exact_operative_action(modal, operator):
    source = f"The Secretary {modal} (unless approval is granted) publish notice."
    element, norm = norm_for(source)
    assert element["action"] == ["publish notice"]
    assert norm.action == "publish notice"
    assert norm.modality == operator
    assert norm.source_text[slice(*element["field_spans"]["action"])] == "publish notice"
    assert norm.source_text[slice(*element["field_spans"]["modal"])] == modal
    assert norm.exceptions[0]["raw_text"] == "approval is granted"
    assert norm.exceptions[0]["span"][1] < element["field_spans"]["action"][0]


@pytest.mark.parametrize("citation", [
    "section 552", "sections 552(a), 553(b), and 554(c)",
    "sections 5.01.020, 5.01.030, and 5.01.040",
])
def test_nested_citation_suffixes_do_not_end_the_outer_exception(citation):
    source = f"The Secretary shall (except as provided in {citation}) publish notice."
    element, norm = norm_for(source)
    assert element["action"] == ["publish notice"]
    assert norm.action == "publish notice"
    assert norm.exceptions[0]["raw_text"] == "as provided in " + citation
    clause = norm.exceptions[0]["clause_span"]
    assert norm.source_text[slice(*clause)] == f"except as provided in {citation})"
    assert norm.support_span.start <= clause[0] < clause[1] <= norm.support_span.end


@pytest.mark.parametrize("exception,body", [
    ("except during an emergency", "during an emergency"),
    ("except for temporary notices", "temporary notices"),
    ("unless approval is granted (in writing)", "approval is granted (in writing)"),
    ('unless the label reads "review (pending)"', 'the label reads "review (pending)"'),
    ("unless approval is granted, and notice is complete", "approval is granted, and notice is complete"),
    ("except during an emergency, as declared by the Director", "during an emergency, as declared by the Director"),
])
def test_substantive_exception_body_stays_exact_and_separate(exception, body):
    source = f"The Secretary shall ({exception}) publish notice."
    element, norm = norm_for(source)
    assert norm.action == "publish notice"
    assert norm.exceptions[0]["raw_text"] == body
    assert norm.source_text[slice(*element["field_spans"]["action"])] == "publish notice"


@pytest.mark.parametrize("tail", [
    "(unless approval is granted publish notice.",
    "(unless approval is granted) (except on holidays) publish notice.",
    "(unless approval is granted).",
    "(for the record) publish notice.",
    '("except as provided in section 552") publish notice.',
    "(“unless approval is granted”) publish notice.",
    "(except during an emergency unless the Director objects) publish notice.",
    "(unless approval is granted, except during an emergency) publish notice.",
])
def test_unsupported_parenthetical_forms_are_not_silently_deleted(tail):
    element, norm = norm_for("The Secretary shall " + tail)
    assert norm.action != "publish notice"
    assert norm.source_text[slice(*element["field_spans"]["action"])].startswith("(")


def test_quoted_norm_does_not_enable_parenthetical_action_repair():
    element, norm = norm_for('"The Secretary shall (except as provided in section 552) publish notice."')
    assert norm.action != "publish notice"
    assert "(except" in norm.source_text[slice(*element["field_spans"]["action"])]


def test_later_parenthetical_is_not_removed_by_the_immediate_modal_rule():
    element, norm = norm_for("The Secretary shall publish (except as provided in section 552) notice.")
    assert norm.action != "publish notice"
    assert "(except" in norm.source_text[slice(*element["field_spans"]["action"])]


def test_following_condition_does_not_enter_the_repaired_action_span():
    element, norm = norm_for(
        "The Secretary shall (unless approval is denied) publish notice if the application is complete."
    )
    assert norm.action == "publish notice"
    assert norm.conditions[0]["raw_text"] == "the application is complete"
    assert norm.exceptions[0]["raw_text"] == "approval is denied"
    assert norm.source_text[slice(*element["field_spans"]["action"])] == "publish notice"


def test_direct_nested_exception_span_uses_the_matching_outer_parenthesis():
    source = "The Secretary shall (unless approval is granted (in writing)) publish notice."
    exception, = extract_exception_details(source)
    assert exception["raw_text"] == "approval is granted (in writing)"
    assert source[slice(*exception["span"])] == exception["raw_text"]
    assert source[slice(*exception["clause_span"])] == "unless approval is granted (in writing))"


@pytest.mark.parametrize("exception,body", [
    ("unless approval is granted", "approval is granted"),
    ("except as provided in this section", "as provided in this section"),
])
def test_whitespace_inside_outer_parenthesis_does_not_absorb_the_action(exception, body):
    element, norm = norm_for(f"The Secretary shall (  {exception}  ) publish notice.")
    assert norm.action == "publish notice"
    assert [item["raw_text"] for item in norm.exceptions] == [body]
    assert norm.source_text[slice(*element["field_spans"]["action"])] == "publish notice"
