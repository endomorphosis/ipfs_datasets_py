"""Authored finite scope/arity controls; no learned or statutory result.

All signatures, contexts, trees and score vectors below are independently
authored engineering fixtures. Historical predictions, reference labels, model
checkpoints and training targets are not imported. The original v1 suites remain
unchanged. The native qualification owner, not this test module, owns execution.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import re

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as selection
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_scope_filter_v1 as subject


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


def context(arities=(2,)):
    """Synthetic object predicates with explicitly ordered argument roles."""
    obj = dict(arguments=[], kind="atomic", name="Object", schema_version="syntax-logic-sort/v1")
    boolean = dict(arguments=[], kind="bool", name="Bool", schema_version="syntax-logic-sort/v1")
    symbols, roles = [], []
    for index, arity in enumerate(arities):
        name = "FixtureRelation" + str(index)
        symbols.append(dict(domain=[deepcopy(obj) for _ in range(arity)], kind="predicate",
            metadata={}, name=name, range=deepcopy(boolean), schema_version="syntax-symbol-declaration/v1"))
        roles.append(dict(symbol=name, roles=["argument" + str(i) for i in range(arity)]))
    return dict(schema=CONTEXT_SCHEMA, argument_roles=roles, signature=dict(
        family=identity("family", "tdfol"), features=[], interface="LogicSignature@1", metadata={},
        profile=identity("profile", "tdfol_default"), schema_version="syntax-logic-signature/v1",
        sorts=[boolean, obj], symbols=symbols))


def document(tree):
    return dict(schema=CONTENT_SCHEMA, tree=tree)


def atom(index=0, variables=(0, 0)):
    return ["predicate", index, [["variable", value] for value in variables]]


@pytest.fixture(scope="module")
def codec():
    return tokens.build_compact_content_token_codec_v1()


def options(ctx, codec):
    raw = wire(ctx)
    return raw, dict(expected_context_sha256=sha(raw), codec=codec,
                     expected_codec_sha256=tokens.compact_content_token_codec_sha256(codec))


def lexical_ids(text, codec):
    """Independent lexical lookup; never calls the candidate tokenizer/parser."""
    pieces = LEXICAL.findall(text)
    assert "".join(pieces) == text
    index = {value: key for key, value in enumerate(codec["vocabulary"])}
    return [codec["bos_id"], *(index[piece] for piece in pieces)]


def ids_for(value, codec, *, eos=True):
    result = lexical_ids(wire(value).decode(), codec)
    return result + ([codec["eos_id"]] if eos else [])


def token(text, codec):
    return codec["vocabulary"].index(text)


def prefix(offered, ctx, codec):
    raw, kwargs = options(ctx, codec)
    return subject.allowed_token_ids(offered, raw, **kwargs)


def baseline_prefix(offered, ctx, codec):
    raw, kwargs = options(ctx, codec)
    return tokens.compact_content_allowed_token_ids_v1(offered, raw, **kwargs)


def select(logits, offered, ctx, codec):
    raw, kwargs = options(ctx, codec)
    return subject.select_token(logits, offered, raw, **kwargs)


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["global_completability_proven"] is False


def conserved_mask(report, offered, ctx, codec):
    original = baseline_prefix(offered, ctx, codec)
    assert report["offered_ids"] == offered
    assert report["baseline_prefix_report"] == original
    assert report["allowed_token_ids"] == sorted(set(report["allowed_token_ids"]))
    assert set(report["allowed_token_ids"]) <= set(original["allowed_token_ids"])
    assert report["removed_token_ids"] == sorted(set(original["allowed_token_ids"]) - set(report["allowed_token_ids"]))
    assert report["policy"]
    no_authority(report)


def test_public_api_has_no_reference_target_or_invented_binding_argument():
    common = {"prefix_ids", "context_raw", "expected_context_sha256", "codec", "expected_codec_sha256"}
    assert set(inspect.signature(subject.allowed_token_ids).parameters) == common
    assert set(inspect.signature(subject.select_token).parameters) == common | {"logits"}


@pytest.mark.parametrize("arity", [1, 2, 8])
def test_empty_root_removes_positive_arity_predicate_without_forcing_quantifier(arity, codec):
    ctx = context((arity,))
    offered = lexical_ids(HEADER + "[", codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    predicate = token('"predicate"', codec)
    assert predicate in report["baseline_prefix_report"]["allowed_token_ids"]
    assert report["removed_token_ids"] == [predicate]
    assert report["allowed_token_ids"] == [i for i in report["baseline_prefix_report"]["allowed_token_ids"] if i != predicate]
    assert token('"forall"', codec) in report["allowed_token_ids"]
    assert token('"exists"', codec) in report["allowed_token_ids"]
    assert token('"extension"', codec) in report["allowed_token_ids"]


@pytest.mark.parametrize("wrapper", ['["not",', '["extension","O",', '["extension","P",',
    '["extension","F",', '["and",', '["or",', '["implies",', '["iff",'])
def test_boolean_or_modal_wrapper_does_not_create_a_lexical_binder(wrapper, codec):
    ctx = context()
    offered = lexical_ids(HEADER + wrapper + "[", codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert token('"predicate"', codec) in report["removed_token_ids"]
    assert token('"forall"', codec) in report["allowed_token_ids"]


def test_one_bound_variable_can_fill_both_ordered_predicate_arguments(codec):
    ctx = context()
    offered = lexical_ids(HEADER + '["forall",0,[', codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert token('"predicate"', codec) in report["allowed_token_ids"]
    assert report["removed_token_ids"] == []
    # Arity means argument positions, not a demand for distinct variables.
    complete = ids_for(document(["forall", 0, atom()]), codec)
    assert prefix(complete[:-1], ctx, codec)["allowed_token_ids"] == [2]
    raw, kwargs = options(ctx, codec)
    decoded = tokens.decode_compact_content_tokens_v1(complete, raw, **kwargs)
    assert decoded["status"] == "valid_candidate"
    assert decoded["prediction"]["content"]["tree"][2] == atom()


def test_global_previous_binder_is_not_active_in_unquantified_sibling(codec):
    ctx = context((1,))
    offered = lexical_ids(HEADER + '["and",["forall",0,["predicate",0,[["variable",0]]]],[' , codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert report["baseline_prefix_report"]["counts"]["quantifiers"] == 1
    assert token('"predicate"', codec) in report["removed_token_ids"]
    assert token('"forall"', codec) in report["allowed_token_ids"]


def test_outer_binder_survives_sibling_but_inner_binder_does_not_escape(codec):
    ctx = context((1,))
    sibling = HEADER + '["forall",0,["and",["exists",1,["predicate",0,[["variable",1]]]],['
    report = prefix(lexical_ids(sibling, codec), ctx, codec)
    assert token('"predicate"', codec) in report["allowed_token_ids"]
    argument = lexical_ids(sibling + '"predicate",0,[["variable",', codec)
    state = prefix(argument, ctx, codec)
    conserved_mask(state, argument, ctx, codec)
    assert state["allowed_token_ids"] == [token("0", codec)]
    assert token("1", codec) not in state["allowed_token_ids"]


def test_nested_scope_preserves_both_active_variable_alternatives(codec):
    ctx = context()
    offered = lexical_ids(HEADER + '["forall",0,["exists",1,["predicate",0,[["variable",', codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert report["allowed_token_ids"] == sorted([token("0", codec), token("1", codec)])


def test_existing_impossible_predicate_index_prefix_is_not_extended(codec):
    ctx = context()
    offered = lexical_ids(HEADER + '["predicate",', codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert report["baseline_prefix_report"]["allowed_token_ids"] == [token("0", codec)]
    assert report["allowed_token_ids"] == []
    scores = [0.0] * 537
    result = select(scores, offered, ctx, codec)
    assert result["status"] == "no_selection" and result["selected_token_id"] is None
    assert result["next_prefix_ids"] == offered and result["logits"] == scores


@pytest.mark.parametrize("case", ["repeated_arguments", "nested_quantifiers", "modal_negation", "all_predicates"])
def test_independently_authored_complete_formulas_keep_eos_and_exact_v1_decode(case, codec):
    ctx = context()
    if case == "repeated_arguments":
        tree = ["forall", 0, atom()]
    elif case == "nested_quantifiers":
        tree = ["forall", 0, ["exists", 1, atom(variables=(1, 0))]]
    elif case == "modal_negation":
        tree = ["forall", 0, ["extension", "F", ["not", atom()]]]
    else:
        ctx = context((1, 2))
        tree = ["forall", 0, ["and", atom(variables=(0,)), atom(1)]]
    value = document(tree)
    ids = ids_for(value, codec)
    for position, expected_next in enumerate(ids):
        offered = ids[:position]
        state = prefix(offered, ctx, codec)
        conserved_mask(state, offered, ctx, codec)
        assert expected_next in state["allowed_token_ids"], (case, position, expected_next)
    before_eos = prefix(ids[:-1], ctx, codec)
    assert before_eos["allowed_token_ids"] == [2] and before_eos["removed_token_ids"] == []
    ended = prefix(ids, ctx, codec)
    assert ended["status"] == "complete" and ended["allowed_token_ids"] == []
    conserved_mask(ended, ids, ctx, codec)
    raw, kwargs = options(ctx, codec)
    decoded = tokens.decode_compact_content_tokens_v1(ids, raw, **kwargs)
    assert decoded["status"] == "valid_candidate" and decoded["prediction"]["content"] == value


def test_completed_tree_cannot_omit_a_declared_predicate(codec):
    ctx = context((1, 2))
    ids = ids_for(document(["forall", 0, atom(variables=(0,))]), codec, eos=False)
    report = prefix(ids, ctx, codec)
    conserved_mask(report, ids, ctx, codec)
    assert report["status"] == "rejected" and report["allowed_token_ids"] == []
    assert 2 not in report["allowed_token_ids"]


def budget_prefix(codec):
    # Balanced, individually scoped legal grammar: the limitation is transport
    # length, not excessive recursive depth or a fabricated free variable.
    trees = [atom(variables=(0,)) for _ in range(32)]
    while len(trees) > 1:
        trees = [["and", trees[i], trees[i + 1]] for i in range(0, len(trees), 2)]
    ids = ids_for(document(["forall", 0, trees[0]]), codec, eos=False)
    assert len(ids) > 512
    return ids[:512]


def test_total_token_budget_is_preserved_without_truncation_or_eos_injection(codec):
    ctx, offered = context((1,)), budget_prefix(codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert report["status"] == "budget_exhausted" and report["allowed_token_ids"] == []
    assert report["offered_ids"] == offered and len(offered) == 512


def test_excessive_tree_depth_remains_rejected(codec):
    ctx = context((1,))
    offered = lexical_ids(HEADER + '["not",' * 50 + "[", codec)
    report = prefix(offered, ctx, codec)
    conserved_mask(report, offered, ctx, codec)
    assert report["status"] == "rejected" and report["allowed_token_ids"] == []


def test_zero_arity_context_stays_outside_the_current_public_context_contract(codec):
    raw, kwargs = options(context((0,)), codec)
    offered = lexical_ids(HEADER + "[", codec)
    with pytest.raises(ValueError):
        tokens.compact_content_allowed_token_ids_v1(offered, raw, **kwargs)
    with pytest.raises(ValueError):
        subject.allowed_token_ids(offered, raw, **kwargs)


@pytest.mark.parametrize("wrapper", ["", '["not",'])
def test_selector_consumes_filtered_mask_and_preserves_unmodified_baseline_choice(wrapper, codec):
    ctx = context()
    offered = lexical_ids(HEADER + wrapper + "[", codec)
    scores = [-10.0] * 537
    predicate, extension = token('"predicate"', codec), token('"extension"', codec)
    scores[predicate], scores[extension], scores[token('"forall"', codec)] = 9.0, 8.0, 7.0
    before = deepcopy((scores, offered, ctx, codec))
    report = select(scores, offered, ctx, codec)
    raw, kwargs = options(ctx, codec)
    baseline = selection.select_compact_content_token_v1(scores, offered, raw, **kwargs)
    assert baseline["selected_token_id"] == predicate
    assert report["baseline_selection"] == baseline
    assert report["status"] == "selected" and report["selected_token_id"] == extension
    assert report["next_prefix_ids"] == offered + [extension]
    assert report["logits"] == scores and report["tie_breaker"] == "lowest_token_id"
    assert report["prefix_report"] == prefix(offered, ctx, codec)
    assert (scores, offered, ctx, codec) == before
    no_authority(report["prefix_report"])


def test_filtered_equal_scores_keep_lowest_allowed_token_tie_rule(codec):
    offered, ctx = lexical_ids(HEADER + "[", codec), context()
    report = select([0.0] * 537, offered, ctx, codec)
    allowed = report["prefix_report"]["allowed_token_ids"]
    assert report["selected_token_id"] == min(allowed)
    assert report["tie_breaker"] == "lowest_token_id"
    assert report["next_prefix_ids"] == offered + [min(allowed)]


def test_bos_and_eos_are_scored_tokens_not_silent_prefix_repairs(codec):
    ctx = context()
    complete = ids_for(document(["forall", 0, atom()]), codec)
    for offered, wanted in [([], 1), (complete[:-1], 2)]:
        scores = [-2.0] * 537
        scores[wanted] = 3.0
        result = select(scores, offered, ctx, codec)
        assert result["status"] == "selected" and result["selected_token_id"] == wanted
        assert result["next_prefix_ids"] == offered + [wanted]


@pytest.mark.parametrize("case", ["complete", "rejected", "budget_exhausted"])
def test_nonselectable_prefix_retains_scores_and_offered_ids(case, codec):
    ctx = context((1,))
    if case == "complete":
        offered = ids_for(document(["forall", 0, atom(variables=(0,))]), codec)
    elif case == "rejected":
        offered = [1, 0]
    else:
        offered = budget_prefix(codec)
    scores = [-1.0] * 537
    scores[2] = 100.0
    result = select(scores, offered, ctx, codec)
    assert result["status"] == "no_selection" and result["selected_token_id"] is None
    assert result["next_prefix_ids"] == offered and result["logits"] == scores
    assert result["prefix_report"]["status"] == case


@pytest.mark.parametrize("offered", [None, (), [True], [1.0], [1] * 513])
def test_malformed_or_overlong_prefix_does_not_become_a_model_rejection(offered, codec):
    with pytest.raises(ValueError):
        prefix(offered, context(), codec)


@pytest.mark.parametrize("damage", ["short", "long", "nan", "positive_infinity", "negative_infinity", "boolean", "unsafe_integer"])
def test_complete_score_vector_is_validated_even_at_removed_predicate_token(damage, codec):
    scores = [0.0] * 537
    index = token('"predicate"', codec)
    if damage == "short":
        scores.pop()
    elif damage == "long":
        scores.append(0.0)
    else:
        scores[index] = {"nan": float("nan"), "positive_infinity": float("inf"),
            "negative_infinity": -float("inf"), "boolean": True, "unsafe_integer": 1 << 53}[damage]
    with pytest.raises(ValueError):
        select(scores, lexical_ids(HEADER + "[", codec), context(), codec)


@pytest.mark.parametrize("binding", ["context", "codec"])
def test_independent_context_and_codec_hash_mismatch_refuse(binding, codec):
    raw, kwargs = options(context(), codec)
    kwargs["expected_" + binding + "_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.allowed_token_ids([1], raw, **kwargs)


def test_duplicate_context_fields_are_not_normalized_into_authority(codec):
    raw, kwargs = options(context(), codec)
    raw = b'{"schema":"legal-relational-compact-context/v1",' + raw[1:]
    kwargs["expected_context_sha256"] = sha(raw)
    with pytest.raises(ValueError):
        subject.allowed_token_ids([1], raw, **kwargs)
