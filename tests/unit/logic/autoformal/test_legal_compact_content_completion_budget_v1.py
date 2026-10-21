"""Authored finite completion witnesses for the opt-in budget policy.

The corpus below is engineering input, not a statute, learned prediction,
checkpoint target, legal review or completeness proof. The lexical oracle uses
only JSON serialization and a separately authored token regex. Native execution
and source custody belong to the existing qualification owner.
"""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as selection
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_scope_filter_v1 as scope
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_completion_budget_v1 as subject


CONTENT_SCHEMA = "legal-relational-compact-content/v1"
CONTEXT_SCHEMA = "legal-relational-compact-context/v1"
LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')
HEADER = '{"schema":"legal-relational-compact-content/v1","tree":'


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(namespace, value):
    return dict(interface="LogicIdentityNamespaces@1", namespace=namespace,
                schema_version="logic-identity-namespaces/v1", value=value, version="1.0.0")


def context(arities=(1,)):
    obj = dict(arguments=[], kind="atomic", name="Object", schema_version="syntax-logic-sort/v1")
    boolean = dict(arguments=[], kind="bool", name="Bool", schema_version="syntax-logic-sort/v1")
    symbols, roles = [], []
    for index, arity in enumerate(arities):
        name = "AuthoredRelation" + str(index)
        symbols.append(dict(domain=[deepcopy(obj) for _ in range(arity)], kind="predicate",
            metadata={}, name=name, range=deepcopy(boolean), schema_version="syntax-symbol-declaration/v1"))
        roles.append(dict(symbol=name, roles=["argument" + str(i) for i in range(arity)]))
    return dict(schema=CONTEXT_SCHEMA, argument_roles=roles, signature=dict(
        family=identity("family", "tdfol"), features=[], interface="LogicSignature@1", metadata={},
        profile=identity("profile", "tdfol_default"), schema_version="syntax-logic-signature/v1",
        sorts=[boolean, obj], symbols=symbols))


def atom(index=0, variables=(0,)):
    return ["predicate", index, [["variable", value] for value in variables]]


def document(tree):
    return dict(schema=CONTENT_SCHEMA, tree=tree)


@pytest.fixture(scope="module")
def codec():
    return tokens.build_compact_content_token_codec_v1()


def options(ctx, codec):
    raw = wire(ctx)
    return raw, dict(expected_context_sha256=sha(raw), codec=codec,
                     expected_codec_sha256=tokens.compact_content_token_codec_sha256(codec))


def lexical_ids(text, codec):
    pieces = LEXICAL.findall(text)
    assert "".join(pieces) == text
    positions = {value: index for index, value in enumerate(codec["vocabulary"])}
    return [codec["bos_id"], *(positions[piece] for piece in pieces)]


def ids_for(tree, codec):
    return lexical_ids(wire(document(tree)).decode(), codec) + [codec["eos_id"]]


def token(value, codec):
    return codec["vocabulary"].index(value)


def prefix(offered, ctx, codec, budget):
    raw, kwargs = options(ctx, codec)
    return subject.allowed_token_ids(offered, raw, remaining_new_tokens=budget, **kwargs)


def selected(scores, offered, ctx, codec, budget):
    raw, kwargs = options(ctx, codec)
    return subject.select_token(scores, offered, raw, remaining_new_tokens=budget, **kwargs)


def scoped(offered, ctx, codec):
    raw, kwargs = options(ctx, codec)
    return scope.allowed_token_ids(offered, raw, **kwargs)


def conserved(report, offered, ctx, codec, budget):
    original = scoped(offered, ctx, codec)
    assert report["offered_ids"] == offered
    assert report["scope_prefix_report"] == original
    assert report["baseline_prefix_report"] == original["baseline_prefix_report"]
    assert report["remaining_new_tokens"] == budget
    assert report["effective_remaining_tokens"] == min(budget, 512 - len(offered))
    assert report["allowed_token_ids"] == sorted(set(report["allowed_token_ids"]))
    assert set(report["allowed_token_ids"]) <= set(original["allowed_token_ids"])
    assert report["budget_removed_token_ids"] == sorted(
        set(original["allowed_token_ids"]) - set(report["allowed_token_ids"]))
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def witnessed_corpus():
    """Finite independent witnesses, deliberately not an exhaustive language."""
    yield "unary", context(), ["forall", 0, atom()]
    yield "repeated_binary_arguments", context((2,)), ["forall", 0, atom(variables=(0, 0))]
    yield "arity_eight", context((8,)), ["forall", 0, atom(variables=(0,) * 8)]
    yield "nested_scope", context((2,)), ["forall", 0, ["exists", 1, atom(variables=(1, 0))]]
    for modality in ("O", "P", "F"):
        yield "modal_" + modality, context(), ["forall", 0, ["extension", modality, ["not", atom()]]]
    for connective in ("and", "or", "implies", "iff"):
        yield connective, context(), ["forall", 0, [connective, atom(), atom()]]
    yield "sibling_scope", context(), ["and", ["forall", 0, atom()],
        ["exists", 1, atom(variables=(1,))]]
    yield "all_predicates", context((1, 2)), ["forall", 0,
        ["and", atom(), atom(1, variables=(0, 0))]]


CORPUS = list(witnessed_corpus())


def test_api_has_explicit_budget_and_no_target_or_reference_parameter():
    common = {"prefix_ids", "context_raw", "expected_context_sha256", "codec", "expected_codec_sha256",
              "remaining_new_tokens"}
    assert set(inspect.signature(subject.allowed_token_ids).parameters) == common
    assert set(inspect.signature(subject.select_token).parameters) == common | {"logits"}
    for function in (subject.allowed_token_ids, subject.select_token):
        assert inspect.signature(function).parameters["remaining_new_tokens"].kind == inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("name,ctx,tree", CORPUS, ids=[row[0] for row in CORPUS])
def test_every_prefix_preserves_an_independently_witnessed_exact_budget_completion(name, ctx, tree, codec):
    complete = ids_for(tree, codec)
    for position, expected in enumerate(complete):
        offered, remaining = complete[:position], len(complete) - position
        report = prefix(offered, ctx, codec, remaining)
        assert expected in report["allowed_token_ids"], (name, position, expected)
        bound = report["prefix_lower_bound"]
        if bound["status"] == "lower_bound":
            assert type(bound["minimum_additional_tokens"]) is int
            assert 0 <= bound["minimum_additional_tokens"] <= remaining
        else:
            assert bound["status"] == "unknown" and bound["minimum_additional_tokens"] is None
        choices = [row for row in report["candidate_bounds"] if row["token_id"] == expected]
        assert len(choices) == 1
        if choices[0]["minimum_tokens_with_choice"] is not None:
            assert choices[0]["minimum_tokens_with_choice"] <= remaining
        assert choices[0]["disposition"] in {"keep", "keep_unknown"}
    ended = prefix(complete, ctx, codec, 0)
    assert ended["status"] == "complete" and ended["allowed_token_ids"] == []
    raw, kwargs = options(ctx, codec)
    decoded = tokens.decode_compact_content_tokens_v1(complete, raw, **kwargs)
    assert decoded["status"] == "valid_candidate" and decoded["prediction"]["content"] == document(tree)


def test_eos_is_one_scored_token_and_never_injected(codec):
    ctx = context()
    complete = ids_for(["forall", 0, atom()], codec)
    offered = complete[:-1]
    for budget, wanted in ((0, []), (1, [2]), (2, [2])):
        report = prefix(offered, ctx, codec, budget)
        conserved(report, offered, ctx, codec, budget)
        assert report["allowed_token_ids"] == wanted
    scores = [-3.0] * 537
    scores[2] = 4.0
    no_room = selected(scores, offered, ctx, codec, 0)
    assert no_room["status"] == "no_selection" and no_room["selected_token_id"] is None
    assert no_room["next_prefix_ids"] == offered and no_room["logits"] == scores
    room = selected(scores, offered, ctx, codec, 1)
    assert room["status"] == "selected" and room["selected_token_id"] == 2
    assert room["next_prefix_ids"] == complete and room["logits"] == scores


def test_exact_shortest_tail_prunes_wrapper_but_keeps_predicate_without_target_input(codec):
    ctx = context()
    complete = ids_for(["forall", 0, atom()], codec)
    offered = lexical_ids(HEADER + '["forall",0,[', codec)
    budget = len(complete) - len(offered)
    report = prefix(offered, ctx, codec, budget)
    conserved(report, offered, ctx, codec, budget)
    assert token('"predicate"', codec) in report["allowed_token_ids"]
    assert token('"extension"', codec) in report["scope_prefix_report"]["allowed_token_ids"]
    assert token('"extension"', codec) in report["budget_removed_token_ids"]
    row = next(row for row in report["candidate_bounds"] if row["token_id"] == token('"extension"', codec))
    assert row["disposition"] == "remove_proven_over_budget" and row["minimum_tokens_with_choice"] > budget


@pytest.mark.parametrize("budget", [None, False, True, -1, 513, 1.0, "1", [], {}])
def test_invalid_budget_is_contract_failure_even_at_complete_prefix(budget, codec):
    ctx = context()
    complete = ids_for(["forall", 0, atom()], codec)
    with pytest.raises(ValueError):
        prefix(complete, ctx, codec, budget)
    with pytest.raises(ValueError):
        selected([0.0] * 537, complete, ctx, codec, budget)


def test_selection_uses_refined_mask_with_unmodified_logits_and_lowest_id_ties(codec):
    ctx, offered = context(), lexical_ids(HEADER + '["forall",0,[', codec)
    complete = ids_for(["forall", 0, atom()], codec)
    budget = len(complete) - len(offered)
    scores = [0.0] * 537
    scores[token('"extension"', codec)] = 100.0
    before = deepcopy((scores, offered, ctx, codec))
    result = selected(scores, offered, ctx, codec, budget)
    assert result["prefix_report"] == prefix(offered, ctx, codec, budget)
    choices = result["prefix_report"]["allowed_token_ids"]
    assert result["selected_token_id"] == min(choices)
    assert result["next_prefix_ids"] == offered + [min(choices)]
    assert result["logits"] == scores and result["tie_breaker"] == "lowest_token_id"
    raw, kwargs = options(ctx, codec)
    original_scope = scope.select_token(scores, offered, raw, **kwargs)
    assert result["scope_selection"] == original_scope
    assert result["baseline_selection"] == original_scope["baseline_selection"]
    assert result["scope_selection"]["selected_token_id"] == token('"extension"', codec)
    assert (scores, offered, ctx, codec) == before


@pytest.mark.parametrize("damage", ["nan", "boolean", "short", "unsafe_integer"])
def test_zero_budget_still_validates_every_score(damage, codec):
    scores = [0.0] * 537
    if damage == "short":
        scores.pop()
    else:
        scores[0] = {"nan": float("nan"), "boolean": True, "unsafe_integer": 1 << 53}[damage]
    with pytest.raises(ValueError):
        selected(scores, [1], context(), codec, 0)


@pytest.mark.parametrize("offered", [None, (), [True], [1.0], [1] * 513])
def test_zero_budget_does_not_hide_malformed_prefix(offered, codec):
    with pytest.raises(ValueError):
        prefix(offered, context(), codec, 0)


@pytest.mark.parametrize("binding", ["context", "codec"])
def test_hash_custody_refuses_before_budget_masking(binding, codec):
    raw, kwargs = options(context(), codec)
    kwargs["expected_" + binding + "_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.allowed_token_ids([1], raw, remaining_new_tokens=0, **kwargs)


@pytest.mark.parametrize("pin", ["_SELF_SHA", "_SCOPE_SHA"])
def test_new_module_source_custody_failure_is_not_budget_exhaustion(pin, codec, monkeypatch):
    monkeypatch.setattr(subject, pin, "0" * 64)
    with pytest.raises(ValueError):
        prefix([1], context(), codec, 0)
    with pytest.raises(ValueError):
        selected([0.0] * 537, [1], context(), codec, 0)


@pytest.mark.parametrize("damage", ["allowed_mask", "context_identity", "offered_prefix"])
def test_select_refuses_disagreeing_scope_receipt(damage, codec, monkeypatch):
    original = subject._prefix
    def disagreeing(*args):
        report = original(*args)
        observed = report["scope_prefix_report"]
        if damage == "allowed_mask":
            observed["allowed_token_ids"] = []
        elif damage == "context_identity":
            observed["context_raw_sha256"] = "0" * 64
        else:
            observed["offered_ids"] = []
        return report
    # Only the new adapter's receipt seam is changed. Genuine upstream owners
    # independently produce the observation which must disagree.
    monkeypatch.setattr(subject, "_prefix", disagreeing)
    with pytest.raises(ValueError):
        selected([0.0] * 537, [1], context(), codec, 512)


def test_unknown_lower_bound_is_kept_without_claiming_completability(codec, monkeypatch):
    def unavailable(*_args):
        return dict(status="unknown", minimum_additional_tokens=None,
                    reason="authored test has no conservative bound", method="relaxed-canonical-grammar/v1", completed=False)
    monkeypatch.setattr(subject, "_completion_lower_bound", unavailable)
    ctx, offered = context(), lexical_ids(HEADER + '["forall",0,[', codec)
    report = prefix(offered, ctx, codec, 1)
    conserved(report, offered, ctx, codec, 1)
    assert report["allowed_token_ids"] == report["scope_prefix_report"]["allowed_token_ids"]
    assert report["budget_removed_token_ids"] == []
    assert report["candidate_bounds"]
    assert all(row["disposition"] == "keep_unknown" and row["minimum_tokens_with_choice"] == 1
               for row in report["candidate_bounds"])
    assert prefix(offered, ctx, codec, 0)["allowed_token_ids"] == []


def test_original_qualified_owners_are_unchanged_and_separately_identified(codec):
    expected = ((tokens, "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
                (selection, "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"),
                (scope, "7b77e5d71012f9394ec0eb9fa05a70310644a3ed5e334f8e91904354b6a187b9"))
    for owner, digest in expected:
        assert sha(Path(owner.__file__).read_bytes()) == digest
    report = prefix([1], context(), codec, 512)
    assert report["owner_pins"] != report["scope_prefix_report"]["owner_pins"]
    assert codec["max_sequence_tokens"] == 512 and codec["vocabulary_size"] == 537


def test_returned_masks_and_reports_are_detached(codec):
    ctx, offered = context(), [1]
    report = prefix(offered, ctx, codec, 512)
    before = deepcopy(report)
    report["allowed_token_ids"].clear()
    report["scope_prefix_report"]["allowed_token_ids"].clear()
    report["authority"]["accepted"] = True
    assert prefix(offered, ctx, codec, 512) == before
    assert offered == [1]
