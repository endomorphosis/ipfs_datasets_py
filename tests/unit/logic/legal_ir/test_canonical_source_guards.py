"""Source-only competing-actor diagnostics, with exact character spans."""
from __future__ import annotations

import hashlib

import pytest
from ipfs_datasets_py.logic.legal_ir.canonical_source_guards import analyze_canonical_source


@pytest.mark.parametrize("text", [
    "The clerk told the custodian that they must retain the application.",
    "The officer informed the registrar that she may authorize the filing.",
    "The clerk said to the officer that he shall not retain the record.",
    "The department manager warned the senior officer that they are required to file notice.",
])
def test_competing_named_participants_require_clarification_with_source_bound_span(text):
    result = analyze_canonical_source(text)
    assert result["requires_clarification"] is True
    assert result["status"] == "clarification_required"
    assert result["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert result["model_calls"] == 0 and result["qualified"] is False
    diagnostic = result["diagnostics"][0]
    assert text[diagnostic["start"]:diagnostic["end"]] == diagnostic["pronoun"]
    assert len(diagnostic["competing_participants"]) == 2


@pytest.mark.parametrize("text", [
    "The clerk must retain the application.",
    "The clerk told the custodian that the officer must retain the application.",
    "The clerk told the clerk that they must retain the application.",
    "The clerk told them that they must retain the application.",
    "They must retain the application.",
    'The example reads "The clerk told the custodian that they must retain the application."',
    "The clerk's notice says that the custodian must retain the application.",
])
def test_no_trigger_is_limited_to_pattern_absence_and_does_not_resolve_other_syntax(text):
    result = analyze_canonical_source(text)
    assert result["requires_clarification"] is False
    assert result["diagnostics"] == [] and result["qualified"] is False


@pytest.mark.parametrize("text", [None, "", "  ", "x" * 65_537, "\ud800"])
def test_inputs_fail_at_declared_bounds_without_truncation(text):
    with pytest.raises(ValueError):
        analyze_canonical_source(text)


def test_diagnostic_overflow_fails_without_silently_dropping_actors():
    source = "The clerk told the custodian that they must retain the application. " * 129
    with pytest.raises(ValueError, match="diagnostic count"):
        analyze_canonical_source(source)


def test_unicode_character_offsets_remain_exact_with_preceding_non_ascii_text():
    source = "Préface. The clerk told the custodian that they must retain the application."
    diagnostic = analyze_canonical_source(source)["diagnostics"][0]
    assert source[diagnostic["start"]:diagnostic["end"]] == "they"
