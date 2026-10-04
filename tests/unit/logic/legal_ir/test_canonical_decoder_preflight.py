"""Source-only profile warnings, exact receipts, and limited negative evidence."""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_decoder_preflight as subject


def reseal(record):
    body = {key: value for key, value in record.items() if key != "content_sha256"}
    record["content_sha256"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()).hexdigest()
    return record


@pytest.mark.parametrize("text,code,surface,outcome", [
    ("Every clerk must review every application.", "source.quantified_binding", "Every", "unsupported_profile"),
    ("Each officer must assign exactly one reviewer to each application.", "source.quantified_cardinality", "exactly one", "unsupported_profile"),
    ("The officer must assign exactly 2 reviewers.", "source.quantified_cardinality", "exactly 2", "unsupported_profile"),
    ("A clerk may notify an applicant only if that applicant's application is complete.", "source.linked_variable_binding", "only if that applicant's", "unsupported_profile"),
    ("The clerk may retain the application only if their application is complete.", "source.linked_variable_binding", "only if their", "unsupported_profile"),
    ("The clerk is not required to notify the applicant.", "source.negated_obligation", "is not required to", "unsupported_profile"),
    ("The clerk need not notify the applicant.", "source.negated_obligation", "need not", "unsupported_profile"),
    ("The clerk is not obligated to notify the applicant.", "source.negated_obligation", "is not obligated to", "unsupported_profile"),
    ("The clerk must notify the applicant if the application is complete or fees have been paid.", "source.condition_disjunction", "or", "unsupported_profile"),
    ("The clerk must notify the applicant unless a court order applies and a legal hold applies.", "source.exception_conjunction", "and", "unsupported_profile"),
    ("The clerk must notify the applicant next Friday.", "source.relative_calendar_anchor", "next Friday", "clarification_required"),
    ("The clerk must retain the application tomorrow.", "source.relative_calendar_anchor", "tomorrow", "clarification_required"),
    ("The clerk told the custodian that they must retain the application.", "source.unresolved_actor_pronoun", "they", "clarification_required"),
])
def test_explicit_profile_gaps_have_exact_source_spans(text, code, surface, outcome):
    result = subject.analyze_decoder_source(text)
    assert result["outcome"] == outcome
    diagnostic = next(item for item in result["diagnostics"] if item["code"] == code)
    assert diagnostic["source_text"] == surface == text[diagnostic["start"]:diagnostic["end"]]
    assert subject.validate_decoder_preflight(result) == result
    assert all(result[field] is False for field in subject._FLAGS)


@pytest.mark.parametrize("text", [
    "The clerk must review the application.",
    "The clerk must not review the application.",
    "The clerk is required to review the application.",
    "The clerk must assign one reviewer.",
    "The clerk must review the exact copy.",
    "Every report contains five pages.",
    "The clerk must record every report.",
    "The clerk must retain the application if a court order applies and a legal hold applies.",
    "The clerk must retain the application unless a court order applies or a legal hold applies.",
    "The clerk must notify the applicant and custodian.",
    "The clerk may notify the applicant or custodian.",
    "The clerk may notify an applicant only if the application is complete.",
    "The clerk must notify the applicant on Friday.",
    "The report describes next Friday and exactly one reviewer.",
    "They must retain the application.",
    "The clerk told the custodian that the officer must retain the application.",
    "Unfamiliar source syntax is deliberately unassessed.",
])
def test_no_pattern_match_stays_unassessed_and_does_not_certify_representation(text):
    result = subject.analyze_decoder_source(text)
    assert result["outcome"] == "unassessed" and result["diagnostics"] == []
    assert "representable" not in result and "accepted" not in result
    assert result["source_fidelity_established"] is result["qualified"] is False


@pytest.mark.parametrize("quotation", ['"{}"', "“{}”", "‘{}’", "'{}'"])
def test_quoted_metalinguistic_examples_do_not_trigger_pattern_warnings(quotation):
    inside = "Every clerk must notify exactly one applicant next Friday if fees paid or waived."
    text = "The example reads " + quotation.format(inside)
    assert subject.analyze_decoder_source(text)["outcome"] == "unassessed"


def test_quoted_connective_is_ignored_but_unquoted_clause_is_checked():
    text = 'The clerk must retain "a or b" if fees paid and evidence verified.'
    assert subject.analyze_decoder_source(text)["outcome"] == "unassessed"
    text = 'The clerk must retain "a and b" unless fees waived and evidence missing.'
    result = subject.analyze_decoder_source(text)
    assert [item["source_text"] for item in result["diagnostics"]] == ["and"]


def test_case_whitespace_unicode_and_later_sentences_keep_original_offsets():
    text = "Préface.  The CLERK\tMUST notify the applicant IF fees paid\nOR waived."
    result = subject.analyze_decoder_source(text)
    diagnostic = result["diagnostics"][0]
    assert diagnostic["code"] == "source.condition_disjunction"
    assert text[diagnostic["start"]:diagnostic["end"]] == "OR"
    assert result["source_text"] == text and result["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("context,required", [("The clerk is the actor.", False),
    ("The clerk is the actor.", True), ("", True), (" ", False), (" ", True)])
def test_context_is_retained_and_never_applied_or_silently_discarded(context, required):
    text = "The clerk must retain the application."
    result = subject.analyze_decoder_source(text, context_text=context, requires_context_resolution=required)
    assert result["outcome"] == "clarification_required"
    assert result["context"] == {"text": context, "sha256": hashlib.sha256(context.encode()).hexdigest(),
                                 "requires_resolution": required, "applied": False}
    assert "source.context_resolution_unavailable" in {item["code"] for item in result["diagnostics"]}
    assert ("source.required_context_missing" in {item["code"] for item in result["diagnostics"]}) is (required and not context.strip())


def test_clarification_takes_priority_while_preserving_unsupported_diagnostics():
    result = subject.analyze_decoder_source("Every clerk must notify the applicant tomorrow.")
    assert result["outcome"] == "clarification_required"
    assert {item["code"] for item in result["diagnostics"]} == {"source.quantified_binding", "source.relative_calendar_anchor"}


@pytest.mark.parametrize("text", [None, 12, True, "", "  ", "x" * 65_537, "\ud800"])
def test_invalid_source_fails_without_truncation(text):
    with pytest.raises(ValueError):
        subject.analyze_decoder_source(text)


@pytest.mark.parametrize("context,required", [(None, False), ("\ud800", False),
    ("x" * 2_001, False), ("", 1), ("", "yes")])
def test_context_and_context_declaration_have_exact_bounds_and_types(context, required):
    with pytest.raises(ValueError):
        subject.analyze_decoder_source("The clerk must retain the application.",
                                       context_text=context, requires_context_resolution=required)


def test_source_over_decoder_profile_limit_is_preserved_as_unsupported():
    text = "x" * 16_385
    result = subject.analyze_decoder_source(text)
    assert result["source_text"] == text and result["outcome"] == "unsupported_profile"
    assert result["diagnostics"][0]["end"] == len(text)
    assert result["diagnostics"][0]["code"] == "source.profile_character_bound"
    assert subject.analyze_decoder_source("x" * 65_536)["source_text"] == "x" * 65_536


def test_warning_overflow_fails_instead_of_truncating():
    text = "A must act if a or b;" * 257
    with pytest.raises(ValueError, match="diagnostic count"):
        subject.analyze_decoder_source(text)


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(outcome="unassessed"),
    lambda row: row.update(source_sha256="0" * 64),
    lambda row: row.update(source_profile="general-semantic-gate/v1"),
    lambda row: row.update(qualified=True),
    lambda row: row.update(target_access=0),
    lambda row: row.update(diagnostics=[]),
    lambda row: row["diagnostics"][0].update(start=1),
    lambda row: row["diagnostics"][0].update(source_text="different"),
    lambda row: row["diagnostics"][0].update(message="Resolved by an oracle."),
    lambda row: row["context"].update(applied=True),
    lambda row: row["context"].update(sha256="0" * 64),
])
def test_resealed_tampering_cannot_change_source_recomputed_receipt(mutate):
    row = subject.analyze_decoder_source("Every clerk must retain the application.")
    mutate(row)
    with pytest.raises(ValueError):
        subject.validate_decoder_preflight(reseal(row))


@pytest.mark.parametrize("field", ["canonical_ir", "target", "row_kind", "expected_outcome", "vocabulary"])
def test_hidden_evaluation_channels_are_rejected_by_api_and_schema(field):
    text = "The clerk must retain the application."
    with pytest.raises(TypeError):
        subject.analyze_decoder_source(text, **{field: "oracle"})
    row = subject.analyze_decoder_source(text)
    row[field] = "oracle"
    with pytest.raises(ValueError, match="closed"):
        subject.validate_decoder_preflight(reseal(row))


def test_receipts_are_detached_and_digest_uses_exact_unicode_json():
    first = subject.analyze_decoder_source("The clerk must retain the café tomorrow.")
    second = subject.validate_decoder_preflight(first)
    assert second == first and second is not first and second["diagnostics"] is not first["diagnostics"]
    assert reseal(copy.deepcopy(first)) == first
    first["diagnostics"][0]["message"] = "Caller mutation"
    assert second["diagnostics"][0]["message"] != "Caller mutation"


def test_preflight_has_no_model_parser_target_or_vocabulary_dependency():
    tree = ast.parse(inspect.getsource(subject))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert set(imports) == {"__future__", "hashlib", "json", "re", "canonical_source_guards"}
    assert set(inspect.signature(subject.analyze_decoder_source).parameters) == {
        "source_text", "context_text", "requires_context_resolution"}
