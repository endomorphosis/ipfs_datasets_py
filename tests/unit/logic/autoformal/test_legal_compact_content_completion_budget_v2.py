"""Pure authored grammar controls; no Torch, checkpoint, scores from a model or fit.

The saved-generation regression is independently written from the retained
prefix metadata: or/or/or and or/and/and,100 new IDs, a binary predicate context.
References below are independent completion witnesses, never policy inputs.
"""
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as legacy
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v2 as subject
from tests.unit.logic.autoformal import test_legal_compact_content_completion_budget_v1 as authored


HEADER = '{"schema":"legal-relational-compact-content/v1","tree":'
WITNESS_CASES = ("unary", "repeated_binary_arguments", "nested_scope", "sibling_scope", "all_predicates")


@pytest.fixture
def codec():
    return authored.tokens.build_compact_content_token_codec_v1()


def options(ctx, codec):
    return authored.options(ctx, codec)


def prefix(ids, ctx, codec, remaining, horizon=8):
    raw, kwargs = options(ctx, codec)
    return subject.allowed_token_ids(ids, raw, remaining_new_tokens=remaining,
                                     max_forced_tokens=horizon, **kwargs)


def old_prefix(ids, ctx, codec, remaining):
    raw, kwargs = options(ctx, codec)
    return legacy.allowed_token_ids(ids, raw, remaining_new_tokens=remaining, **kwargs)


def select(scores, ids, ctx, codec, remaining, horizon=8):
    raw, kwargs = options(ctx, codec)
    return subject.select_token(scores, ids, raw, remaining_new_tokens=remaining,
                                max_forced_tokens=horizon, **kwargs)


def choice(report, token_id):
    return next(row for row in report["candidate_lookahead"] if row["token_id"] == token_id)


def retained_constructor_prefix(codec, middle="or"):
    return authored.lexical_ids(HEADER + '["or",["' + middle + '",[', codec)


def no_authority(report):
    assert all(value is False for value in report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["global_completability_proven"] is False


def test_api_has_only_old_inputs_and_explicit_bounded_forced_horizon():
    common = {"prefix_ids", "context_raw", "expected_context_sha256", "codec",
              "expected_codec_sha256", "remaining_new_tokens", "max_forced_tokens"}
    assert set(inspect.signature(subject.allowed_token_ids).parameters) == common
    assert set(inspect.signature(subject.select_token).parameters) == common | {"logits"}
    for function in (subject.allowed_token_ids, subject.select_token):
        parameter = inspect.signature(function).parameters["max_forced_tokens"]
        assert parameter.kind == inspect.Parameter.KEYWORD_ONLY and parameter.default == 8
    assert subject.MAX_FORCED_TOKENS == 16


@pytest.mark.parametrize("mode,middle,constructor", [
    ("every_step", "or", "or"), ("first_step", "and", "and")],
    ids=["retained_or_or_or", "retained_or_and_and"])
def test_saved_third_binary_choice_reaches_empty_frontier_after_exactly_two_forced_tokens(
        mode, middle, constructor, codec):
    ctx = authored.context((2,))
    ids = retained_constructor_prefix(codec, middle)
    assert len(ids) == 15  # BOS plus14 emitted IDs;86 remain in the100-ID cap.
    candidate = authored.token('"' + constructor + '"', codec)
    baseline = old_prefix(ids, ctx, codec, 86)
    assert candidate in baseline["allowed_token_ids"]
    old_cost = next(x for x in baseline["candidate_bounds"] if x["token_id"] == candidate)
    assert old_cost["minimum_tokens_with_choice"] == 86
    report = prefix(ids, ctx, codec, 86, 2)
    row = choice(report, candidate)
    assert candidate not in report["allowed_token_ids"]
    assert row["disposition"] == "remove_proven_dead_end"
    assert row["forced_token_ids"] == [authored.token(",", codec), authored.token("[", codec)]
    assert row["prefix_inspections"] == 3
    assert row["terminal_prefix_ids"] == ids + [candidate] + row["forced_token_ids"]
    assert len(row["terminal_prefix_ids"]) == 18 and row["terminal_remaining_new_tokens"] == 83
    assert row["terminal_allowed_token_ids"] == []
    assert row["terminal_reason"] == "no_scope_continuation_within_remaining_budget"
    assert row["completion_witness"] is None
    assert report["baseline_prefix_report"] == baseline
    assert set(report["allowed_token_ids"]) <= set(baseline["allowed_token_ids"])
    no_authority(report)


def test_one_forced_token_horizon_retains_the_same_binary_as_unknown(codec):
    ctx = authored.context((2,))
    ids = retained_constructor_prefix(codec)
    candidate = authored.token('"or"', codec)
    report = prefix(ids, ctx, codec, 86, 1)
    row = choice(report, candidate)
    assert candidate in report["allowed_token_ids"]
    assert row["disposition"] == "keep_unknown" and row["reason"] == "forced_token_horizon"
    assert row["forced_token_ids"] == [authored.token(",", codec)]
    assert row["terminal_remaining_new_tokens"] == 84 and row["prefix_inspections"] == 2
    assert row["completion_witness"] is None


def test_already_blocked_retained_seventeen_id_prefix_is_preserved_not_repaired(codec):
    ctx = authored.context((2,))
    ids = authored.lexical_ids(HEADER + '["or",["or",["or",[', codec)
    assert len(ids) == 18
    report = prefix(ids, ctx, codec, 83, 8)
    assert report["offered_ids"] == ids and report["allowed_token_ids"] == []
    assert report["candidate_lookahead"] == [] and report["prefix_inspections"] == 1
    assert report["baseline_prefix_report"]["prefix_lower_bound"]["minimum_additional_tokens"] == 83
    assert report["reason"] == "no_scope_continuation_within_remaining_budget"


@pytest.mark.parametrize("kind", ["bos", "binary_choice", "blocked", "complete"],
                         ids=["bos", "binary_choice", "blocked", "complete"])
def test_zero_horizon_is_exact_old_choice_mask_passthrough_without_witness(kind, codec):
    ctx = authored.context((2,))
    complete = authored.ids_for(["forall", 0, authored.atom(variables=(0, 0))], codec)
    ids, remaining = {
        "bos": ([1], 100), "binary_choice": (retained_constructor_prefix(codec), 86),
        "blocked": (authored.lexical_ids(HEADER + '["or",["or",["or",[', codec), 83),
        "complete": (complete, 0),
    }[kind]
    baseline = old_prefix(ids, ctx, codec, remaining)
    report = prefix(ids, ctx, codec, remaining, 0)
    assert report["baseline_prefix_report"] == baseline
    assert report["allowed_token_ids"] == baseline["allowed_token_ids"]
    assert report["status"] == baseline["status"] and report["reason"] == baseline["reason"]
    assert report["prefix_inspections"] == 1 and report["typed_witness_inspections"] == 0
    assert report["prefix_completion_witness"] is None
    assert all(x["reason"] == "lookahead_disabled" and x["prefix_inspections"] == 0
               and x["terminal_prefix_ids"] is None and x["completion_witness"] is None
               for x in report["candidate_lookahead"])


def test_branchpoint_stops_without_search_or_completion_claim(codec):
    ctx = authored.context((2,))
    report = prefix([1], ctx, codec, 100, 8)
    row = choice(report, authored.token("{", codec))
    assert row["reason"] == "original_branchpoint" and row["disposition"] == "keep_unknown"
    assert len(row["terminal_allowed_token_ids"]) > 1 and len(row["forced_token_ids"]) == 7
    assert row["completion_witness"] is None
    assert report["branch_search_performed"] is report["model_or_future_score_queries"] is False
    no_authority(report)


def test_unknown_old_lower_bound_does_not_become_a_completion_or_dead_end(codec, monkeypatch):
    monkeypatch.setattr(legacy, "_completion_lower_bound",
                        lambda *args: legacy._unknown("authored_unknown_bound"))
    report = prefix([1], authored.context(), codec, 100, 1)
    row = choice(report, authored.token("{", codec))
    assert report["baseline_prefix_report"]["prefix_lower_bound"]["status"] == "unknown"
    assert row["disposition"] == "keep_unknown" and row["reason"] == "forced_token_horizon"
    assert row["completion_witness"] is None and report["removed_token_ids"] == []
    no_authority(report)


@pytest.mark.parametrize("name", WITNESS_CASES, ids=list(WITNESS_CASES))
def test_every_prefix_preserves_an_independent_typed_exact_budget_witness(name, codec):
    name, ctx, tree = next(row for row in authored.witnessed_corpus() if row[0] == name)
    complete = authored.ids_for(tree, codec)
    for position, expected in enumerate(complete):
        offered, remaining = complete[:position], len(complete) - position
        report = prefix(offered, ctx, codec, remaining, 2)
        assert expected in report["allowed_token_ids"], (name, position, expected)
        assert set(report["allowed_token_ids"]) <= set(report["baseline_prefix_report"]["allowed_token_ids"])
        no_authority(report)
    raw, kwargs = options(ctx, codec)
    decoded = authored.tokens.decode_compact_content_tokens_v1(complete, raw, **kwargs)
    assert decoded["status"] == "valid_candidate" and decoded["prediction"]["content"] == authored.document(tree)


def test_scored_eos_is_a_terminal_witness_not_an_empty_frontier(codec):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    report = prefix(complete[:-1], ctx, codec, 1, 1)
    assert report["allowed_token_ids"] == [2]
    row = choice(report, 2)
    assert row["disposition"] == "keep_witness" and row["forced_token_ids"] == []
    assert row["terminal_remaining_new_tokens"] == 0 and row["terminal_status"] == "complete"
    assert row["completion_witness"]["token_ids"] == complete
    assert row["completion_witness"]["model_generated_completion"] is False


def test_forced_eos_counts_once_and_is_not_appended_to_the_selected_prefix(codec):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    offered = complete[:-2]
    report = prefix(offered, ctx, codec, 2, 1)
    closing = authored.token("}", codec)
    row = choice(report, closing)
    assert row["forced_token_ids"] == [2] and row["terminal_remaining_new_tokens"] == 0
    assert row["completion_witness"]["token_ids"] == complete
    scores = [-4.0] * 537
    selected = select(scores, offered, ctx, codec, 2, 1)
    assert selected["selected_token_id"] == closing
    assert selected["next_prefix_ids"] == offered + [closing]
    assert selected["tokens_appended"] == 1 and selected["logits"] == scores


def test_existing_terminal_prefix_requires_actual_typed_eos_witness(codec):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    report = prefix(complete, ctx, codec, 0, 1)
    assert report["status"] == "complete" and report["allowed_token_ids"] == []
    assert report["prefix_completion_witness"]["token_ids"] == complete
    body = prefix(complete[:-1], ctx, codec, 0, 1)
    assert body["status"] != "complete" and body["prefix_completion_witness"] is None


def test_complete_prefix_cannot_claim_witness_if_original_typed_decoder_disagrees(codec, monkeypatch):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    real = authored.tokens.decode_compact_content_tokens_v1

    def disagree(*args, **kwargs):
        result = real(*args, **kwargs)
        result["status"] = "rejected"
        return result

    monkeypatch.setattr(authored.tokens, "decode_compact_content_tokens_v1", disagree)
    with pytest.raises(ValueError, match="typed witness disagree"):
        prefix(complete[:-1], ctx, codec, 1, 1)


def test_full_scores_are_preserved_when_old_best_choice_is_removed(codec):
    ctx = authored.context((2,))
    ids = retained_constructor_prefix(codec)
    removed = authored.token('"or"', codec)
    scores = [-3.0] * 537
    scores[removed] = 100.0
    result = select(scores, ids, ctx, codec, 86, 2)
    assert result["baseline_selection"]["selected_token_id"] == removed
    assert removed not in result["prefix_report"]["allowed_token_ids"]
    assert result["selected_token_id"] == min(result["prefix_report"]["allowed_token_ids"])
    assert result["logits"] == scores and result["tie_breaker"] == "lowest_token_id"
    assert result["next_prefix_ids"] == ids + [result["selected_token_id"]]
    assert result["tokens_appended"] == 1


@pytest.mark.parametrize("bad", [True, -1, 17, 1.0, None, "2"],
                         ids=["boolean", "negative", "over16", "float", "null", "text"])
def test_horizon_is_plain_bounded_integer_before_probing(bad, codec):
    with pytest.raises(ValueError, match="max_forced_tokens"):
        prefix([1], authored.context(), codec, 100, bad)


@pytest.mark.parametrize("bad", [True, -1, 513, 1.0],
                         ids=["boolean", "negative", "over512", "float"])
def test_original_remaining_budget_validation_is_preserved(bad, codec):
    with pytest.raises(ValueError):
        prefix([1], authored.context(), codec, bad, 2)


def test_maximum_horizon_and_effective_total_limit_stay_with_original_owner(codec):
    report = prefix([1], authored.context(), codec, 512, 16)
    assert report["max_forced_tokens"] == 16 and report["effective_remaining_tokens"] == 511
    assert report["prefix_inspections"] <= subject.MAX_PREFIX_INSPECTIONS
    assert max((len(x["forced_token_ids"]) for x in report["candidate_lookahead"]), default=0) <= 16


def test_nonfinite_score_is_rejected_even_when_no_choice_can_be_selected(codec):
    scores = [-1.0] * 537
    scores[536] = float("nan")
    with pytest.raises(ValueError):
        select(scores, [1], authored.context(), codec, 0, 2)


def test_context_hash_mismatch_remains_contract_failure(codec):
    raw, kwargs = options(authored.context(), codec)
    kwargs["expected_context_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        subject.allowed_token_ids([1], raw, remaining_new_tokens=100, **kwargs)


def test_codec_mutation_is_not_interpreted_as_a_search_dead_end(codec):
    raw, kwargs = options(authored.context(), codec)
    changed = deepcopy(codec)
    changed["vocabulary"][3] = "invented"
    kwargs["codec"] = changed
    with pytest.raises(ValueError):
        subject.allowed_token_ids([1], raw, remaining_new_tokens=100, **kwargs)


def test_original_owner_exception_propagates_instead_of_removing_a_choice(codec, monkeypatch):
    real = legacy.allowed_token_ids
    calls = 0

    def failed_probe(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("original_probe_failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(legacy, "allowed_token_ids", failed_probe)
    with pytest.raises(RuntimeError, match="original_probe_failure"):
        prefix([1], authored.context(), codec, 100, 2)


def test_original_selection_disagreement_refuses(codec, monkeypatch):
    real = legacy.select_token

    def disagree(*args, **kwargs):
        result = real(*args, **kwargs)
        result["prefix_report"]["reason"] = "contradictory_original_report"
        return result

    monkeypatch.setattr(legacy, "select_token", disagree)
    with pytest.raises(ValueError, match="disagree"):
        select([-1.0] * 537, [1], authored.context(), codec, 100, 0)


def test_caller_mutation_during_nested_owner_call_is_detected(codec, monkeypatch):
    offered = [1]
    raw, kwargs = options(authored.context(), codec)
    real = legacy.allowed_token_ids

    def mutate(*args, **inner):
        result = real(*args, **inner)
        offered.append(3)
        return result

    monkeypatch.setattr(legacy, "allowed_token_ids", mutate)
    with pytest.raises(ValueError, match="changed|differ"):
        subject.allowed_token_ids(offered, raw, remaining_new_tokens=100,
                                  max_forced_tokens=0, **kwargs)


def test_new_source_pin_failure_refuses_before_policy_work(codec, monkeypatch):
    monkeypatch.setattr(subject, "_LEGACY_SHA", "0" * 64)
    with pytest.raises(ValueError, match="pinned canonical"):
        prefix([1], authored.context(), codec, 100, 2)


def test_input_and_returned_observations_are_detached(codec):
    offered = retained_constructor_prefix(codec)
    ctx = authored.context((2,))
    original_ids, original_context, original_codec = deepcopy(offered), deepcopy(ctx), deepcopy(codec)
    first = prefix(offered, ctx, codec, 86, 2)
    first["allowed_token_ids"].clear()
    first["baseline_prefix_report"]["allowed_token_ids"].clear()
    first["candidate_lookahead"][0]["forced_token_ids"].append(536)
    second = prefix(offered, ctx, codec, 86, 2)
    assert offered == original_ids and ctx == original_context and codec == original_codec
    assert second["allowed_token_ids"] and second["baseline_prefix_report"]["allowed_token_ids"]


def test_old_policy_and_generation_runtime_bytes_remain_unchanged():
    source = Path(legacy.__file__).absolute()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7"
    runtime = source.with_name("legal_compact_content_persistent_runtime_v1.py")
    assert hashlib.sha256(runtime.read_bytes()).hexdigest() == "1978436fed3bbee1b97ad3e720fc54806fa078d98bb91adac9b26ac212792615"
