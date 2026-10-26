"""Fixed lexical content transport and local prefix grammar; no learned result.

The retained A/B trees are two hypotheses for one physical occurrence. Their
engineering-derived context is independently committed, not held-out-permission
qualified. Other contexts/trees below are explicitly authored. Fixtures are
embedded; no historical artifact or dynamic fixture imports occur at runtime.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import re

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as content_owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as subject


CONTENT_RAW = {"A": b'{"schema":"legal-relational-compact-content/v1","tree":["forall",0,["forall",1,["forall",2,["implies",["extension","P",["or",["predicate",0,[["variable",0],["variable",1]]],["predicate",1,[["variable",0],["variable",1]]]]],["predicate",2,[["variable",2],["variable",0]]]]]]]}',
               "B": b'{"schema":"legal-relational-compact-content/v1","tree":["forall",0,["forall",1,["forall",2,["extension","P",["implies",["or",["predicate",0,[["variable",0],["variable",1]]],["predicate",1,[["variable",0],["variable",1]]]],["predicate",2,[["variable",2],["variable",0]]]]]]]]}'}
CONTEXT_RAW = b'{"argument_roles":[{"roles":["recipient","duties"],"symbol":"Assign"},{"roles":["recipient","duties"],"symbol":"Transfer"},{"roles":["approver","recipient"],"symbol":"Approve"}],"schema":"legal-relational-compact-context/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Assign","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Transfer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Approve","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}}'

CONTENT_SHA = {
    "A": "719ce8351155bf64f096997dada4e493b401c1ae1b816cda47cbb07e4ab81427",
    "B": "61d5c35821044d0a1d73a750378002a025e01143dc1cf935e86520f644f33485",
}
CONTEXT_SHA = "64c9e1574f5c344936cea743adbfda6004d6f5f81b153df10ad25d9f6a9c87af"
LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def content(label="A"):
    return json.loads(CONTENT_RAW[label])


def context():
    return json.loads(CONTEXT_RAW)


def lex(value):
    """Independent canonical JSON lexical oracle, not subject's tokenizer."""
    raw = wire(value).decode("utf-8")
    tokens = LEXICAL.findall(raw)
    assert "".join(tokens) == raw
    return tokens


@pytest.fixture(scope="module")
def codec():
    return subject.build_compact_content_token_codec_v1()


def codec_sha(codec):
    return subject.compact_content_token_codec_sha256(codec)


def ids_for(value, codec, *, eos=True):
    table = {token: index for index, token in enumerate(codec["vocabulary"])}
    return [codec["bos_id"], *(table[token] for token in lex(value)),
            *([codec["eos_id"]] if eos else [])]


def encode(value, ctx, codec):
    c, x = wire(value), wire(ctx)
    return subject.encode_compact_content_tokens_v1(c, x,
        expected_content_sha256=sha(c), expected_context_sha256=sha(x),
        codec=codec, expected_codec_sha256=codec_sha(codec))


def decode(ids, ctx, codec):
    x = wire(ctx)
    return subject.decode_compact_content_tokens_v1(ids, x,
        expected_context_sha256=sha(x), codec=codec, expected_codec_sha256=codec_sha(codec))


def prefix(ids, ctx, codec):
    x = wire(ctx)
    return subject.compact_content_allowed_token_ids_v1(ids, x,
        expected_context_sha256=sha(x), codec=codec, expected_codec_sha256=codec_sha(codec))


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    prediction = report.get("prediction")
    if prediction is not None:
        assert prediction["request"]["source_binding"] is None
        assert prediction["identity_mode"] == "generated"
        assert all(value is False for value in prediction["authority"].values())
        assert prediction["training_mask"] == prediction["evaluation_gold_mask"] == 0


def unary_context(*, arity=1, name="Eligible"):
    """Authored reduced vocabulary, never labelled a retained source target."""
    ctx = context()
    symbol = deepcopy(ctx["signature"]["symbols"][0])
    symbol["name"] = name
    symbol["domain"] = [deepcopy(symbol["domain"][0]) for _ in range(arity)]
    ctx["signature"]["symbols"] = [symbol]
    ctx["argument_roles"] = [{"symbol": name,
        "roles": ["argument" + str(i) for i in range(arity)]}]
    return ctx


def unary_content():
    return {"schema": content_owner.CONTENT_SCHEMA,
            "tree": ["forall", 0, ["predicate", 0, [["variable", 0]]]]}


def tree_nodes(value):
    result = []
    def visit(tree):
        result.append(tree)
        if tree[0] == "predicate":
            for child in tree[2]: visit(child)
        elif tree[0] in {"forall", "exists", "extension"}: visit(tree[2])
        elif tree[0] in {"and", "or", "implies", "iff"}:
            visit(tree[1]); visit(tree[2])
        elif tree[0] == "not": visit(tree[1])
    visit(value["tree"])
    return result


def public_prediction(value, ctx):
    c, x = wire(value), wire(ctx)
    return content_owner.decode_prediction_v1(c, x,
        expected_content_sha256=sha(c), expected_context_sha256=sha(x))


def test_fixed_vocabulary_is_target_independent_and_uses_inherited_special_spellings(codec):
    strings = ["schema", "tree", content_owner.CONTENT_SCHEMA, "variable", "predicate",
               "forall", "exists", "and", "or", "implies", "iff", "not", "extension", "O", "P", "F"]
    expected = ["<pad>", "<bos>", "<eos>", *sorted(set(
        [json.dumps(s) for s in strings] + list("{}[],:" ) + [str(i) for i in range(512)]))]
    assert codec["vocabulary"] == expected
    assert codec["vocabulary_size"] == len(expected) == 537
    assert (codec["pad_id"], codec["bos_id"], codec["eos_id"]) == (0, 1, 2)
    assert codec["max_sequence_tokens"] == 512
    assert codec["integer_min"] == 0 and codec["integer_max"] == 511
    assert len(set(expected)) == len(expected) and "512" not in expected
    before = deepcopy(codec)
    encode(content("A"), context(), codec)
    encode(unary_content(), unary_context(), codec)
    assert codec == before == subject.build_compact_content_token_codec_v1()


@pytest.mark.parametrize("label", ["A", "B"])
def test_actual_99_lexical_tokens_101_ids_every_prefix_and_public_prediction(label, codec):
    """198 lexical decisions overall are not198legal samples or test cases."""
    assert len(CONTENT_RAW[label]) == 275 and sha(CONTENT_RAW[label]) == CONTENT_SHA[label]
    assert len(CONTEXT_RAW) == 2003 and sha(CONTEXT_RAW) == CONTEXT_SHA
    value, ctx = content(label), context()
    expected_ids = ids_for(value, codec)
    report = encode(value, ctx, codec)
    assert report["lexical_tokens"] == lex(value)
    assert report["target_ids"] == expected_ids
    assert report["lexical_token_count"] == len(lex(value)) == 99
    assert report["total_token_count"] == len(expected_ids) == 101
    assert report["canonical_content_raw_utf8"].encode() == CONTENT_RAW[label]
    assert report["content_sha256"] == CONTENT_SHA[label]
    assert report["context_sha256"] == CONTEXT_SHA
    empty = prefix([], ctx, codec)
    assert empty["status"] == "empty" and empty["allowed_token_ids"] == [1]
    for position in range(1, len(expected_ids)):
        current = expected_ids[:position]
        state = prefix(current, ctx, codec)
        assert state["status"] == "prefix"
        assert state["offered_ids"] == current
        assert expected_ids[position] in state["allowed_token_ids"], (label, position)
        assert 0 not in state["allowed_token_ids"] and 1 not in state["allowed_token_ids"]
        assert state["local_prefix_only"] is True
        assert state["global_completability_proven"] is False
        assert state["remaining_token_slots"] == 512 - len(current)
        no_authority(state)
    ended = prefix(expected_ids, ctx, codec)
    assert ended["status"] == "complete" and ended["allowed_token_ids"] == []
    decoded = decode(expected_ids, ctx, codec)
    assert decoded["status"] == "valid_candidate" and decoded["reason"] is None
    assert decoded["generated_ids"] == expected_ids
    assert decoded["generated_content_raw_utf8"].encode() == CONTENT_RAW[label]
    assert decoded["generated_content_hex"] == CONTENT_RAW[label].hex()
    assert decoded["generated_content_sha256"] == CONTENT_SHA[label]
    assert decoded["prediction"] == public_prediction(value, ctx) == report["prediction"]
    assert decoded["counts"] == {"nodes": 15, "quantifiers": 3, "modal_nodes": 1,
                                  "predicate_occurrences": 3}
    for item in (report, decoded, ended): no_authority(item)


def test_prediction_and_prefix_apis_have_no_reference_target_or_identity_sidecar():
    expected = {"context_raw", "expected_context_sha256", "codec", "expected_codec_sha256"}
    assert set(inspect.signature(subject.decode_compact_content_tokens_v1).parameters) == expected | {"generated_ids"}
    assert set(inspect.signature(subject.compact_content_allowed_token_ids_v1).parameters) == expected | {"prefix_ids"}


@pytest.mark.parametrize("mutation", ["other_scope", "connective", "argument_order", "quantifier", "modal_letter"])
def test_valid_new_predictions_survive_without_reference_repair(mutation, codec):
    value, ctx = content(), context()
    if mutation == "other_scope": value = content("B")
    else:
        rows = tree_nodes(value)
        if mutation == "connective": next(row for row in rows if row[0] == "or")[0] = "and"
        elif mutation == "argument_order":
            next(row for row in rows if row[0] == "predicate" and row[1] == 2)[2].reverse()
        elif mutation == "quantifier": value["tree"][0] = "exists"
        else: next(row for row in rows if row[0] == "extension")[1] = "F"
    ids = ids_for(value, codec)
    report = decode(ids, ctx, codec)
    assert report["status"] == "valid_candidate"
    assert report["prediction"]["content"] == value != content()
    assert report["generated_ids"] == ids
    assert report["prediction"]["context"] == ctx
    no_authority(report)


@pytest.mark.parametrize("connective", ["and", "or", "implies", "iff"])
def test_authored_binary_constructor_and_order_are_preserved(connective, codec):
    value = unary_content()
    atom = value["tree"][2]
    value["tree"][2] = [connective, atom, ["not", deepcopy(atom)]]
    report = decode(ids_for(value, codec), unary_context(), codec)
    assert report["status"] == "valid_candidate" and report["prediction"]["content"] == value
    no_authority(report)


@pytest.mark.parametrize("letter", ["O", "P", "F"])
def test_authored_modal_operators_and_exists_survive(letter, codec):
    value = unary_content()
    value["tree"] = ["exists", 0, ["extension", letter, value["tree"][2]]]
    report = decode(ids_for(value, codec), unary_context(), codec)
    assert report["status"] == "valid_candidate" and report["prediction"]["content"] == value


def test_valid_role_row_reordering_is_new_context_and_old_independent_pin_refuses(codec):
    ctx = context()
    ctx["argument_roles"].reverse()
    ids = ids_for(content(), codec)
    x = wire(ctx)
    with pytest.raises(ValueError):
        subject.decode_compact_content_tokens_v1(ids, x,
            expected_context_sha256=CONTEXT_SHA, codec=codec, expected_codec_sha256=codec_sha(codec))
    report = decode(ids, ctx, codec)
    assert report["status"] == "valid_candidate"
    assert report["prediction"]["context"]["argument_roles"] == ctx["argument_roles"]
    assert report["context_sha256"] == sha(x) != CONTEXT_SHA
    assert prefix(ids, ctx, codec)["status"] == "complete"
    no_authority(report)


def test_encoding_whitespace_commitment_is_separate_from_canonical_lexical_content(codec):
    c = json.dumps(content(), indent=2).encode()
    x = json.dumps(context(), indent=2).encode()
    report = subject.encode_compact_content_tokens_v1(c, x,
        expected_content_sha256=sha(c), expected_context_sha256=sha(x),
        codec=codec, expected_codec_sha256=codec_sha(codec))
    assert report["original_content_raw_sha256"] == sha(c) != CONTENT_SHA["A"]
    assert report["context_raw_sha256"] == sha(x) != CONTEXT_SHA
    assert report["content_sha256"] == CONTENT_SHA["A"] and report["context_sha256"] == CONTEXT_SHA
    assert report["target_ids"] == ids_for(content(), codec)


@pytest.mark.parametrize("mutation", ["free", "negative_reference", "reused_binder", "nonpreorder", "capture", "wrong_predicate", "arity", "formula_argument", "unused_predicate", "zero_quantifiers"])
def test_context_aware_grammar_refuses_invalid_binding_reference_arity_and_population(mutation, codec):
    value, ctx = content(), context()
    rows = tree_nodes(value)
    if mutation == "free": next(row for row in rows if row[0] == "variable")[1] = 511
    elif mutation == "negative_reference":
        #Negative integers have no lexical token; an unknown offered ID is retained.
        ids = ids_for(value, codec); ids[3] = -1
        report = decode(ids, ctx, codec)
        assert report["status"] == "rejected" and report["generated_ids"] == ids
        return
    elif mutation == "reused_binder": [row for row in rows if row[0] == "forall"][1][1] = 0
    elif mutation == "nonpreorder": value["tree"][1] = 1
    elif mutation == "capture":
        value["tree"] = ["and",
            ["forall", 0, ["predicate", 0, [["variable", 0], ["variable", 0]]]],
            ["forall", 1, ["and", ["predicate", 1, [["variable", 1], ["variable", 1]]],
                                    ["predicate", 2, [["variable", 1], ["variable", 0]]]]]]
    elif mutation == "wrong_predicate": next(row for row in rows if row[0] == "predicate")[1] = 511
    elif mutation == "arity": next(row for row in rows if row[0] == "predicate")[2].pop()
    elif mutation == "formula_argument":
        next(row for row in rows if row[0] == "predicate")[2][0] = ["not", ["variable", 0]]
    elif mutation == "unused_predicate":
        next(row for row in rows if row[0] == "predicate" and row[1] == 1)[1] = 0
    else: value["tree"] = ["predicate", 0, [["variable", 0], ["variable", 0]]]
    ids = ids_for(value, codec)
    report = decode(ids, ctx, codec)
    assert report["status"] == "rejected"
    assert report["generated_ids"] == ids and report["prediction"] is None
    assert prefix(ids, ctx, codec)["status"] == "rejected"
    no_authority(report)


def test_variable_prefix_choices_are_exact_active_lexical_binders(codec):
    #All three context predicates can occur later; this prefix has one binder.
    value = unary_content()
    raw = wire(value).decode()
    tokens = LEXICAL.findall(raw)
    #Prefix ends immediately before the variable's integer slot.
    marker = tokens.index('"variable"')
    table = {token: i for i, token in enumerate(codec["vocabulary"])}
    ids = [1, *(table[token] for token in tokens[:marker + 2])]
    state = prefix(ids, unary_context(), codec)
    assert state["status"] == "prefix"
    assert state["allowed_token_ids"] == [table["0"]]
    assert table["1"] not in state["allowed_token_ids"]


def test_predicate_prefix_choices_follow_context_and_exact_arity(codec):
    value = unary_content()
    tokens = lex(value)
    marker = tokens.index('"predicate"')
    table = {token: i for i, token in enumerate(codec["vocabulary"])}
    ids = [1, *(table[token] for token in tokens[:marker + 2])]
    assert prefix(ids, unary_context(), codec)["allowed_token_ids"] == [table["0"]]
    #With arity2context, premature argument-array closure cannot be allowed.
    tokens = tokens[:-4]
    state = prefix([1, *(table[token] for token in tokens)], unary_context(arity=2), codec)
    assert state["status"] == "prefix"
    assert state["allowed_token_ids"] == [table[","]]
    assert table["]"] not in state["allowed_token_ids"]


def test_eos_is_forbidden_until_complete_closed_tree_and_complete_predicate_population(codec):
    ids = ids_for(content(), codec)
    assert 2 not in prefix(ids[:12], context(), codec)["allowed_token_ids"]
    assert prefix(ids[:-1], context(), codec)["allowed_token_ids"] == [2]
    incomplete = decode(ids[:-1], context(), codec)
    assert incomplete["status"] == "incomplete" and incomplete["reason"] == "missing_eos"
    assert incomplete["prediction"] is None and incomplete["generated_ids"] == ids[:-1]
    #Closing a tree that uses only one of3declaredpredicates is not a completion.
    unused = unary_content()
    unused["tree"][2][2].append(["variable", 0])
    declined = decode(ids_for(unused, codec), context(), codec)
    assert declined["status"] == "rejected" and declined["prediction"] is None


@pytest.mark.parametrize("damage,status", [("empty", "incomplete"), ("missing_eos", "incomplete"),
    ("missing_bos", "rejected"), ("pad", "rejected"), ("interior_bos", "rejected"),
    ("interior_eos", "rejected"), ("post_eos", "rejected"), ("unknown", "rejected")])
def test_generated_framing_keeps_every_offered_id_without_repair(damage, status, codec):
    ids = ids_for(content(), codec)
    if damage == "empty": ids = []
    elif damage == "missing_eos": ids.pop()
    elif damage == "missing_bos": ids.pop(0)
    elif damage == "pad": ids.insert(20, 0)
    elif damage == "interior_bos": ids.insert(20, 1)
    elif damage == "interior_eos": ids.insert(20, 2)
    elif damage == "post_eos": ids.append(codec["vocabulary"].index("0"))
    else: ids[20] = len(codec["vocabulary"])
    before = deepcopy(ids)
    report = decode(ids, context(), codec)
    assert report["status"] == status
    assert report["generated_ids"] == ids == before
    assert report["prediction"] is None and report["counts"] is None
    no_authority(report)


@pytest.mark.parametrize("ids", [None, (), [True], [1.0], [1 << 63], [1] * 513])
def test_malformed_api_ids_and_whole_sequence_overflow_raise_before_candidate_outcome(ids, codec):
    for operation in (decode, prefix):
        with pytest.raises(ValueError): operation(ids, context(), codec)


def test_literal_json_order_shape_and_repeated_or_unknown_fields_are_rejected(codec):
    vocabulary = codec["vocabulary"]
    by_token = {token: index for index, token in enumerate(vocabulary)}
    #Every token is in the fixed lexical vocabulary; order and repeatedfields
    #still violate the exact canonical wrapper, rather than being defaulted.
    malformed = [
        ['{', '"tree"', ':', '[', '"forall"', ',', '0', ',', '[', '"predicate"', ',', '0', ',', '[', '[', '"variable"', ',', '0', ']', ']', ']', ']', ',', '"schema"', ':', json.dumps(content_owner.CONTENT_SCHEMA), '}'],
        ['{', '"schema"', ':', json.dumps(content_owner.CONTENT_SCHEMA), ',', '"schema"', ':', json.dumps(content_owner.CONTENT_SCHEMA), '}'],
        ['{', '"schema"', ':', json.dumps(content_owner.CONTENT_SCHEMA), ',', '"tree"', ':', '[', '"variable"', ',', '0', ']', '}'],
    ]
    for lexical in malformed:
        ids = [1, *(by_token[token] for token in lexical), 2]
        report = decode(ids, unary_context(), codec)
        assert report["status"] == "rejected" and report["generated_ids"] == ids
        assert report["prediction"] is None


@pytest.mark.parametrize("field", ["source_binding", "authority", "identity_sidecar", "original_request_sha256"])
def test_encoding_content_cannot_intake_provenance_or_original_identity_fields(field, codec):
    value = content()
    value[field] = None
    with pytest.raises(ValueError): encode(value, context(), codec)


@pytest.mark.parametrize("location", ["content", "context"])
def test_duplicate_json_keys_refused_before_semantic_decode(location, codec):
    c, x = CONTENT_RAW["A"], CONTEXT_RAW
    raw = c if location == "content" else x
    duplicate = b'{"schema":' + wire(json.loads(raw)["schema"]) + b',' + raw[1:]
    if location == "content": c = duplicate
    else: x = duplicate
    with pytest.raises(ValueError):
        subject.encode_compact_content_tokens_v1(c, x,
            expected_content_sha256=sha(c), expected_context_sha256=sha(x),
            codec=codec, expected_codec_sha256=codec_sha(codec))


@pytest.mark.parametrize("location", ["content", "context", "codec"])
def test_independent_raw_or_codec_hash_change_is_not_classified_model_rejection(location, codec):
    with pytest.raises(ValueError):
        subject.encode_compact_content_tokens_v1(CONTENT_RAW["A"], CONTEXT_RAW,
            expected_content_sha256="0" * 64 if location == "content" else CONTENT_SHA["A"],
            expected_context_sha256="0" * 64 if location == "context" else CONTEXT_SHA,
            codec=codec, expected_codec_sha256="0" * 64 if location == "codec" else codec_sha(codec))


@pytest.mark.parametrize("mutation", ["vocabulary", "special", "extra", "profile"])
def test_changed_or_resealed_fixed_codec_refuses_even_if_plain_hash_matches(mutation, codec):
    changed = deepcopy(codec)
    if mutation == "vocabulary": changed["vocabulary"][3:5] = reversed(changed["vocabulary"][3:5])
    elif mutation == "special": changed["eos_id"] = 1
    elif mutation == "extra": changed["target_dictionary"] = {"answer": "retained"}
    else: changed["profile"] += "-changed"
    with pytest.raises(ValueError):
        subject.decode_compact_content_tokens_v1([], CONTEXT_RAW,
            expected_context_sha256=CONTEXT_SHA, codec=changed, expected_codec_sha256=sha(wire(changed)))


def test_invalid_context_is_operation_failure_even_for_empty_or_bad_generated_ids(codec):
    bad = context()
    bad["signature"]["profile"]["value"] = "unsupported"
    for ids in ([], [-1]):
        with pytest.raises(ValueError): decode(ids, bad, codec)
    injected = context()
    injected["source_binding"] = {"accepted": True}
    with pytest.raises(ValueError): decode([], injected, codec)


def balanced(rows):
    rows = list(rows)
    while len(rows) > 1:
        combined = [["and", rows[i], rows[i + 1]] for i in range(0, len(rows) - 1, 2)]
        if len(rows) % 2: combined.append(rows[-1])
        rows = combined
    return rows[0]


def near_limit_content():
    body = balanced([["predicate", 0, [["variable", 0]]] for _ in range(27)])
    return {"schema": content_owner.CONTENT_SCHEMA,
            "tree": ["forall", 0, ["exists", 1, ["not", ["not", body]]]]}


def test_real_511_id_positive_and_overbudget_valid_tree_refuses_whole_input(codec):
    value, ctx = near_limit_content(), unary_context()
    ids = ids_for(value, codec)
    assert len(ids) == 511
    report = encode(value, ctx, codec)
    assert report["target_ids"] == ids and report["total_token_count"] == 511
    assert decode(ids, ctx, codec)["status"] == "valid_candidate"
    assert prefix(ids[:-1], ctx, codec)["allowed_token_ids"] == [2]
    value["tree"][2][2] = ["not", value["tree"][2][2]]
    oversized = ids_for(value, codec)
    assert len(oversized) == 515
    #The authoritative content remains valid. Only this tokenbudget refusesit.
    assert public_prediction(value, ctx)["content"] == value
    with pytest.raises(ValueError): encode(value, ctx, codec)
    with pytest.raises(ValueError): decode(oversized, ctx, codec)


def test_local_prefix_can_exhaust_total_budget_without_becoming_complete(codec):
    value = near_limit_content()
    value["tree"][2][2] = ["not", value["tree"][2][2]]
    ids = ids_for(value, codec, eos=False)[:512]
    assert len(ids) == 512 and 2 not in ids
    state = prefix(ids, unary_context(), codec)
    assert state["status"] == "budget_exhausted"
    assert state["allowed_token_ids"] == [] and state["offered_ids"] == ids
    assert state["remaining_token_slots"] == 0
    assert state["global_completability_proven"] is False
    outcome = decode(ids, unary_context(), codec)
    assert outcome["status"] != "valid_candidate" and outcome["prediction"] is None


def test_returned_populations_and_candidate_mutation_do_not_change_originals(codec):
    value, ctx = content(), context()
    before = deepcopy((value, ctx, codec))
    report = encode(value, ctx, codec)
    result = decode(report["target_ids"], ctx, codec)
    result["generated_ids"].append(0)
    result["prediction"]["request"]["source_binding"] = {"accepted": True}
    assert (value, ctx, codec) == before
    assert encode(value, ctx, codec) == report
    fresh = decode(report["target_ids"], ctx, codec)
    assert fresh["generated_ids"] == report["target_ids"]
    no_authority(fresh)



def test_local_next_step_acceptance_does_not_claim_future_completion_of_dead_end(codec):
    value = unary_content()
    value["tree"][2][2].append(["variable", 0])
    ids = ids_for(value, codec, eos=False)
    #Only predicate0 is used. The root's closing bracket is locally possible,
    #but the next document-close would leave predicates1and2 absent forever.
    locally_possible = prefix(ids[:-2], context(), codec)
    close = codec["vocabulary"].index("]")
    assert locally_possible["status"] == "prefix" and close in locally_possible["allowed_token_ids"]
    assert locally_possible["global_completability_proven"] is False
    dead_end = prefix(ids[:-1], context(), codec)
    assert dead_end["status"] == "rejected" and dead_end["allowed_token_ids"] == []
    assert dead_end["offered_ids"] == ids[:-1]
    assert prefix(ids_for(content(), codec), context(), codec)["status"] == "complete"


@pytest.mark.parametrize("location", ["content", "context"])
def test_real_raw_byte_caps_refuse_complete_oversize_intakes(location, codec):
    c, x = CONTENT_RAW["A"], CONTEXT_RAW
    limit = subject.MAX_CONTENT_BYTES if location == "content" else subject.MAX_CONTEXT_BYTES
    if location == "content": c += b" " * (limit + 1 - len(c))
    else: x += b" " * (limit + 1 - len(x))
    with pytest.raises(ValueError):
        subject.encode_compact_content_tokens_v1(c, x,
            expected_content_sha256=sha(c), expected_context_sha256=sha(x),
            codec=codec, expected_codec_sha256=codec_sha(codec))


@pytest.mark.parametrize("raw", [b'\xff', b'{', b'{"schema":NaN}', b'{"schema":1.0}', b'{"schema":9223372036854775808}'])
def test_malformed_ordinary_content_json_is_operation_refusal_not_candidate_outcome(raw, codec):
    with pytest.raises(ValueError):
        subject.encode_compact_content_tokens_v1(raw, CONTEXT_RAW,
            expected_content_sha256=sha(raw), expected_context_sha256=CONTEXT_SHA,
            codec=codec, expected_codec_sha256=codec_sha(codec))


@pytest.mark.parametrize("value", [1.0, float("nan"), {1: "nonstring-key"}, {"nul": "\x00"}, {"surrogate": "\ud800"}])
def test_public_codec_hash_refuses_nonordinary_json(value):
    with pytest.raises(ValueError): subject.compact_content_token_codec_sha256(value)


def test_public_codec_hash_refuses_repeated_alias_byte_overflow_before_full_serialization(monkeypatch):
    #Only8KiB of string storage is reused8times. Its complete JSON would exceed
    #the fixed32KiB codec cap; the complete serialization must never be built.
    value = ["x" * 8192] * 8
    def forbidden_dumps(*args, **kwargs):
        raise AssertionError("complete serialization preceded cumulative-byte admission")
    #Labelled new-module JSON serializer seam; no AST/context owner is patched.
    monkeypatch.setattr(subject.json, "dumps", forbidden_dumps)
    with pytest.raises(ValueError, match="before serialization"):
        subject.compact_content_token_codec_sha256(value)


def test_pure_json_budget_escape_unicode_cycle_depth_and_item_seams():
    value = {"escape": '\\"\n\t\x01', "unicode": "é漢🙂"}
    assert subject._wire(value, len(wire(value))) == wire(value)
    with pytest.raises(ValueError): subject._wire(value, len(wire(value)) - 1)
    cyclic = []; cyclic.append(cyclic)
    with pytest.raises(ValueError): subject._wire(cyclic, 1024)
    nested = None
    for _ in range(98): nested = [nested]
    with pytest.raises(ValueError): subject._wire(nested, 4096)
    with pytest.raises(ValueError): subject._wire([None] * 100001, 2 * 1024 * 1024)


@pytest.mark.parametrize("operation", ["encode", "prefix", "decode"])
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, KeyboardInterrupt])
def test_operation_owner_unavailability_or_interrupt_propagates_without_model_outcome(operation, error_type, codec, monkeypatch):
    ids = ids_for(content(), codec)
    failure = error_type("authored new-module owner-load failure")
    def unavailable(): raise failure
    #Labelled operation-loader seam. The authoritative public content owner,
    #its strict validator and lowering are not monkeypatched or substituted.
    monkeypatch.setattr(subject, "_owner", unavailable)
    with pytest.raises(error_type) as raised:
        if operation == "encode": encode(content(), context(), codec)
        elif operation == "prefix": prefix(ids, context(), codec)
        else: decode(ids, context(), codec)
    assert raised.value is failure


@pytest.mark.parametrize("pin", ["_SELF_SHA", "_OWNER_SHA"])
def test_real_source_pin_refusal_stays_operation_failure_even_for_bad_candidate(pin, codec, monkeypatch):
    monkeypatch.setattr(subject, pin, "0" * 64)
    with pytest.raises(ValueError): decode([-1], context(), codec)


@pytest.mark.parametrize("operation", ["encode", "prefix", "decode"])
def test_final_report_serialization_precedes_actual_source_closeout_integrity_seam(operation, codec, monkeypatch):
    ids = ids_for(content(), codec)
    detach, seen = subject._detach, []
    def changing_detach(value, maximum):
        result = detach(value, maximum)
        if type(value) is dict and value.get("schema") in {
                subject.ENCODING_SCHEMA, subject.PREFIX_SCHEMA, subject.CANDIDATE_SCHEMA}:
            seen.append(value["schema"])
            monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
        return result
    #Only the final new-module report serialization is instrumented; the real
    #on-disk source check and authoritative public content owner remain active.
    monkeypatch.setattr(subject, "_detach", changing_detach)
    with pytest.raises(ValueError):
        if operation == "encode": encode(content(), context(), codec)
        elif operation == "prefix": prefix(ids, context(), codec)
        else: decode(ids, context(), codec)
    assert len(seen) == 1
