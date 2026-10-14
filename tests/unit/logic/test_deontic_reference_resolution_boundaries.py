"""Fictional source qualifiers and caller-declared resolution boundary checks.

Resolution metadata in these fixtures is an explicit caller claim. These tests
do not attest to the content, applicability, or authority of an actual law.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def element(family, citation="section 552", *, mixed=False):
    if family == "condition":
        source = f"Subject to {citation}, the Secretary shall publish the notice"
        source += " if notice is complete." if mixed else "."
    else:
        source = f"The Secretary shall publish the notice except as provided in {citation}"
        source += ", unless publication is impossible." if mixed else "."
    row, = extract_normative_elements(source)
    return row


def reference(target="552", kind="section", **changes):
    row = {"reference_type": kind, "target": target, "canonical_citation": f"{kind} {target}",
           "same_document": True, "resolution_scope": "same_document",
           "resolved_source_id": "fictional-caller-declared-target-" + target}
    row.update(changes)
    return row


def assert_source_backed_qualifier(norm, family, citation):
    records = getattr(norm, family + "s")
    assert records, "The qualifier must survive parser-to-IR before testing formula readiness."
    normalized_citation = citation.replace("U.S.C.", "USC")
    assert any(normalized_citation in record["raw_text"] for record in records)
    for slot in ("conditions", "exceptions"):
        for record in getattr(norm, slot):
            start, end = record["span"]
            assert norm.source_text[start:end] == record["raw_text"]
    return norm


def norm_from_row(row, family, citation="section 552"):
    return assert_source_backed_qualifier(LegalNormIR.from_parser_element(row), family, citation)


def assert_blocked(norm, family):
    before = deepcopy(norm)
    formula = build_deontic_formula_from_ir(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert record["proof_ready"] is False
    assert record["requires_validation"] is True
    assert record["repair_required"] is True
    assert record["deterministic_resolution"] == {}
    assert f"formula_reference_{family}_unresolved" in record["blockers"]
    assert record["formula"] == formula
    assert norm == before
    return record


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("citation", ["this section", "section 552", "sections 552 and 553"])
def test_pure_local_or_fully_covered_same_document_controls_remain_ready(family, citation):
    row = element(family, citation)
    row["resolved_cross_references"] = (
        [] if citation == "this section" else [reference(), reference("553")]
        if citation.startswith("sections ") else [reference()]
    )
    norm = norm_from_row(row, family, citation)
    before = deepcopy(norm)
    record = build_deontic_formula_record_from_ir(norm)
    assert record["proof_ready"] is True
    assert record["requires_validation"] is False
    assert not any(blocker.startswith("formula_reference_") for blocker in record["blockers"])
    assert norm == before


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("source_citation,target,kind", [
    ("section 552", "55", "section"),
    ("section 552", "5520", "section"),
    ("section 552", "553", "section"),
    ("section 552", "552(a)", "section"),
    ("section 552(a)", "552(b)", "section"),
    ("section 552", "552", "chapter"),
    ("chapter 552", "552", "section"),
])
def test_reference_matching_preserves_complete_identifier_and_kind(family, source_citation, target, kind):
    row = element(family, source_citation)
    row["resolved_cross_references"] = [reference(target, kind)]
    assert_blocked(norm_from_row(row, family, source_citation), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("targets", [("552",), ("553",), ("552", "552")])
def test_partial_plural_coverage_cannot_clear_the_whole_clause(family, targets):
    row = element(family, "sections 552 and 553")
    row["resolved_cross_references"] = [reference(target) for target in targets]
    assert_blocked(norm_from_row(row, family, "sections 552 and 553"), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("changes", [
    {"resolution_scope": "external"},
    {"document_scope": "other_document"},
    {"source_scope": "external_document"},
    {"scope": "external"},
    {"same_document": False},
    {"same_document": 1},
    {"same_document": "true"},
    {"resolved": False},
    {"resolved": 1},
    {"resolved": "true"},
    {"target_exists": False},
    {"target_exists": 1},
    {"target_exists": "true"},
    {"resolution_status": "unresolved"},
    {"resolution_status": "pending"},
    {"resolution_status": "failed"},
])
def test_contradictory_or_malformed_resolution_flags_do_not_clear_readiness(family, changes):
    row = element(family)
    row["resolved_cross_references"] = [reference(**changes)]
    assert_blocked(norm_from_row(row, family), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("key,value", [
    ("target", "553"), ("raw_text", "section 553"),
    ("value", "section 553"), ("normalized_text", "section 553"),
    ("citation", "section 553"), ("reference_type", "chapter"),
    ("type", "chapter"), ("subsection", "552"), ("reference_type", "garbage"),
])
def test_conflicting_citation_aliases_cannot_be_hidden_by_canonical_precedence(family, key, value):
    row = element(family)
    metadata = reference()
    metadata[key] = value
    row["resolved_cross_references"] = [metadata]
    assert_blocked(norm_from_row(row, family), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
def test_local_target_does_not_hide_explicit_external_or_numbered_metadata(family):
    row = element(family, "this section")
    row["resolved_cross_references"] = [reference(
        target="this", canonical_citation="section 553", resolution_scope="external"
    )]
    assert_blocked(norm_from_row(row, family, "this section"), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("changes", [
    {"same_document": False},
    {"resolved": False},
    {"target": "553"},
])
def test_local_placeholder_compatibility_does_not_hide_explicit_contradictions(family, changes):
    row = element(family, "this section")
    metadata = {"reference_type": "section", "target": "this", "canonical_citation": "this section"}
    metadata.update(changes)
    row["resolved_cross_references"] = [metadata]
    assert_blocked(norm_from_row(row, family, "this section"), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("cached_kind", [
    "source_grounded_reconstruction_warning_bundle",
    "resolved_same_document_reference_condition",
    "resolved_same_document_reference_exception",
    "compiler_guidance_deontic_ir_reconstruction",
])
def test_missing_resolution_cannot_be_waived_by_promoted_norm_or_saved_clearance(family, cached_kind):
    row = element(family, mixed=True)
    row["resolved_cross_references"] = []
    norm = norm_from_row(row, family)
    readiness = {**norm.quality.export_readiness, "blockers": [],
                 "formula_proof_ready": True, "formula_requires_validation": False,
                 "formula_repair_required": False,
                 "deterministic_resolution": {"type": cached_kind, "resolved_blockers": []}}
    norm = replace(norm, quality=replace(norm.quality, parser_warnings=[],
                                        promotable_to_theorem=True, export_readiness=readiness))
    assert norm.proof_ready is True
    assert_blocked(norm, family)


def test_two_exact_condition_references_can_use_evidence_from_both_record_containers():
    source = "Subject to section 552, subject to section 553, the Secretary shall publish the notice."
    row, = extract_normative_elements(source)
    row["resolved_cross_references"] = [reference()]
    marked = False
    for item in row["cross_reference_details"]:
        start, end = item["span"]
        assert row["text"][start:end] == item["raw_text"]
        if item["raw_text"] == "section 553":
            item.update(same_document=True, resolution_scope="same_document")
            marked = True
    assert marked
    norm = norm_from_row(row, "condition")
    assert_source_backed_qualifier(norm, "condition", "section 553")
    assert len(norm.conditions) == 2
    record = build_deontic_formula_record_from_ir(norm)
    assert record["proof_ready"] is True
    assert "formula_reference_condition_unresolved" not in record["blockers"]


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("canonical", ["section 552", "42 U.S.C. 552"])
def test_us_code_title_is_not_erased_when_matching_local_section_metadata(family, canonical):
    row = element(family, "5 U.S.C. 552")
    row["resolved_cross_references"] = [reference(canonical_citation=canonical)]
    assert_blocked(norm_from_row(row, family, "5 U.S.C. 552"), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
@pytest.mark.parametrize("citation,targets", [
    ("sections 552 through 554", ("552",)),
    ("sections 552 through 554", ("552", "554")),
])
def test_uncovered_range_members_cannot_be_treated_as_resolved(family, citation, targets):
    row = element(family, citation)
    row["resolved_cross_references"] = [reference(target) for target in targets]
    assert_blocked(norm_from_row(row, family, citation), family)


@pytest.mark.parametrize("family", ["condition", "exception"])
def test_complete_source_backed_typed_list_requires_every_member(family):
    """Isolate formula validation from the separately recorded comma-list parser gap."""
    citation = "sections 552, 553, and 554"
    row = element(family, citation)
    row["resolved_cross_references"] = [reference(), reference("553")]
    norm = LegalNormIR.from_parser_element(row)
    raw_text = citation if family == "condition" else "as provided in " + citation
    start = norm.source_text.index(raw_text)
    end = start + len(raw_text)
    qualifier = {
        "type": family,
        "clause_type": "subject_to" if family == "condition" else "except",
        "raw_text": raw_text,
        "normalized_text": raw_text.lower(),
        "value": raw_text.lower(),
        "span": [start, end],
        "clause_span": [0, end + 1] if family == "condition" else [norm.source_text.index("except"), end],
    }
    # This caller-supplied complete typed slot is authenticated against the same
    # full source. It does not claim that the parser recovered the complete list.
    norm = replace(norm, **{family + "s": [qualifier]})
    assert_source_backed_qualifier(norm, family, citation)
    assert_blocked(norm, family)
