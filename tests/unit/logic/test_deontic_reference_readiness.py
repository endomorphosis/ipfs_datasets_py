"""Reference readiness uses current source-backed slots, not cached clearance."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.formula_builder import (
    build_deontic_formula_from_ir,
    build_deontic_formula_record_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def source_norm(source):
    element, = extract_normative_elements(source)
    norm = LegalNormIR.from_parser_element(element)
    for slot in norm.conditions + norm.exceptions:
        start, end = slot["span"]
        assert norm.source_text[start:end] == slot["raw_text"]
    return norm


def assert_blocked(norm, marker):
    before = deepcopy(norm)
    formula = build_deontic_formula_from_ir(norm)
    result = build_deontic_formula_record_from_ir(norm)
    assert result["formula"] == formula
    assert result["proof_ready"] is False
    assert result["repair_required"] is result["requires_validation"] is True
    assert result["deterministic_resolution"] == {}
    assert marker in result["blockers"]
    assert norm == before


@pytest.mark.parametrize("source", [
    "The chapter applies to food carts.",
    "This section applies to food carts described in section 552.",
])
@pytest.mark.parametrize("cached", [False, True])
def test_external_applicability_cannot_borrow_local_or_cached_clearance(source, cached):
    norm = source_norm(source)
    if cached:
        norm = replace(norm, quality=replace(
            norm.quality, parser_warnings=[], promotable_to_theorem=True,
            export_readiness={"blockers": [], "deterministic_resolution": {
                "type": "local_scope_applicability", "scopes": ["this section"],
            }},
        ))
    assert_blocked(norm, "formula_external_applicability_unresolved")


@pytest.mark.parametrize("metadata", [
    {"reference_type": "section", "target": "552"},
    {"reference_type": "section", "target": "this", "resolution_scope": "external"},
    {"reference_type": "section", "target": "this", "canonical_citation": "section 552"},
    {"reference_type": "section", "target": "this", "same_document": False},
    {"reference_type": "section", "target": "this", "resolved": False},
    {"reference_type": "section", "target": "this", "same_document": True,
     "target_exists": False},
    {"reference_type": "section", "target": "this", "target_document": "same-document",
     "target_exists": False},
])
def test_local_applicability_rejects_conflicting_reference_inventory(metadata):
    norm = source_norm("This section applies to food carts.")
    norm = replace(norm, resolved_cross_references=[metadata])
    assert_blocked(norm, "formula_external_applicability_unresolved")


@pytest.mark.parametrize("scope", ["section", "chapter", "title", "article", "part"])
def test_simple_local_applicability_keeps_supported_self_scope(scope):
    norm = source_norm(f"This {scope} applies to food carts.")
    result = build_deontic_formula_record_from_ir(norm)
    assert result["proof_ready"] is True
    if result["deterministic_resolution"]:
        assert result["deterministic_resolution"]["type"] == "local_scope_applicability"
    assert "formula_external_applicability_unresolved" not in result["blockers"]


@pytest.mark.parametrize("source,slot,marker", [
    ("Subject to approval, subject to section 552, the Director shall issue a permit.",
     "conditions", "formula_reference_condition_unresolved"),
    ("The Director shall issue a permit unless approval is denied, except as provided in section 552.",
     "exceptions", "formula_reference_exception_unresolved"),
])
@pytest.mark.parametrize("metadata", [[], [{
    "reference_type": "section", "target": "552", "canonical_citation": "section 552",
    "same_document": True,
}]])
def test_actual_mixed_slots_remain_blocked_without_warnings_or_with_complete_reference_metadata(
    source, slot, marker, metadata,
):
    norm = source_norm(source)
    assert len(getattr(norm, slot)) == 2
    norm = replace(norm, cross_references=[], resolved_cross_references=metadata,
                   quality=replace(norm.quality, parser_warnings=[], promotable_to_theorem=True,
                                   export_readiness={"blockers": []}))
    assert_blocked(norm, marker)
