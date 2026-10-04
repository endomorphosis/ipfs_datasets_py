"""Independent authored grammar boundaries; no model or evaluation corpus used."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import instruction_scope as scope


def accepted(text):
    report = scope.assess_intent_instruction_scope(text)
    assert report["eligible_for_inference"] is True, report["reasons"]
    assert report["status"] == "within_declared_single_action_grammar"
    assert report["complete_consumption"] is True and report["reasons"] == []
    assert scope.validate_instruction_scope_report(report, instruction=text) == report
    return report


def rejected(text):
    report = scope.assess_intent_instruction_scope(text)
    assert report["eligible_for_inference"] is False
    assert report["status"] == "unsupported_by_scope_policy"
    assert report["complete_consumption"] is False and report["reasons"]
    assert report["continue_planning"] is report["raw_instruction_preserved"] is True
    assert scope.validate_instruction_scope_report(report, instruction=text) == report
    return report


@pytest.mark.parametrize("modal", [
    "must", "shall", "must not", "shall not", "may", "should", "intends to",
    "is required to", "is forbidden to", "is prohibited from", "is allowed to",
    "is permitted to", "is advised to", "is recommended to",
])
@pytest.mark.parametrize("actor", ["agent", "the build agent", "service_role", "opaqueactor"])
def test_actor_modal_productions_are_fully_consumed(modal, actor):
    report = accepted(f"{actor} {modal} inspect cached audit records.")
    assert report["grammar_shape"] == "actor_modal"


@pytest.mark.parametrize("text,shape", [
    ("read cache", "bare_imperative"),
    ("Read cache.", "bare_imperative"),
    ("please refactor the parser module.", "please_imperative"),
    ("Please validate cached test fixtures.", "please_imperative"),
    ("must inspect cache.", "omitted_actor_modal"),
    ("shall not delete retained records.", "omitted_actor_modal"),
    ("do not deploy application.", "omitted_actor_modal"),
    ("never publish credentials.", "omitted_actor_modal"),
    ("May inspect cache.", "omitted_actor_modal"),
    ("should test parser.", "omitted_actor_modal"),
    ("please do not remove cache.", "negative_request"),
    ("Please never remove cache.", "negative_request"),
    ("Required: inspect cache.", "modal_heading"),
    ("must not do: delete records.", "modal_heading"),
    ("permitted: please inspect cache.", "modal_heading"),
    ("please ask the operator to inspect the cache.", "delegated_single_action_request"),
    ("Please ask build agent to inspect cache.", "delegated_single_action_request"),
    ("The build agent must inspect cache.", "actor_modal"),
    ("check content-agnostic parser_state2.", "bare_imperative"),
    ("search for agents by skill.", "bare_imperative"),
])
def test_complete_positive_productions(text, shape):
    assert accepted(text)["grammar_shape"] == shape


@pytest.mark.parametrize("prefix", ["agent must", "the agent is required to", "must", "required:", "please ask agent to"])
def test_opaque_verbs_in_explicit_grammar_positions_are_not_predicted_slots(prefix):
    report = accepted(f"{prefix} quasarify cache.")
    for key in ("actor", "action", "object", "modality", "frame", "expected_frame", "normalized_instruction"):
        assert key not in report


@pytest.mark.parametrize("text", ["quasarify cache.", "please quasarify cache.", "flurbit report."])
def test_unknown_bare_verbs_are_policy_abstentions_not_claims_of_incorrect_meaning(text):
    report = rejected(text)
    assert report["reasons"] == ["bare_action_unclassified_by_policy"]
    assert report["source_semantics_verified"] is False


@pytest.mark.parametrize("object_", [
    "the if statement", "a when clause", "an or operator", "unless condition",
    "the before keyword", "the after token", "the then branch", "while loops",
    "the not expression", "the required guard",
])
def test_whole_object_keyword_mentions_do_not_become_instruction_conditions(object_):
    accepted("read " + object_ + ".")


@pytest.mark.parametrize("text", [
    "if tests pass inspect cache.", "If tests pass inspect cache.",
    "when ready inspect cache.", "Unless allowed delete cache.",
    "before deployment inspect cache.", "after testing deploy application.",
    "while builds run inspect cache.", "once ready deploy application.",
    "given permission inspect cache.", "then inspect cache.", "first inspect cache.",
    "finally deploy application.", "otherwise inspect cache.",
    "read cache if tests pass.", "read cache when ready.", "read cache unless empty.",
    "read cache until tests pass.", "read cache before deployment.",
    "read cache after deployment.", "read cache provided permission.",
    "read cache without authorization.", "read cache except credentials.",
    "read cache then inspect logs.", "read cache and inspect logs.",
    "read cache or logs.", "read either cache.", "read both logs.",
    "read cache but preserve logs.", "read cache while tests run.",
    "read cache if condition.", "read the if statement when ready.",
    "read the if statement and the when clause.",
])
def test_conditional_workflow_coordination_and_exception_scopes_abstain(text):
    rejected(text)


@pytest.mark.parametrize("text", [
    "Archive audit records alternatively compare checksum manifests.",
    "archive notes alternatively compare manifests.",
    "agent must archive notes alternatively compare manifests.",
    "required: archive notes alternatively compare manifests.",
])
def test_explicit_alternative_actions_abstain_under_v2_development_regression(text):
    # The first example was disclosed after the frozen independent challenge.
    # These are development regressions, not new blind evaluation examples.
    report = rejected(text)
    assert report["policy_id"] == "intent-single-action-lowercase-grammar/v2"
    assert report["reasons"] == ["object_contains_coordination_or_disjunction"]


def test_alternative_keyword_mention_preserves_opaque_object_scope():
    report = accepted("read the alternatively keyword.")
    assert report["source_semantics_verified"] is False
    assert all(value is False for key, value in report.items() if key.endswith("_authority"))


@pytest.mark.parametrize("text", [
    "read all records.", "read any record.", "read every record.", "read each record.",
    "read no records.", "read only records.", "read these records.", "read its contents.",
    "read that cache.", "inspect the previous result.", "inspect the same cache.",
    "read the cache that failed.", "read logs which failed.",
    "read the cache to inspect logs.", "read logs as needed.",
    "you must inspect cache.", "they should inspect cache.", "their agent must inspect cache.",
    "the previous agent must inspect cache.", "agent must inspect our cache.",
])
def test_reference_quantifier_and_subordinate_scope_limits_are_explicit(text):
    rejected(text)


@pytest.mark.parametrize("text", [
    "agent may not delete cache.", "agent should not delete cache.",
    "agent could inspect cache.", "agent can inspect cache.", "agent might inspect cache.",
    "may not delete cache.", "should not delete cache.", "must never delete cache.",
    "please must inspect cache.", "required: may inspect cache.",
    "required: do not inspect cache.", "must agent inspect cache.",
    "agent does not inspect cache.", "agent inspected cache.",
])
def test_unsupported_negation_ability_nested_modals_and_descriptions_are_not_collapsed(text):
    rejected(text)


@pytest.mark.parametrize("text", [
    "can you inspect cache?", "can you inspect cache", "Could agent inspect cache.",
    "would you inspect cache.", "why inspect cache.", "inspect cache?", "what failed.",
    "read `cache`.", "read cache.py.", "read /tmp/cache.", "read cache[0].",
    "read cache; delete logs.", "read cache, inspect logs.", "read cache. inspect logs.",
    "read cache\ninspect logs.", "read cache\rinspect logs.", "- read cache.", "1. read cache.",
    "required: required: read cache.", "allowed: read cache.", "read cache!", "read 'cache'.",
    "read <unk>.", "<encode> read cache.", "read <actor> agent.", "read foo(bar).",
    "read cache | inspect logs.", "read cache && inspect logs.", "read cache\\logs.",
])
def test_questions_code_reserved_tokens_and_unconsumed_structure_abstain(text):
    rejected(text)


@pytest.mark.parametrize("text", [
    "Agent must inspect cache.", "Opaqueactor must inspect cache.", "Read must inspect cache.",
    "READ cache.", "read Cache.", "read cacheID.", "read HTTP headers.", "the Agent must read cache.",
    "required: Read cache.", "read _cache.", "read cache_.", "read cache--entry.",
    "read 123.", "read café.", "read cache\x00.", "read cache\x7f.", "read \ud800.",
])
def test_identifier_case_lexical_shape_and_unicode_are_not_silently_folded(text):
    rejected(text)


def test_codec_bounds_for_actor_object_and_original_instruction():
    accepted("red build service agent must inspect cache.")
    rejected("small red build service agent must inspect cache.")
    accepted("inspect " + " ".join(["record"] * 12) + ".")
    rejected("inspect " + " ".join(["record"] * 13) + ".")
    accepted("inspect " + "x" * 160 + ".")
    rejected("inspect " + "x" * 161 + ".")
    assert rejected("inspect " + "record " * 48)["reasons"] == ["instruction_word_limit"]
    assert rejected(" " * 4096 + "read cache")["reasons"] == ["instruction_character_limit"]


@pytest.mark.parametrize("text", ["", " ", "\n\t "])
def test_empty_text_retains_fail_open_report(text):
    assert rejected(text)["reasons"] == ["empty_instruction"]


@pytest.mark.parametrize("value", [None, 1, False, b"read cache", ["read cache"]])
def test_nonstring_is_an_api_error(value):
    with pytest.raises(ValueError, match="exact original instruction"):
        scope.assess_intent_instruction_scope(value)


def test_source_binding_authority_and_no_target_or_model_operations():
    text = " \tPlease\t inspect   cached records. \n"
    report = accepted(text)
    assert report["instruction_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["instruction_bytes"] == len(text.encode())
    assert report["instruction_chars"] == len(text)
    assert report["normalization"] == ["strip_outer_whitespace", "collapse_horizontal_whitespace",
                                        "lowercase_recognized_initial_grammar_token"]
    assert report["continue_planning"] is report["raw_instruction_preserved"] is True
    assert report["training_steps"] == report["provider_calls"] == report["download_calls"] == 0
    assert all(value is False for key, value in report.items() if key.endswith("_authority"))
    assert report["source_semantics_verified"] is False
    assert report["scope_limits"] == list(scope.POLICY_SCOPE_LIMITS)
    assert not any(key in report for key in ("frame", "target", "slots", "actor", "action", "object", "modality"))
    with pytest.raises(ValueError, match="differs"):
        scope.validate_instruction_scope_report(report, instruction=text.strip())


@pytest.mark.parametrize("key,value", [
    ("policy_id", "other-policy"), ("policy_sha256", "a" * 64), ("producer_sha256", "b" * 64),
    ("eligible_for_inference", True), ("status", "within_declared_single_action_grammar"),
    ("reasons", []), ("complete_consumption", True), ("grammar_shape", "actor_modal"),
    ("proof_authority", True), ("execution_authority", True), ("omission_authority", True),
    ("semantic_correctness_authority", True), ("source_semantics_verified", True),
    ("instruction_bytes", 0), ("instruction_sha256", "c" * 64), ("scope_limits", []),
    ("normalization", ["delete_unmatched_suffix"]), ("provider_calls", False),
])
def test_rehashed_report_mutations_still_fail_source_policy_replay(key, value):
    text = "read cache if ready."
    report = scope.assess_intent_instruction_scope(text)
    report[key] = value
    report.pop("report_sha256")
    report["report_sha256"] = scope._sha(scope._wire(report))
    with pytest.raises(ValueError, match="differs"):
        scope.validate_instruction_scope_report(report, instruction=text)


def test_policy_mutation_does_not_modify_assessment_and_unknown_report_fields_fail():
    before = accepted("inspect cache.")
    policy = scope.instruction_scope_policy()
    policy["bare_actions"].append("arbitrary")
    policy["scope_limits"].clear()
    assert accepted("inspect cache.") == before
    assert "arbitrary" not in scope.instruction_scope_policy()["bare_actions"]
    report = deepcopy(before)
    report["target"] = {"object": "cache"}
    with pytest.raises(ValueError, match="differs"):
        scope.validate_instruction_scope_report(report, instruction="inspect cache.")
    report = deepcopy(before)
    report["provider_calls"] = float("nan")
    with pytest.raises(ValueError, match="canonical JSON"):
        scope.validate_instruction_scope_report(report, instruction="inspect cache.")


def test_json_roundtrip_and_full_digest_are_replayable():
    report = accepted("read cache.")
    saved = json.loads(json.dumps(report))
    assert scope.validate_instruction_scope_report(saved, instruction="read cache.") == report
    digest = report.pop("report_sha256")
    assert digest == scope._sha(scope._wire(report))
