"""Pure score-to-witness bridge controls; the qualified search engine is reused.

These tests exercise the adapter, not another41-case search qualification.
Fictional typed fixtures are witnesses only; no model or legal gold is supplied.
"""
from copy import deepcopy
import hashlib
import inspect
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as legacy
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v3 as witness
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_branch_selection_v1 as subject
from tests.unit.logic.autoformal import test_legal_compact_content_completion_budget_v1 as authored


@pytest.fixture
def codec():
    return authored.tokens.build_compact_content_token_codec_v1()


def select(scores, ids, ctx, codec, remaining=100, **bounds):
    raw, options = authored.options(ctx, codec)
    return subject.select_token(scores, ids, raw, remaining_new_tokens=remaining,
                                **options, **bounds)


def frame(kind, codec):
    ctx = authored.context((1, 1))
    lexical = authored.HEADER + '["forall",0,'
    if kind == "viable_after_dead":
        lexical += '["and",' + authored.wire(authored.atom()).decode() + ','
    elif kind == "both_viable":
        lexical += ('["and",' + authored.wire(authored.atom()).decode() + ',["and",'
                    + authored.wire(authored.atom(1)).decode() + ',')
    ids = authored.lexical_ids(lexical + '["predicate",', codec)
    zero, one = authored.token("0", codec), authored.token("1", codec)
    scores = [-9.0] * 537
    scores[zero], scores[one] = 50.0, 40.0
    return ctx, ids, scores, zero, one


def outcome(report, token):
    return next(row for row in report["candidate_results"] if row["token_id"] == token)


def observe_work(monkeypatch):
    observed = dict(frontiers=[], searches=[])
    real_frontier, real_search = legacy.allowed_token_ids, witness.find_completion_witness

    def frontier(*args, **kwargs):
        observed["frontiers"].append((list(args[0]), kwargs["remaining_new_tokens"]))
        return real_frontier(*args, **kwargs)

    def search(*args, **kwargs):
        report = real_search(*args, **kwargs)
        observed["searches"].append(dict(prefix=list(args[0]), options=dict(kwargs), report=report))
        return report

    monkeypatch.setattr(legacy, "allowed_token_ids", frontier)
    monkeypatch.setattr(witness, "find_completion_witness", search)
    return observed


def conserved(report, scores, ids, cap, observed=None):
    baseline = report["baseline_prefix_report"]["allowed_token_ids"]
    rows = report["candidate_results"]
    assert [row["token_id"] for row in rows] == sorted(baseline, key=lambda token: (-scores[token], token))
    assert set(report["allowed_token_ids"]) <= set(baseline)
    assert report["root_prefix_inspections"] == 1
    assert report["actual_prefix_inspections"] == 1 + report["candidate_prefix_inspections"]
    assert 1 <= report["actual_prefix_inspections"] <= cap
    assert report["remaining_prefix_inspections"] == cap - report["actual_prefix_inspections"]
    assert report["candidate_prefix_inspections"] == sum(row["actual_prefix_inspections"] for row in rows)
    assert report["witness_calls"] == sum(row["queried"] is True for row in rows)
    assert report["offered_prefix_ids"] == ids and report["logits"] == scores
    assert report["logits_sha256"] == authored.sha(authored.wire(scores))
    assert report["certificate_bytes"] <= report["report_caps"]["certificate_bytes"]
    assert report["certificate_items"] <= report["report_caps"]["certificate_items"]
    assert all(value is False for value in report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    for row in rows:
        if row["disposition"] == "remove_proven_dead_end":
            assert row["queried"] is row["certificate_retained"] is True
            assert row["search_status"] == "DEAD_END"
            certificate = report["certificates"][row["certificate_index"]]
            assert certificate["status"] == "DEAD_END" and certificate["frontier_closed"] is True
        if row["certificate_retained"]:
            certificate = report["certificates"][row["certificate_index"]]
            assert row["certificate_sha256"] == authored.sha(authored.wire(certificate))
            assert certificate["actual_prefix_inspections"] == row["actual_prefix_inspections"]
        if not row["queried"]:
            assert row["disposition"] == "keep_unqueried" and row["actual_prefix_inspections"] == 0
            assert row["certificate_index"] is None and row["certificate_retained"] is False
    removed = {row["token_id"] for row in rows if row["disposition"] == "remove_proven_dead_end"}
    assert set(report["allowed_token_ids"]) == set(baseline) - removed
    if observed is not None:
        assert len(observed["frontiers"]) == report["actual_prefix_inspections"]
        assert len(observed["searches"]) == report["witness_calls"]
        assert sum(row["report"]["actual_prefix_inspections"] for row in observed["searches"]) == report["candidate_prefix_inspections"]
        allowance = cap - 1
        for row in observed["searches"]:
            assert row["options"]["max_prefix_inspections"] == allowance and allowance > 0
            assert row["options"]["remaining_new_tokens"] == report["baseline_prefix_report"]["remaining_new_tokens"] - 1
            assert row["prefix"][:-1] == ids
            allowance -= row["report"]["actual_prefix_inspections"]


def test_api_adds_only_one_scored_selection_over_the_existing_bounded_witness_inputs():
    assert set(inspect.signature(subject.select_token).parameters) == {
        "logits", "prefix_ids", "context_raw", "expected_context_sha256", "codec",
        "expected_codec_sha256", "remaining_new_tokens", "max_prefix_inspections",
        "max_search_depth", "max_frontier_nodes"}
    parameters = inspect.signature(subject.select_token).parameters
    for name, default in (("max_prefix_inspections", 256), ("max_search_depth", 512),
                          ("max_frontier_nodes", 512)):
        assert parameters[name].kind == inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default == default


def test_highest_scored_dead_predicate_is_removed_then_next_scored_typed_witness_selected(codec, monkeypatch):
    observed = observe_work(monkeypatch)
    ctx, ids, scores, zero, one = frame("viable_after_dead", codec)
    report = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    assert report["baseline_argmax_token_id"] == report["raw_argmax_token_id"] == zero
    assert outcome(report, zero)["disposition"] == "remove_proven_dead_end"
    assert outcome(report, one)["disposition"] == "keep_witness"
    assert report["selected_token_id"] == one and report["selected_score"] == scores[one]
    assert report["next_prefix_ids"] == ids + [one] and report["tokens_appended"] == 1
    certificate = report["certificates"][outcome(report, one)["certificate_index"]]
    expected = authored.ids_for(["forall", 0, ["and", authored.atom(), authored.atom(1)]], codec)
    assert certificate["witness"]["token_ids"] == expected
    conserved(report, scores, ids, 64, observed)


def test_root_only_budget_keeps_the_unqueried_highest_score_and_performs_no_witness_call(codec, monkeypatch):
    observed = observe_work(monkeypatch)
    ctx, ids, scores, zero, _ = frame("viable_after_dead", codec)
    report = select(scores, ids, ctx, codec, max_prefix_inspections=1)
    assert report["selected_token_id"] == zero
    assert outcome(report, zero)["disposition"] == "keep_unqueried"
    assert report["witness_calls"] == 0 and report["certificates"] == []
    assert report["allowed_token_ids"] == report["baseline_prefix_report"]["allowed_token_ids"]
    conserved(report, scores, ids, 1, observed)


def test_shared_budget_spent_proving_first_dead_never_resets_or_queries_next_with_zero_allowance(codec, monkeypatch):
    observed = observe_work(monkeypatch)
    ctx, ids, scores, zero, one = frame("viable_after_dead", codec)
    full = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    first = outcome(full, zero)
    assert first["disposition"] == "remove_proven_dead_end"
    cap = full["root_prefix_inspections"] + first["actual_prefix_inspections"]
    assert 1 < cap < full["actual_prefix_inspections"]
    observed["frontiers"].clear()
    observed["searches"].clear()
    limited = select(scores, ids, ctx, codec, max_prefix_inspections=cap)
    assert outcome(limited, zero)["disposition"] == "remove_proven_dead_end"
    assert outcome(limited, one)["disposition"] == "keep_unqueried"
    assert limited["selected_token_id"] == one
    assert limited["witness_calls"] == 1 and limited["remaining_prefix_inspections"] == 0
    conserved(limited, scores, ids, cap, observed)


def test_all_original_predicate_choices_proven_dead_returns_no_selection_with_valid_full_scores(codec, monkeypatch):
    observed = observe_work(monkeypatch)
    ctx, ids, scores, zero, one = frame("all_dead", codec)
    report = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    assert {row["token_id"] for row in report["candidate_results"]} == {zero, one}
    assert all(row["disposition"] == "remove_proven_dead_end" for row in report["candidate_results"])
    assert report["status"] == "no_selection" and report["selection_performed"] is False
    assert report["selected_token_id"] is report["selected_score"] is None
    assert report["allowed_token_ids"] == [] and report["tokens_appended"] == 0
    assert report["next_prefix_ids"] == ids
    conserved(report, scores, ids, 64, observed)


@pytest.mark.parametrize("kind", ["closing", "eos"])
def test_eos_and_a_probed_eos_witness_are_scored_without_injecting_a_completion_suffix(kind, codec):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    offered = complete[:-2] if kind == "closing" else complete[:-1]
    expected = complete[len(offered)]
    scores = [-4.0] * 537
    scores[536], scores[expected] = 100.0, 5.0
    report = select(scores, offered, ctx, codec, len(complete) - len(offered), max_prefix_inspections=8)
    assert report["raw_argmax_token_id"] == 536
    assert report["selected_token_id"] == expected and report["selected_score"] == 5.0
    assert report["next_prefix_ids"] == offered + [expected] and report["tokens_appended"] == 1
    row = outcome(report, expected)
    assert row["disposition"] == "keep_witness"
    certificate = report["certificates"][row["certificate_index"]]
    assert certificate["witness"]["token_ids"] == complete
    assert certificate["witness"]["model_generated_completion"] is False
    if kind == "closing":
        assert certificate["witness"]["suffix_token_ids"] == [2]
        assert 2 not in report["next_prefix_ids"]
    conserved(report, scores, offered, 8)


def test_equal_scored_valid_choices_keep_lowest_token_id_and_every_original_score(codec):
    ctx, ids, scores, zero, one = frame("both_viable", codec)
    scores[zero] = scores[one] = 5.0
    scores[536] = 100.0
    report = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    assert zero < one and report["selected_token_id"] == zero
    assert report["baseline_argmax_token_id"] == zero and report["raw_argmax_token_id"] == 536
    assert report["tie_breaker"] == "lowest_token_id" and report["logits"] == scores
    assert outcome(report, one)["disposition"] == "keep_unqueried"
    conserved(report, scores, ids, 64)


def test_one_actual_candidate_probe_unknown_retains_the_highest_score_without_pruning(codec, monkeypatch):
    observed = observe_work(monkeypatch)
    ctx, ids, scores, zero, _ = frame("viable_after_dead", codec)
    report = select(scores, ids, ctx, codec, max_prefix_inspections=2)
    row = outcome(report, zero)
    assert row["queried"] is True and row["actual_prefix_inspections"] == 1
    assert row["search_status"] == "UNKNOWN" and row["disposition"] == "keep_unknown"
    assert report["selected_token_id"] == zero
    assert report["allowed_token_ids"] == report["baseline_prefix_report"]["allowed_token_ids"]
    conserved(report, scores, ids, 2, observed)


@pytest.mark.parametrize("bound", ["MAX_CERTIFICATE_BYTES", "MAX_CERTIFICATE_ITEMS"],
                         ids=["certificate_byte_limit", "certificate_item_limit"])
def test_unretained_dead_certificate_is_charged_but_cannot_remove_the_highest_scored_choice(bound, codec, monkeypatch):
    observed = observe_work(monkeypatch)
    monkeypatch.setattr(subject, bound, 0)
    ctx, ids, scores, zero, _ = frame("viable_after_dead", codec)
    report = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    row = outcome(report, zero)
    assert observed["searches"][0]["report"]["status"] == "DEAD_END"
    assert row["queried"] is True and row["actual_prefix_inspections"] > 0
    assert row["observed_search_status"] == "DEAD_END" and row["search_status"] == "UNKNOWN"
    assert row["disposition"] == "keep_unknown" and row["reason"] == "certificate_report_limit"
    assert row["certificate_index"] is None and row["certificate_retained"] is False
    assert report["selected_token_id"] == zero and report["certificates"] == []
    assert report["omitted_certificates"] == 1
    assert report["allowed_token_ids"] == report["baseline_prefix_report"]["allowed_token_ids"]
    conserved(report, scores, ids, 64, observed)


@pytest.mark.parametrize("damage", ["short", "boolean", "nan", "unsafe_integer"])
def test_every_full_score_is_validated_before_any_candidate_witness_query_even_with_no_root_budget(
        damage, codec, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid score reached a witness query")

    monkeypatch.setattr(witness, "find_completion_witness", forbidden)
    scores = [-1.0] * 537
    if damage == "short":
        scores.pop()
    else:
        scores[536] = {"boolean": True, "nan": float("nan"), "unsafe_integer": 1 << 54}[damage]
    with pytest.raises(ValueError):
        select(scores, [1], authored.context(), codec, 0, max_prefix_inspections=1)


@pytest.mark.parametrize("name,bad", [
    ("max_prefix_inspections", True), ("max_prefix_inspections", 0), ("max_prefix_inspections", 1025),
    ("max_search_depth", True), ("max_frontier_nodes", 0),
], ids=["inspection_boolean", "inspection_zero", "inspection_over1024", "depth_boolean", "frontier_zero"])
def test_adapter_validates_analysis_controls_even_when_the_original_root_has_no_choice(name, bad, codec):
    with pytest.raises(ValueError):
        select([-1.0] * 537, [1], authored.context(), codec, 0, **{name: bad})


@pytest.mark.parametrize("kind", ["body_without_eos_budget", "already_complete"])
def test_empty_original_frontier_with_valid_scores_returns_none_and_never_queries_or_appends(kind, codec, monkeypatch):
    observed = observe_work(monkeypatch)
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    offered = complete[:-1] if kind == "body_without_eos_budget" else complete
    scores = [-1.0] * 537
    report = select(scores, offered, ctx, codec, 0, max_prefix_inspections=1)
    assert report["status"] == "no_selection" and report["selected_token_id"] is None
    assert report["selected_score"] is None and report["tokens_appended"] == 0
    assert report["next_prefix_ids"] == offered and report["witness_calls"] == 0
    assert report["candidate_results"] == report["certificates"] == []
    conserved(report, scores, offered, 1, observed)


@pytest.mark.parametrize("binding", ["context", "codec"])
def test_original_hash_custody_refuses_before_any_candidate_query(binding, codec, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("bad hash reached a witness query")

    monkeypatch.setattr(witness, "find_completion_witness", forbidden)
    raw, options = authored.options(authored.context(), codec)
    options["expected_" + binding + "_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.select_token([-1.0] * 537, [1], raw, remaining_new_tokens=100, **options)


def test_original_witness_exception_propagates_without_turning_into_unknown_or_a_pruned_choice(codec, monkeypatch):
    class AuthoredWitnessFailure(RuntimeError):
        pass

    def fail(*args, **kwargs):
        raise AuthoredWitnessFailure("authored unchanged witness owner failed")

    monkeypatch.setattr(witness, "find_completion_witness", fail)
    ctx, ids, scores, _, _ = frame("viable_after_dead", codec)
    with pytest.raises(AuthoredWitnessFailure, match="unchanged witness owner failed"):
        select(scores, ids, ctx, codec, max_prefix_inspections=64)


def test_new_selector_source_pin_failure_refuses_before_candidate_work(codec, monkeypatch):
    monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
    with pytest.raises(ValueError):
        select([-1.0] * 537, [1], authored.context(), codec)


def test_caller_score_mutation_during_actual_witness_work_is_refused_at_the_closing_fence(codec, monkeypatch):
    ctx, ids, scores, _, _ = frame("viable_after_dead", codec)
    real = witness.find_completion_witness

    def mutate(*args, **kwargs):
        result = real(*args, **kwargs)
        scores[536] = 123.0
        return result

    monkeypatch.setattr(witness, "find_completion_witness", mutate)
    with pytest.raises(ValueError, match="changed"):
        select(scores, ids, ctx, codec, max_prefix_inspections=64)


def test_closing_selector_source_pin_change_is_not_relabelled_as_a_proof_limit(codec, monkeypatch):
    ctx, ids, scores, _, _ = frame("viable_after_dead", codec)
    real = witness.find_completion_witness

    def mutate(*args, **kwargs):
        result = real(*args, **kwargs)
        monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
        return result

    monkeypatch.setattr(witness, "find_completion_witness", mutate)
    with pytest.raises(ValueError):
        select(scores, ids, ctx, codec, max_prefix_inspections=64)


def test_returned_candidate_and_certificate_observations_are_detached_from_inputs_and_next_call(codec):
    ctx, ids, scores, _, _ = frame("viable_after_dead", codec)
    snapshot = deepcopy((ctx, ids, scores))
    first = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    first["logits"][0] = 123.0
    first["allowed_token_ids"].append(536)
    first["candidate_results"][0]["disposition"] = "caller_mutation"
    first["certificates"][0]["trace"].append({"caller_mutation": True})
    second = select(scores, ids, ctx, codec, max_prefix_inspections=64)
    assert (ctx, ids, scores) == snapshot and second["logits"] == scores
    assert 536 not in second["allowed_token_ids"]
    assert all(row["disposition"] != "caller_mutation" for row in second["candidate_results"])
    assert all("caller_mutation" not in node for certificate in second["certificates"] for node in certificate["trace"])


def test_qualified_original_budget_and_witness_sources_remain_byte_exact():
    assert hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest() == "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7"
    assert hashlib.sha256(Path(witness.__file__).read_bytes()).hexdigest() == "38387c5573c42a03f41c99f6fbedf6a70f0755f3ac564990cafa481498c52e7f"
