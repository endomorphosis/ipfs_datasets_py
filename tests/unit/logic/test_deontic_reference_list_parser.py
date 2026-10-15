"""Citation list punctuation never substitutes generated text for source spans."""

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (
    extract_condition_details,
    extract_cross_reference_details,
    extract_exception_details,
    extract_normative_elements,
    extract_override_clause_details,
)


def assert_exact(source, records):
    for record in records:
        start, end = record["span"]
        assert 0 <= start < end <= len(source)
        assert source[start:end] == record["raw_text"]
        if "clause_span" in record:
            clause_start, clause_end = record["clause_span"]
            assert 0 <= clause_start <= start < end <= clause_end <= len(source)


@pytest.mark.parametrize("body", [
    "sections 552,\t553, and 554",
    "sections 552,\n553, and 554",
    "section 552,   section 553, and section 554",
])
@pytest.mark.parametrize("family", ["condition", "exception"])
def test_original_whitespace_and_member_offsets_are_preserved(body, family):
    source = (f"Préambule. Subject to {body}, the Secretary shall publish notice." if family == "condition"
              else f"Préambule. Except as provided in {body}, the Secretary shall publish notice.")
    details = (extract_condition_details if family == "condition" else extract_exception_details)(source)
    expected = body if family == "condition" else "as provided in " + body
    assert len(details) == 1
    assert details[0]["raw_text"] == expected
    refs = extract_cross_reference_details(source)
    assert [item["value"] for item in refs] == ["552", "553", "554"]
    assert_exact(source, details + refs)
    assert "shall" not in source[slice(*details[0]["clause_span"])]


@pytest.mark.parametrize("notation", ["5 U.S.C. sections", "5 U.S.C. §§", "5 USC §", "12 USC"])
def test_qualified_list_members_keep_their_title_namespace(notation):
    source = f"Subject to {notation} 552, 553, and 554, the Secretary shall publish notice."
    refs = extract_cross_reference_details(source)
    title = notation.split()[0]
    assert [(item["type"], item["value"]) for item in refs] == [
        ("usc", f"{title} {value}") for value in ("552", "553", "554")
    ]
    conditions = extract_condition_details(source)
    assert conditions[0]["raw_text"] == f"{notation} 552, 553, and 554"
    assert_exact(source, refs + conditions)


@pytest.mark.parametrize("intro,slot", [("Subject to", "conditions"), ("Except as provided in", "exceptions")])
def test_outer_parentheses_do_not_truncate_citation_subsections(intro, slot):
    body = "sections 552(a), 553(b), and 554(c)"
    source = f"({intro} {body}), the Secretary shall publish notice."
    row, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(row)
    expected = body if slot == "conditions" else "as provided in " + body
    assert [item["raw_text"] for item in getattr(norm, slot)] == [expected]
    assert norm.actor == "Secretary"
    assert norm.action == "publish notice"
    assert_exact(norm.source_text, getattr(norm, slot) + norm.cross_references)


@pytest.mark.parametrize("tail", ["10 days after notice", "10 dollars", "10 applicants", "2026 applications"])
def test_numeric_prose_is_retained_but_does_not_become_an_inherited_member(tail):
    body = f"sections 552, 553, and {tail}"
    source = f"Subject to {body}, the Secretary shall publish notice."
    row, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.conditions[0]["raw_text"] == body
    assert [item["value"] for item in norm.cross_references] == ["552", "553"]
    assert norm.action == "publish notice"
    assert_exact(norm.source_text, norm.conditions + norm.cross_references)


def test_single_reference_duration_tail_cannot_clear_using_only_first_reference():
    body = "section 552, 30 days after notice"
    source = f"Subject to {body}, the Secretary shall publish notice."
    row, = extract_normative_elements(source)
    row["resolved_cross_references"] = [{"reference_type": "section", "target": "552", "same_document": True}]
    norm = LegalNormIR.from_parser_element(row)
    assert norm.conditions[0]["raw_text"] == body
    assert norm.action == "publish notice"
    assert [item["value"] for item in norm.cross_references] == ["552"]
    assert build_deontic_formula_record_from_ir(norm)["proof_ready"] is False


@pytest.mark.parametrize("source", [
    "Subject to approval, the Secretary shall publish notice.",
    "The Secretary shall publish notice on January 2, 2026.",
    "Subject to 3 applications, the Secretary shall publish notice.",
])
def test_unrelated_commas_and_dates_do_not_create_reference_lists(source):
    assert extract_cross_reference_details(source) == []
    if source.startswith("Subject"):
        detail, = extract_condition_details(source)
        assert detail["raw_text"] == source.split("Subject to ")[1].split(",")[0]
        assert_exact(source, [detail])


@pytest.mark.parametrize("intro,extractor", [("Subject to", extract_condition_details),
                                            ("Notwithstanding", extract_override_clause_details)])
def test_range_inventory_remains_a_range_without_invented_interior_members(intro, extractor):
    source = f"{intro} sections 552 through 554, the Secretary shall publish notice."
    detail, = extractor(source)
    assert detail["raw_text"] == "sections 552 through 554"
    refs = extract_cross_reference_details(source)
    assert [(item["type"], item["value"]) for item in refs] == [("section_range", "552-554")]
    assert_exact(source, refs + [detail])


@pytest.mark.parametrize("kind", ["chapter", "title"])
def test_numeric_nonsection_lists_preserve_the_explicit_kind(kind):
    source = f"Subject to {kind}s 12, 13, and 14, the Secretary shall publish notice."
    refs = extract_cross_reference_details(source)
    assert [(item["type"], item["value"]) for item in refs] == [(kind, str(value)) for value in (12, 13, 14)]
    assert_exact(source, refs)
