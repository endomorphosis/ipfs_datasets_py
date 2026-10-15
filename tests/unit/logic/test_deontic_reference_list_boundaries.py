"""Actual-source reference-list boundaries, without completed-slot injection.

The prose is fictional. Resolution records are explicit caller declarations,
not assertions about legal applicability or the contents of referenced law.
"""

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


LISTS = [
    ("sections 552, 553", ("552", "553")),
    ("sections 552, and 553", ("552", "553")),
    ("sections 552, or 553", ("552", "553")),
    ("sections 552, 553, and 554", ("552", "553", "554")),
    ("sections 552, 553 or 554", ("552", "553", "554")),
    ("sections 552, 553, or 554", ("552", "553", "554")),
    ("sections 552, 553, 554", ("552", "553", "554")),
    ("sections 552a, 553b, and 554c", ("552a", "553b", "554c")),
    ("sections 5.01.020, 5.01.030, and 5.01.040", ("5.01.020", "5.01.030", "5.01.040")),
    ("sections 12-3, 12-4, and 12-5", ("12-3", "12-4", "12-5")),
    ("sections 552(a), 552(b), and 552(c)", ("552(a)", "552(b)", "552(c)")),
    ("section 552, section 553, and section 554", ("552", "553", "554")),
]


def sentence(family, citation):
    if family == "condition":
        return f"Subject to {citation}, the Secretary shall publish the notice."
    return f"The Secretary shall publish the notice except as provided in {citation}."


def declared_reference(target):
    return {
        "reference_type": "section", "target": target,
        "canonical_citation": "section " + target,
        "same_document": True, "resolution_scope": "same_document",
        "resolved_source_id": "fictional-caller-declared-section-" + target,
    }


def check_source_records(norm):
    for record in norm.conditions + norm.exceptions + norm.cross_references:
        start, end = record["span"]
        assert type(start) is type(end) is int
        assert 0 <= start < end <= len(norm.source_text)
        assert norm.source_text[start:end] == record["raw_text"]


def parsed(source):
    row, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(row)
    check_source_records(norm)
    return row, norm


def reference_qualifier(norm, family, expected):
    records = getattr(norm, family + "s")
    assert records
    matches = [item for item in records if item["raw_text"] == expected]
    assert len(matches) == 1
    item = matches[0]
    clause_start, clause_end = item["clause_span"]
    start, end = item["span"]
    assert clause_start <= start < end <= clause_end <= len(norm.source_text)
    assert " shall " not in norm.source_text[clause_start:clause_end].lower()
    return item


def formula_with_metadata(row, targets):
    declared = deepcopy(row)
    declared["resolved_cross_references"] = [declared_reference(target) for target in targets]
    norm = LegalNormIR.from_parser_element(declared)
    before = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert norm == before
    return record


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("citation,targets", LISTS)
def test_source_list_is_complete_and_only_complete_metadata_clears_readiness(family, citation, targets):
    row, norm = parsed(sentence(family, citation))
    expected = citation if family == "condition" else "as provided in " + citation
    reference_qualifier(norm, family, expected)
    assert norm.actor == "Secretary"
    assert norm.action == "publish the notice"
    values = {item.get("value") for item in norm.cross_references}
    assert set(targets).issubset(values)
    marker = "formula_reference_" + family + "_unresolved"
    results = [formula_with_metadata(row, supplied) for supplied in ((), targets[:1], targets)]
    for record in results[:2]:
        assert record["proof_ready"] is False
        assert record["requires_validation"] is record["repair_required"] is True
        assert marker in record["blockers"]
        assert record["deterministic_resolution"] == {}
    assert results[2]["proof_ready"] is True
    assert results[2]["requires_validation"] is False
    assert marker not in results[2]["blockers"]
    assert len({record["formula"] for record in results}) == 1


@pytest.mark.parametrize("citation", ["sections 552, 553", "sections 552, 553, and 554"])
def test_fronted_exception_stops_before_the_operative_actor(citation):
    _, norm = parsed(f"Except as provided in {citation}, the Secretary shall publish the notice.")
    reference_qualifier(norm, "exception", "as provided in " + citation)
    assert norm.actor == "Secretary"
    assert norm.action == "publish the notice"


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("body", [
    "approval under sections 552, 553, and 554",
    "sections 552, 553, and 554 as amended",
])
def test_substantive_text_beside_list_is_retained_and_not_cleared_as_pure_reference(family, body):
    row, norm = parsed(sentence(family, body))
    expected = body if family == "condition" else "as provided in " + body
    reference_qualifier(norm, family, expected)
    record = formula_with_metadata(row, ("552", "553", "554"))
    assert record["proof_ready"] is False
    assert "formula_reference_" + family + "_unresolved" in record["blockers"]


@pytest.mark.parametrize("family,tail,substantive", [
    ("condition", " if approval is granted", "approval is granted"),
    ("exception", ", unless publication is prohibited", "publication is prohibited"),
])
def test_separate_substantive_qualifier_is_not_absorbed_into_reference_list(family, tail, substantive):
    citation = "sections 552, 553, and 554"
    row, norm = parsed(sentence(family, citation)[:-1] + tail + ".")
    expected = citation if family == "condition" else "as provided in " + citation
    reference_qualifier(norm, family, expected)
    assert any(item["raw_text"] == substantive for item in getattr(norm, family + "s"))
    result = formula_with_metadata(row, ("552", "553", "554"))
    assert result["proof_ready"] is False


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("body", ["approval", "written approval", "section 552"])
def test_non_list_comma_still_ends_the_qualifier(family, body):
    if family == "condition":
        source = f"Subject to {body}, the Secretary shall publish the notice."
    else:
        source = f"Except as provided in {body}, the Secretary shall publish the notice."
    _, norm = parsed(source)
    expected = body if family == "condition" else "as provided in " + body
    reference_qualifier(norm, family, expected)
    assert norm.action == "publish the notice"


@pytest.mark.parametrize("body,targets,numeric_tail", [
    ("sections 552, 553, and 10 days after notice", ("552", "553"), "10"),
    ("section 552, 30 days after notice", ("552",), "30"),
])
def test_numeric_prose_after_comma_is_not_an_inherited_reference_or_ready_prefix(body, targets, numeric_tail):
    row, norm = parsed(sentence("condition", body))
    assert all(item.get("value") != numeric_tail for item in norm.cross_references)
    result = formula_with_metadata(row, targets)
    assert result["proof_ready"] is False
    assert result["requires_validation"] is True


@pytest.mark.parametrize("modal", ["shall", "must", "may", "are required to", "are authorized to", "are permitted to"])
def test_numbered_operative_actor_is_not_an_inherited_reference(modal):
    citation = "sections 552, 553, and 554"
    _, norm = parsed(f"Subject to {citation}, 3 agencies {modal} publish the notice.")
    reference_qualifier(norm, "condition", citation)
    assert all(item.get("value") != "3" for item in norm.cross_references)
    assert norm.action == "publish the notice"
    assert "agencies" in norm.actor


def test_repeated_list_in_separate_norms_keeps_each_occurrence_source_bound():
    source = (
        "Subject to sections 552, 553, and 554, the Secretary shall publish the notice. "
        "Subject to sections 552, 553, and 554, the Clerk shall file the report."
    )
    rows = extract_normative_elements(source)
    assert len(rows) == 2
    norms = [LegalNormIR.from_parser_element(row) for row in rows]
    for norm in norms:
        check_source_records(norm)
        reference_qualifier(norm, "condition", "sections 552, 553, and 554")
    assert [norm.action for norm in norms] == ["publish the notice", "file the report"]


@pytest.mark.parametrize("separator", [". ", "\n", ".\n"])
def test_reference_list_does_not_attach_to_a_later_unqualified_norm(separator):
    rows = extract_normative_elements(
        "Subject to sections 552, 553, and 554, the Secretary shall publish the notice"
        + separator + "The Clerk shall file the report."
    )
    assert len(rows) == 2
    first, second = [LegalNormIR.from_parser_element(row) for row in rows]
    reference_qualifier(first, "condition", "sections 552, 553, and 554")
    assert second.conditions == []
    assert second.exceptions == []
    assert second.action == "file the report"


@pytest.mark.parametrize("family,cue", [
    ("condition", "Subject to"), ("exception", "Except as provided in"),
])
def test_semicolon_ends_reference_body_before_the_operative_clause(family, cue):
    citation = "sections 552, 553, and 554"
    _, norm = parsed(f"{cue} {citation}; the Secretary shall publish the notice.")
    expected = citation if family == "condition" else "as provided in " + citation
    item = reference_qualifier(norm, family, expected)
    assert norm.source_text[item["span"][1]] == ";"
    assert norm.action == "publish the notice"
