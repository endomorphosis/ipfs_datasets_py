"""Independent exact-source grounding and output-contract boundaries."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_source_grounding as subject
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalAtomVocabulary,
    CompilerRequest,
)

LITERAL, FIXED, ANCHORED = subject.DECODER_PROFILES
FALSE_AUTHORITY_FIELDS = (
    "target_access", "model_executed", "source_fidelity_established",
    "qualified", "proof_authority",
)
SPECIAL_TOKENS = ["<pad>", "<bos>", "<eos>"]


@pytest.fixture
def vocabulary():
    return CanonicalAtomVocabulary(
        actors=("assessor",), actions=("record", "retain"),
        objects=("application", "evidence"),
        qualifiers=("application_complete", "fees_paid", "legal_hold", "emergency",
                    "within_48_hours", "within_10_days"),
    )


def request(text, vocabulary, **kwargs):
    return CompilerRequest(text, "independent-source", vocabulary, **kwargs)


def grounded(text, vocabulary, **kwargs):
    return subject.construct_grounded_source(request(text, vocabulary), **kwargs)


def anchor(record, path):
    return next(item for item in record["anchors"] if item["field_path"] == path)


def reseal(record):
    body = {key: value for key, value in record.items() if key != "content_sha256"}
    record["content_sha256"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return record


def serialized_proposal(record):
    return json.dumps(record["canonical_ir"], sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def character_codec(record):
    return SPECIAL_TOKENS + sorted(set(serialized_proposal(record)))


def issue_codes(transport):
    return {item["code"] for item in transport["issues"]}


def test_repeated_object_mentions_have_distinct_structural_anchors(vocabulary):
    text = "The assessor must retain the application if the application is complete."
    record = grounded(text, vocabulary)
    assert record["outcome"] == "grounded_candidate"
    object_anchor = anchor(record, "/rules/0/object")
    condition_anchor = anchor(record, "/rules/0/conditions/0")
    assert object_anchor["canonical_symbol"] == "application"
    assert (object_anchor["start"], object_anchor["end"]) == (25, 40)
    assert object_anchor["source_text"] == "the application"
    assert condition_anchor["canonical_symbol"] == "application_complete"
    assert (condition_anchor["start"], condition_anchor["end"]) == (44, 71)
    assert condition_anchor["source_text"] == "the application is complete"
    assert object_anchor["end"] < condition_anchor["start"]
    assert subject.validate_grounded_source(record) == record
    for item in record["anchors"]:
        assert item["source_text"] == text[item["start"]:item["end"]]
        assert item["offset_unit"] == "unicode_character_half_open"


@pytest.mark.parametrize("leading", [False, True])
def test_flat_connectives_keep_source_order_separate_from_canonical_order(vocabulary, leading):
    condition = "fees have been paid and the application is complete"
    core = "the assessor may record evidence within 48 hours and within 10 days"
    exception = "a legal hold applies or emergency"
    text = (f"If {condition}, {core}, unless {exception}." if leading else
            f"{core} if {condition}, unless {exception}.")
    record = grounded(text, vocabulary)
    rule = record["canonical_ir"]["rules"][0]
    assert rule["conditions"] == ["application_complete", "fees_paid"]
    assert rule["exceptions"] == ["emergency", "legal_hold"]
    assert rule["temporal"] == ["within_10_days", "within_48_hours"]
    assert record["facet_operators"] == {"conditions": "all", "exceptions": "any", "temporal": "all"}
    for facet, surfaces in {
        "conditions": ["the application is complete", "fees have been paid"],
        "exceptions": ["emergency", "a legal hold applies"],
        "temporal": ["within 10 days", "within 48 hours"],
    }.items():
        first, second = (anchor(record, f"/rules/0/{facet}/{index}") for index in range(2))
        assert [first["source_text"], second["source_text"]] == surfaces
        assert first["start"] > second["start"]
        for item, surface in zip((first, second), surfaces, strict=True):
            assert item["start"] == text.index(surface)
            assert item["end"] == item["start"] + len(surface)
    assert subject.validate_grounded_source(record) == record


@pytest.mark.parametrize("modal,symbol", [("must", "O"), ("must not", "F"),
                                          ("shall", "O"), ("shall not", "F"), ("may", "P")])
def test_modal_polarity_is_grounded_in_the_complete_modal_surface(vocabulary, modal, symbol):
    text = f"The assessor {modal} record evidence."
    record = grounded(text, vocabulary)
    item = anchor(record, "/rules/0/modality")
    assert item["canonical_symbol"] == record["canonical_ir"]["rules"][0]["modality"] == symbol
    assert item["source_text"] == modal
    assert (item["start"], item["end"]) == (13, 13 + len(modal))


def test_case_and_irregular_whitespace_do_not_change_or_normalize_literal_anchors(vocabulary):
    text = (" \tTHE ASSESSOR  MUST NOT retain\tthe application within 48 hours "
            "IF fees have been paid, UNLESS a legal hold applies. \n")
    record = grounded(text, vocabulary)
    assert record["request"]["source_text"] == text
    assert anchor(record, "/rules/0/actor")["source_text"] == "THE ASSESSOR"
    assert anchor(record, "/rules/0/modality")["source_text"] == "MUST NOT"
    assert record["canonical_ir"]["rules"][0]["modality"] == "F"
    for item in record["anchors"]:
        assert item["source_text"] == text[item["start"]:item["end"]]
    assert subject.validate_grounded_source(record) == record


def test_empty_object_does_not_invent_an_anchor(vocabulary):
    record = grounded("The assessor must record.", vocabulary)
    assert record["canonical_ir"]["rules"][0]["object"] == ""
    assert {item["field_path"] for item in record["anchors"]} == {
        "/rules/0/actor", "/rules/0/modality", "/rules/0/action",
    }
    assert subject.assess_decoder_transport(record, decoder_profile=LITERAL)["outcome"] == "transport_compatible"


@pytest.mark.parametrize("context,required", [("Assessor means the tax office.", False),
                                              ("Assessor means the tax office.", True), ("", True)])
def test_source_context_is_retained_but_blocks_compilation(vocabulary, monkeypatch, context, required):
    def forbid_compilation(*args, **kwargs):
        raise AssertionError("context must be rejected by source-only preflight")

    monkeypatch.setattr(subject.grammar.ExplicitQualifierCanonicalCompiler, "compile", forbid_compilation)
    record = grounded("The assessor must record evidence.", vocabulary,
                      context_text=context, requires_context_resolution=required)
    assert record["outcome"] == "source_blocked"
    assert record["preflight"]["context"]["text"] == context
    assert record["preflight"]["context"]["requires_resolution"] is required
    assert record["compiler_result"] is record["canonical_ir"] is None
    assert record["anchors"] == [] and record["context_applied"] is False
    assert subject.validate_grounded_source(record) == record
    for profile in subject.DECODER_PROFILES:
        tokens = SPECIAL_TOKENS + ["x"] if profile == FIXED else None
        result = subject.assess_decoder_transport(record, decoder_profile=profile, codec_tokens=tokens)
        assert result["outcome"] == "source_blocked"
        assert result["minimum_content_tokens"] is None


@pytest.mark.parametrize("text", [
    "The assessor must record evidence if the application is incomplete.",
    "The assessor must record evidence if fees have been paid according to policy.",
    "The assessor must record evidence. The assessor may retain application.",
    "The assessor must record evidence if fees have been paid unless unknown hold.",
    "The assessor must record evidence if fees have been paid and.",
])
def test_unknown_atoms_and_unconsumed_suffixes_never_emit_partial_proposals(vocabulary, text):
    record = grounded(text, vocabulary)
    assert record["outcome"] == "proposal_unavailable"
    assert record["canonical_ir"] is None and record["anchors"] == []
    assert record["partial_projection"] is False
    result = subject.assess_decoder_transport(record, decoder_profile=ANCHORED)
    assert result["outcome"] == "proposal_unavailable"


@pytest.mark.parametrize("text", [
    "Every assessor must record evidence.",
    "The assessor need not record evidence.",
    "The assessor must record evidence if fees paid or application complete.",
    "The assessor must record evidence next Friday.",
])
def test_preflight_profile_gaps_cannot_be_recast_as_anchored_compatibility(vocabulary, text):
    record = grounded(text, vocabulary)
    assert record["outcome"] == "source_blocked"
    assert record["compiler_result"] is None
    assert subject.assess_decoder_transport(record, decoder_profile=ANCHORED)["outcome"] == "source_blocked"


@pytest.mark.parametrize("kwargs", [{"allow_explicit_partial": True}, {"config": {"fallback": True}}])
def test_grounding_rejects_partial_projection_and_request_overrides(vocabulary, kwargs):
    with pytest.raises(ValueError):
        subject.construct_grounded_source(request("The assessor must record evidence.", vocabulary, **kwargs))


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(outcome="source_blocked"),
    lambda row: row.update(profile="generic-semantic-gate/v1"),
    lambda row: row.update(explicit_compiler_config_cid="changed"),
    lambda row: row.update(anchors=[]),
    lambda row: row["anchors"][0].update(start=0),
    lambda row: row["anchors"][0].update(end=1),
    lambda row: row["anchors"][0].update(source_text="oracle surface"),
    lambda row: row["anchors"][0].update(canonical_symbol="oracle_symbol"),
    lambda row: row["anchors"][0].update(field_path="/rules/0/conditions/0"),
    lambda row: row["anchors"][0].update(facet="conditions"),
    lambda row: row["anchors"][0].update(offset_unit="utf8_byte_half_open"),
    lambda row: row["facet_operators"].update(conditions="any"),
    lambda row: row["canonical_ir"]["rules"][0].update(modality="F"),
    lambda row: row["request"].update(source_text="The assessor must retain application."),
    lambda row: row["compiler_result"].update(canonical_ir=None),
    lambda row: row.update(context_applied=True),
    lambda row: row.update(partial_projection=True),
    lambda row: row.update(target_access=0),
    lambda row: row.update(qualified=True),
    lambda row: row.update(proof_authority=True),
    lambda row: row.update(model_executed=True),
    lambda row: row.update(source_fidelity_established=True),
])
@pytest.mark.parametrize("resealed", [False, True])
def test_grounding_rejects_changed_fields_offsets_source_and_authority(vocabulary, mutation, resealed):
    record = grounded("The assessor must retain the application if the application is complete.", vocabulary)
    mutation(record)
    with pytest.raises(ValueError):
        subject.validate_grounded_source(reseal(record) if resealed else record)


def test_fully_rebound_request_cannot_reuse_other_source_anchors(vocabulary):
    record = grounded("The assessor must record evidence.", vocabulary)
    record["request"] = request("The assessor must retain application.", vocabulary).to_dict()
    with pytest.raises(ValueError):
        subject.validate_grounded_source(reseal(record))


@pytest.mark.parametrize("field", ["target", "canonical_ir", "expected_outcome", "row_kind", "gold"])
def test_no_hidden_evaluation_channel_is_accepted(vocabulary, field):
    bound_request = request("The assessor must record evidence.", vocabulary)
    with pytest.raises(TypeError):
        subject.construct_grounded_source(bound_request, **{field: "oracle"})
    record = subject.construct_grounded_source(bound_request)
    with pytest.raises(TypeError):
        subject.assess_decoder_transport(record, decoder_profile=ANCHORED, **{field: "oracle"})
    record[field] = "oracle"
    with pytest.raises(ValueError):
        subject.validate_grounded_source(reseal(record))


def test_grounder_requires_a_bound_request(vocabulary):
    with pytest.raises(ValueError):
        subject.construct_grounded_source("The assessor must record evidence.")
    assert set(inspect.signature(subject.construct_grounded_source).parameters) == {
        "request", "context_text", "requires_context_resolution",
    }


def test_literal_transport_requires_unique_case_sensitive_canonical_mentions(vocabulary):
    simple = grounded("The assessor must record evidence if emergency.", vocabulary)
    assert subject.assess_decoder_transport(simple, decoder_profile=LITERAL)["outcome"] == "transport_compatible"
    repeated = grounded("The assessor must retain the application if the application is complete.", vocabulary)
    result = subject.assess_decoder_transport(repeated, decoder_profile=LITERAL)
    assert result["outcome"] == "unsupported_transport"
    assert {item["field_path"] for item in result["issues"] if item["code"] == "literal_span.ambiguous_mention"} == {"/rules/0/object"}
    assert "literal_span.atom_absent" in issue_codes(result)
    mixed_case = grounded("The ASSESSOR must record evidence.", vocabulary)
    case_result = subject.assess_decoder_transport(mixed_case, decoder_profile=LITERAL)
    assert case_result["outcome"] == "unsupported_transport"
    assert case_result["issues"] == [{"code": "literal_span.atom_absent", "field_path": "/rules/0/actor"}]


def test_literal_transport_does_not_count_substrings_inside_other_tokens():
    vocabulary = CanonicalAtomVocabulary(actors=("assessor",), actions=("record",),
                                         objects=("recordkeeper",))
    record = grounded("The assessor must record recordkeeper.", vocabulary)
    result = subject.assess_decoder_transport(record, decoder_profile=LITERAL)
    assert result["outcome"] == "transport_compatible" and result["issues"] == []


def test_literal_transport_cannot_drop_extra_atoms_or_canonicalize_spaces(vocabulary):
    text = "The assessor must record evidence within 48 hours if emergency and fees paid."
    record = grounded(text, vocabulary)
    result = subject.assess_decoder_transport(record, decoder_profile=LITERAL)
    assert result["outcome"] == "unsupported_transport"
    assert "literal_span.multiple_qualifier_atoms" in issue_codes(result)
    assert {item["field_path"] for item in result["issues"] if item["code"] == "literal_span.atom_absent"} == {
        "/rules/0/conditions/1", "/rules/0/temporal/0",
    }
    assert subject.assess_decoder_transport(record, decoder_profile=ANCHORED)["outcome"] == "transport_compatible"


def test_character_piece_codec_reaches_symbols_absent_as_whole_tokens(vocabulary):
    record = grounded("The assessor must retain application if the application is complete.", vocabulary)
    tokens = character_codec(record)
    assert "assessor" not in tokens and "application_complete" not in tokens
    result = subject.assess_decoder_transport(record, decoder_profile=FIXED, codec_tokens=tokens)
    assert result["outcome"] == "transport_compatible"
    assert result["minimum_content_tokens"] == len(serialized_proposal(record))
    assert subject.validate_decoder_transport(result, record, codec_tokens=tokens) == result


def test_fixed_codec_uses_compact_sorted_json_and_counts_bos_and_eos(vocabulary):
    record = grounded("The assessor must record evidence.", vocabulary)
    compact = serialized_proposal(record)
    one_piece = SPECIAL_TOKENS + [compact]
    result = subject.assess_decoder_transport(record, decoder_profile=FIXED, codec_tokens=one_piece, output_cap=3)
    assert result["outcome"] == "transport_compatible" and result["minimum_content_tokens"] == 1
    spaced = json.dumps(record["canonical_ir"], sort_keys=True)
    assert spaced != compact
    incompatible = subject.assess_decoder_transport(record, decoder_profile=FIXED,
                                                    codec_tokens=SPECIAL_TOKENS + [spaced])
    assert incompatible["outcome"] == "unsupported_transport"
    assert incompatible["minimum_content_tokens"] is None


def test_output_cap_includes_both_special_tokens_at_the_exact_boundary(vocabulary):
    record = grounded("The assessor must record evidence.", vocabulary)
    tokens = character_codec(record)
    minimum = len(serialized_proposal(record))
    fits = subject.assess_decoder_transport(record, decoder_profile=FIXED,
                                           codec_tokens=tokens, output_cap=minimum + 2)
    exceeds = subject.assess_decoder_transport(record, decoder_profile=FIXED,
                                              codec_tokens=tokens, output_cap=minimum + 1)
    assert fits["outcome"] == "transport_compatible"
    assert exceeds["outcome"] == "unsupported_transport"
    assert exceeds["minimum_content_tokens"] == minimum
    assert issue_codes(exceeds) == {"fixed_codec.BOS_content_EOS_exceeds_output_cap"}


def test_codec_missing_a_needed_character_cannot_use_special_token_characters(vocabulary):
    record = grounded("The assessor must record evidence.", vocabulary)
    tokens = [token for token in character_codec(record) if token != "a"]
    assert "a" in "<pad>" and "a" not in tokens
    result = subject.assess_decoder_transport(record, decoder_profile=FIXED, codec_tokens=tokens)
    assert result["outcome"] == "unsupported_transport" and result["minimum_content_tokens"] is None
    assert issue_codes(result) == {"fixed_codec.serialized_proposal_unrepresentable"}


@pytest.mark.parametrize("tokens", [
    None, ("<pad>", "<bos>", "<eos>", "x"), SPECIAL_TOKENS,
    ["<bos>", "<pad>", "<eos>", "x"], SPECIAL_TOKENS + [""],
    SPECIAL_TOKENS + [1], SPECIAL_TOKENS + ["x", "x"], SPECIAL_TOKENS + ["x" * 4097],
])
def test_fixed_codec_rejects_unbound_or_malformed_vocabularies(vocabulary, tokens):
    record = grounded("The assessor must record evidence.", vocabulary)
    with pytest.raises(ValueError):
        subject.assess_decoder_transport(record, decoder_profile=FIXED, codec_tokens=tokens)


@pytest.mark.parametrize("cap", [False, 2, 4097, 3.0, "512", None])
def test_output_cap_is_bounded_integer_configuration(vocabulary, cap):
    record = grounded("The assessor must record evidence.", vocabulary)
    with pytest.raises(ValueError):
        subject.assess_decoder_transport(record, decoder_profile=ANCHORED, output_cap=cap)


@pytest.mark.parametrize("profile", [None, "unknown-decoder/v1"])
def test_unknown_decoder_profiles_are_rejected(vocabulary, profile):
    with pytest.raises(ValueError):
        subject.assess_decoder_transport(grounded("The assessor must record evidence.", vocabulary),
                                         decoder_profile=profile)


@pytest.mark.parametrize("profile", [LITERAL, ANCHORED])
def test_codec_cannot_be_injected_into_other_profiles(vocabulary, profile):
    with pytest.raises(ValueError):
        subject.assess_decoder_transport(grounded("The assessor must record evidence.", vocabulary),
                                         decoder_profile=profile, codec_tokens=SPECIAL_TOKENS + ["x"])


@pytest.mark.parametrize("profile", subject.DECODER_PROFILES)
def test_transport_compatibility_never_grants_acceptance_or_authority(vocabulary, profile):
    record = grounded("The assessor must record evidence.", vocabulary)
    tokens = character_codec(record) if profile == FIXED else None
    result = subject.assess_decoder_transport(record, decoder_profile=profile, codec_tokens=tokens)
    assert result["outcome"] == "transport_compatible"
    assert all(record[field] is result[field] is False for field in FALSE_AUTHORITY_FIELDS)
    assert result["generated_candidate_assessed"] is result["checkpoint_selected"] is False
    assert result["assessment_scope"] == "source_constructed_proposal_transport_only"
    assert "accepted" not in result and "proof_passed" not in result


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(grounding_sha256="0" * 64),
    lambda row: row.update(outcome="unsupported_transport"),
    lambda row: row.update(issues=[{"code": "forged", "field_path": None}]),
    lambda row: row.update(minimum_content_tokens=1),
    lambda row: row.update(codec_tokens_sha256="0" * 64),
    lambda row: row.update(configured_output_cap=3),
    lambda row: row.update(assessment_scope="independent-semantic-review"),
    lambda row: row.update(generated_candidate_assessed=True),
    lambda row: row.update(checkpoint_selected=True),
    lambda row: row.update(proof_authority=True),
    lambda row: row.update(source_fidelity_established=True),
    lambda row: row.update(qualified=True),
    lambda row: row.update(target_access=0),
])
@pytest.mark.parametrize("resealed", [False, True])
def test_transport_rejects_modified_receipts_even_when_resealed(vocabulary, mutation, resealed):
    record = grounded("The assessor must record evidence.", vocabulary)
    tokens = character_codec(record)
    result = subject.assess_decoder_transport(record, decoder_profile=FIXED, codec_tokens=tokens)
    mutation(result)
    with pytest.raises(ValueError):
        subject.validate_decoder_transport(reseal(result) if resealed else result, record, codec_tokens=tokens)


def test_transport_rejects_stale_grounding_and_changed_codec_bindings(vocabulary):
    first = grounded("The assessor must record evidence.", vocabulary)
    second = grounded("The assessor must retain application.", vocabulary)
    tokens = character_codec(first)
    result = subject.assess_decoder_transport(first, decoder_profile=FIXED, codec_tokens=tokens)
    with pytest.raises(ValueError):
        subject.validate_decoder_transport(result, second, codec_tokens=tokens)
    with pytest.raises(ValueError):
        subject.validate_decoder_transport(result, first, codec_tokens=tokens + ["assessor"])
    result["grounding_sha256"] = second["content_sha256"]
    with pytest.raises(ValueError):
        subject.validate_decoder_transport(reseal(result), second, codec_tokens=tokens)


def test_lazy_grounding_path_does_not_import_or_execute_optional_models():
    program = """
import builtins
import sys
original = builtins.__import__
forbidden = {'torch', 'numpy', 'spacy', 'transformers', 'sentence_transformers', 'huggingface_hub'}
def guard(name, *args, **kwargs):
    if name.split('.')[0] in forbidden:
        raise AssertionError('Optional model import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guard
from ipfs_datasets_py.logic.legal_ir.canonical_source_grounding import construct_grounded_source
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalAtomVocabulary, CompilerRequest
vocabulary = CanonicalAtomVocabulary(actors=('assessor',), actions=('record',), objects=('evidence',))
record = construct_grounded_source(CompilerRequest('The assessor must record evidence.', 'lazy-check', vocabulary))
assert record['outcome'] == 'grounded_candidate'
assert not (forbidden & set(sys.modules))
"""
    completed = subprocess.run([sys.executable, "-c", program],
                               cwd=Path(subject.__file__).resolve().parents[3],
                               capture_output=True, text=True, timeout=20, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_receipt_digest_covers_exact_source_and_does_not_mutate_caller_records(vocabulary):
    record = grounded("  The assessor must record\tevidence.\n", vocabulary)
    saved = copy.deepcopy(record)
    assert reseal(copy.deepcopy(record)) == record
    assert subject.validate_grounded_source(record) == saved
    result = subject.assess_decoder_transport(record, decoder_profile=ANCHORED)
    assert record == saved
    assert subject.validate_decoder_transport(result, record) == result


def test_grounding_validation_returns_detached_recomputed_nested_fields(vocabulary):
    record = grounded("The assessor must retain application if fees paid.", vocabulary)
    checked = subject.validate_grounded_source(record)
    assert checked == record and checked is not record
    assert checked["anchors"] is not record["anchors"]
    assert checked["canonical_ir"] is not record["canonical_ir"]
    record["anchors"][0]["source_text"] = "Caller mutation"
    record["canonical_ir"]["rules"][0]["conditions"].clear()
    assert checked["anchors"][0]["source_text"] != "Caller mutation"
    assert checked["canonical_ir"]["rules"][0]["conditions"] == ["fees_paid"]


def test_transport_validation_returns_detached_recomputed_issues(vocabulary):
    record = grounded("The assessor must record evidence if fees paid.", vocabulary)
    transport = subject.assess_decoder_transport(record, decoder_profile=LITERAL)
    checked = subject.validate_decoder_transport(transport, record)
    assert checked == transport and checked is not transport
    assert checked["issues"] is not transport["issues"]
    transport["issues"][0]["code"] = "Caller mutation"
    assert checked["issues"][0]["code"] == "literal_span.atom_absent"
