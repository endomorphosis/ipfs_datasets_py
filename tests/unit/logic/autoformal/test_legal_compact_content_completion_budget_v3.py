"""Authored pure reachability certificates; no models, scores or semantic gold."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from . import test_legal_compact_content_completion_budget_v1 as authored
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v3 as subject


HELPER_SHA = "5f31d2c05057167a1b3aac624c9f87fc36ebea6987a00d96af159279679747ab"
codec = authored.codec


def helper_fence():
    path = Path(__file__).absolute().with_name("test_legal_compact_content_completion_budget_v1.py")
    assert type(authored.__file__) is str and Path(authored.__file__).absolute() == path
    assert path.resolve(strict=True) == path and path.stat().st_size == 15521
    assert hashlib.sha256(path.read_bytes()).hexdigest() == HELPER_SHA


@pytest.fixture(autouse=True)
def original_fixture_source_custody():
    helper_fence()
    yield
    helper_fence()


def find(ids, ctx, codec, remaining=100, **bounds):
    raw, options = authored.options(ctx, codec)
    return subject.find_completion_witness(ids, raw, remaining_new_tokens=remaining, **options, **bounds)


def mask_ids(encoded):
    assert type(encoded) is str and len(encoded) == 135 and encoded == encoded.lower()
    value = int(encoded, 16)
    assert value >> 537 == 0 and format(value, "0135x") == encoded
    return [token for token in range(537) if value & (1 << token)]


def certificate(report, ids, ctx, codec, remaining):
    assert report["offered_ids"] == ids
    assert report["actual_prefix_inspections"] == report["recorded_node_count"] + report["unrecorded_inspections"]
    assert report["actual_prefix_inspections"] <= report["max_prefix_inspections"]
    assert report["peak_frontier_nodes"] <= report["max_frontier_nodes"]
    assert report["recorded_node_count"] == len(report["trace"])
    assert report["trace_bytes"] <= report["report_caps"]["trace_bytes"]
    assert report["trace_items"] <= report["report_caps"]["trace_items"]
    assert len(authored.wire(report)) <= 2 * 1024**2
    assert report["global_completability_proven"] is False
    assert report["model_or_future_score_queries"] is False
    assert report["generated_token_selection_performed"] is False
    assert report["parser_subclassing"] is False
    assert all(value is False for value in report["authority"].values())
    raw, options = authored.options(ctx, codec)
    assert report["codec_sha256"] == options["expected_codec_sha256"]
    assert report["context_raw_sha256"] == options["expected_context_sha256"]
    prefixes, observations = {}, {}
    for node in report["trace"]:
        number, parent = node["node_id"], node["parent_id"]
        if parent is None:
            assert number == 0 and node["via_token_id"] is None
            offered = list(ids)
        else:
            assert parent in prefixes and node["via_token_id"] in observations[parent]["allowed_token_ids"]
            offered = prefixes[parent] + [node["via_token_id"]]
        assert node["depth"] == len(offered) - len(ids)
        assert node["remaining_new_tokens"] == remaining - node["depth"]
        old = authored.prefix(offered, ctx, codec, remaining - node["depth"])
        assert mask_ids(node["allowed_mask_hex"]) == sorted(old["allowed_token_ids"])
        assert node["allowed_count"] == len(old["allowed_token_ids"])
        assert (node["status"], node["reason"]) == (old["status"], old["reason"])
        assert node["effective_remaining_tokens"] == old["effective_remaining_tokens"]
        assert node["bound_status"] == old["prefix_lower_bound"]["status"]
        assert node["minimum_additional_tokens"] == old["prefix_lower_bound"]["minimum_additional_tokens"]
        assert node["owner_report_sha256"] == authored.sha(authored.wire(old))
        costs = {row["token_id"]: row["minimum_tokens_with_choice"] for row in old["candidate_bounds"]}
        ordered = sorted(old["allowed_token_ids"], key=lambda token: (costs[token], token))
        assert node["ordering_sha256"] == authored.sha(authored.wire(ordered))
        prefixes[number], observations[number] = offered, old
    if report["status"] == "WITNESS":
        witness = report["witness"]
        assert witness["token_ids"] == prefixes[witness["node_id"]]
        assert witness["suffix_token_ids"] == witness["token_ids"][len(ids):]
        assert len(witness["suffix_token_ids"]) <= remaining
        raw, options = authored.options(ctx, codec)
        decoded = authored.tokens.decode_compact_content_tokens_v1(witness["token_ids"], raw, **options)
        assert decoded["status"] == "valid_candidate" and decoded["framing"]["eos_terminal"]
        assert decoded["generated_content_sha256"] == witness["generated_content_sha256"]
        assert witness["typed_report_sha256"] == authored.sha(authored.wire(decoded))
        assert witness["counts"] == decoded["counts"]
        assert witness["model_generated_completion"] is False and witness["syntactic_only"] is True
    elif report["status"] == "DEAD_END":
        assert report["witness"] is None and report["unresolved_frontier_root_count"] == 0
        assert report["frontier_closed"] and report["exhaustive_relative_to_original_policy"]
        assert report["pending_nodes"] == report["unexpanded_parents"] == []
        for node in report["trace"]:
            children = [child["via_token_id"] for child in report["trace"] if child["parent_id"] == node["node_id"]]
            assert sorted(children) == sorted(observations[node["node_id"]]["allowed_token_ids"])
    else:
        assert report["status"] == "UNKNOWN" and report["witness"] is None
        assert report["unresolved_frontier_root_count"] > 0
        assert not report["frontier_closed"] and not report["exhaustive_relative_to_original_policy"]


def two_predicate_prefix(codec, *, first_atom=False):
    lexical = authored.HEADER + '["forall",0,'
    if first_atom:
        lexical += '["and",' + authored.wire(authored.atom()).decode() + ','
    return authored.lexical_ids(lexical + '["predicate",', codec)


def forced_dead_length(ids, token, ctx, codec, remaining):
    """Independent finite single-chain oracle after one authored index choice."""
    offered, count = ids + [token], 0
    for _ in range(40):
        old = authored.prefix(offered, ctx, codec, remaining - len(offered) + len(ids))
        count += 1
        assert old["status"] != "complete"
        if not old["allowed_token_ids"]:
            return count
        assert len(old["allowed_token_ids"]) == 1
        offered.append(old["allowed_token_ids"][0])
    raise AssertionError("authored finite single-chain oracle exceeded its bound")


def test_api_is_only_pure_witness_search_with_explicit_hard_caps():
    assert set(inspect.signature(subject.find_completion_witness).parameters) == {
        "prefix_ids", "context_raw", "expected_context_sha256", "codec", "expected_codec_sha256",
        "remaining_new_tokens", "max_prefix_inspections", "max_search_depth", "max_frontier_nodes"}
    assert not hasattr(subject, "allowed_token_ids") and not hasattr(subject, "select_token")
    assert subject.DEFAULT_MAX_PREFIX_INSPECTIONS == 256 and subject.MAX_PREFIX_INSPECTIONS == 1024
    assert subject.MAX_REPORT_BYTES == 2 * 1024**2 and subject.MASK_HEX_WIDTH == 135


def test_real_branch_finds_missing_second_predicate_after_dead_first_sibling(codec):
    ctx, ids = authored.context((1, 1)), two_predicate_prefix(codec, first_atom=True)
    old = authored.prefix(ids, ctx, codec, 100)
    assert len(old["allowed_token_ids"]) == 2
    report = find(ids, ctx, codec, max_prefix_inspections=64)
    assert report["status"] == "WITNESS"
    expected = ["forall", 0, ["and", authored.atom(), authored.atom(1)]]
    assert report["witness"]["token_ids"] == authored.ids_for(expected, codec)
    assert any(node["allowed_count"] == 0 and node["status"] != "complete" for node in report["trace"])
    certificate(report, ids, ctx, codec, 100)


def test_all_original_children_dead_closes_exactly_at_the_inspection_cap(codec):
    ctx, ids = authored.context((1, 1)), two_predicate_prefix(codec)
    old = authored.prefix(ids, ctx, codec, 100)
    expected = 1 + sum(forced_dead_length(ids, token, ctx, codec, 100) for token in old["allowed_token_ids"])
    assert 1 < expected < 64 and len(old["allowed_token_ids"]) == 2
    report = find(ids, ctx, codec, max_prefix_inspections=expected)
    assert report["status"] == "DEAD_END" and report["actual_prefix_inspections"] == expected
    certificate(report, ids, ctx, codec, 100)


def test_dead_first_sibling_plus_unvisited_second_is_unknown(codec):
    ctx, ids = authored.context((1, 1)), two_predicate_prefix(codec)
    old = authored.prefix(ids, ctx, codec, 100)
    costs = {row["token_id"]: row["minimum_tokens_with_choice"] for row in old["candidate_bounds"]}
    first = min(old["allowed_token_ids"], key=lambda token: (costs[token], token))
    limit = 1 + forced_dead_length(ids, first, ctx, codec, 100)
    report = find(ids, ctx, codec, max_prefix_inspections=limit)
    assert report["status"] == "UNKNOWN" and report["reason"] == "prefix_inspection_limit"
    assert report["trace"][-1]["allowed_count"] == 0 and len(report["pending_nodes"]) == 1
    assert report["trace"][1]["via_token_id"] == first
    certificate(report, ids, ctx, codec, 100)


def test_existing_candidate_bound_precedes_token_id_in_dfs_order(codec):
    ctx, ids = authored.context((2, 1)), two_predicate_prefix(codec)
    old = authored.prefix(ids, ctx, codec, 100)
    costs = {row["token_id"]: row["minimum_tokens_with_choice"] for row in old["candidate_bounds"]}
    zero, one = authored.token("0", codec), authored.token("1", codec)
    assert zero < one and costs[one] < costs[zero]
    report = find(ids, ctx, codec, max_prefix_inspections=2)
    assert report["status"] == "UNKNOWN" and report["trace"][1]["via_token_id"] == one
    certificate(report, ids, ctx, codec, 100)


def test_unknown_original_bounds_preserve_all_original_children(codec, monkeypatch):
    monkeypatch.setattr(authored.subject, "_completion_lower_bound",
                        lambda *args: authored.subject._unknown("authored_unknown"))
    ctx, ids = authored.context((1, 1)), two_predicate_prefix(codec)
    old = authored.prefix(ids, ctx, codec, 100)
    report = find(ids, ctx, codec, max_prefix_inspections=1)
    assert report["status"] == "UNKNOWN" and report["trace"][0]["bound_status"] == "unknown"
    assert mask_ids(report["trace"][0]["allowed_mask_hex"]) == old["allowed_token_ids"]
    certificate(report, ids, ctx, codec, 100)


@pytest.mark.parametrize("boundary", ["depth", "frontier"], ids=["zero_depth", "one_frontier"])
def test_unexpanded_branch_choices_remain_explicitly_unknown(boundary, codec):
    ctx, ids = authored.context((1, 1)), two_predicate_prefix(codec)
    kwargs = {"max_search_depth": 0} if boundary == "depth" else {"max_frontier_nodes": 1}
    report = find(ids, ctx, codec, **kwargs)
    assert report["status"] == "UNKNOWN" and report["unresolved_frontier_root_count"] == 2
    assert report["unexpanded_parents"][0]["parent_id"] == 0
    assert len(mask_ids(report["unexpanded_parents"][0]["allowed_mask_hex"])) == 2
    certificate(report, ids, ctx, codec, 100)


@pytest.mark.parametrize("kind", ["bytes", "items"], ids=["trace_byte_cap", "trace_item_cap"])
def test_report_cutoff_counts_actual_unrecorded_root_and_keeps_it_unknown(kind, codec, monkeypatch):
    monkeypatch.setattr(subject, "MAX_TRACE_BYTES" if kind == "bytes" else "MAX_TRACE_ITEMS", 0)
    report = find([1], authored.context(), codec)
    assert report["status"] == "UNKNOWN" and report["reason"] == "trace_report_limit"
    assert report["actual_prefix_inspections"] == report["unrecorded_inspections"] == 1
    assert report["recorded_node_count"] == 0 and report["pending_nodes"][0]["node_id"] == 0
    certificate(report, [1], authored.context(), codec, 100)


@pytest.mark.parametrize("limit,status", [(1, "UNKNOWN"), (2, "WITNESS")], ids=["root_only", "eos_last_slot"])
def test_eos_consumes_last_slot_and_every_forced_inspection(limit, status, codec):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    report = find(complete[:-1], ctx, codec, 1, max_prefix_inspections=limit)
    assert report["status"] == status and report["actual_prefix_inspections"] == limit
    if status == "WITNESS":
        assert report["witness"]["suffix_token_ids"] == [2]
    certificate(report, complete[:-1], ctx, codec, 1)


def test_complete_terminal_precedes_empty_frontier_and_depth_limit(codec):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    report = find(complete, ctx, codec, 0, max_prefix_inspections=1, max_search_depth=0, max_frontier_nodes=1)
    assert report["status"] == "WITNESS" and report["witness"]["suffix_token_ids"] == []
    certificate(report, complete, ctx, codec, 0)


def test_closed_sibling_binder_is_not_available_in_the_next_sibling(codec):
    ctx = authored.context()
    tree = ["and", ["forall", 0, authored.atom()], ["exists", 1, authored.atom(variables=(1,))]]
    complete = authored.ids_for(tree, codec)
    # Leave only the final variable index and fixed delimiters/EOS to inspect.
    position = max(index for index, token in enumerate(complete) if codec["vocabulary"][token] == '"variable"') + 2
    offered = complete[:position]
    old = authored.prefix(offered, ctx, codec, len(complete) - position)
    assert old["allowed_token_ids"] == [authored.token("1", codec)]
    report = find(offered, ctx, codec, len(complete) - position, max_prefix_inspections=32)
    assert report["status"] == "WITNESS" and report["witness"]["token_ids"] == complete
    certificate(report, offered, ctx, codec, len(complete) - position)


def test_already_blocked_retained_prefix_is_not_repaired(codec):
    ctx = authored.context((2,))
    offered = authored.lexical_ids(authored.HEADER + '["or",["or",["or",[', codec)
    report = find(offered, ctx, codec, 83, max_prefix_inspections=1)
    assert report["status"] == "DEAD_END" and report["offered_ids"] == offered
    assert report["actual_prefix_inspections"] == 1
    certificate(report, offered, ctx, codec, 83)


@pytest.mark.parametrize("name,value", [
    ("max_prefix_inspections", True), ("max_prefix_inspections", 0), ("max_prefix_inspections", 1025),
    ("max_search_depth", False), ("max_search_depth", -1), ("max_search_depth", 513),
    ("max_frontier_nodes", True), ("max_frontier_nodes", 0), ("max_frontier_nodes", 513),
], ids=["inspection_bool", "inspection_zero", "inspection_over", "depth_bool", "depth_negative",
        "depth_over", "frontier_bool", "frontier_zero", "frontier_over"])
def test_caps_require_plain_bounded_integers(name, value, codec):
    with pytest.raises(ValueError):
        find([1], authored.context(), codec, **{name: value})


@pytest.mark.parametrize("remaining", [True, -1, 513, 1.0], ids=["bool", "negative", "over512", "float"])
def test_original_remaining_allowance_contract_is_not_coerced(remaining, codec):
    with pytest.raises(ValueError):
        find([1], authored.context(), codec, remaining)


@pytest.mark.parametrize("binding", ["context", "codec"], ids=["context_hash", "codec_hash"])
def test_hash_custody_is_checked_before_any_witness(binding, codec):
    raw, options = authored.options(authored.context(), codec)
    options["expected_" + binding + "_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.find_completion_witness([1], raw, remaining_new_tokens=100, **options)


def test_original_policy_exception_is_not_relabelled_unknown(codec, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("authored original-policy failure")
    monkeypatch.setattr(authored.subject, "allowed_token_ids", fail)
    with pytest.raises(RuntimeError, match="authored original-policy failure"):
        find([1], authored.context(), codec)


def test_typed_terminal_disagreement_is_not_a_witness_or_dead_end(codec, monkeypatch):
    ctx = authored.context()
    complete = authored.ids_for(["forall", 0, authored.atom()], codec)
    original = authored.tokens.decode_compact_content_tokens_v1
    def contradictory(*args, **kwargs):
        report = original(*args, **kwargs)
        return dict(report, status="authored_contradiction")
    monkeypatch.setattr(authored.tokens, "decode_compact_content_tokens_v1", contradictory)
    with pytest.raises(ValueError, match="typed decoder disagree"):
        find(complete, ctx, codec, 0)


def test_closing_input_mutation_refuses_after_real_original_inspection(codec, monkeypatch):
    offered, ctx = [1], authored.context()
    original = authored.subject.allowed_token_ids
    def mutate_after_real_read(*args, **kwargs):
        report = original(*args, **kwargs)
        offered.append(1)
        return report
    monkeypatch.setattr(authored.subject, "allowed_token_ids", mutate_after_real_read)
    with pytest.raises(ValueError, match="inputs changed"):
        find(offered, ctx, codec, max_prefix_inspections=1)


def test_own_source_pin_failure_is_not_a_search_cutoff(codec, monkeypatch):
    monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
    with pytest.raises(ValueError):
        find([1], authored.context(), codec)


def test_closing_source_pin_change_refuses_after_real_policy_read(codec, monkeypatch):
    original = authored.subject.allowed_token_ids
    def change_pin_after_real_read(*args, **kwargs):
        report = original(*args, **kwargs)
        monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
        return report
    monkeypatch.setattr(authored.subject, "allowed_token_ids", change_pin_after_real_read)
    with pytest.raises(ValueError):
        find([1], authored.context(), codec, max_prefix_inspections=1)


@pytest.mark.parametrize("offered", [(1,), [True], [1.0]], ids=["tuple", "boolean_id", "float_id"])
def test_original_prefix_input_contract_is_not_coerced(offered, codec):
    with pytest.raises(ValueError):
        find(offered, authored.context(), codec)


def test_result_detachment_does_not_mutate_inputs(codec):
    offered, ctx = [1], authored.context()
    before = deepcopy((offered, ctx, codec))
    report = find(offered, ctx, codec, max_prefix_inspections=1)
    report["offered_ids"].append(2)
    assert (offered, ctx, codec) == before


@pytest.mark.parametrize("arities,limit", [((1,), 24), ((1, 1), 32)], ids=["one_predicate_24", "two_predicate_32"])
def test_bounded_bos_reachability_is_only_an_engineering_observation(arities, limit, codec, tmp_path):
    ctx = authored.context(arities)
    report = find([1], ctx, codec, max_prefix_inspections=limit)
    certificate(report, [1], ctx, codec, 100)
    assert report["actual_prefix_inspections"] <= limit
    (tmp_path / "authored-bos-reachability.json").write_bytes(authored.wire(report))
